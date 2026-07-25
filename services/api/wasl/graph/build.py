"""Graph assembly.

    gate_precrawl -> crawl -> induce -> synthesize -> critic -> score
                                 ^                      |
                                 +------ reject --------+  (max 3 rounds)

Three design decisions worth stating.

**Evidence is rebuilt from state between nodes, not passed as an object.**
`EvidenceRecord` is serialisable, `EvidenceStore` is not. Reconstructing it at
each node costs microseconds and buys real Postgres checkpointing — which means a
scan that dies at the critic resumes at the critic instead of re-crawling. That
matters more here than in most pipelines, because re-crawling is not a local
operation: it sends fresh requests to somebody else's server.

**The pre-crawl gate is a separate node, before any network call.** The master
prompt places a single human gate after scoring, which is too late to prevent an
out-of-allowlist crawl from happening. That gate is kept, as `gate_pregenerate`
below; this one is added.

**Progress events travel in the run config, not in state.** A node emits by
pulling a callback out of `config["configurable"]["emit"]`. The alternative —
letting the caller drive the loop and report between nodes — collapses a 12-page
crawl at 0.5 req/s into a single silent 24-second step, because LangGraph only
yields once a node returns. The callback is deliberately absent from `WaslState`:
it is not serialisable, and anything in state has to survive a checkpoint.

`gate_pregenerate` is not a node. Generation needs the raw pre-JS HTML and the
verification outcome, neither of which is in state and neither of which should
be, so it runs at the generation boundary in `runner.py` instead. Putting it in
the graph would mean carrying megabytes of HTML through every checkpoint to
serve one call.
"""

# NOTE: no `from __future__ import annotations` here, deliberately.
# LangGraph decides whether to inject the run config by inspecting the
# parameter's annotation. Under PEP 563 that annotation is the *string*
# "RunnableConfig | None", the check fails, config is never passed, and every
# node runs perfectly while the client receives no progress at all. Python
# 3.11 evaluates `X | None` natively, so nothing here needs the import.

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph

from wasl.crawler.evidence import Evidence, EvidenceStore
from wasl.crawler.policy import CrawlPolicy
from wasl.graph import events as ev
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


# --- progress -----------------------------------------------------------------


async def _emit(config: RunnableConfig | None, event: Any) -> None:
    """Send a progress event, if this run was given somewhere to send it.

    A missing callback is the normal case for a test or an eval run, not an
    error, so it is silently skipped. An emit that raises must never take the
    scan down with it: the report is the deliverable and a dropped progress
    frame is cosmetic.
    """
    if not config:
        return
    emit = (config.get("configurable") or {}).get("emit")
    if emit is None:
        return
    try:
        await emit(event)
    except Exception:  # pragma: no cover - progress is never load-bearing
        logger.debug("progress emit failed", exc_info=True)


# --- gates --------------------------------------------------------------------


async def gate_precrawl(state: WaslState, config: RunnableConfig | None = None) -> dict:
    """Refuse, or pause for confirmation, before a single request is sent.

    The exclusion registry is checked first and cannot be overridden by a user
    submission. An out-of-allowlist domain does not fail — it pauses, and a human
    decides.

    A fixture replays a page already on disk and sends no request, so there is
    nothing here for the gate to protect and it passes straight through.
    """
    with node_span("gate_precrawl", job_id=state.job_id):
        await _emit(config, ev.node_start(state.job_id, "gate_precrawl"))

        if state.source == "fixture":
            await _emit(
                config,
                ev.node_complete(state.job_id, "gate_precrawl", decision="fixture"),
            )
            return {"awaiting_confirmation": None}

        decision = CrawlPolicy().check_domain(
            state.root_url, user_submitted=state.user_submitted
        )

        if decision.allowed:
            await _emit(
                config, ev.node_complete(state.job_id, "gate_precrawl", decision="allowed")
            )
            return {"awaiting_confirmation": None}

        if decision.rule == "excluded":
            message = f"refused [excluded]: {decision.reason}"
            await _emit(config, ev.error(state.job_id, message, node="gate_precrawl"))
            return {"errors": [message], "awaiting_confirmation": None}

        pause = (
            f"{decision.reason}. Confirm you own this domain or have permission "
            "to scan it before the crawl proceeds."
        )
        await _emit(config, ev.error(state.job_id, pause, node="gate_precrawl"))
        return {"awaiting_confirmation": pause}


def gate_pregenerate(state: WaslState, *, owns_domain: bool = False) -> str | None:
    """Confirm before writing artifacts for a domain the user does not own.

    Returns the confirmation text to show, or None to proceed.

    Not a graph node, deliberately: generation needs the raw pre-JS HTML and the
    verification outcome, and neither belongs in a checkpointed state object. It
    is called at the generation boundary instead, which is the point it actually
    guards.

    The artifacts are illustrative and unsigned. Emitting an MCP server that
    claims to speak for somebody else's business is the failure this exists to
    prevent, so scanning a third party is allowed and generating for one pauses.
    """
    if owns_domain or state.source == "fixture":
        return None
    return (
        f"The artifacts about to be generated describe {state.domain or state.root_url}, "
        "a domain you have not confirmed you own. They are illustrative and unsigned: "
        "they are not published by that business and do not speak for it. Confirm you "
        "understand before they are written."
    )


def _after_gate(state: WaslState) -> str:
    if state.awaiting_confirmation:
        return "halt"
    if state.errors:
        return "halt"
    return "crawl"


# --- node wrappers -----------------------------------------------------------


async def _crawl(state: WaslState, config: RunnableConfig | None = None) -> dict:
    await _emit(config, ev.node_start(state.job_id, "crawl"))
    result = await crawl_node.crawl(state)

    if result.get("errors"):
        await _emit(config, ev.error(state.job_id, result["errors"][0], node="crawl"))
        return result

    pages = result.pop("_pages", None)
    artifacts = result.pop("_artifacts", None)

    for summary in result.get("pages", []):
        await _emit(
            config,
            ev.progress(
                state.job_id,
                "crawl",
                summary.final_url,
                status=summary.status_code,
                robots_blocked=summary.robots_blocked,
                pre_js_chars=summary.pre_js_chars,
                post_js_chars=summary.post_js_chars,
            ),
        )
    await _emit(
        config,
        ev.node_complete(state.job_id, "crawl", pages=len(result.get("pages", []))),
    )

    if pages is not None:
        # Extraction is deterministic and cheap; running it here avoids carrying
        # captured pages across a checkpoint boundary.
        await _emit(config, ev.node_start(state.job_id, "extract"))
        extracted = await extract_node.extract(
            state.model_copy(update={"pages": result.get("pages", [])}),
            pages=pages,
            artifacts=artifacts,
        )
        store = extracted.pop("_store", None)
        result.update(extracted)

        if store is not None:
            for kind, count in store.kind_counts().items():
                await _emit(config, ev.progress(state.job_id, "extract", kind, count=count))
            await _emit(
                config,
                ev.node_complete(
                    state.job_id,
                    "extract",
                    evidence=len(store),
                    kinds=len(store.kind_counts()),
                ),
            )
    return result


async def _induce(state: WaslState, router: ModelRouter, config: RunnableConfig | None = None) -> dict:
    await _emit(config, ev.node_start(state.job_id, "induce"))
    result = await induce_node.induce(
        state, store=store_from_records(state.evidence), router=router
    )
    for capability in result.get("candidate_capabilities", []):
        await _emit(
            config,
            ev.ScanEvent(
                type=ev.EventType.CAPABILITY,
                job_id=state.job_id,
                node="induce",
                message=capability.name,
                data={
                    "name": capability.name,
                    "verb": capability.verb,
                    "noun": capability.noun,
                    "evidence_ids": capability.evidence_ids,
                },
            ),
        )
    await _emit(
        config,
        ev.node_complete(
            state.job_id,
            "induce",
            candidates=len(result.get("candidate_capabilities", [])),
        ),
    )
    return result


async def _synthesize(state: WaslState, router: ModelRouter, config: RunnableConfig | None = None) -> dict:
    await _emit(config, ev.node_start(state.job_id, "synthesize"))
    result = await synthesize_node.synthesize(
        state, store=store_from_records(state.evidence), router=router
    )
    await _emit(
        config,
        ev.node_complete(
            state.job_id,
            "synthesize",
            schemas=sum(
                1 for c in result.get("candidate_capabilities", []) if c.tool_schema
            ),
        ),
    )
    return result


async def _critique(state: WaslState, router: ModelRouter, config: RunnableConfig | None = None) -> dict:
    await _emit(config, ev.node_start(state.job_id, "critic"))
    result = await critic_node.critique(
        state, store=store_from_records(state.evidence), router=router
    )
    for rejection in result.get("rejections", []):
        await _emit(
            config,
            ev.ScanEvent(
                type=ev.EventType.REJECTION,
                job_id=state.job_id,
                node="critic",
                message=rejection.capability_name,
                data={"rule_id": rejection.rule_id, "reason": rejection.reason},
            ),
        )
    await _emit(
        config,
        ev.node_complete(
            state.job_id,
            "critic",
            accepted=len(result.get("accepted_capabilities", [])),
            refused=len(result.get("rejections", [])),
        ),
    )
    return result


async def _score(state: WaslState, config: RunnableConfig | None = None) -> dict:
    await _emit(config, ev.node_start(state.job_id, "score"))
    result = await score_node.score(state, store=store_from_records(state.evidence))
    result.pop("_score", None)
    await _emit(
        config,
        ev.ScanEvent(
            type=ev.EventType.SCORE,
            job_id=state.job_id,
            node="score",
            data=result.get("score") or {},
        ),
    )
    await _emit(config, ev.node_complete(state.job_id, "score"))
    return result


def _after_crawl(state: WaslState) -> str:
    if state.errors and not state.pages:
        # A refusal is terminal: there is nothing to score and nothing to report
        # beyond the refusal itself, which is already in state.
        return "halt"
    if not state.pages or state.pages_ok == 0:
        # Nothing was read, so there is nothing to induce from. Scoring still
        # runs: "we reached nothing" is itself a reportable result.
        return "score"
    return "induce"


def build_graph(router: ModelRouter | None = None, *, checkpointer: Any = None):
    """Assemble the scan graph."""
    router = router or ModelRouter()
    graph: StateGraph = StateGraph(WaslState)

    # These are `async def` closures rather than lambdas on purpose. LangGraph
    # decides whether to await a node with `iscoroutinefunction`, and a lambda is
    # a *sync* callable that happens to return a coroutine — so a lambda node is
    # invoked, never awaited, and its work silently does not happen. That was the
    # shape of the original code here, and it is the clearest single piece of
    # evidence that this graph had never actually been run.
    async def induce(state: WaslState, config: RunnableConfig | None = None) -> dict:
        return await _induce(state, router, config)

    async def synthesize(state: WaslState, config: RunnableConfig | None = None) -> dict:
        return await _synthesize(state, router, config)

    async def critic(state: WaslState, config: RunnableConfig | None = None) -> dict:
        return await _critique(state, router, config)

    graph.add_node("gate_precrawl", gate_precrawl)
    graph.add_node("crawl", _crawl)
    graph.add_node("induce", induce)
    graph.add_node("synthesize", synthesize)
    graph.add_node("critic", critic)
    graph.add_node("score", _score)

    graph.set_entry_point("gate_precrawl")
    graph.add_conditional_edges(
        "gate_precrawl", _after_gate, {"crawl": "crawl", "halt": END}
    )
    graph.add_conditional_edges(
        "crawl", _after_crawl, {"induce": "induce", "score": "score", "halt": END}
    )
    graph.add_edge("induce", "synthesize")
    graph.add_edge("synthesize", "critic")
    graph.add_edge("critic", "score")
    graph.add_edge("score", END)

    return graph.compile(checkpointer=checkpointer)
