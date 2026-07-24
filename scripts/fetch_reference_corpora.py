#!/usr/bin/env python
"""Download the grounding corpora into data/reference/ (gitignored).

Why each one is here, since "download some datasets" is not a reason:

- **schema.org vocabulary** — Axis 2 awards 4 points for JSON-LD that validates
  with no required-property violations. schema.org does not actually define
  "required" properties, so Phase 3 builds an operational definition on top of
  this vocabulary and has to be able to point at the source it derived it from.

- **APIs.guru directory** — thousands of real OpenAPI specs. The tool-schema
  synthesizer in Phase 5 needs known-good ground truth to be tested against;
  without it we would only ever test the synthesizer on inputs we invented,
  which proves nothing.

- **MCP servers repository** — reference implementations. The generator's output
  should look like servers people actually ship, not like our idea of one.

- **A2A specification** — the Agent Card schema we emit against.

- **Tranco** — a research-grade top-sites list, used as the sampling frame so the
  leaderboard's composition is defensible rather than hand-picked.

Everything lands under data/reference/ and is gitignored: these are other
people's artifacts, some are large, and all are reproducible from this script.

    uv run python scripts/fetch_reference_corpora.py
    uv run python scripts/fetch_reference_corpora.py --only schemaorg a2a
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from wasl.crawler.policy import repo_root  # noqa: E402

TIMEOUT_SECONDS = 120


@dataclass(frozen=True, slots=True)
class Corpus:
    key: str
    url: str
    filename: str
    why: str
    approx_mb: float


CORPORA: tuple[Corpus, ...] = (
    Corpus(
        key="schemaorg",
        url="https://schema.org/version/latest/schemaorg-current-https.jsonld",
        filename="schemaorg-current-https.jsonld",
        why="Axis 2 JSON-LD validation vocabulary",
        approx_mb=12.0,
    ),
    Corpus(
        key="apisguru",
        url="https://api.apis.guru/v2/list.json",
        filename="apis-guru-list.json",
        why="Real OpenAPI specs as ground truth for the tool synthesizer",
        approx_mb=8.0,
    ),
    # The A2A spec is now canonically a Protobuf definition. `a2a.json` is a
    # generated, explicitly non-normative artifact that is no longer committed to
    # the repository — it is built during docs publishing. So we take the proto
    # as the source of truth for the Agent Card shape, and the published JSON
    # Schema alongside it for convenience when validating what we emit.
    Corpus(
        key="a2a_proto",
        url="https://raw.githubusercontent.com/a2aproject/A2A/main/specification/a2a.proto",
        filename="a2a.proto",
        why="Canonical Agent Card definition (normative)",
        approx_mb=0.1,
    ),
    Corpus(
        key="a2a_json",
        url="https://a2a-protocol.org/latest/spec/a2a.json",
        filename="a2a-schema.json",
        why="Generated JSON Schema for the Agent Card (non-normative, convenience)",
        approx_mb=0.3,
    ),
    Corpus(
        key="mcp_servers",
        url="https://raw.githubusercontent.com/modelcontextprotocol/servers/main/README.md",
        filename="mcp-servers-README.md",
        why="Reference implementations index for generator output style",
        approx_mb=0.1,
    ),
    Corpus(
        key="mcp_schema",
        url="https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/schema/2025-06-18/schema.json",
        filename="mcp-schema.json",
        why="MCP protocol schema for validating generated servers",
        approx_mb=0.2,
    ),
    Corpus(
        key="tranco",
        url="https://tranco-list.eu/top-1m-id",
        filename="tranco-latest-id.txt",
        why="Sampling frame reference for leaderboard composition",
        approx_mb=0.001,
    ),
)


def fetch(corpus: Corpus, destination: Path, *, force: bool) -> tuple[bool, str]:
    target = destination / corpus.filename
    if target.exists() and not force:
        return True, f"already present ({target.stat().st_size / 1e6:.1f} MB) — use --force to refetch"

    try:
        with httpx.Client(follow_redirects=True, timeout=TIMEOUT_SECONDS) as client:
            response = client.get(corpus.url)
            response.raise_for_status()
            target.write_bytes(response.content)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"

    return True, f"{target.stat().st_size / 1e6:.1f} MB"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", choices=[c.key for c in CORPORA])
    parser.add_argument("--force", action="store_true", help="refetch even if present")
    parser.add_argument("--list", action="store_true", help="show sources and exit")
    args = parser.parse_args()

    destination = repo_root() / "data" / "reference"
    destination.mkdir(parents=True, exist_ok=True)

    selected = [c for c in CORPORA if not args.only or c.key in args.only]

    if args.list:
        for corpus in selected:
            print(f"{corpus.key:<14} ~{corpus.approx_mb:>5.1f} MB  {corpus.why}\n{'':<14} {corpus.url}")
        return 0

    print(f"WASL AI — reference corpora -> {destination}\n")

    failures: list[str] = []
    for corpus in selected:
        print(f"  {corpus.key:<14} ", end="", flush=True)
        ok, detail = fetch(corpus, destination, force=args.force)
        print(f"{'ok' if ok else 'FAILED'}  {detail}")
        if not ok:
            failures.append(f"{corpus.key}: {detail}")

    if failures:
        print(f"\n{len(failures)} of {len(selected)} failed:")
        for failure in failures:
            print(f"  - {failure}")
        print(
            "\nThese are third-party URLs and they move. Check the source repositories "
            "for the current path rather than assuming the corpus is gone."
        )
        return 1

    print(f"\n{len(selected)} corpora in {destination.relative_to(repo_root())} (gitignored).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
