"""Text-in-image and alt-coverage evidence (Axis 4, 3 points).

The check the rubric asks for is "text-in-image ratio below threshold". Actually
reading text out of images would need OCR, which is not in the dependency list
and would be a heavy, error-prone way to answer a question we can answer well
enough from markup.

So this measures the observable proxy, and says so plainly rather than implying
more precision than it has: how much of the page's substance is carried by images
versus text nodes, and whether those images have alt text. An image-heavy page
with no alt attributes is unreadable to an agent whether or not the images
contain words — which is the outcome the check exists to catch.

Stated as a limitation in the README rather than hidden.
"""

from __future__ import annotations

from bs4 import BeautifulSoup
from bs4.element import Tag

from wasl.crawler.evidence import Evidence
from wasl.crawler.types import CapturedPage
from wasl.crawler.detectors.rendering import meaningful_text

# Images below this size are icons and spacers, not content.
_MIN_CONTENT_DIMENSION = 100

_DECORATIVE_HINTS = ("icon", "logo", "sprite", "spacer", "pixel", "avatar", "bullet", "arrow")


def _is_probably_content(img: Tag) -> bool:
    """Filter out chrome so the ratio describes content, not the design system."""
    for attr in ("width", "height"):
        raw = img.get(attr)
        if isinstance(raw, str) and raw.strip().isdigit():
            if int(raw.strip()) < _MIN_CONTENT_DIMENSION:
                return False

    haystack = " ".join(
        str(img.get(a, "")) for a in ("src", "class", "id", "alt", "role")
    ).lower()
    if any(hint in haystack for hint in _DECORATIVE_HINTS):
        return False
    if img.get("role") == "presentation" or img.get("aria-hidden") == "true":
        return False
    return True


def detect(page: CapturedPage) -> list[Evidence]:
    phases = page.available_phases
    phase = "post_js" if "post_js" in phases else "pre_js"
    html = page.html_for(phase)
    if not html.strip():
        return []

    soup = BeautifulSoup(html, "lxml")
    text = meaningful_text(html)

    all_images = [img for img in soup.find_all("img") if isinstance(img, Tag)]
    content_images = [img for img in all_images if _is_probably_content(img)]

    with_alt = [img for img in content_images if str(img.get("alt", "")).strip()]
    empty_alt = [img for img in content_images if img.has_attr("alt") and not str(img.get("alt", "")).strip()]
    missing_alt = [img for img in content_images if not img.has_attr("alt")]

    # Rough proxy: how much text would each content image need to carry for the
    # page to be image-dominant? Low text with many images is the failure shape.
    text_chars = len(text)
    images_per_kb = (len(content_images) / max(text_chars / 1000, 0.1)) if content_images else 0.0

    alt_coverage = len(with_alt) / len(content_images) if content_images else 1.0

    if images_per_kb >= 4 and text_chars < 1500:
        verdict = "image-dominant — little machine-readable text relative to imagery"
    elif alt_coverage < 0.5 and len(content_images) >= 5:
        verdict = "imagery is largely undescribed — alt coverage below 50%"
    else:
        verdict = "text-dominant or adequately described"

    return [
        Evidence(
            source_url=page.final_url,
            kind="media",
            selector="media#text-image-balance",
            raw=(
                "Proxy measurement for text-in-image (no OCR is performed; this reports "
                "the ratio of content imagery to machine-readable text and its alt coverage).\n"
                f"meaningful text: {text_chars} chars\n"
                f"images: {len(all_images)} total, {len(content_images)} judged content-bearing\n"
                f"alt text: {len(with_alt)} present, {len(empty_alt)} empty, {len(missing_alt)} missing\n"
                f"alt coverage: {alt_coverage:.0%}\n"
                f"content images per 1k chars of text: {images_per_kb:.2f}\n"
                f"verdict: {verdict}\n"
                + "\n".join(
                    f"  missing alt: {str(img.get('src', ''))[:120]}" for img in missing_alt[:8]
                )
            ),
            phase=phase,
        )
    ]
