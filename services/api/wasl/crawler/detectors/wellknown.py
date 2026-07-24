"""`.well-known` evidence (Axis 3, 6 points — an existing agent manifest).

RFC 8615 made `/.well-known/` the standard place for machine-facing metadata, and
it is increasingly where agent manifests live. Finding an MCP endpoint or an A2A
Agent Card here is the strongest single signal in the whole rubric that a site is
already agent-native — it means someone shipped for agents deliberately.

Which is exactly why this detector validates the payload shape rather than
trusting a 200. A site that serves its SPA for every unmatched path would
otherwise score six points for having a router.
"""

from __future__ import annotations

import json
import re

from wasl.crawler.evidence import Evidence
from wasl.crawler.types import FetchedResource, SiteArtifacts

# Probed in this order. Cheap: one HEAD-ish GET each, once per site.
WELLKNOWN_PATHS: tuple[str, ...] = (
    "/.well-known/mcp.json",
    "/.well-known/mcp",
    "/.well-known/agent.json",
    "/.well-known/agent-card.json",
    "/.well-known/ai-plugin.json",
    "/.well-known/ai.txt",
    "/.well-known/security.txt",
)

# A manifest that mentions none of these is not an agent manifest.
_AGENT_MARKERS = (
    "mcp",
    "tools",
    "skills",
    "capabilities",
    "agent",
    "protocolversion",
    "protocol_version",
    "api_endpoint",
    "schema_version",
)

_HTML_SHELL = re.compile(r"<\s*(html|!doctype|head|body)\b", re.IGNORECASE)


def _is_agent_manifest(resource: FetchedResource) -> tuple[bool, str]:
    """(is a real manifest, why we concluded that)."""
    if _HTML_SHELL.search(resource.text[:500]):
        return False, "served HTML, not a manifest — likely a catch-all route"

    try:
        payload = json.loads(resource.text)
    except json.JSONDecodeError:
        return False, "not valid JSON"

    if not isinstance(payload, dict):
        return False, "JSON is not an object"

    keys = {k.lower() for k in payload}
    hits = sorted(keys & set(_AGENT_MARKERS))
    if not hits:
        return False, f"JSON object with no agent-related keys (found: {sorted(keys)[:6]})"

    return True, f"agent manifest keys present: {hits}"


def detect(artifacts: SiteArtifacts) -> list[Evidence]:
    evidence: list[Evidence] = []
    found_any = False

    for resource in artifacts.wellknown:
        if not resource.found:
            continue

        path = resource.url.split(artifacts.domain, 1)[-1]

        if resource.url.endswith(("security.txt", "ai.txt")):
            # Not agent manifests, but both indicate a site that publishes
            # machine-facing policy. Recorded for Axis 6.
            evidence.append(
                Evidence(
                    source_url=resource.url,
                    kind="wellknown",
                    selector=f"wellknown{path}",
                    raw=resource.text[:1000],
                    phase="pre_js",
                )
            )
            continue

        is_manifest, why = _is_agent_manifest(resource)
        if is_manifest:
            found_any = True
            evidence.append(
                Evidence(
                    source_url=resource.url,
                    kind="wellknown",
                    selector=f"wellknown{path}#manifest",
                    raw=f"{why}\n\n{resource.text[:2000]}",
                    phase="pre_js",
                )
            )
        else:
            evidence.append(
                Evidence(
                    source_url=resource.url,
                    kind="wellknown",
                    selector=f"wellknown{path}#not-a-manifest",
                    raw=f"HTTP 200 but {why}. Not counted as an agent manifest.",
                    phase="pre_js",
                )
            )

    if not found_any:
        evidence.append(
            Evidence(
                source_url=artifacts.root_url,
                kind="wellknown",
                selector="wellknown#absent",
                raw=(
                    "No agent manifest found. Probed: " + ", ".join(WELLKNOWN_PATHS)
                ),
                phase="pre_js",
            )
        )

    return evidence
