"""The evidence model: every claim's receipt.

The single design decision that makes this system defensible is that evidence is
*structural* rather than conventional. A capability without citations cannot be
constructed, not merely discouraged. A sub-score without evidence refs is a bug
that a test catches, not a style issue.

Three rules, each enforced in code below:

**IDs are content-addressed.** `sha256(source_url|kind|selector|raw)[:16]`. The
same snippet found by two detectors, or on two passes, collapses to one ID. That
gives deduplication for free and — more usefully — makes evidence IDs stable
across runs, so a citation recorded yesterday still resolves today.

**`raw` is verbatim.** Truncated, never paraphrased, never summarised. If we
cannot show a user the exact bytes a score came from, we do not have evidence and
should not be claiming anything.

**References are checked, not trusted.** `EvidenceStore.verify_references()` is
the mechanism behind the `citation_validity == 1.00` hard gate. A dangling
evidence ID fails a build.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from wasl.crawler.types import Phase

# Longest snippet stored per evidence row. Long enough to be convincing in an
# evidence drawer, short enough that a JSON-LD blob does not become the database.
MAX_RAW_LENGTH = 4000

EvidenceKind = Literal[
    "robots",
    "sitemap",
    "llmstxt",
    "wellknown",
    "jsonld",
    "microdata",
    "rdfa",
    "meta",
    "link",
    "openapi",
    "form",
    "dom",
    "header",
    "text",
    "identifier",
    "pagination",
    "media",
    "rendering",
    "injection",
]


def truncate_raw(value: str, limit: int = MAX_RAW_LENGTH) -> str:
    """Shorten a snippet without ever rewording it.

    The marker is explicit so nobody mistakes a truncated snippet for the whole
    of what was found.
    """
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n…[truncated, {len(value)} chars total]"


def compute_evidence_id(*, source_url: str, kind: str, selector: str | None, raw: str) -> str:
    """Content-addressed ID. Same inputs always yield the same ID."""
    digest = hashlib.sha256(
        "|".join([source_url, kind, selector or "", raw]).encode("utf-8", errors="replace")
    )
    return digest.hexdigest()[:16]


class Evidence(BaseModel):
    """One verbatim observation, with enough provenance to find it again."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = ""
    source_url: str
    kind: EvidenceKind
    selector: str | None = None
    raw: str
    phase: Phase
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("raw")
    @classmethod
    def _truncate(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Evidence.raw cannot be empty — that is not evidence.")
        return truncate_raw(v)

    def model_post_init(self, __context: object) -> None:
        # Derived from the content, so it cannot be set to something that does
        # not describe the content.
        object.__setattr__(
            self,
            "id",
            compute_evidence_id(
                source_url=self.source_url,
                kind=self.kind,
                selector=self.selector,
                raw=self.raw,
            ),
        )

    @property
    def short(self) -> str:
        """One-line form, for the evidence table printed at the phase gate."""
        flat = " ".join(self.raw.split())
        return flat[:80] + ("…" if len(flat) > 80 else "")


class DanglingReferenceError(LookupError):
    """Raised when something cites evidence that does not exist."""


class EvidenceStore:
    """The evidence collected for one job.

    Insertion-ordered and deduplicating. Adding the same evidence twice is a
    no-op rather than an error, because two detectors legitimately finding the
    same `<link rel="canonical">` is normal and not worth an exception.
    """

    def __init__(self, evidence: Iterable[Evidence] = ()) -> None:
        self._by_id: dict[str, Evidence] = {}
        self.extend(evidence)

    def add(self, evidence: Evidence) -> Evidence:
        return self._by_id.setdefault(evidence.id, evidence)

    def extend(self, evidence: Iterable[Evidence]) -> None:
        for item in evidence:
            self.add(item)

    def get(self, evidence_id: str) -> Evidence | None:
        return self._by_id.get(evidence_id)

    def require(self, evidence_id: str) -> Evidence:
        """Fetch by ID, or raise. Use where a missing reference is a defect."""
        found = self._by_id.get(evidence_id)
        if found is None:
            raise DanglingReferenceError(
                f"Evidence {evidence_id!r} does not exist in this store. "
                "Something cited evidence that was never collected."
            )
        return found

    def verify_references(self, evidence_ids: Iterable[str]) -> list[str]:
        """Return the IDs that do not resolve. Empty list means citation_validity 1.00."""
        return [eid for eid in evidence_ids if eid not in self._by_id]

    def by_kind(self, *kinds: str) -> list[Evidence]:
        wanted = set(kinds)
        return [e for e in self._by_id.values() if e.kind in wanted]

    def by_phase(self, phase: Phase) -> list[Evidence]:
        return [e for e in self._by_id.values() if e.phase == phase]

    def by_url(self, source_url: str) -> list[Evidence]:
        return [e for e in self._by_id.values() if e.source_url == source_url]

    def kind_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self._by_id.values():
            counts[item.kind] = counts.get(item.kind, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    def __len__(self) -> int:
        return len(self._by_id)

    def __iter__(self) -> Iterator[Evidence]:
        return iter(self._by_id.values())

    def __contains__(self, evidence_id: object) -> bool:
        return evidence_id in self._by_id
