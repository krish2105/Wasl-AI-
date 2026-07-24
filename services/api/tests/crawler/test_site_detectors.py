"""Site-level detectors: robots.txt, sitemap, llms.txt, .well-known, OpenAPI.

Two themes run through these tests.

**Absence is a result.** Every one of these detectors must emit evidence when it
finds nothing, because "no llms.txt" is exactly what Axis 1 wants to know and a
silent detector is indistinguishable from a broken one.

**A 200 is not a yes.** Single-page apps serve their HTML shell for every
unmatched path, so a naive presence check hands out points for having a router.
Each detector validates the payload shape, and the SPA-shell case is tested
explicitly.
"""

from __future__ import annotations

import json

from wasl.crawler.detectors import llmstxt, openapi, robots_txt, sitemap, wellknown
from wasl.crawler.robots import parse_robots
from wasl.crawler.types import FetchedResource, RobotsInfo, SiteArtifacts

ROOT = "https://example.com"
SPA_SHELL = '<!DOCTYPE html><html><head><title>App</title></head><body><div id="root"></div></body></html>'


def artifacts(**overrides) -> SiteArtifacts:
    payload = {
        "root_url": ROOT,
        "domain": "example.com",
        "robots": RobotsInfo(url=f"{ROOT}/robots.txt", present=False, parseable=False),
    }
    payload.update(overrides)
    return SiteArtifacts(**payload)  # type: ignore[arg-type]


def resource(path: str, text: str, status: int = 200) -> FetchedResource:
    return FetchedResource(url=f"{ROOT}{path}", status_code=status, text=text)


def selectors(evidence) -> list[str]:
    return [e.selector or "" for e in evidence]


def joined(evidence) -> str:
    return "\n".join(e.raw for e in evidence)


# --- robots.txt --------------------------------------------------------------

ROBOTS_WITH_AI = """\
User-agent: *
Disallow: /admin
Crawl-delay: 5

User-agent: GPTBot
Disallow: /

User-agent: ClaudeBot
Allow: /

Sitemap: https://example.com/sitemap.xml
"""


def test_ai_agent_stanzas_are_extracted() -> None:
    info = parse_robots(ROBOTS_WITH_AI, url=f"{ROOT}/robots.txt")
    assert set(info.ai_agent_stanzas) == {"GPTBot", "ClaudeBot"}
    assert info.sitemaps == ("https://example.com/sitemap.xml",)
    assert info.crawl_delay == 5.0


def test_a_disallowing_ai_stanza_still_counts_as_a_stanza() -> None:
    """Clarity scores, not the verdict. A site is never penalised for saying no."""
    info = parse_robots(ROBOTS_WITH_AI, url=f"{ROOT}/robots.txt")
    found = robots_txt.detect(artifacts(robots=info))

    gptbot = [e for e in found if e.selector and "GPTBot" in e.selector]
    assert len(gptbot) == 1
    assert "Disallow: /" in gptbot[0].raw


def test_robots_without_an_ai_stanza_yields_none() -> None:
    info = parse_robots("User-agent: *\nDisallow:\n", url=f"{ROOT}/robots.txt")
    assert info.ai_agent_stanzas == ()
    found = robots_txt.detect(artifacts(robots=info))
    assert not [s for s in selectors(found) if "user-agent:" in s]


def test_absent_robots_is_recorded_as_evidence() -> None:
    found = robots_txt.detect(artifacts())
    assert selectors(found) == ["robots.txt#absent"]


# --- sitemap -----------------------------------------------------------------

SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/a</loc><lastmod>2026-01-01</lastmod></url>
  <url><loc>https://example.com/b</loc></url>
</urlset>"""


def test_sitemap_urls_are_parsed_and_counted() -> None:
    found = sitemap.detect(artifacts(sitemaps=(resource("/sitemap.xml", SITEMAP_XML),)))
    assert "sitemap#present" in selectors(found)
    assert "2 <loc> entries" in joined(found)
    assert "1 with <lastmod>" in joined(found)


def test_sitemap_index_is_labelled_as_such() -> None:
    index = '<?xml version="1.0"?><sitemapindex><sitemap><loc>https://example.com/s1.xml</loc></sitemap></sitemapindex>'
    found = sitemap.detect(artifacts(sitemaps=(resource("/sitemap.xml", index),)))
    assert "sitemap index reachable" in joined(found)


def test_malformed_sitemap_still_yields_its_urls() -> None:
    """Sitemaps in the wild are frequently invalid XML; a strict parse loses them."""
    broken = "<urlset><url><loc>https://example.com/a</loc></urlset>"
    assert sitemap.parse_urls(broken) == ["https://example.com/a"]


def test_absent_sitemap_is_recorded() -> None:
    assert selectors(sitemap.detect(artifacts())) == ["sitemap#absent"]


# --- llms.txt ----------------------------------------------------------------

LLMS_TXT = """# Example Co

> Industrial supplier operating across the UAE.

## Catalogue
- [Products](https://example.com/catalogue): full product listing
- [API](https://example.com/api-reference): public REST API
"""


def test_real_llms_txt_is_detected() -> None:
    found = llmstxt.detect(artifacts(llms_txt=resource("/llms.txt", LLMS_TXT)))
    assert selectors(found) == ["llms.txt#present"]
    assert "1 H1, 2 links" in joined(found)


def test_spa_shell_served_at_llms_txt_is_not_counted() -> None:
    """A 200 from a catch-all route must not earn the four points."""
    found = llmstxt.detect(artifacts(llms_txt=resource("/llms.txt", SPA_SHELL)))
    assert selectors(found) == ["llms.txt#not-markdown"]


def test_absent_llms_txt_is_recorded() -> None:
    found = llmstxt.detect(artifacts(llms_txt=resource("/llms.txt", "", status=404)))
    assert selectors(found) == ["llms.txt#absent"]


# --- .well-known -------------------------------------------------------------


def test_agent_manifest_is_detected() -> None:
    manifest = json.dumps({"protocolVersion": "2025-06-18", "tools": [{"name": "search"}]})
    found = wellknown.detect(artifacts(wellknown=(resource("/.well-known/mcp.json", manifest),)))
    assert any("#manifest" in s for s in selectors(found))


def test_spa_shell_at_a_wellknown_path_is_rejected() -> None:
    found = wellknown.detect(artifacts(wellknown=(resource("/.well-known/mcp.json", SPA_SHELL),)))
    assert any("#not-a-manifest" in s for s in selectors(found))
    assert "catch-all route" in joined(found)


def test_json_without_agent_keys_is_rejected() -> None:
    found = wellknown.detect(
        artifacts(wellknown=(resource("/.well-known/mcp.json", '{"hello":"world"}'),))
    )
    assert any("#not-a-manifest" in s for s in selectors(found))


def test_security_txt_is_recorded_but_is_not_a_manifest() -> None:
    found = wellknown.detect(
        artifacts(
            wellknown=(resource("/.well-known/security.txt", "Contact: mailto:s@example.com"),)
        )
    )
    assert "wellknown#absent" in selectors(found)
    assert any("security.txt" in s for s in selectors(found))


def test_no_wellknown_probes_hitting_yields_an_absent_row() -> None:
    assert "wellknown#absent" in selectors(wellknown.detect(artifacts()))


# --- openapi specs -----------------------------------------------------------

SPEC = json.dumps(
    {
        "openapi": "3.0.0",
        "info": {"title": "Example API", "version": "1.2"},
        "paths": {
            "/products": {"get": {}},
            "/products/{id}": {"get": {}},
            "/orders": {"get": {}, "post": {}},
        },
    }
)


def test_real_openapi_spec_is_parsed_and_summarised() -> None:
    found = openapi.detect_specs(artifacts(openapi_candidates=(resource("/openapi.json", SPEC),)))
    assert "openapi#spec" in selectors(found)
    raw = joined(found)
    assert "Example API" in raw
    assert "3 paths, 4 operations" in raw


def test_yaml_spec_is_recognised() -> None:
    yaml_spec = "openapi: 3.0.0\ninfo:\n  title: X\npaths:\n  /a:\n    get: {}\n"
    found = openapi.detect_specs(
        artifacts(openapi_candidates=(resource("/openapi.yaml", yaml_spec),))
    )
    assert "openapi#spec" in selectors(found)


def test_html_page_at_a_spec_path_is_not_a_spec() -> None:
    """This is the hard negative: an /api-docs marketing page earns 3 points, never 6."""
    found = openapi.detect_specs(artifacts(openapi_candidates=(resource("/api-docs", SPA_SHELL),)))
    assert "openapi#not-a-spec" in selectors(found)
    assert "openapi#spec" not in selectors(found)


def test_json_without_an_openapi_version_is_not_a_spec() -> None:
    found = openapi.detect_specs(
        artifacts(openapi_candidates=(resource("/openapi.json", '{"paths": {}}'),))
    )
    assert "openapi#not-a-spec" in selectors(found)


def test_no_spec_found_is_recorded_with_the_paths_probed() -> None:
    found = openapi.detect_specs(artifacts())
    assert "openapi#no-spec" in selectors(found)
    assert "/openapi.json" in joined(found)
