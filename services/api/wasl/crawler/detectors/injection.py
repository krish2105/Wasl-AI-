"""Prompt-injection evidence (Axis 6, 2 points).

Thin wrapper turning `wasl.security.injection` matches into Evidence rows. Kept
separate from the scanner so the same scanner can serve the Phase 5 probe node
without either importing the other's concerns.

Note the polarity, which is easy to get backwards: Axis 6 awards points for the
*absence* of injection payloads. Evidence produced here is therefore evidence
against the site, and the scoring module reads it that way. A page with no
findings still needs a row saying so — "we scanned and found nothing" is a
different claim from "we never scanned", and only one of them should score.
"""

from __future__ import annotations

from wasl.crawler.evidence import Evidence
from wasl.crawler.types import CapturedPage
from wasl.security.injection import PATTERNS_VERSION, scan_html


def detect(page: CapturedPage) -> list[Evidence]:
    evidence: list[Evidence] = []
    total = 0

    for phase in page.available_phases:
        matches = scan_html(page.html_for(phase))
        total += len(matches)

        for match in matches:
            evidence.append(
                Evidence(
                    source_url=page.final_url,
                    kind="injection",
                    selector=f"injection#{match.pattern_id}#{match.location}",
                    raw=(
                        f"category: {match.category}\n"
                        f"pattern: {match.pattern_id} (severity {match.severity})\n"
                        f"location: {match.location}\n"
                        f"selector: {match.selector}\n"
                        f"why: {match.description}\n"
                        f"snippet: {match.snippet}"
                    ),
                    phase=phase,
                )
            )

    if total == 0:
        evidence.append(
            Evidence(
                source_url=page.final_url,
                kind="injection",
                selector="injection#clean",
                raw=(
                    f"Scanned with pattern set v{PATTERNS_VERSION} across "
                    f"{', '.join(page.available_phases)}: no injection payloads found in "
                    "hidden elements, comments, attributes or visible text."
                ),
                phase=page.available_phases[0] if page.available_phases else "pre_js",
            )
        )

    return evidence
