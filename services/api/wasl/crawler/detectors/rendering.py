"""Pre-JS vs post-JS rendering delta (Axis 4, 5 points — the headline signal).

This is the single most informative measurement Wasl takes. Everything else on
Axis 4 is a proxy; this is the thing itself. If a page's meaningful text only
exists after hydration, then every client that does not run a full browser — most
agents, most scrapers, most of the long tail of automation — sees an empty
document. That is what "invisible to agents" concretely means.

Meaningful text excludes `<script>`, `<style>`, `<noscript>` and comments,
because a 400KB React bundle in the raw response is not content an agent can
read, and counting it would make the worst offenders look best.

On a degraded capture there is no post-JS DOM to compare against. This detector
emits an explicit `unavailable` marker rather than a zero ratio, so Phase 3 can
suppress the check instead of scoring it — "we could not look" must not be
recorded as "we looked and found nothing".
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Comment

from wasl.crawler.evidence import Evidence
from wasl.crawler.types import CaptureMode, CapturedPage

_NON_CONTENT_TAGS = ("script", "style", "noscript", "template", "svg")

# Below this, a "page" has no content worth comparing and the ratio is noise.
MIN_MEANINGFUL_CHARS = 200


def meaningful_text(html: str) -> str:
    """Visible text with scripts, styles and comments stripped out."""
    if not html.strip():
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(_NON_CONTENT_TAGS):
        tag.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    return " ".join((soup.body or soup).get_text(" ", strip=True).split())


def detect(page: CapturedPage) -> list[Evidence]:
    pre_text = meaningful_text(page.pre_js_html)

    if page.mode is CaptureMode.DEGRADED or not page.post_js_html.strip():
        return [
            Evidence(
                source_url=page.final_url,
                kind="rendering",
                selector="rendering#unavailable",
                raw=(
                    "Pre-JS/post-JS comparison unavailable — this page was captured without "
                    "a browser, so the hydrated DOM was never observed. This check must be "
                    "SUPPRESSED rather than scored zero.\n"
                    f"pre-JS meaningful text: {len(pre_text)} chars"
                ),
                phase="pre_js",
            )
        ]

    post_text = meaningful_text(page.post_js_html)

    # Guard the denominator: an empty post-JS DOM means the capture failed, not
    # that the site is perfectly server-rendered.
    if len(post_text) < MIN_MEANINGFUL_CHARS:
        return [
            Evidence(
                source_url=page.final_url,
                kind="rendering",
                selector="rendering#insufficient-content",
                raw=(
                    f"Post-JS DOM holds only {len(post_text)} chars of meaningful text "
                    f"(pre-JS: {len(pre_text)}). Too little to compute a reliable ratio."
                ),
                phase="post_js",
            )
        ]

    ratio = len(pre_text) / len(post_text)

    if ratio >= 0.9:
        verdict = "server-rendered — an agent sees essentially the full content without JS"
    elif ratio >= 0.5:
        verdict = "partially server-rendered — an agent sees most content without JS"
    elif ratio >= 0.15:
        verdict = "mostly hydration-dependent — an agent without JS sees a fragment"
    else:
        verdict = "hydration-only — an agent without JS sees essentially nothing"

    return [
        Evidence(
            source_url=page.final_url,
            kind="rendering",
            selector="rendering#delta",
            raw=(
                f"pre-JS meaningful text: {len(pre_text)} chars\n"
                f"post-JS meaningful text: {len(post_text)} chars\n"
                f"ratio: {ratio:.3f}\n"
                f"verdict: {verdict}\n\n"
                f"pre-JS sample: {pre_text[:300] or '(empty)'}\n"
                f"post-JS sample: {post_text[:300]}"
            ),
            phase="post_js",
        )
    ]
