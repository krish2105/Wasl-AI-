"""robots.txt evidence (Axis 1).

The subtlety this detector encodes: an explicit AI-agent stanza scores whether it
allows or disallows. `User-agent: GPTBot / Disallow: /` is a site that has
thought about agents and said no, which is legible and deliberate. Silence is
neither. So the evidence records *which* agents were named and what the verdict
was, and the rubric rewards the clarity rather than the answer.
"""

from __future__ import annotations

import re

from wasl.crawler.evidence import Evidence
from wasl.crawler.types import SiteArtifacts

_STANZA = re.compile(
    r"^\s*user-agent\s*:\s*(?P<agent>.+?)\s*$(?P<body>(?:\n(?!\s*user-agent\s*:).*)*)",
    re.IGNORECASE | re.MULTILINE,
)


def _stanza_body(raw: str, agent: str) -> str:
    """The directives following a given User-agent line, verbatim."""
    for match in _STANZA.finditer(raw):
        if match.group("agent").strip().lower() == agent.strip().lower():
            return f"User-agent: {agent}{match.group('body')}".strip()
    return f"User-agent: {agent}"


def detect(artifacts: SiteArtifacts) -> list[Evidence]:
    robots = artifacts.robots
    evidence: list[Evidence] = []

    if not robots.present:
        # Absence is a finding. Recorded so Axis 1 can score it and so the user
        # can see we looked rather than assumed.
        return [
            Evidence(
                source_url=robots.url,
                kind="robots",
                selector="robots.txt#absent",
                raw=f"No robots.txt retrieved: {robots.fetch_error or 'not found'}",
                phase="pre_js",
            )
        ]

    evidence.append(
        Evidence(
            source_url=robots.url,
            kind="robots",
            selector="robots.txt",
            raw=robots.raw[:2000] or "(empty robots.txt)",
            phase="pre_js",
        )
    )

    if not robots.parseable:
        evidence.append(
            Evidence(
                source_url=robots.url,
                kind="robots",
                selector="robots.txt#unparseable",
                raw="robots.txt was retrieved but could not be parsed.",
                phase="pre_js",
            )
        )

    for agent in robots.ai_agent_stanzas:
        evidence.append(
            Evidence(
                source_url=robots.url,
                kind="robots",
                selector=f"robots.txt#user-agent:{agent}",
                raw=_stanza_body(robots.raw, agent),
                phase="pre_js",
            )
        )

    for sitemap_url in robots.sitemaps:
        evidence.append(
            Evidence(
                source_url=robots.url,
                kind="robots",
                selector="robots.txt#sitemap",
                raw=f"Sitemap: {sitemap_url}",
                phase="pre_js",
            )
        )

    if robots.crawl_delay is not None:
        evidence.append(
            Evidence(
                source_url=robots.url,
                kind="robots",
                selector="robots.txt#crawl-delay",
                raw=f"Crawl-delay: {robots.crawl_delay}",
                phase="pre_js",
            )
        )

    return evidence
