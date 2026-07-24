"""Full extraction pass: every detector over a whole crawl.

This is where referential integrity is actually exercised. Individual detector
tests prove each one emits sensible evidence; this proves that when all fifteen
run together the store stays consistent, IDs deduplicate across pages, and
nothing produces a citation that cannot be resolved.
"""

from __future__ import annotations

import json

from tests.conftest import captured
from wasl.crawler.detectors import extract_all, run_page_detectors, run_site_detectors
from wasl.crawler.evidence import EvidenceStore
from wasl.crawler.robots import parse_robots
from wasl.crawler.types import FetchedResource, RobotsInfo, SiteArtifacts

ROOT = "https://nadisupply.example"


def site_artifacts() -> SiteArtifacts:
    return SiteArtifacts(
        root_url=ROOT,
        domain="nadisupply.example",
        robots=parse_robots(
            "User-agent: *\nDisallow: /admin\n\nUser-agent: GPTBot\nAllow: /\n"
            f"Sitemap: {ROOT}/sitemap.xml\n",
            url=f"{ROOT}/robots.txt",
        ),
        llms_txt=FetchedResource(
            url=f"{ROOT}/llms.txt",
            status_code=200,
            text="# Nadi Supply Co\n\n> Industrial fittings.\n\n- [Catalogue](/catalogue): products\n- [API](/api): rest api\n",
        ),
        sitemaps=(
            FetchedResource(
                url=f"{ROOT}/sitemap.xml",
                status_code=200,
                text=f"<urlset><url><loc>{ROOT}/catalogue</loc></url></urlset>",
            ),
        ),
        openapi_candidates=(
            FetchedResource(
                url=f"{ROOT}/openapi.json",
                status_code=200,
                text=json.dumps(
                    {"openapi": "3.0.0", "info": {"title": "Nadi API", "version": "1"},
                     "paths": {"/products": {"get": {}}}}
                ),
            ),
        ),
    )


def test_extraction_runs_every_detector_over_a_crawl() -> None:
    pages = [
        captured("rich_site", url=f"{ROOT}/catalogue"),
        captured("spa_site", url=f"{ROOT}/listings"),
    ]

    store = extract_all(pages, site_artifacts())

    kinds = set(store.kind_counts())
    # One kind per major evidence family — if any is missing a detector silently died.
    assert {"robots", "sitemap", "llmstxt", "openapi", "jsonld", "form", "dom",
            "identifier", "rendering", "header", "pagination", "media",
            "injection", "link"} <= kinds


def test_every_evidence_id_resolves_in_its_own_store() -> None:
    """The mechanism behind citation_validity == 1.00."""
    store = extract_all([captured("rich_site")], site_artifacts())
    assert store.verify_references([e.id for e in store]) == []


def test_identical_evidence_across_pages_deduplicates() -> None:
    """Content-addressed IDs mean the same nav on two pages is stored once."""
    page = captured("rich_site", url=f"{ROOT}/catalogue")
    once = extract_all([page], site_artifacts())
    twice = extract_all([page, page], site_artifacts())

    assert len(once) == len(twice)


def test_different_pages_produce_distinct_evidence() -> None:
    store = extract_all(
        [captured("rich_site", url=f"{ROOT}/a"), captured("rich_site", url=f"{ROOT}/b")],
        site_artifacts(),
    )
    assert len(store.by_url(f"{ROOT}/a")) > 0
    assert len(store.by_url(f"{ROOT}/b")) > 0


def test_a_failing_detector_does_not_lose_the_others() -> None:
    """One malformed page must not zero out a whole crawl's evidence."""
    broken = captured("rich_site")
    object.__setattr__(broken, "post_js_html", "<html><body>" + "<div>" * 200)

    evidence = run_page_detectors(broken)

    assert len(evidence) > 0


def test_failed_pages_contribute_no_evidence() -> None:
    """A page we never successfully fetched must not generate findings about itself."""
    good = captured("rich_site", url=f"{ROOT}/a")
    failed = captured("rich_site", url=f"{ROOT}/b", status_code=0)
    object.__setattr__(failed, "fetch_error", "timeout")

    store = extract_all([good, failed], site_artifacts())

    assert store.by_url(f"{ROOT}/b") == []


def test_site_detectors_run_once_regardless_of_page_count() -> None:
    artifacts = site_artifacts()
    site_evidence = EvidenceStore(run_site_detectors(artifacts))

    store = extract_all([captured("rich_site")] * 3, artifacts)

    for evidence in site_evidence:
        assert evidence.id in store


def test_spa_site_extraction_reports_the_hydration_problem() -> None:
    store = extract_all([captured("spa_site", url=f"{ROOT}/listings")], site_artifacts())
    rendering = [e for e in store.by_kind("rendering")]
    assert rendering
    assert "hydration-only" in rendering[0].raw
