"""Axis 4 — Content Extractability (15 points, 4 checks).

Can an agent read the content, or does it need a full browser to see anything?

`check_server_rendered` is the most informative measurement in the whole rubric,
and it is also the one that must be **suppressed rather than failed** on a
degraded capture. Without a browser there is no post-JS DOM to compare against,
so the ratio is unknown, not zero. Scoring it zero would punish sites for a
limitation of our own infrastructure.
"""

from __future__ import annotations

from wasl.crawler.evidence import Evidence, EvidenceStore
from wasl.scoring.types import CheckResult, ScoringInput

# Pre-JS text must be at least this fraction of post-JS text for the site to
# count as server-rendered. 0.5 means an agent without a browser sees at least
# half the content — imperfect but usable.
SERVER_RENDER_THRESHOLD = 0.5

# Alt-text coverage below which imagery counts as undescribed.
ALT_COVERAGE_THRESHOLD = 0.5


def _refs(*evidence: Evidence) -> tuple[str, ...]:
    return tuple(e.id for e in evidence)


def _ratio_from(raw: str) -> float | None:
    for line in raw.splitlines():
        if line.startswith("ratio:"):
            try:
                return float(line.split(":", 1)[1].strip())
            except ValueError:
                return None
    return None


def check_server_rendered(store: EvidenceStore, scoring_input: ScoringInput) -> CheckResult:
    unavailable = [
        e for e in store.by_kind("rendering") if e.selector == "rendering#unavailable"
    ]
    deltas = [e for e in store.by_kind("rendering") if e.selector == "rendering#delta"]

    if not deltas and unavailable:
        return CheckResult(
            check_id="a4_server_rendered",
            label="Meaningful content present in server-rendered HTML",
            points_awarded=0,
            max_points=5,
            evidence_refs=_refs(*unavailable[:3]),
            suppressed=True,
            suppressed_reason=(
                "Captured without a browser, so the pre-JS/post-JS comparison was never "
                "observed. Unknown is not the same as zero, so this check is excluded "
                "from the total rather than failed."
            ),
        )

    if not deltas:
        return CheckResult(
            check_id="a4_server_rendered",
            label="Meaningful content present in server-rendered HTML",
            points_awarded=0,
            max_points=5,
            suppressed=True,
            suppressed_reason="No page produced a usable rendering comparison.",
        )

    ratios = [(e, _ratio_from(e.raw)) for e in deltas]
    measured = [(e, r) for e, r in ratios if r is not None]
    if not measured:
        return CheckResult(
            check_id="a4_server_rendered",
            label="Meaningful content present in server-rendered HTML",
            points_awarded=0,
            max_points=5,
            suppressed=True,
            suppressed_reason="Rendering evidence was present but no ratio could be read.",
        )

    average = sum(r for _, r in measured) / len(measured)
    passed = average >= SERVER_RENDER_THRESHOLD

    return CheckResult(
        check_id="a4_server_rendered",
        label="Meaningful content present in server-rendered HTML",
        points_awarded=5 if passed else 0,
        max_points=5,
        evidence_refs=_refs(*[e for e, _ in measured[:6]]),
        detail=(
            f"Mean pre-JS/post-JS text ratio across {len(measured)} page(s) is "
            f"{average:.2f}; threshold is {SERVER_RENDER_THRESHOLD}. "
            + (
                "An agent without a browser sees most of the content."
                if passed
                else "An agent without a browser sees only a fragment of the content."
            )
        ),
    )


def check_semantic_html(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    landmarks = [e for e in store.by_kind("dom") if e.selector == "semantics#landmarks"]
    headings = [e for e in store.by_kind("dom") if e.selector == "semantics#headings"]

    if not landmarks:
        return CheckResult(
            check_id="a4_semantic_html",
            label="Semantic HTML: landmarks present, single-h1 hierarchy",
            points_awarded=0,
            max_points=4,
            suppressed=True,
            suppressed_reason="No page yielded a semantic-structure reading.",
        )

    pages_with_main = sum(
        1 for e in landmarks if "<main>=0" not in e.raw or "role=main:0" not in e.raw
    )
    has_main = any("<main>=0" not in e.raw for e in landmarks) or any(
        "role=main:0" not in e.raw for e in landmarks
    )
    has_nav = any("<nav>=0" not in e.raw for e in landmarks)
    single_h1 = any("1 <h1>" in e.raw for e in headings)
    no_skips = any("hierarchy skips: none" in e.raw for e in headings)

    satisfied = sum([has_main, has_nav, single_h1, no_skips])
    points = {4: 4, 3: 3, 2: 2, 1: 1, 0: 0}[satisfied]

    return CheckResult(
        check_id="a4_semantic_html",
        label="Semantic HTML: landmarks present, single-h1 hierarchy",
        points_awarded=points,
        max_points=4,
        evidence_refs=_refs(*landmarks[:4], *headings[:4]),
        detail=(
            f"main={has_main}, nav={has_nav}, single-h1={single_h1}, "
            f"clean-heading-hierarchy={no_skips} "
            f"({satisfied} of 4 satisfied across {len(landmarks)} page(s))."
        ),
    )


def check_text_not_locked_in_images(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    media = [e for e in store.by_kind("media")]
    if not media:
        return CheckResult(
            check_id="a4_text_in_images",
            label="Content is text, not text baked into images",
            points_awarded=0,
            max_points=3,
            suppressed=True,
            suppressed_reason="No page produced a media/text balance reading.",
        )

    failing = [
        e
        for e in media
        if "image-dominant" in e.raw or "largely undescribed" in e.raw
    ]
    passed = len(failing) < len(media) / 2

    return CheckResult(
        check_id="a4_text_in_images",
        label="Content is text, not text baked into images",
        points_awarded=3 if passed else 0,
        max_points=3,
        evidence_refs=_refs(*media[:6]),
        detail=(
            f"{len(media) - len(failing)} of {len(media)} page(s) are text-dominant or have "
            "adequately described imagery. Measured as a proxy — no OCR is performed."
        ),
    )


def check_crawlable_pagination(store: EvidenceStore, _: ScoringInput) -> CheckResult:
    crawlable = [
        e
        for e in store.by_kind("pagination")
        if e.selector in {"pagination#crawlable-urls", "pagination#rel"}
    ]
    infinite_only = [
        e
        for e in store.by_kind("pagination")
        if e.selector == "pagination#infinite-scroll" and "may be unreachable" in e.raw
    ]

    if crawlable:
        return CheckResult(
            check_id="a4_crawlable_pagination",
            label="Pagination uses stable, crawlable URLs",
            points_awarded=3,
            max_points=3,
            evidence_refs=_refs(*crawlable[:6]),
            detail="Listings can be enumerated by URL without executing JavaScript.",
        )

    if infinite_only:
        return CheckResult(
            check_id="a4_crawlable_pagination",
            label="Pagination uses stable, crawlable URLs",
            points_awarded=0,
            max_points=3,
            evidence_refs=_refs(*infinite_only[:4]),
            detail=(
                "Infinite scroll with no crawlable pagination URLs — results beyond the "
                "first screen are unreachable without a browser."
            ),
        )

    return CheckResult(
        check_id="a4_crawlable_pagination",
        label="Pagination uses stable, crawlable URLs",
        points_awarded=0,
        max_points=3,
        detail="No pagination controls were found on any crawled page.",
    )


CHECKS = (
    check_server_rendered,
    check_semantic_html,
    check_text_not_locked_in_images,
    check_crawlable_pagination,
)


def evaluate(store: EvidenceStore, scoring_input: ScoringInput) -> tuple[CheckResult, ...]:
    return tuple(check(store, scoring_input) for check in CHECKS)
