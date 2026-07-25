"""Versioned prompt files, loaded by name and hashed into every trace.

Prompts are code. They change behaviour, they regress, and a metric produced
under `induce.v1` is not comparable to one produced under `induce.v2`. So they
live in versioned `.md` files rather than string literals, and every load records
the file's SHA — which then appears in the OTel span and in the eval report.

Without that, "capability precision 0.91" is a number with no idea which prompt
produced it, and the first prompt edit silently invalidates it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class Prompt:
    name: str
    version: str
    sha: str
    text: str

    @property
    def id(self) -> str:
        return f"{self.name}.{self.version}"

    def render(self, **variables: object) -> str:
        """Substitute {placeholders}. Missing ones raise rather than silently blank."""
        try:
            return self.text.format(**variables)
        except KeyError as exc:
            raise KeyError(
                f"Prompt {self.id} needs variable {exc.args[0]!r}, which was not supplied."
            ) from exc


@lru_cache(maxsize=32)
def load(name: str, version: str = "v1") -> Prompt:
    """Load `{name}.{version}.md` from this directory."""
    path = PROMPTS_DIR / f"{name}.{version}.md"
    if not path.exists():
        available = sorted(p.name for p in PROMPTS_DIR.glob("*.md"))
        raise FileNotFoundError(f"No prompt {path.name!r}. Available: {available}")

    text = path.read_text()
    return Prompt(
        name=name,
        version=version,
        sha=hashlib.sha256(text.encode()).hexdigest()[:12],
        text=text,
    )


def all_prompts() -> dict[str, str]:
    """Every prompt id mapped to its SHA. Recorded in the eval report."""
    found: dict[str, str] = {}
    for path in sorted(PROMPTS_DIR.glob("*.md")):
        stem = path.stem
        if "." not in stem:
            continue
        name, _, version = stem.rpartition(".")
        prompt = load(name, version)
        found[prompt.id] = prompt.sha
    return found
