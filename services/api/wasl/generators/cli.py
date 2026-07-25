"""Generate artifacts for a fixture and prove the ship gate works.

    uv run python -m wasl.generators.cli --fixture rich_site

Runs the real pipeline (induce -> synthesize -> critic) against a saved page,
generates the server, imports it in a clean subprocess, and lists its tools. The
exit code is the gate: non-zero when verification fails, so this can sit in CI.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from pathlib import Path

from wasl.config import get_settings
from wasl.crawler.detectors import extract_all
from wasl.generators.packager import generate_all
from wasl.graph.build import store_from_records
from wasl.graph.nodes import critic as critic_node
from wasl.graph.nodes import extract as extract_node
from wasl.graph.nodes import induce as induce_node
from wasl.graph.nodes import score as score_node
from wasl.graph.nodes import synthesize as synthesize_node
from wasl.graph.nodes.crawl import summarise
from wasl.graph.state import WaslState
from wasl.llm.router import ModelRouter
from wasl.scoring.cli import load_fixture, neutral_artifacts

RULE = "=" * 78


async def run(fixture: str, output_root: Path) -> int:
    router = ModelRouter()
    page = load_fixture(fixture)
    artifacts = neutral_artifacts(page.final_url)
    pages = [page]

    store = extract_all(pages, artifacts)
    state = WaslState(
        job_id=f"{fixture}-{uuid.uuid4().hex[:6]}",
        root_url=page.final_url,
        domain=artifacts.domain,
        pages=[summarise(page)],
        evidence=extract_node.to_records(store),
    )
    rebuilt = store_from_records(state.evidence)

    print(f"{RULE}\nGENERATE  {fixture}  ({artifacts.domain})\n{RULE}")

    induced = await induce_node.induce(state, store=rebuilt, router=router)
    state = state.model_copy(update={"candidate_capabilities": induced.get("candidate_capabilities", [])})

    synthesized = await synthesize_node.synthesize(state, store=rebuilt, router=router)
    state = state.model_copy(update={"candidate_capabilities": synthesized.get("candidate_capabilities", [])})

    critiqued = await critic_node.critique(state, store=rebuilt, router=router)
    state = state.model_copy(
        update={
            "accepted_capabilities": critiqued.get("accepted_capabilities", []),
            "rejections": critiqued.get("rejections", []),
        }
    )

    scored = await score_node.score(state, store=rebuilt)
    state = state.model_copy(update={"score": scored.get("score")})

    print(f"  accepted: {len(state.accepted_capabilities)}   refused: {len(state.rejections)}")

    outcome = await generate_all(
        job_id=state.job_id,
        domain=artifacts.domain,
        site_name=fixture.replace("_", " ").title(),
        capabilities=[*state.accepted_capabilities, *state.candidate_capabilities],
        pages=state.pages,
        store=rebuilt,
        score=state.score,
        output_root=output_root,
    )

    print(f"\n  output: {outcome.directory}")
    for path in sorted(outcome.directory.iterdir()):
        print(f"    {path.name:<28} {path.stat().st_size:>8} bytes")

    print(f"\n{RULE}\nSHIP GATE — clean subprocess import\n{RULE}")
    print(outcome.verification.summary())

    print(f"\n  packaged: {'yes — ' + Path(outcome.artifacts.zip_path).name if outcome.artifacts.zip_path else 'NO (verification failed)'}")
    return 0 if outcome.shipped else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)-5s %(name)s: %(message)s",
    )
    output_root = args.output or get_settings().artifacts_dir
    return asyncio.run(run(args.fixture, output_root))


if __name__ == "__main__":
    raise SystemExit(main())
