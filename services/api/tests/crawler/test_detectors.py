"""Detectors, against saved fixtures.

Each detector gets a passing case and a failing case, because a detector that
only ever sees good input is untested — most scoring bugs are false positives on
thin sites, not false negatives on rich ones.

Three fixtures carry most of it:
  rich_site  — structured, server-rendered, stable IDs, GET search, pagination
  thin_site  — real brochureware: content, but nothing machine-actionable
  spa_site   — hydration-only, infinite scroll, empty pre-JS DOM
"""

from __future__ import annotations

import pytest

from tests.conftest import captured
from wasl.crawler.detectors import (
    forms,
    headers,
    identifiers,
    injection,
    jsonld,
    media,
    openapi,
    pagination,
    rendering,
    semantics,
)


def selectors(evidence) -> list[str]:
    return [e.selector or "" for e in evidence]


def joined(evidence) -> str:
    return "\n".join(e.raw for e in evidence)


# --- jsonld ------------------------------------------------------------------


def test_jsonld_finds_every_entity_type_including_nested() -> None:
    found = jsonld.detect(captured("rich_site"))
    types = {s.split("#")[-1] for s in selectors(found)}

    assert {"Organization", "Product", "Offer", "FAQPage"} <= types
    # Offer is nested inside Product — flat extraction would miss it.
    assert "Offer" in types


def test_jsonld_finds_nothing_on_a_site_without_it() -> None:
    assert jsonld.detect(captured("thin_site", degraded=True)) == []


def test_jsonld_prefers_the_hydrated_dom() -> None:
    """Sites inject structured data via tag managers; judging pre-JS understates them."""
    page = captured("rich_site")
    found = jsonld.detect(page)
    assert any(e.phase == "post_js" for e in found)


# --- forms -------------------------------------------------------------------


def test_get_search_form_is_recorded_as_a_capability() -> None:
    found = forms.detect(captured("rich_site"))
    assert any("#get#search" in (s or "") for s in selectors(found))
    assert "an agent can construct this URL directly" in joined(found)


def test_post_form_is_recorded_but_flagged_as_never_submitted() -> None:
    found = forms.detect(captured("thin_site", degraded=True))
    assert any("#post#" in (s or "") for s in selectors(found))
    assert "never submitted" in joined(found)


def test_form_label_coverage_is_measured() -> None:
    rich = joined(forms.detect(captured("rich_site")))
    thin = joined(forms.detect(captured("thin_site", degraded=True)))

    assert "100% label coverage" in rich
    assert "0% label coverage" in thin


# --- semantics ---------------------------------------------------------------


def test_semantic_landmarks_are_counted() -> None:
    found = joined(semantics.detect(captured("rich_site")))
    assert "<main>=1" in found
    assert "<article>=3" in found
    assert "<nav>=2" in found


def test_div_soup_reports_no_landmarks() -> None:
    found = joined(semantics.detect(captured("thin_site", degraded=True)))
    assert "<main>=0" in found
    assert "<article>=0" in found


def test_heading_hierarchy_is_recorded() -> None:
    found = joined(semantics.detect(captured("rich_site")))
    assert "1 <h1>" in found
    assert "hierarchy skips: none" in found


# --- rendering (the headline Axis 4 signal) ----------------------------------


def test_server_rendered_site_scores_a_high_ratio() -> None:
    found = rendering.detect(captured("rich_site"))
    assert len(found) == 1
    assert "server-rendered" in found[0].raw


def test_hydration_only_site_is_caught() -> None:
    """The pre-JS DOM is an empty root div; this is what an agent actually sees."""
    found = rendering.detect(captured("spa_site"))
    assert "hydration-only" in found[0].raw
    assert "ratio: 0.0" in found[0].raw


def test_degraded_capture_is_suppressed_not_scored_zero() -> None:
    """'We could not look' must never be recorded as 'we looked and found nothing'."""
    found = rendering.detect(captured("rich_site", degraded=True))
    assert selectors(found) == ["rendering#unavailable"]
    assert "SUPPRESSED rather than scored zero" in found[0].raw


# --- identifiers -------------------------------------------------------------


def test_structured_identifiers_are_extracted() -> None:
    found = joined(identifiers.detect(captured("rich_site")))
    assert "sku = NSC-BCE-22" in found
    assert "productID = 884213" in found


def test_stable_url_patterns_are_generalised_and_counted() -> None:
    found = identifiers.detect(captured("rich_site"))
    patterns = [s for s in selectors(found) if s.startswith("url-pattern#")]
    assert any("/product/{id}" in p for p in patterns)
    assert "3 distinct link(s)" in joined(found)


def test_no_identifiers_on_a_brochureware_site() -> None:
    found = identifiers.detect(captured("thin_site", degraded=True))
    assert found == []


# --- pagination --------------------------------------------------------------


def test_crawlable_pagination_is_detected() -> None:
    found = pagination.detect(captured("rich_site"))
    assert "pagination#crawlable-urls" in selectors(found)
    assert "pagination#rel" in selectors(found)


def test_infinite_scroll_without_crawlable_urls_is_flagged() -> None:
    found = pagination.detect(captured("spa_site"))
    raw = joined(found)
    assert "pagination#infinite-scroll" in selectors(found)
    assert "may be unreachable without a browser" in raw


def test_page_with_no_pagination_says_so_explicitly() -> None:
    found = pagination.detect(captured("thin_site", degraded=True))
    assert selectors(found) == ["pagination#none"]


# --- headers -----------------------------------------------------------------


def test_canonical_link_is_found() -> None:
    found = headers.detect(captured("rich_site"))
    assert "link[rel=canonical]" in selectors(found)


def test_missing_canonical_is_recorded_as_absent() -> None:
    found = headers.detect(captured("thin_site", degraded=True))
    assert "link[rel=canonical]#absent" in selectors(found)


def test_rate_limit_headers_are_recorded_passively() -> None:
    page = captured(
        "rich_site",
        headers={"content-type": "text/html", "retry-after": "120", "x-ratelimit-limit": "1000"},
    )
    found = headers.detect(page)
    raw = joined(found)
    assert "header#rate-limit" in selectors(found)
    assert "no probing was performed" in raw


def test_captcha_interstitial_is_detected() -> None:
    page = captured("thin_site", degraded=True, headers={"cf-mitigated": "challenge"})
    assert "header#interstitial" in selectors(headers.detect(page))


def test_a_403_is_treated_as_a_gated_discovery_path() -> None:
    page = captured("thin_site", degraded=True, status_code=403)
    found = headers.detect(page)
    assert "header#interstitial" in selectors(found)
    assert "HTTP 403" in joined(found)


# --- media -------------------------------------------------------------------


def test_described_imagery_passes() -> None:
    found = joined(media.detect(captured("rich_site")))
    assert "alt coverage: 100%" in found
    assert "text-dominant or adequately described" in found


def test_undescribed_image_heavy_page_is_flagged() -> None:
    found = joined(media.detect(captured("thin_site", degraded=True)))
    assert "alt coverage: 0%" in found
    assert "image-dominant" in found or "largely undescribed" in found


def test_media_detector_states_it_does_not_ocr() -> None:
    """The rubric asks for text-in-image; we measure a proxy and must say so."""
    assert "no OCR is performed" in joined(media.detect(captured("rich_site")))


# --- openapi page links ------------------------------------------------------


def test_api_documentation_links_are_found() -> None:
    found = joined(openapi.detect_page_links(captured("rich_site")))
    assert "/api-reference" in found
    assert "/developers" in found


def test_no_api_links_on_a_brochureware_site() -> None:
    assert openapi.detect_page_links(captured("thin_site", degraded=True)) == []


# --- injection ---------------------------------------------------------------


def test_clean_page_records_that_it_was_scanned() -> None:
    """'Scanned, found nothing' and 'never scanned' are different claims."""
    found = injection.detect(captured("rich_site"))
    assert selectors(found) == ["injection#clean"]
    assert "pattern set v" in found[0].raw


def test_seeded_payloads_are_all_detected() -> None:
    """Injection-detection recall against the hand-written ground truth."""
    import yaml

    from tests.conftest import FIXTURES

    page = captured("injection_payloads", degraded=True)
    expected = yaml.safe_load((FIXTURES / "injection_payloads.expected.yaml").read_text())
    want = {p["pattern_id"] for p in expected["payloads"]}

    found = injection.detect(page)
    got = {(s or "").split("#")[1] for s in selectors(found) if "#" in (s or "")}

    missed = want - got
    assert not missed, f"injection recall below 1.00 — missed: {sorted(missed)}"
