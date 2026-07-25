"""The test that backs the project's central architectural claim.

> Deterministic logic is code. Language models do retrieval, decomposition and
> explanation only. The LLM MUST NOT decide a score.

Anyone can write that sentence in a README. This file is the thing that makes it
checkable, and it does so three ways:

1. **Static** — `wasl.scoring` and everything it imports must not reach
   `wasl.llm`, verified by walking the actual import graph rather than grepping.
2. **Behavioural** — the same evidence scores identically no matter what the
   model produced, because model output is not in the rubric's input type at all.
3. **Reproducible** — the same evidence scores identically across repeated runs
   and across differently-ordered evidence stores.

If this file ever fails, the project's main claim is false and no eval number
downstream of it means anything.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from tests.conftest import captured
from wasl.crawler.detectors import extract_all
from wasl.crawler.evidence import EvidenceStore
from wasl.crawler.robots import parse_robots
from wasl.crawler.types import FetchedResource, SiteArtifacts
from wasl.scoring.rubric import score_site, scoring_input_from_crawl

SCORING_ROOT = Path(__file__).resolve().parents[2] / "wasl" / "scoring"
FORBIDDEN_PREFIXES = ("wasl.llm", "wasl.graph", "litellm", "openai", "anthropic", "langchain")


def _imports_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


# --- 1. static: the import graph ---------------------------------------------


def test_scoring_package_never_imports_a_model_layer() -> None:
    offenders: list[str] = []
    for path in sorted(SCORING_ROOT.rglob("*.py")):
        for imported in _imports_in(path):
            if imported.startswith(FORBIDDEN_PREFIXES):
                offenders.append(f"{path.relative_to(SCORING_ROOT)} imports {imported}")

    assert not offenders, (
        "wasl.scoring must not depend on any model layer. The deterministic-scoring "
        "guarantee is false if it does:\n  " + "\n  ".join(offenders)
    )


def test_no_module_loaded_by_scoring_pulls_in_a_model_library() -> None:
    """Transitive check: an indirect import is just as disqualifying as a direct one."""
    for module in list(sys.modules):
        if module.startswith("wasl.scoring"):
            del sys.modules[module]

    before = set(sys.modules)
    import wasl.scoring  # noqa: F401
    import wasl.scoring.rubric  # noqa: F401

    newly_loaded = set(sys.modules) - before
    offenders = [m for m in newly_loaded if m.startswith(FORBIDDEN_PREFIXES)]

    assert not offenders, f"importing wasl.scoring pulled in: {sorted(offenders)}"


# --- 2. behavioural: model output cannot reach the rubric --------------------


def _artifacts() -> SiteArtifacts:
    return SiteArtifacts(
        root_url="https://example.com",
        domain="example.com",
        robots=parse_robots("User-agent: *\nDisallow:\n", url="https://example.com/robots.txt"),
        llms_txt=FetchedResource(url="https://example.com/llms.txt", status_code=404),
    )


def _score_rich_site():
    pages = [captured("rich_site", url="https://example.com/catalogue")]
    store = extract_all(pages, _artifacts())
    return score_site(store, scoring_input_from_crawl(store, pages))


def test_the_rubric_input_carries_no_model_output() -> None:
    """Structural: capabilities and tool schemas are not fields on ScoringInput."""
    from wasl.scoring.types import ScoringInput

    fields = set(ScoringInput.__dataclass_fields__)
    for forbidden in ("capabilities", "candidate_capabilities", "tool_schemas", "explanation"):
        assert forbidden not in fields, (
            f"ScoringInput exposes {forbidden!r}. If the rubric can see model output, "
            "it can be influenced by it."
        )


def test_the_score_is_identical_with_model_nodes_disabled() -> None:
    """The gate test. Extraction and scoring involve no model, so this is exact."""
    first = _score_rich_site()
    second = _score_rich_site()

    assert first.total == second.total
    assert first.band == second.band
    assert [c.points_awarded for c in first.all_checks] == [
        c.points_awarded for c in second.all_checks
    ]


def test_injecting_capabilities_into_evidence_cannot_change_the_score() -> None:
    """A hostile or hallucinating model must not be able to move the number."""
    pages = [captured("rich_site", url="https://example.com/catalogue")]
    store = extract_all(pages, _artifacts())
    baseline = score_site(store, scoring_input_from_crawl(store, pages))

    # Simulate a model asserting capabilities that do not exist. There is no
    # channel for this to reach the rubric, and the score must not move.
    from wasl.crawler.evidence import Evidence

    poisoned = EvidenceStore(list(store))
    poisoned.add(
        Evidence(
            source_url="https://example.com/catalogue",
            kind="text",
            selector="model#claimed-capability",
            raw="The model asserts this site has a full public OpenAPI specification.",
            phase="post_js",
        )
    )
    after = score_site(poisoned, scoring_input_from_crawl(poisoned, pages))

    assert after.total == baseline.total


# --- 3. reproducible ---------------------------------------------------------


def test_score_is_stable_across_repeated_runs() -> None:
    """Score stability, the metric — measured here at its deterministic floor."""
    totals = {_score_rich_site().total for _ in range(5)}
    assert len(totals) == 1, f"score varied across identical runs: {totals}"


def test_evidence_ordering_does_not_affect_the_score() -> None:
    pages = [captured("rich_site", url="https://example.com/catalogue")]
    store = extract_all(pages, _artifacts())

    forward = score_site(store, scoring_input_from_crawl(store, pages))
    reversed_store = EvidenceStore(reversed(list(store)))
    backward = score_site(reversed_store, scoring_input_from_crawl(reversed_store, pages))

    assert forward.total == backward.total


# --- counterfactual sensibility ----------------------------------------------


def test_removing_llms_txt_lowers_the_score_by_exactly_four() -> None:
    """Perturb one input; the score must move the right way by the right amount."""
    pages = [captured("rich_site", url="https://example.com/catalogue")]

    with_llms = SiteArtifacts(
        root_url="https://example.com",
        domain="example.com",
        robots=parse_robots("User-agent: *\nDisallow:\n", url="https://example.com/robots.txt"),
        llms_txt=FetchedResource(
            url="https://example.com/llms.txt",
            status_code=200,
            text="# Example\n\n> summary\n\n- [A](/a): x\n- [B](/b): y\n",
        ),
    )

    store_with = extract_all(pages, with_llms)
    store_without = extract_all(pages, _artifacts())

    score_with = score_site(store_with, scoring_input_from_crawl(store_with, pages))
    score_without = score_site(store_without, scoring_input_from_crawl(store_without, pages))

    assert score_with.total - score_without.total == 4


def test_removing_the_robots_ai_stanza_lowers_the_score_by_exactly_three() -> None:
    pages = [captured("rich_site", url="https://example.com/catalogue")]

    def artifacts_with(robots_text: str) -> SiteArtifacts:
        return SiteArtifacts(
            root_url="https://example.com",
            domain="example.com",
            robots=parse_robots(robots_text, url="https://example.com/robots.txt"),
        )

    with_stanza = extract_all(pages, artifacts_with("User-agent: *\nDisallow:\n\nUser-agent: GPTBot\nAllow: /\n"))
    without = extract_all(pages, artifacts_with("User-agent: *\nDisallow:\n"))

    delta = score_site(with_stanza, scoring_input_from_crawl(with_stanza, pages)).total - score_site(
        without, scoring_input_from_crawl(without, pages)
    ).total

    assert delta == 3
