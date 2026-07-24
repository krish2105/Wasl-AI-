"""Form evidence (Axis 3 contact capability, Axis 5 form labelling).

The rule that shapes this module: **GET forms are capability signals, POST forms
are not, and neither is ever submitted.** A GET search form advertises a URL
pattern an agent can construct for itself — that is a real, usable capability. A
POST form is a state-changing endpoint on someone else's server, and Wasl is
read-only, so we record its shape and stop there.

Nothing in this file performs I/O. It reads markup and describes it.
"""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import Tag

from wasl.crawler.evidence import Evidence
from wasl.crawler.types import CapturedPage

_INPUT_TAGS = ("input", "select", "textarea")
_IGNORED_INPUT_TYPES = {"submit", "button", "reset", "image", "hidden"}

_SEARCH_HINTS = ("search", "query", "q", "keyword", "term", "find", "lookup")
_CONTACT_HINTS = ("contact", "enquiry", "inquiry", "message", "feedback", "support", "quote")


def _labelled(field: Tag, soup: BeautifulSoup) -> bool:
    """Does this input have an accessible name an agent can rely on?"""
    if field.get("aria-label") or field.get("aria-labelledby") or field.get("title"):
        return True
    field_id = field.get("id")
    if isinstance(field_id, str) and field_id:
        if soup.find("label", attrs={"for": field_id}):
            return True
    return field.find_parent("label") is not None


def _fields(form: Tag, soup: BeautifulSoup) -> list[dict[str, object]]:
    described: list[dict[str, object]] = []
    for field in form.find_all(_INPUT_TAGS):
        if not isinstance(field, Tag):
            continue
        field_type = str(field.get("type", "text")).lower()
        if field.name == "input" and field_type in _IGNORED_INPUT_TYPES:
            continue
        described.append(
            {
                "tag": field.name,
                "type": field_type if field.name == "input" else field.name,
                "name": field.get("name"),
                "id": field.get("id"),
                "required": field.has_attr("required"),
                "labelled": _labelled(field, soup),
                "placeholder": field.get("placeholder"),
            }
        )
    return described


def _classify(form: Tag, fields: list[dict[str, object]]) -> str:
    haystack = " ".join(
        str(v).lower()
        for v in [
            form.get("id"),
            form.get("name"),
            form.get("class"),
            form.get("action"),
            *[f.get("name") for f in fields],
            *[f.get("placeholder") for f in fields],
        ]
        if v
    )
    if any(hint in haystack for hint in _SEARCH_HINTS):
        return "search"
    if any(hint in haystack for hint in _CONTACT_HINTS):
        return "contact"
    return "other"


def detect(page: CapturedPage) -> list[Evidence]:
    evidence: list[Evidence] = []

    for phase in page.available_phases:
        html = page.html_for(phase)
        soup = BeautifulSoup(html, "lxml")
        forms = soup.find_all("form")
        if not forms:
            continue

        for index, form in enumerate(forms[:20]):
            if not isinstance(form, Tag):
                continue

            method = str(form.get("method", "get")).lower()
            action = str(form.get("action", "")).strip()
            absolute_action = urljoin(page.final_url, action) if action else page.final_url
            fields = _fields(form, soup)
            if not fields:
                continue

            named = sum(1 for f in fields if f["name"])
            labelled = sum(1 for f in fields if f["labelled"])
            purpose = _classify(form, fields)

            selector = form.get("id") or form.get("name") or f"form:nth-of-type({index + 1})"
            field_lines = "\n".join(
                f"  - <{f['tag']} type={f['type']}> name={f['name']!r} id={f['id']!r} "
                f"required={f['required']} labelled={f['labelled']}"
                for f in fields[:20]
            )

            evidence.append(
                Evidence(
                    source_url=page.final_url,
                    kind="form",
                    selector=f"form#{selector}#{method}#{purpose}",
                    raw=(
                        f"{method.upper()} form, purpose={purpose}, action={absolute_action}\n"
                        f"{len(fields)} fields, {named} named, {labelled} labelled "
                        f"({labelled / len(fields):.0%} label coverage)\n"
                        f"{'GET form — an agent can construct this URL directly.' if method == 'get' else 'POST form — recorded only; never submitted.'}\n"
                        f"{field_lines}"
                    ),
                    phase=phase,
                )
            )

        if evidence:
            break

    return evidence
