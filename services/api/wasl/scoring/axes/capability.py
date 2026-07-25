"""Axis 3 — Capability Exposure (25 points, 6 checks). The heaviest axis.

Can an agent *do* anything here, or only read?

Two design decisions carry most of the weight:

**A spec and a docs page are not the same thing.** A machine-readable OpenAPI
spec is 6 points because an agent can build a client from it unaided. A prose
documentation page is 3, because a human still has to translate first. Collapsing
them would make an `/api` marketing page score like a real API, and that is the
exact hard-negative case the golden set exists to catch.

**"Core business verbs via stable URL patterns" needs a falsifiable test.** The
spec's wording is a judgement call, and judgement calls are how a language model
sneaks back into a rubric that claims to be deterministic. The operational test
is stated in `check_stable_discovery_urls` and is deliberately conservative.

Nothing here reads `candidate_capabilities`. The score does not depend on what
the induce node proposed, which is what makes it reproducible without a model.
"""

from __future__ import annotations

from wasl.crawler.evidence import Evidence, EvidenceStore
from wasl.scoring.types import CheckResult, ScoringInput

# Two independent patterns, because one URL shaped like a record could be
# anything. Two distinct shapes on a site is a structure, not a coincidence.
MIN_DISCOVERY_PATTERNS = 2
MIN_URLS_PER_PATTERN = 2


def _refs(*evidence: Evidence) -> tuple[str, ...]:
    return tuple(e.id for e in evidence)


def check_openapi_spec(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    specs = [e for e in store.by_kind("openapi") if e.selector == "openapi#spec"]
    if specs:
        return CheckResult(
            check_id="a3_openapi_spec",
            label="Public OpenAPI/Swagger spec discoverable",
            points_awarded=6,
            max_points=6,
            evidence_refs=_refs(*specs),
            detail=f"{len(specs)} machine-readable spec(s) found.",
        )

    near_misses = [e for e in store.by_kind("openapi") if e.selector == "openapi#not-a-spec"]
    return CheckResult(
        check_id="a3_openapi_spec",
        label="Public OpenAPI/Swagger spec discoverable",
        points_awarded=0,
        max_points=6,
        evidence_refs=_refs(*near_misses[:5]),
        detail=(
            "A probed spec path responded, but the body is not an OpenAPI document."
            if near_misses
            else "No OpenAPI or Swagger spec found at any conventional path."
        ),
    )


def check_documented_api(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    """3 points for discoverable API documentation, spec or no spec."""
    links = [
        e
        for e in store.by_kind("openapi")
        if (e.selector or "").startswith("a[href") or "developer" in e.raw.lower()
    ]
    docs = [e for e in links if (e.selector or "").startswith("a[href")]

    if docs:
        return CheckResult(
            check_id="a3_documented_api",
            label="Documented public API discoverable (docs page, spec not required)",
            points_awarded=3,
            max_points=3,
            evidence_refs=_refs(*docs[:8]),
            detail=(
                f"{len(docs)} link(s) to API or developer documentation. A human can build "
                "a client from this; an agent still needs the spec to do it unaided."
            ),
        )

    return CheckResult(
        check_id="a3_documented_api",
        label="Documented public API discoverable (docs page, spec not required)",
        points_awarded=0,
        max_points=3,
        detail="No links to API reference or developer documentation were found.",
    )


def check_agent_manifest(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    manifests = [e for e in store.by_kind("wellknown") if "#manifest" in (e.selector or "")]
    if manifests:
        return CheckResult(
            check_id="a3_agent_manifest",
            label="MCP endpoint or .well-known agent manifest already exists",
            points_awarded=6,
            max_points=6,
            evidence_refs=_refs(*manifests),
            detail=f"{len(manifests)} agent manifest(s) served under /.well-known/.",
        )

    rejected = [e for e in store.by_kind("wellknown") if "#not-a-manifest" in (e.selector or "")]
    return CheckResult(
        check_id="a3_agent_manifest",
        label="MCP endpoint or .well-known agent manifest already exists",
        points_awarded=0,
        max_points=6,
        evidence_refs=_refs(*rejected[:4]),
        detail=(
            "A .well-known path responded but did not serve an agent manifest."
            if rejected
            else "No agent manifest found under /.well-known/."
        ),
    )


def check_stable_discovery_urls(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    """Core business verbs reachable via stable URLs without JS-only interaction.

    Operational test, chosen so the check is falsifiable rather than a matter of
    opinion. Award the points when EITHER holds:

      a) at least two distinct stable URL patterns were observed, each on two or
         more links — e.g. /product/{id} and /category/{slug}; or
      b) a GET search or filter form exists, which advertises a URL an agent can
         construct for itself.

    Deliberately conservative. One pattern seen once could be an accident of one
    page's markup; a GET form is an explicit invitation.
    """
    patterns = [
        e for e in store.by_kind("identifier") if (e.selector or "").startswith("url-pattern#")
    ]
    qualifying = [e for e in patterns if "distinct link(s)" in e.raw]

    strong_patterns: list[Evidence] = []
    for evidence in qualifying:
        try:
            count = int(evidence.raw.split(" on ")[1].split(" distinct")[0])
        except (IndexError, ValueError):
            continue
        if count >= MIN_URLS_PER_PATTERN:
            strong_patterns.append(evidence)

    get_forms = [
        e for e in store.by_kind("form") if "#get#search" in (e.selector or "")
    ]

    if len(strong_patterns) >= MIN_DISCOVERY_PATTERNS:
        return CheckResult(
            check_id="a3_stable_discovery",
            label="Core business verbs reachable via stable URL patterns without JS",
            points_awarded=5,
            max_points=5,
            evidence_refs=_refs(*strong_patterns[:6]),
            detail=(
                f"{len(strong_patterns)} distinct stable URL pattern(s), each on "
                f"≥{MIN_URLS_PER_PATTERN} links. An agent can construct these itself."
            ),
        )

    if get_forms:
        return CheckResult(
            check_id="a3_stable_discovery",
            label="Core business verbs reachable via stable URL patterns without JS",
            points_awarded=5,
            max_points=5,
            evidence_refs=_refs(*get_forms[:4]),
            detail=(
                "A GET search/filter form exposes a constructible query URL, which is an "
                "explicit invitation to build the request."
            ),
        )

    return CheckResult(
        check_id="a3_stable_discovery",
        label="Core business verbs reachable via stable URL patterns without JS",
        points_awarded=0,
        max_points=5,
        evidence_refs=_refs(*strong_patterns[:3]),
        detail=(
            f"Found {len(strong_patterns)} qualifying URL pattern(s) and no GET search form; "
            f"the test requires {MIN_DISCOVERY_PATTERNS} patterns or one GET form."
        ),
    )


def check_contact_capability(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    """Contact/enquiry reachable as structured data rather than a phone number in an image."""
    contact_forms = [e for e in store.by_kind("form") if "#contact" in (e.selector or "")]

    well_formed = [
        e
        for e in contact_forms
        if "0 named" not in e.raw and ("labelled=True" in e.raw or "% label coverage" in e.raw)
    ]

    parseable = [
        e
        for e in well_formed
        if _label_coverage(e.raw) is not None and (_label_coverage(e.raw) or 0) >= 0.5
    ]

    if parseable:
        return CheckResult(
            check_id="a3_contact_capability",
            label="Contact/enquiry capability is machine-parseable",
            points_awarded=3,
            max_points=3,
            evidence_refs=_refs(*parseable[:4]),
            detail="A labelled contact form with named inputs was found.",
        )

    return CheckResult(
        check_id="a3_contact_capability",
        label="Contact/enquiry capability is machine-parseable",
        points_awarded=0,
        max_points=3,
        evidence_refs=_refs(*contact_forms[:4]),
        detail=(
            "A contact form exists but its inputs are unnamed or unlabelled, so an agent "
            "cannot tell which field is which."
            if contact_forms
            else "No machine-parseable contact or enquiry capability was found."
        ),
    )


def _label_coverage(raw: str) -> float | None:
    """Pull the '(NN% label coverage)' figure out of form evidence."""
    if "% label coverage" not in raw:
        return None
    try:
        chunk = raw.split("% label coverage")[0]
        return int(chunk.rsplit("(", 1)[-1]) / 100
    except (IndexError, ValueError):
        return None


def check_pricing_without_login(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    """Availability or pricing readable without authenticating."""
    structured = [
        e for e in store.by_kind("text") if (e.selector or "").startswith("pricing#structured")
    ]
    rendered = [
        e for e in store.by_kind("text") if (e.selector or "").startswith("pricing#rendered")
    ]
    gated = [e for e in store.by_kind("header") if e.selector == "header#interstitial"]

    if (structured or rendered) and not gated:
        return CheckResult(
            check_id="a3_pricing_without_login",
            label="Availability/pricing reachable without login",
            points_awarded=2,
            max_points=2,
            evidence_refs=_refs(*(structured or rendered)[:6]),
            detail=(
                "Price or availability information was readable on a public page with no "
                "authentication and no interstitial."
            ),
        )

    if gated:
        return CheckResult(
            check_id="a3_pricing_without_login",
            label="Availability/pricing reachable without login",
            points_awarded=0,
            max_points=2,
            evidence_refs=_refs(*gated[:3]),
            detail="Discovery paths are gated by an interstitial or challenge.",
        )

    return CheckResult(
        check_id="a3_pricing_without_login",
        label="Availability/pricing reachable without login",
        points_awarded=0,
        max_points=2,
        detail="No price or availability information was found on public pages.",
    )


CHECKS = (
    check_openapi_spec,
    check_documented_api,
    check_agent_manifest,
    check_stable_discovery_urls,
    check_contact_capability,
    check_pricing_without_login,
)


def evaluate(store: EvidenceStore, scoring_input: ScoringInput) -> tuple[CheckResult, ...]:
    return tuple(check(store, scoring_input) for check in CHECKS)
