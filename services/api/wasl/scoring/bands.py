"""Grade bands.

Five bands, contiguous, no gaps. The boundaries are from the rubric spec and are
not tunable — moving a band edge to make a result read better is the single
easiest way to make a public score worthless.

Bands are computed on the *percentage*, not the raw total, so a degraded scan
with suppressed checks lands in the band its evidence actually supports rather
than being dragged down by points it was never able to earn.
"""

from __future__ import annotations

from enum import StrEnum


class Band(StrEnum):
    INVISIBLE = "Invisible"
    EMERGING = "Emerging"
    READABLE = "Readable"
    AGENT_READY = "Agent-Ready"
    AGENT_NATIVE = "Agent-Native"


# (inclusive lower bound, inclusive upper bound, band)
BAND_RANGES: tuple[tuple[int, int, Band], ...] = (
    (0, 24, Band.INVISIBLE),
    (25, 44, Band.EMERGING),
    (45, 64, Band.READABLE),
    (65, 84, Band.AGENT_READY),
    (85, 100, Band.AGENT_NATIVE),
)

BAND_DESCRIPTIONS: dict[Band, str] = {
    Band.INVISIBLE: (
        "An agent cannot meaningfully read or act on this site. Content is "
        "unavailable without a browser, and there are no machine-readable identifiers."
    ),
    Band.EMERGING: (
        "Some structure is present but an agent would need to guess. Basic metadata "
        "exists; capabilities are not exposed in any usable form."
    ),
    Band.READABLE: (
        "An agent can read this site reliably but cannot do much with it. Content and "
        "structured data are accessible; there is no documented capability surface."
    ),
    Band.AGENT_READY: (
        "An agent can both read the site and act against a documented surface. Stable "
        "identifiers and an API or spec make workflows possible."
    ),
    Band.AGENT_NATIVE: (
        "Built for machine consumption. Specs, manifests, structured data and stable "
        "identifiers are all present and consistent."
    ),
}


def band_for(percentage: float) -> Band:
    """Map a 0-100 percentage to its band.

    Rounds to the nearest whole point first so that 24.6 lands in Emerging rather
    than Invisible — the displayed number and the band must agree, or the report
    looks broken to anyone who checks.
    """
    value = max(0, min(100, round(percentage)))
    for low, high, band in BAND_RANGES:
        if low <= value <= high:
            return band
    raise AssertionError(f"unreachable: {value} fell outside every band")  # pragma: no cover


def describe(band: Band) -> str:
    return BAND_DESCRIPTIONS[band]
