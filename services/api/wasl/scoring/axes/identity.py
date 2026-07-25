"""Axis 1 — Machine-Readable Identity (15 points, 5 checks).

Can a machine find out what this site is and what it contains, without guessing?

The check worth understanding is `robots_agent_stanza`. It awards 3 points for an
explicit AI-crawler stanza **whether that stanza allows or disallows**. This
looks odd until you state what the axis measures: not whether a site welcomes
agents, but whether it has made a legible decision about them. `Disallow: /` for
GPTBot is a clear, deliberate, machine-readable answer. Silence is not an answer.

A site is never penalised for saying no. It is penalised for saying nothing.
"""

from __future__ import annotations

from wasl.crawler.evidence import EvidenceStore
from wasl.scoring.types import CheckResult, ScoringInput

CANONICAL_COVERAGE_THRESHOLD = 0.80


def _refs(*evidence) -> tuple[str, ...]:
    return tuple(e.id for e in evidence)


def check_robots_present(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    robots = store.by_kind("robots")
    present = [e for e in robots if e.selector == "robots.txt"]
    unparseable = [e for e in robots if e.selector == "robots.txt#unparseable"]

    if present and not unparseable:
        return CheckResult(
            check_id="a1_robots_present",
            label="robots.txt present and parseable",
            points_awarded=2,
            max_points=2,
            evidence_refs=_refs(*present),
            detail="robots.txt was retrieved and parsed successfully.",
        )

    if present and unparseable:
        return CheckResult(
            check_id="a1_robots_present",
            label="robots.txt present and parseable",
            points_awarded=0,
            max_points=2,
            evidence_refs=_refs(*present, *unparseable),
            detail="robots.txt exists but could not be parsed.",
        )

    return CheckResult(
        check_id="a1_robots_present",
        label="robots.txt present and parseable",
        points_awarded=0,
        max_points=2,
        evidence_refs=_refs(*[e for e in robots if e.selector == "robots.txt#absent"]),
        detail="No robots.txt was found at the site root.",
    )


def check_robots_agent_stanza(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    stanzas = [
        e for e in store.by_kind("robots") if (e.selector or "").startswith("robots.txt#user-agent:")
    ]
    if stanzas:
        named = [(e.selector or "").split(":", 1)[-1] for e in stanzas]
        return CheckResult(
            check_id="a1_robots_agent_stanza",
            label="robots.txt names an AI/agent user-agent explicitly",
            points_awarded=3,
            max_points=3,
            evidence_refs=_refs(*stanzas),
            detail=(
                f"Explicit stanza(s) for: {', '.join(named)}. Clarity is what scores here — "
                "allowing and disallowing count equally."
            ),
        )

    return CheckResult(
        check_id="a1_robots_agent_stanza",
        label="robots.txt names an AI/agent user-agent explicitly",
        points_awarded=0,
        max_points=3,
        detail=(
            "No stanza names an AI crawler. The site has not stated a position on "
            "agent access either way."
        ),
    )


def check_sitemap(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    present = [e for e in store.by_kind("sitemap") if e.selector == "sitemap#present"]
    if present:
        return CheckResult(
            check_id="a1_sitemap",
            label="sitemap.xml present and reachable",
            points_awarded=3,
            max_points=3,
            evidence_refs=_refs(*present),
            detail=f"{len(present)} reachable sitemap(s).",
        )

    unreachable = [e for e in store.by_kind("sitemap") if e.selector == "sitemap#unreachable"]
    return CheckResult(
        check_id="a1_sitemap",
        label="sitemap.xml present and reachable",
        points_awarded=0,
        max_points=3,
        evidence_refs=_refs(*unreachable),
        detail=(
            "A sitemap was declared but could not be retrieved."
            if unreachable
            else "No sitemap found at /sitemap.xml or declared in robots.txt."
        ),
    )


def check_llms_txt(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    present = [e for e in store.by_kind("llmstxt") if e.selector == "llms.txt#present"]
    if present:
        return CheckResult(
            check_id="a1_llms_txt",
            label="llms.txt present at the site root",
            points_awarded=4,
            max_points=4,
            evidence_refs=_refs(*present),
            detail="A valid markdown llms.txt was served at /llms.txt.",
        )

    not_markdown = [e for e in store.by_kind("llmstxt") if e.selector == "llms.txt#not-markdown"]
    return CheckResult(
        check_id="a1_llms_txt",
        label="llms.txt present at the site root",
        points_awarded=0,
        max_points=4,
        evidence_refs=_refs(*not_markdown),
        detail=(
            "/llms.txt returned a response, but it is the site's HTML shell rather than "
            "an llms.txt. Not counted."
            if not_markdown
            else "No llms.txt at the site root."
        ),
    )


def check_canonical_coverage(store: EvidenceStore, scoring_input: ScoringInput) -> CheckResult:
    if scoring_input.pages_ok == 0:
        return CheckResult(
            check_id="a1_canonical_coverage",
            label=f"Canonical URLs on ≥{CANONICAL_COVERAGE_THRESHOLD:.0%} of crawled pages",
            points_awarded=0,
            max_points=3,
            suppressed=True,
            suppressed_reason="No pages were successfully crawled, so coverage is undefined.",
        )

    with_canonical = [e for e in store.by_kind("link") if e.selector == "link[rel=canonical]"]
    urls_with = {e.source_url for e in with_canonical}
    coverage = len(urls_with) / scoring_input.pages_ok

    passed = coverage >= CANONICAL_COVERAGE_THRESHOLD
    return CheckResult(
        check_id="a1_canonical_coverage",
        label=f"Canonical URLs on ≥{CANONICAL_COVERAGE_THRESHOLD:.0%} of crawled pages",
        points_awarded=3 if passed else 0,
        max_points=3,
        evidence_refs=_refs(*with_canonical[:10]),
        detail=(
            f"{len(urls_with)} of {scoring_input.pages_ok} crawled pages declare a canonical "
            f"URL ({coverage:.0%}); threshold is {CANONICAL_COVERAGE_THRESHOLD:.0%}."
        ),
    )


CHECKS = (
    check_robots_present,
    check_robots_agent_stanza,
    check_sitemap,
    check_llms_txt,
    check_canonical_coverage,
)


def evaluate(store: EvidenceStore, scoring_input: ScoringInput) -> tuple[CheckResult, ...]:
    return tuple(check(store, scoring_input) for check in CHECKS)
