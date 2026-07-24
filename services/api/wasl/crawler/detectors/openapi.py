"""OpenAPI and API-documentation evidence (Axis 3, 6 + 3 points).

Two separate checks, deliberately weighted differently:

- **A discoverable spec (6 pts)** — a machine can read it and build a client with
  no human in the loop. This is the real thing.
- **Documented API without a spec (3 pts)** — a human can build a client. Useful,
  but an agent still needs a person to translate the docs first.

The distinction is the whole point of the axis, so this detector is careful not
to collapse them. A marketing page at `/api` that describes an API in prose earns
the 3, never the 6 — which is also the hard-negative case the golden set needs to
cover.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from wasl.crawler.evidence import Evidence
from wasl.crawler.types import CapturedPage, FetchedResource, SiteArtifacts

# Probed once per site. Ordered by how conventional they are.
OPENAPI_PROBE_PATHS: tuple[str, ...] = (
    "/openapi.json",
    "/openapi.yaml",
    "/swagger.json",
    "/api-docs",
    "/api/openapi.json",
    "/api/swagger.json",
    "/api/v1/openapi.json",
    "/v1/openapi.json",
    "/docs/openapi.json",
    "/.well-known/openapi.json",
)

_DOC_LINK_HINT = re.compile(
    r"(^|[/.\-_])(api|apis|developer|developers|dev-portal|swagger|openapi|graphql|"
    r"api-reference|api-docs|for-developers)([/.\-_?#]|$)",
    re.IGNORECASE,
)

_DOC_TEXT_HINT = re.compile(
    r"\b(api\s+(reference|documentation|docs|guide)|developer\s+(portal|docs|hub|centre|center)|"
    r"rest\s+api|graphql\s+api|api\s+key)\b",
    re.IGNORECASE,
)

_SPEC_YAML_HINT = re.compile(r"^\s*(openapi|swagger)\s*:\s*[\"']?\d", re.IGNORECASE | re.MULTILINE)


def _parse_spec(text: str) -> dict | None:
    """Return the spec as a dict if this really is OpenAPI/Swagger, else None."""
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict) and ("openapi" in payload or "swagger" in payload):
            return payload
        return None

    # YAML specs are common. We avoid a YAML parse here — a version line plus a
    # paths block is enough to identify one, and parsing arbitrary remote YAML is
    # a larger attack surface than this check is worth.
    if _SPEC_YAML_HINT.search(stripped) and re.search(r"^\s*paths\s*:", stripped, re.MULTILINE):
        return {"_format": "yaml"}
    return None


def _describe(spec: dict, resource: FetchedResource) -> str:
    if spec.get("_format") == "yaml":
        return f"OpenAPI/Swagger YAML spec at {resource.url}\n\n{resource.text[:1500]}"

    version = spec.get("openapi") or spec.get("swagger") or "unknown"
    info = spec.get("info") or {}
    paths = spec.get("paths") or {}
    operations = sum(
        1
        for methods in paths.values()
        if isinstance(methods, dict)
        for m in methods
        if m.lower() in {"get", "post", "put", "patch", "delete"}
    )
    return (
        f"OpenAPI {version} spec: {info.get('title', 'untitled')} "
        f"v{info.get('version', '?')}, {len(paths)} paths, {operations} operations.\n"
        + "\n".join(sorted(paths)[:25])
    )


def detect_specs(artifacts: SiteArtifacts) -> list[Evidence]:
    """Site-level: did any probed path yield a real machine-readable spec?"""
    evidence: list[Evidence] = []
    found = False

    for resource in artifacts.openapi_candidates:
        if not resource.found:
            continue
        spec = _parse_spec(resource.text)
        if spec is None:
            evidence.append(
                Evidence(
                    source_url=resource.url,
                    kind="openapi",
                    selector="openapi#not-a-spec",
                    raw=(
                        f"HTTP {resource.status_code} at {resource.url} but the body is not "
                        f"an OpenAPI/Swagger document. Not counted."
                    ),
                    phase="pre_js",
                )
            )
            continue

        found = True
        evidence.append(
            Evidence(
                source_url=resource.url,
                kind="openapi",
                selector="openapi#spec",
                raw=_describe(spec, resource),
                phase="pre_js",
            )
        )

    if not found:
        evidence.append(
            Evidence(
                source_url=artifacts.root_url,
                kind="openapi",
                selector="openapi#no-spec",
                raw="No OpenAPI/Swagger spec found. Probed: " + ", ".join(OPENAPI_PROBE_PATHS),
                phase="pre_js",
            )
        )

    return evidence


def detect_page_links(page: CapturedPage) -> list[Evidence]:
    """Page-level: links that suggest a documented API, spec or not."""
    evidence: list[Evidence] = []
    seen: set[str] = set()

    for phase in page.available_phases:
        soup = BeautifulSoup(page.html_for(phase), "lxml")

        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"]).strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue

            absolute = urljoin(page.final_url, href)
            label = anchor.get_text(" ", strip=True)[:120]

            path_and_text = f"{urlparse(absolute).path} {label}"
            if not (_DOC_LINK_HINT.search(urlparse(absolute).path) or _DOC_TEXT_HINT.search(label)):
                continue
            if absolute in seen:
                continue
            seen.add(absolute)

            evidence.append(
                Evidence(
                    source_url=page.final_url,
                    kind="openapi",
                    selector=f"a[href={href[:80]}]",
                    raw=f"API/developer link: {label or '(no text)'} -> {absolute}\n{path_and_text}",
                    phase=phase,
                )
            )

        if evidence:
            break  # one phase is enough; post-JS repeats the same nav

    return evidence[:15]
