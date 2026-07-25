"""Axis 6 — Agent Governance & Safety (10 points, 4 checks).

Has the site thought about machine clients as a category, and is it safe to read?

Two checks need their polarity stated explicitly, because both are easy to get
backwards:

**`tos_addresses_automation`** scores whether the terms discuss automated access
at all. Terms that *prohibit* crawling score identically to terms that permit it.
The axis measures whether the question was addressed; refusing is an answer.

**`no_injection_detected`** awards points for the *absence* of payloads. Evidence
here is evidence against the site. A page with no findings still needs a row
saying it was scanned — "clean" and "never checked" must not score the same.

`rate_limit_headers` is passive only. Nothing in this codebase probes for a 429,
because manufacturing one means deliberately degrading someone's service to earn
two points.
"""

from __future__ import annotations

from wasl.crawler.evidence import Evidence, EvidenceStore
from wasl.scoring.types import CheckResult, ScoringInput


def _refs(*evidence: Evidence) -> tuple[str, ...]:
    return tuple(e.id for e in evidence)


def check_tos_addresses_automation(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    addressed = [
        e for e in store.by_kind("text") if e.selector == "governance#tos-addresses-automation"
    ]
    silent = [
        e for e in store.by_kind("text") if e.selector == "governance#tos-silent-on-automation"
    ]

    if addressed:
        return CheckResult(
            check_id="a6_tos_automation",
            label="Terms of service address automated/agent access explicitly",
            points_awarded=3,
            max_points=3,
            evidence_refs=_refs(*addressed[:4]),
            detail=(
                "Terms discuss automated access, crawling or AI training. Whether they "
                "permit or prohibit is not scored — only that the question was addressed."
            ),
        )

    if silent:
        return CheckResult(
            check_id="a6_tos_automation",
            label="Terms of service address automated/agent access explicitly",
            points_awarded=0,
            max_points=3,
            evidence_refs=_refs(*silent[:3]),
            detail="A terms page was read but says nothing about automated access.",
        )

    return CheckResult(
        check_id="a6_tos_automation",
        label="Terms of service address automated/agent access explicitly",
        points_awarded=0,
        max_points=3,
        suppressed=True,
        suppressed_reason=(
            "No terms or legal page was reached within the page budget, so the terms were "
            "never read. Not finding the page is different from the page being silent."
        ),
    )


def check_rate_limit_headers(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    observed = [e for e in store.by_kind("header") if e.selector == "header#rate-limit"]

    if observed:
        return CheckResult(
            check_id="a6_rate_limit_headers",
            label="Rate-limit or Retry-After headers present",
            points_awarded=2,
            max_points=2,
            evidence_refs=_refs(*observed[:4]),
            detail=(
                "Rate-limit headers were volunteered during the normal polite crawl. "
                "No probing was performed to elicit them."
            ),
        )

    return CheckResult(
        check_id="a6_rate_limit_headers",
        label="Rate-limit or Retry-After headers present",
        points_awarded=0,
        max_points=2,
        detail=(
            "No rate-limit headers were observed. Measured passively only — Wasl does not "
            "send bursts to discover a site's limits."
        ),
    )


def check_machine_auth_documented(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    documented = [
        e for e in store.by_kind("text") if e.selector == "governance#machine-auth-documented"
    ]

    if documented:
        return CheckResult(
            check_id="a6_machine_auth",
            label="Authenticated surface exists for machine clients (API key/OAuth documented)",
            points_awarded=3,
            max_points=3,
            evidence_refs=_refs(*documented[:4]),
            detail="API key, token or OAuth authentication is documented for machine clients.",
        )

    auth_headers = [e for e in store.by_kind("header") if e.selector == "header#auth"]
    if auth_headers:
        return CheckResult(
            check_id="a6_machine_auth",
            label="Authenticated surface exists for machine clients (API key/OAuth documented)",
            points_awarded=0,
            max_points=3,
            evidence_refs=_refs(*auth_headers[:3]),
            detail=(
                "Authentication headers were observed but no documentation of a machine "
                "client flow was found. An undocumented auth surface is not usable."
            ),
        )

    return CheckResult(
        check_id="a6_machine_auth",
        label="Authenticated surface exists for machine clients (API key/OAuth documented)",
        points_awarded=0,
        max_points=3,
        detail="No documented authentication path for machine clients was found.",
    )


def check_no_injection_detected(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    """Points for the absence of payloads. Evidence here counts against the site."""
    findings = [
        e for e in store.by_kind("injection") if (e.selector or "") != "injection#clean"
    ]
    clean = [e for e in store.by_kind("injection") if e.selector == "injection#clean"]

    if findings:
        categories = sorted(
            {
                line.split(": ", 1)[1]
                for e in findings
                for line in e.raw.splitlines()
                if line.startswith("category: ")
            }
        )
        return CheckResult(
            check_id="a6_no_injection",
            label="No prompt-injection payload in agent-readable regions",
            points_awarded=0,
            max_points=2,
            evidence_refs=_refs(*findings[:8]),
            detail=(
                f"{len(findings)} injection finding(s) across {categories}. Note this may be "
                "third-party or user-generated content rather than something the operator "
                "placed deliberately."
            ),
        )

    if clean:
        return CheckResult(
            check_id="a6_no_injection",
            label="No prompt-injection payload in agent-readable regions",
            points_awarded=2,
            max_points=2,
            evidence_refs=_refs(*clean[:4]),
            detail=(
                f"{len(clean)} page(s) scanned across hidden elements, comments, attributes "
                "and visible text; no payloads found."
            ),
        )

    return CheckResult(
        check_id="a6_no_injection",
        label="No prompt-injection payload in agent-readable regions",
        points_awarded=0,
        max_points=2,
        suppressed=True,
        suppressed_reason="No page was scanned, so cleanliness cannot be asserted.",
    )


CHECKS = (
    check_tos_addresses_automation,
    check_rate_limit_headers,
    check_machine_auth_documented,
    check_no_injection_detected,
)


def evaluate(store: EvidenceStore, scoring_input: ScoringInput) -> tuple[CheckResult, ...]:
    return tuple(check(store, scoring_input) for check in CHECKS)
