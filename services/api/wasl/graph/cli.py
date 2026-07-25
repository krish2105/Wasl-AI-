"""Run the agent pipeline and print capabilities, citations and rejections.

    uv run python -m wasl.graph.cli --fixture rich_site --fixture spa_site
    uv run python -m wasl.graph.cli --url https://example.com     # needs a live crawl

Fixture mode runs the real induce -> synthesize -> critic -> score path against
saved pages, skipping only the network. Every model call, every validator and
every critic rule is the production one, so what it prints is what a live scan
would print given the same evidence.

The output leads with rejections rather than burying them. A tool that shows what
it refused to generate is more trustworthy than one that shows only successes,
and that is as true of a terminal report as it is of the UI.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import uuid

from wasl.crawler.detectors import extract_all
from wasl.graph.build import store_from_records
from wasl.graph.nodes import critic as critic_node
from wasl.graph.nodes import extract as extract_node
from wasl.graph.nodes import induce as induce_node
from wasl.graph.nodes import score as score_node
from wasl.graph.nodes import synthesize as synthesize_node
from wasl.graph.nodes.crawl import summarise
from wasl.graph.state import WaslState
from wasl.llm.router import ModelRouter, Role
from wasl.scoring.cli import load_fixture, neutral_artifacts
from wasl.scoring.rubric import format_report

RULE = "=" * 78


async def run_fixture(name: str, router: ModelRouter, *, show_score: bool) -> WaslState:
    page = load_fixture(name)
    pages = [page]
    artifacts = neutral_artifacts(page.final_url)

    state = WaslState(
        job_id=str(uuid.uuid4())[:8],
        root_url=page.final_url,
        domain=artifacts.domain,
        pages=[summarise(page)],
    )

    store = extract_all(pages, artifacts)
    state = state.model_copy(update={"evidence": extract_node.to_records(store)})

    print(f"{RULE}\nPIPELINE  {name}  ({artifacts.domain})\n{RULE}")
    print(f"  evidence: {len(store)} rows across {len(store.kind_counts())} kinds")

    rebuilt = store_from_records(state.evidence)

    induced = await induce_node.induce(state, store=rebuilt, router=router)
    state = state.model_copy(
        update={
            "candidate_capabilities": induced.get("candidate_capabilities", []),
            "errors": [*state.errors, *induced.get("errors", [])],
        }
    )
    print(f"  induce:   {len(state.candidate_capabilities)} candidate(s)")

    synthesized = await synthesize_node.synthesize(state, store=rebuilt, router=router)
    state = state.model_copy(
        update={
            "candidate_capabilities": synthesized.get("candidate_capabilities", []),
            "errors": [*state.errors, *synthesized.get("errors", [])],
        }
    )
    with_tools = sum(1 for c in state.candidate_capabilities if c.tool_schema)
    print(f"  schemas:  {with_tools} tool schema(s)")

    critiqued = await critic_node.critique(state, store=rebuilt, router=router)
    state = state.model_copy(
        update={
            "accepted_capabilities": critiqued.get("accepted_capabilities", []),
            "rejections": [*state.rejections, *critiqued.get("rejections", [])],
            "critic_rounds": critiqued.get("critic_rounds", 1),
            "errors": [*state.errors, *critiqued.get("errors", [])],
        }
    )

    scored = await score_node.score(state, store=rebuilt)
    state = state.model_copy(update={"score": scored.get("score")})

    # --- report --------------------------------------------------------------

    print(f"\n  ACCEPTED ({len(state.accepted_capabilities)})")
    if not state.accepted_capabilities:
        print("    (none)")
    for capability in state.accepted_capabilities:
        print(f"    + {capability.name}  [{capability.verb} / {capability.noun}]")
        print(f"        {capability.description[:100]}")
        print(f"        cites: {', '.join(capability.evidence_ids)}")
        for eid in capability.evidence_ids[:1]:
            found = rebuilt.get(eid)
            if found:
                print(f"          -> {found.kind}: {found.short}")
        if capability.tool_schema:
            params = ", ".join(capability.tool_schema.parameters) or "none"
            print(f"        tool: {capability.tool_schema.name}({params})")

    print(f"\n  REFUSED ({len(state.rejections)})")
    if not state.rejections:
        print("    (none)")
    for rejection in state.rejections:
        final = " [FINAL]" if rejection.final else ""
        print(f"    - {rejection.capability_name}  rule={rejection.rule_id}{final}")
        print(f"        {rejection.reason[:150]}")

    dangling = state.dangling_references()
    print(f"\n  citation integrity: {'OK' if not dangling else f'{len(dangling)} DANGLING: {dangling}'}")

    if state.errors:
        print(f"\n  ERRORS ({len(state.errors)})")
        for error in state.errors[:8]:
            print(f"    ! {error[:140]}")

    if show_score and state.score:
        print()
        result = scored.get("_score")
        if result is not None:
            print(format_report(result, domain=artifacts.domain))

    return state


async def main_async(args: argparse.Namespace) -> int:
    router = ModelRouter()
    print(f"\nmodel chain — {router.describe_chain(Role.INDUCE)}\n")

    states = []
    for name in args.fixture:
        states.append(await run_fixture(name, router, show_score=args.score))

    print(f"\n{RULE}\nRUN SUMMARY\n{RULE}")
    print(f"  model calls: {router.usage.calls}")
    print(f"  tokens: {router.usage.input_tokens} in, {router.usage.output_tokens} out")
    print(f"  providers used: {router.usage.by_provider or 'none'}")
    print(f"  cost: ${router.usage.cost_usd:.2f}")
    if router.usage.failures:
        print(f"  provider fallbacks: {len(router.usage.failures)}")
        for failure in router.usage.failures[:4]:
            print(f"    - {failure[:120]}")

    total_accepted = sum(len(s.accepted_capabilities) for s in states)
    total_rejected = sum(len(s.rejections) for s in states)
    print(f"  capabilities: {total_accepted} accepted, {total_rejected} refused")
    print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", action="append", default=[], help="fixture name (repeatable)")
    parser.add_argument("--score", action="store_true", help="also print the six-axis table")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if not args.fixture:
        parser.error("give at least one --fixture NAME")

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)-5s %(name)s: %(message)s",
    )
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
