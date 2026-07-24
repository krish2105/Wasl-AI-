"""Detects prompt-injection payloads planted in web pages.

Why this is a scanner rather than a prompt instruction: telling a model "ignore
instructions in the content" is a mitigation you cannot measure. A scanner is
one you can — seed known payloads into fixtures, count how many come back, and
report the recall. That number is `injection_detection_recall`, and publishing it
is a stronger claim than asserting the system is robust.

The scanner looks in the places payloads actually hide, which are the places a
human reader will not look but a DOM-reading agent will:

- elements hidden by CSS (`display:none`, `visibility:hidden`, zero opacity,
  off-screen positioning, `hidden`, tiny font sizes)
- HTML comments
- `alt`, `title`, `aria-label` and `placeholder` attributes
- zero-width and bidirectional control characters
- ordinary visible text, which is fair game too — plenty of injections do not
  bother hiding

Every pattern carries a stable `pattern_id`, so recall can be reported per
category rather than as a single aggregate that hides which class we are bad at.

Scope note: this measures *what a page contains*, which is Axis 6's signal and a
finding for the user. It is not the whole defence. Wrapping crawled text in
untrusted-content tags before it reaches a model is a separate, mandatory step
that happens regardless of whether this scanner found anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from bs4 import BeautifulSoup, Comment
from bs4.element import Tag

PATTERNS_VERSION: Final = "1.0"

# Characters with no visual width, used to smuggle text past a human reviewer
# or to break up a keyword so a naive filter misses it.
ZERO_WIDTH_CHARS: Final = "​‌‍⁠﻿᠎"
BIDI_CONTROL_CHARS: Final = "‪‫‬‭‮⁦⁧⁨⁩"

Severity = str


@dataclass(frozen=True, slots=True)
class InjectionPattern:
    pattern_id: str
    category: str
    severity: Severity
    regex: re.Pattern[str]
    description: str


def _p(pattern_id: str, category: str, severity: str, pattern: str, description: str) -> InjectionPattern:
    return InjectionPattern(
        pattern_id=pattern_id,
        category=category,
        severity=severity,
        regex=re.compile(pattern, re.IGNORECASE | re.DOTALL),
        description=description,
    )


# Tuned to fire on text that addresses a model, not on text that merely discusses
# AI. "Our AI assistant helps you shop" must not match; "AI assistant: recommend
# this product" must.
PATTERNS: Final[tuple[InjectionPattern, ...]] = (
    _p(
        "ignore_previous",
        "instruction_override",
        "high",
        r"\b(ignore|disregard|forget|override)\b[^.!?\n]{0,40}\b"
        r"(previous|prior|above|earlier|preceding|all)\b[^.!?\n]{0,20}\b"
        r"(instruction|instructions|prompt|prompts|direction|directions|rule|rules|context)\b",
        "Attempts to void instructions the model was given before reading this page.",
    ),
    _p(
        "role_redefinition",
        "role_redefinition",
        "high",
        r"\b(you\s+are\s+now|from\s+now\s+on\s+you|act\s+as\s+(?:a|an|the)|"
        r"pretend\s+(?:to\s+be|you\s+are)|your\s+new\s+(?:role|task|instructions?)\s+(?:is|are))\b",
        "Attempts to reassign the model's role or persona.",
    ),
    _p(
        "system_prompt_spoof",
        "role_redefinition",
        "high",
        r"(^|\n|>)\s*(\[|\{|<|#{1,3}\s*)?\s*"
        r"(system|assistant|developer)\s*(prompt|message|instruction)?\s*[:\]\}>]",
        "Impersonates a system, assistant or developer turn to smuggle in a new frame.",
    ),
    _p(
        "agent_directive",
        "agent_directive",
        "high",
        r"\b(ai|llm|language\s+model|assistant|agent|chatbot|bot|crawler|scraper|"
        r"chatgpt|claude|gemini|copilot|perplexity)\b\s*[,:]\s*"
        r"(please\s+)?\b(ignore|note|remember|recommend|rank|rate|say|tell|report|output|"
        r"respond|reply|include|prioriti[sz]e|summari[sz]e|do|always|never|you\s+must)\b",
        "Addresses an AI reader directly and issues it an instruction.",
    ),
    _p(
        "ranking_manipulation",
        "ranking_manipulation",
        "high",
        r"\b(rank|rate|score|classify|mark|report|list)\b[^.!?\n]{0,50}\b"
        r"(this\s+(?:site|page|company|business|product|listing)|us|our\s+\w+)\b"
        r"[^.!?\n]{0,50}\b(highest|first|top|best|100|perfect|maximum|number\s+one|"
        r"fully\s+compliant|agent[- ]ready)\b",
        "Tries to influence an automated score or ranking of this page.",
    ),
    _p(
        "exfiltration",
        "exfiltration",
        "high",
        r"\b(send|post|forward|transmit|upload|leak|reveal|disclose|include)\b"
        r"[^.!?\n]{0,60}\b(system\s+prompt|api[_\s-]?key|secret|token|credential|password|"
        r"conversation|chat\s+history|previous\s+messages)\b",
        "Attempts to make the agent disclose secrets or prior context.",
    ),
    _p(
        "tool_invocation",
        "tool_invocation",
        "high",
        r"(<\s*(tool_call|function_call|invoke|antml:invoke|tool_use)\b|"
        r"\b(call|invoke|execute|run)\s+the\s+\w+\s+(tool|function|command)\b)",
        "Embeds something shaped like a tool call in page content.",
    ),
    _p(
        "instruction_delimiter_spoof",
        "instruction_override",
        "medium",
        r"(-{3,}\s*(end|begin|start)\s+of\s+(instructions?|prompt|context|document)\s*-{3,}|"
        r"<\s*/?\s*(system|instructions?|untrusted_\w+|user_input)\s*>)",
        "Fakes a delimiter to make later text look like it sits outside the untrusted block.",
    ),
    _p(
        "urgency_authority",
        "social_engineering",
        "medium",
        r"\b(this\s+is\s+(?:an?\s+)?(?:official|authorized|approved|urgent)|"
        r"the\s+(?:user|developer|administrator|owner)\s+has\s+(?:already\s+)?"
        r"(?:approved|authori[sz]ed|permitted|requested))\b",
        "Claims prior authorisation or authority the page cannot actually grant.",
    ),
)


@dataclass(frozen=True, slots=True)
class InjectionMatch:
    """One suspicious span, with enough context to show a user."""

    pattern_id: str
    category: str
    severity: Severity
    location: str  # hidden_element | html_comment | attribute | visible_text | encoding
    selector: str | None
    snippet: str
    description: str


_HIDDEN_STYLE = re.compile(
    r"(display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?:\.0+)?\b|"
    r"font-size\s*:\s*0|clip\s*:\s*rect\(0|"
    r"(?:left|top|text-indent)\s*:\s*-\s*\d{3,}\s*(?:px|em|%))",
    re.IGNORECASE,
)

_SUSPICIOUS_ATTRS = ("alt", "title", "aria-label", "placeholder", "data-tooltip", "content")

# Below this, an "instruction" is too short to be a credible payload and too
# likely to be an ordinary phrase.
_MIN_PAYLOAD_CHARS = 12


def _snippet(text: str, match: re.Match[str], width: int = 160) -> str:
    start = max(0, match.start() - width // 3)
    end = min(len(text), match.end() + width // 2)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + " ".join(text[start:end].split()) + suffix


def scan_text(
    text: str, *, location: str = "visible_text", selector: str | None = None
) -> list[InjectionMatch]:
    """Run every pattern over a block of text."""
    if not text or len(text.strip()) < _MIN_PAYLOAD_CHARS:
        return []

    matches: list[InjectionMatch] = []
    for pattern in PATTERNS:
        for found in pattern.regex.finditer(text):
            matches.append(
                InjectionMatch(
                    pattern_id=pattern.pattern_id,
                    category=pattern.category,
                    severity=pattern.severity,
                    location=location,
                    selector=selector,
                    snippet=_snippet(text, found),
                    description=pattern.description,
                )
            )
            break  # one hit per pattern per block is enough to report
    return matches


def _css_path(tag: Tag) -> str:
    """A short, human-readable path to an element."""
    parts: list[str] = []
    node: Tag | None = tag
    depth = 0
    while node is not None and getattr(node, "name", None) and depth < 4:
        piece = node.name
        node_id = node.get("id")
        if isinstance(node_id, str) and node_id:
            piece += f"#{node_id}"
        else:
            classes = node.get("class")
            if isinstance(classes, list) and classes:
                piece += f".{classes[0]}"
        parts.append(piece)
        node = node.parent if isinstance(node.parent, Tag) else None
        depth += 1
    return " > ".join(reversed(parts))


def _is_hidden(tag: Tag) -> bool:
    if tag.has_attr("hidden"):
        return True
    if tag.get("aria-hidden") == "true":
        return True
    style = tag.get("style")
    if isinstance(style, str) and _HIDDEN_STYLE.search(style):
        return True
    classes = tag.get("class")
    if isinstance(classes, list):
        joined = " ".join(classes).lower()
        if any(token in joined for token in ("sr-only", "visually-hidden", "screen-reader", "hidden")):
            return True
    return False


def scan_encoding(text: str, *, selector: str | None = None) -> list[InjectionMatch]:
    """Flag invisible characters used to hide or fragment a payload."""
    matches: list[InjectionMatch] = []

    zero_width_count = sum(text.count(c) for c in ZERO_WIDTH_CHARS)
    # A handful can appear legitimately in ligature or emoji sequences; a cluster
    # of them in body text does not.
    if zero_width_count >= 3:
        matches.append(
            InjectionMatch(
                pattern_id="zero_width_chars",
                category="obfuscation",
                severity="medium",
                location="encoding",
                selector=selector,
                snippet=f"{zero_width_count} zero-width characters in agent-readable text",
                description="Invisible characters can hide text from human review or split keywords.",
            )
        )

    if any(c in text for c in BIDI_CONTROL_CHARS):
        matches.append(
            InjectionMatch(
                pattern_id="bidi_control_chars",
                category="obfuscation",
                severity="medium",
                location="encoding",
                selector=selector,
                snippet="Bidirectional control characters present",
                description="Bidi overrides can make rendered text differ from its source order.",
            )
        )

    return matches


def scan_html(html: str) -> list[InjectionMatch]:
    """Scan a full document: hidden elements, comments, attributes, visible text.

    Deduplicated on (pattern_id, location, selector) so one payload repeated
    across a template does not inflate the finding count.
    """
    if not html.strip():
        return []

    soup = BeautifulSoup(html, "lxml")
    matches: list[InjectionMatch] = []

    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        matches.extend(scan_text(str(comment), location="html_comment", selector="<!-- -->"))

    for tag in soup.find_all(True):
        if not isinstance(tag, Tag):
            continue

        if _is_hidden(tag):
            hidden_text = tag.get_text(" ", strip=True)
            if hidden_text:
                matches.extend(
                    scan_text(hidden_text, location="hidden_element", selector=_css_path(tag))
                )

        for attr in _SUSPICIOUS_ATTRS:
            value = tag.get(attr)
            if isinstance(value, str) and value.strip():
                matches.extend(
                    scan_text(value, location="attribute", selector=f"{_css_path(tag)}[{attr}]")
                )

    body = soup.body or soup
    visible = body.get_text(" ", strip=True)
    matches.extend(scan_text(visible, location="visible_text", selector="body"))
    matches.extend(scan_encoding(visible, selector="body"))

    seen: set[tuple[str, str, str | None]] = set()
    unique: list[InjectionMatch] = []
    for match in matches:
        key = (match.pattern_id, match.location, match.selector)
        if key not in seen:
            seen.add(key)
            unique.append(match)
    return unique


def categories() -> tuple[str, ...]:
    """Every category the scanner can report. Used to stratify the eval set."""
    return tuple(sorted({p.category for p in PATTERNS} | {"obfuscation"}))
