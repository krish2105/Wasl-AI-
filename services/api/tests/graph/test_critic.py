"""Critic rejection rules.

Four of the five rules are deterministic and tested here with no model at all —
which is the point. A critic whose verdicts depend entirely on a model call is
just a second opinion; one where most rejections are reproducible in code is a
rule engine with a model attached for the one genuinely semantic question.
"""

from __future__ import annotations

import pytest

from wasl.crawler.evidence import Evidence, EvidenceStore
from wasl.graph.nodes.critic import check_deterministic
from wasl.graph.state import Capability, ToolSchema


def evidence(raw: str = "GET form with named q parameter", kind: str = "form") -> Evidence:
    return Evidence(
        source_url="https://example.com/x",
        kind=kind,  # type: ignore[arg-type]
        selector="form#search",
        raw=raw,
        phase="pre_js",
    )


def capability(evidence_ids: list[str], **overrides) -> Capability:
    payload = {
        "name": "search_products",
        "verb": "search",
        "noun": "products",
        "description": "Search the catalogue.",
        "evidence_ids": evidence_ids,
    }
    payload.update(overrides)
    return Capability(**payload)


def bounded_schema() -> ToolSchema:
    return ToolSchema(
        name="acme_search_products",
        description="Search products.",
        parameters={"q": {"type": "string", "description": "Keywords", "maxLength": 200}},
    )


# --- rule 1: no_evidence -----------------------------------------------------


def test_a_capability_citing_nonexistent_evidence_is_rejected() -> None:
    real = evidence()
    rejection = check_deterministic(
        capability(["0000000000000000"]), {real.id: real}, set()
    )
    assert rejection is not None
    assert rejection.rule_id == "no_evidence"
    assert "does not exist" in rejection.reason


def test_a_partially_hallucinated_citation_is_still_rejected() -> None:
    """One good citation does not launder a fabricated one."""
    real = evidence()
    rejection = check_deterministic(
        capability([real.id, "0000000000000000"]), {real.id: real}, set()
    )
    assert rejection is not None
    assert rejection.rule_id == "no_evidence"


# --- rule 2: state_changing --------------------------------------------------


@pytest.mark.parametrize("verb", ["book", "buy", "cancel", "submit", "pay", "order", "reserve"])
def test_state_changing_verbs_are_rejected(verb: str) -> None:
    real = evidence()
    rejection = check_deterministic(
        capability([real.id], verb=verb, name=f"{verb}_thing"), {real.id: real}, set()
    )
    assert rejection is not None
    assert rejection.rule_id == "state_changing"


def test_the_state_changing_rejection_explains_it_is_still_reported() -> None:
    """Detecting one is useful information; emitting a tool for it is not."""
    real = evidence()
    rejection = check_deterministic(
        capability([real.id], verb="book", name="book_room"), {real.id: real}, set()
    )
    assert rejection is not None
    assert "reported as detected" in rejection.reason


def test_a_model_claiming_read_only_does_not_override_the_verb() -> None:
    real = evidence()
    rejection = check_deterministic(
        capability([real.id], verb="book", name="book_room", state_changing=False),
        {real.id: real},
        set(),
    )
    assert rejection is not None
    assert rejection.rule_id == "state_changing"


# --- rule 3: unbounded_param -------------------------------------------------


def test_an_unbounded_string_parameter_is_rejected() -> None:
    real = evidence()
    schema = ToolSchema(
        name="acme_search",
        description="Search.",
        parameters={"q": {"type": "string", "description": "Anything"}},
    )
    rejection = check_deterministic(
        capability([real.id], tool_schema=schema), {real.id: real}, set()
    )
    assert rejection is not None
    assert rejection.rule_id == "unbounded_param"
    assert "security boundary" in rejection.reason


def test_a_bounded_schema_passes_the_deterministic_rules() -> None:
    real = evidence()
    assert (
        check_deterministic(
            capability([real.id], tool_schema=bounded_schema()), {real.id: real}, set()
        )
        is None
    )


# --- rule 4: injection_detected ----------------------------------------------


def test_a_capability_resting_on_injection_evidence_is_rejected() -> None:
    """The capability may be something an attacker planted, not something offered."""
    tainted = evidence(raw="category: ranking_manipulation", kind="injection")
    rejection = check_deterministic(
        capability([tainted.id]), {tainted.id: tainted}, {tainted.id}
    )
    assert rejection is not None
    assert rejection.rule_id == "injection_detected"
    assert "attacker planted" in rejection.reason


def test_clean_evidence_is_not_flagged_as_injection() -> None:
    real = evidence()
    assert check_deterministic(capability([real.id]), {real.id: real}, set()) is None


# --- rule ordering -----------------------------------------------------------


def test_missing_evidence_is_checked_before_anything_else() -> None:
    """Cheapest and most fundamental rule first; no point critiquing a phantom."""
    rejection = check_deterministic(
        capability(["0000000000000000"], verb="book", name="book_room"), {}, set()
    )
    assert rejection is not None
    assert rejection.rule_id == "no_evidence"


# --- the happy path ----------------------------------------------------------


def test_a_well_formed_capability_survives_the_deterministic_rules() -> None:
    """It then goes to the model for the one semantic question: does the evidence
    actually support the claim?"""
    real = evidence()
    store = EvidenceStore([real])
    assert check_deterministic(
        capability([real.id], tool_schema=bounded_schema()),
        {e.id: e for e in store},
        set(),
    ) is None
