"""Graph assembly.

    gate_precrawl -> crawl -> extract -> induce -> synthesize -> critic -> score
                                            ^                       |
                                            +------ reject ---------+  (max 3 rounds)

Two design decisions worth stating.

**Evidence is rebuilt from state between nodes, not passed as an object.**
`EvidenceRecord` is serialisable, `EvidenceStore` is not. Reconstructing it at
each node costs microseconds and buys real Postgres checkpointing — which means a
scan that dies at the critic resumes at the critic instead of re-crawling. That
matters more here than in most pipelines, because re-crawling is not a local
operation: it sends fresh requests to somebody else's server.

**The pre-crawl gate is a separate node, before any network call.** The master
prompt places a single human gate after scoring, which is too late to prevent an
out-of-allowlist crawl from happening. That gate is kept, as `gate_pregenerate`
in Phase 5; this one is added.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, StateGraph

from wasl.crawler.evidence import Evidence, EvidenceStore
from wasl.crawler.policy import CrawlPolicy
from wasl.graph.nodes import crawl as crawl_node
from wasl.graph.nodes import critic as critic_node
from wasl.graph.nodes import extract as extract_node
from wasl.graph.nodes import induce as induce_node
from wasl.graph.nodes import score as score_node
from wasl.graph.nodes import synthesize as synthesize_node
from wasl.graph.state import EvidenceRecord, WaslState
from wasl.llm.router import ModelRouter
from wasl.obs.tracing import node_span

logger = logging.getLogger(__name__)


def store_from_records(records: list[EvidenceRecord]) -> EvidenceStore:
    """Rebuild an EvidenceStore from serialised state.

    IDs are content-addressed, so a rebuilt row gets the same ID it had when it
    was first extracted. Citations recorded before a checkpoint still resolve
    after it — which would not be true with any other ID scheme.
    """
    return EvidenceStore(
        Evidence(
            source_url=record.source_url,
            kind=record.kind,  # type: ignore[arg-type]
            selector=record.selector,
            raw=record.raw,
            phase=record.phase,  # type: ignore[arg-type]
        )
        for record in records
    )


# --- gate --------------------------------------------------------------------


async def gate_precrawl(state: WaslState) -> dict:
    """Refuse, or pause for confirmation, before a single request is sent.

    The exclusion registry is checked first and cannot be overridden by a user
    submission. An out-of-allowlist domain does not fail — it pauses, and a human
    decides.
    """
    with node_span("gate_precrawl", job_id=state.job_id):
        decision = CrawlPolicy().check_domain(
            state.root_url, user_submitted=state.user_submitted
        )

        if decision.allowed:
            return {"awaiting_confirmation": None}

        if decision.rule == "excluded":
            return {
                "errors": [f"refused [excluded]: {decision.reason}"],
                "awaiting_confirmation": None,
            }

        return {
            "awaiting_confirmation": (
                f"{decision.reason}. Confirm you own this domain or have permission "
                "to scan it before the crawl proceeds."
            )
        }


def _after_gate(state: WaslState) -> str:
    if state.awaiting_confirmation:
        return "halt"
    if state.errors:
        return "halt"
    return "crawl"


# --- node wrappers -----------------------------------------------------------


async def _crawl(state: WaslState) -> dict:
    result = await crawl_node.crawl(state)
    pages = result.pop("_pages", None)
    artifacts = result.pop("_artifacts", None)
    if pages is not None:
        # Extraction is deterministic and cheap; running it here avoids carrying
        # captured pages across a checkpoint boundary.
        extracted = await extract_node.extract(
            state.model_copy(update={"pages": result.get("pages", [])}),
            pages=pages,
            artifacts=artifacts,
        )
        extracted.pop("_store", None)
        result.update(extracted)
    return result


async def _induce(state: WaslState, router: ModelRouter) -> dict:
    return await induce_node.induce(state, store=store_from_records(state.evidence), router=router)


async def _synthesize(state: WaslState, router: ModelRouter) -> dict:
    return await synthesize_node.synthesize(
        state, store=store_from_records(state.evidence), router=router
    )


async def _critique(state: WaslState, router: ModelRouter) -> dict:
    return await critic_node.critique(
        state, store=store_from_records(state.evidence), router=router
    )


async def _score(state: WaslState) -> dict:
    result = await score_node.score(state, store=store_from_records(state.evidence))
    result.pop("_score", None)
    return result


def _after_crawl(state: WaslState) -> str:
    if not state.pages or state.pages_ok == 0:
        # Nothing was read, so there is nothing to induce from. Scoring still
        # runs: "we reached nothing" is itself a reportable result.
        return "score"
    return "induce"


def build_graph(router: ModelRouter | None = None, *, checkpointer: Any = None):
    """Assemble the scan graph."""
    router = router or ModelRouter()
    graph: StateGraph = StateGraph(WaslState)

    graph.add_node("gate_precrawl", gate_precrawl)
    graph.add_node("crawl", _crawl)
    graph.add_node("induce", lambda s: _induce(s, router))
    graph.add_node("synthesize", lambda s: _synthesize(s, router))
    graph.add_node("critic", lambda s: _critique(s, router))
    graph.add_node("score", _score)

    graph.set_entry_point("gate_precrawl")
    graph.add_conditional_edges(
        "gate_precrawl", _after_gate, {"crawl": "crawl", "halt": END}
    )
    graph.add_conditional_edges("crawl", _after_crawl, {"induce": "induce", "score": "score"})
    graph.add_edge("induce", "synthesize")
    graph.add_edge("synthesize", "critic")
    graph.add_edge("critic", "score")
    graph.add_edge("score", END)

    return graph.compile(checkpointer=checkpointer)
