"""HTTP header and canonical evidence (Axis 1 canonicals, Axis 5 gating, Axis 6 rate limits).

The rate-limit check here is **passive and must stay that way**. It reports the
headers a site volunteered during an ordinary polite crawl. It never probes,
never bursts, never sends a request whose purpose is to see whether we get a 429.
Manufacturing a rate-limit response to earn two points would mean deliberately
degrading someone's service for our own score, which is exactly the behaviour the
rest of this crawler exists to avoid.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from wasl.crawler.evidence import Evidence
from wasl.crawler.types import CapturedPage

RATE_LIMIT_HEADERS = (
    "retry-after",
    "ratelimit",
    "ratelimit-limit",
    "ratelimit-remaining",
    "ratelimit-reset",
    "ratelimit-policy",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "x-rate-limit-limit",
)

AUTH_HEADERS = ("www-authenticate", "x-api-key", "authorization")

# Fingerprints for interstitials that block a discovery path. Matched against
# markup and headers, never triggered on purpose.
_CAPTCHA_MARKERS = re.compile(
    r"(recaptcha|hcaptcha|turnstile|cf-challenge|challenge-platform|"
    r"px-captcha|perimeterx|datadome|incapsula|distil_r_captcha|"
    r"just\s+a\s+moment|checking\s+your\s+browser|verify\s+you\s+are\s+human|"
    r"enable\s+javascript\s+and\s+cookies\s+to\s+continue)",
    re.IGNORECASE,
)

_CDN_CHALLENGE_HEADERS = ("cf-mitigated", "x-datadome", "x-px-block")


def detect(page: CapturedPage) -> list[Evidence]:
    evidence: list[Evidence] = []
    lower = {k.lower(): v for k, v in page.headers.items()}

    # --- canonical (Axis 1) --------------------------------------------------
    canonical = None
    for phase in page.available_phases:
        soup = BeautifulSoup(page.html_for(phase), "lxml")
        link = soup.find("link", rel=lambda v: bool(v) and "canonical" in str(v).lower())
        if link and link.get("href"):
            canonical = str(link["href"])
            evidence.append(
                Evidence(
                    source_url=page.final_url,
                    kind="link",
                    selector="link[rel=canonical]",
                    raw=f'<link rel="canonical" href="{canonical}">',
                    phase=phase,
                )
            )
            break

    if canonical is None and "link" in lower and "canonical" in lower["link"].lower():
        canonical = lower["link"]
        evidence.append(
            Evidence(
                source_url=page.final_url,
                kind="header",
                selector="header#link-canonical",
                raw=f"Link: {lower['link']}",
                phase="pre_js",
            )
        )

    if canonical is None:
        evidence.append(
            Evidence(
                source_url=page.final_url,
                kind="link",
                selector="link[rel=canonical]#absent",
                raw="No canonical URL declared in markup or Link header.",
                phase="pre_js",
            )
        )

    # --- rate limiting, observed passively (Axis 6) --------------------------
    observed = {name: lower[name] for name in RATE_LIMIT_HEADERS if name in lower}
    if observed:
        evidence.append(
            Evidence(
                source_url=page.final_url,
                kind="header",
                selector="header#rate-limit",
                raw=(
                    "Rate-limit headers observed during the normal polite crawl "
                    "(no probing was performed):\n"
                    + "\n".join(f"  {k}: {v}" for k, v in observed.items())
                ),
                phase="pre_js",
            )
        )

    # --- machine auth surface (Axis 6) ---------------------------------------
    auth = {name: lower[name] for name in AUTH_HEADERS if name in lower}
    if auth:
        evidence.append(
            Evidence(
                source_url=page.final_url,
                kind="header",
                selector="header#auth",
                raw="\n".join(f"{k}: {v}" for k, v in auth.items()),
                phase="pre_js",
            )
        )

    # --- CAPTCHA / interstitial (Axis 5) -------------------------------------
    challenge_header = next((h for h in _CDN_CHALLENGE_HEADERS if h in lower), None)
    markup_hit = None
    for phase in page.available_phases:
        found = _CAPTCHA_MARKERS.search(page.html_for(phase)[:200_000])
        if found:
            markup_hit = (phase, found.group(0))
            break

    if challenge_header or markup_hit or page.status_code in {403, 429, 503}:
        details = []
        if challenge_header:
            details.append(f"challenge header {challenge_header}: {lower[challenge_header]}")
        if markup_hit:
            details.append(f"markup marker {markup_hit[1]!r} in {markup_hit[0]}")
        if page.status_code in {403, 429, 503}:
            details.append(f"HTTP {page.status_code}")
        evidence.append(
            Evidence(
                source_url=page.final_url,
                kind="header",
                selector="header#interstitial",
                raw="Discovery path appears gated: " + "; ".join(details),
                phase=markup_hit[0] if markup_hit else "pre_js",
            )
        )

    # --- the raw response line, always kept ----------------------------------
    interesting = {
        k: v
        for k, v in lower.items()
        if k
        in {
            "content-type", "server", "cache-control", "x-powered-by",
            "vary", "content-language", "x-robots-tag",
        }
    }
    evidence.append(
        Evidence(
            source_url=page.final_url,
            kind="header",
            selector="header#response",
            raw=(
                f"HTTP {page.status_code} in {page.response_time_ms}ms"
                f"{f' (redirected from {page.url})' if page.redirected else ''}\n"
                + "\n".join(f"{k}: {v}" for k, v in sorted(interesting.items()))
            ),
            phase="pre_js",
        )
    )

    return evidence
