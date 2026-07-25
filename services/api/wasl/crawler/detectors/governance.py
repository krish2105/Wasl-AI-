"""Terms-of-service and machine-authentication evidence (Axis 6, 3 + 3 points).

Axis 6 asks whether a site's terms address automated access explicitly, and
whether there is a documented way for a machine client to authenticate. Both are
answered here by keyword matching over legal and developer pages, with the
matched sentence stored verbatim as evidence.

Keyword matching rather than a model, deliberately. The moment a language model
decides whether terms "address agent access", the score stops being a
deterministic function of evidence and the whole architecture argument
collapses. A regex is cruder and occasionally wrong, but it is inspectable,
testable, and identical on every run — and when it is wrong, the stored snippet
lets a human see exactly why.

Polarity note: terms that *prohibit* automated access score the same as terms
that permit it. What Axis 6 measures is whether the site addressed the question
at all. Silence is the failure, not refusal.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from wasl.crawler.evidence import Evidence
from wasl.crawler.types import CapturedPage
from wasl.crawler.detectors.rendering import meaningful_text

# Pages whose content is worth scanning for these signals.
_LEGAL_PATH = re.compile(
    r"/(terms|tos|terms-of-(service|use)|legal|conditions|acceptable-use|aup|"
    r"robots-policy|crawling|scraping)(/|$|\.)",
    re.IGNORECASE,
)
_DEVELOPER_PATH = re.compile(
    r"/(developer|developers|api|apis|api-reference|api-docs|docs|documentation|"
    r"dev-portal|integrations?)(/|$|\.)",
    re.IGNORECASE,
)

# Language that shows the terms considered automated clients at all.
_AGENT_TERMS = re.compile(
    r"\b("
    r"automated (access|means|system|tool|agent|process|quer(?:y|ies)|method)|"
    r"web ?(crawler|crawling|scraper|scraping|spider|robot)|"
    r"data (mining|harvesting|extraction|scraping)|"
    r"bots?\b[^.!?]{0,40}\b(access|permitted|prohibited|allowed|use)|"
    r"artificial intelligence[^.!?]{0,60}\b(train|training|model|dataset)|"
    r"machine learning[^.!?]{0,60}\b(train|training|dataset)|"
    r"(ai|llm|generative)[^.!?]{0,30}\btraining\b|"
    r"robots\.txt|"
    r"text and data mining"
    r")\b",
    re.IGNORECASE,
)

# Documented ways a machine client can authenticate.
_MACHINE_AUTH = re.compile(
    r"\b("
    r"api[- ]key|api[- ]token|access[- ]token|bearer[- ]token|"
    r"client[- ](id|secret)|oauth\s*2(\.0)?|"
    r"personal access token|service account|"
    r"authorization header|x-api-key"
    r")\b",
    re.IGNORECASE,
)

_MAX_SNIPPET = 400


def _sentences_around(text: str, pattern: re.Pattern[str], limit: int = 3) -> list[str]:
    """Verbatim spans around each match, so a human can check the call."""
    found: list[str] = []
    for match in pattern.finditer(text):
        start = max(0, match.start() - 160)
        end = min(len(text), match.end() + 240)
        snippet = " ".join(text[start:end].split())[:_MAX_SNIPPET]
        if snippet not in found:
            found.append(snippet)
        if len(found) >= limit:
            break
    return found


def _page_kind(url: str) -> str | None:
    path = urlparse(url).path or "/"
    if _LEGAL_PATH.search(path):
        return "legal"
    if _DEVELOPER_PATH.search(path):
        return "developer"
    return None


def detect(page: CapturedPage) -> list[Evidence]:
    kind = _page_kind(page.final_url)
    if kind is None:
        return []

    phases = page.available_phases
    if not phases:
        return []
    phase = "post_js" if "post_js" in phases else "pre_js"
    text = meaningful_text(page.html_for(phase))
    if len(text) < 200:
        return []

    evidence: list[Evidence] = []

    if kind == "legal":
        matches = _sentences_around(text, _AGENT_TERMS)
        if matches:
            evidence.append(
                Evidence(
                    source_url=page.final_url,
                    kind="text",
                    selector="governance#tos-addresses-automation",
                    raw=(
                        "Terms page mentions automated access, crawling or AI training. "
                        "Whether it permits or prohibits is not scored — only that the "
                        "question was addressed.\n\n" + "\n---\n".join(matches)
                    ),
                    phase=phase,
                )
            )
        else:
            evidence.append(
                Evidence(
                    source_url=page.final_url,
                    kind="text",
                    selector="governance#tos-silent-on-automation",
                    raw=(
                        f"Terms page scanned ({len(text)} chars); no language about automated "
                        "access, crawlers, scraping or AI training was found."
                    ),
                    phase=phase,
                )
            )

    auth_matches = _sentences_around(text, _MACHINE_AUTH)
    if auth_matches:
        evidence.append(
            Evidence(
                source_url=page.final_url,
                kind="text",
                selector="governance#machine-auth-documented",
                raw=(
                    "Documented authentication for machine clients:\n\n"
                    + "\n---\n".join(auth_matches)
                ),
                phase=phase,
            )
        )

    return evidence
