"""The compiled graph is the execution path, and its gates actually fire.

These exist because for most of this project's life `build_graph()` was defined
and never called. The pipeline ran as a straight line of direct node calls in
`runner.py`, which meant `gate_precrawl` could not fire, the Postgres
checkpointer that was added as an approved dependency deviation was never
reached, and nothing noticed — every one of the 427 other tests passed
throughout, because none of them touched the graph.

So the assertions here are deliberately about wiring rather than about node
behaviour, which is covered elsewhere: that the gate refuses, that a refusal
terminates instead of falling through to scoring, and that progress still
reaches a caller now that events travel in the run config rather than being
emitted by the caller itself.
"""

from __future__ import annotations

import pytest

from wasl.graph import events as ev
from wasl.graph.build import (
    _after_crawl,
    _after_gate,
    _emit,
    build_graph,
    gate_precrawl,
    gate_pregenerate,
)
from wasl.graph.state import PageSummary, WaslState


def state(**overrides) -> WaslState:
    payload = {"job_id": "j1", "root_url": "https://example.com", "domain": "example.com"}
    payload.update(overrides)
    return WaslState(**payload)


# --- gate_precrawl -----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_fixture_needs_no_crawl_permission() -> None:
    """A fixture is a page already on disk. There is no request to gate."""
    result = await gate_precrawl(state(source="fixture"))
    assert result["awaiting_confirmation"] is None


@pytest.mark.asyncio
async def test_an_unlisted_domain_pauses_rather_than_failing() -> None:
    result = await gate_precrawl(state(root_url="https://not-in-the-seed-list.example"))
    assert result.get("awaiting_confirmation")
    assert "permission" in result["awaiting_confirmation"]


@pytest.mark.asyncio
async def test_the_gate_runs_before_any_request_is_sent() -> None:
    """No network call may precede the decision.

    Asserted by giving the gate a domain that is not allowlisted and checking it
    returns a pause without a Crawler ever being constructed — the crawl node is
    a separate graph node reached only through the conditional edge.
    """
    result = await gate_precrawl(state(root_url="https://not-in-the-seed-list.example"))
    assert _after_gate(state(awaiting_confirmation=result["awaiting_confirmation"])) == "halt"


# --- gate_pregenerate --------------------------------------------------------


def test_generating_for_someone_elses_domain_pauses() -> None:
    message = gate_pregenerate(state(), owns_domain=False)
    assert message is not None
    # The point of the gate is the unsigned/illustrative disclosure, so the text
    # has to actually carry it rather than being a generic confirm prompt.
    assert "illustrative and unsigned" in message
    assert "example.com" in message


def test_acknowledging_ownership_lets_generation_proceed() -> None:
    assert gate_pregenerate(state(), owns_domain=True) is None


def test_a_fixture_generates_without_a_prompt() -> None:
    """Our own saved page. There is no third party to misrepresent."""
    assert gate_pregenerate(state(source="fixture"), owns_domain=False) is None


# --- routing -----------------------------------------------------------------


def test_a_refused_crawl_terminates_instead_of_scoring() -> None:
    """A refusal must not fall through and produce a score of zero.

    Scoring a site we were refused permission to read would publish a number
    that looks like a finding about that site and is actually a finding about
    our own access.
    """
    refused = state(errors=["crawl refused [not_allowlisted]: nope"], pages=[])
    assert _after_crawl(refused) == "halt"


def test_reaching_nothing_still_scores() -> None:
    """Distinct from a refusal: we were allowed, and found nothing."""
    empty = state(pages=[PageSummary(url="u", final_url="u", status_code=404)])
    assert _after_crawl(empty) == "score"


def test_a_readable_page_goes_on_to_induce() -> None:
    ok = state(pages=[PageSummary(url="u", final_url="u", status_code=200)])
    assert _after_crawl(ok) == "induce"


# --- progress ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_progress_reaches_a_caller_through_the_run_config() -> None:
    seen: list[ev.ScanEvent] = []

    async def emit(event: ev.ScanEvent) -> None:
        seen.append(event)

    await _emit({"configurable": {"emit": emit}}, ev.node_start("j1", "crawl"))
    assert [e.node for e in seen] == ["crawl"]


@pytest.mark.asyncio
async def test_a_run_with_nowhere_to_report_still_runs() -> None:
    """Eval runs and tests pass no callback. That is normal, not an error."""
    await _emit(None, ev.node_start("j1", "crawl"))
    await _emit({}, ev.node_start("j1", "crawl"))
    await _emit({"configurable": {}}, ev.node_start("j1", "crawl"))


@pytest.mark.asyncio
async def test_a_failing_emit_does_not_take_the_scan_down() -> None:
    """The report is the deliverable; a dropped progress frame is cosmetic."""

    async def broken(event: ev.ScanEvent) -> None:
        raise RuntimeError("client vanished mid-stream")

    await _emit({"configurable": {"emit": broken}}, ev.node_start("j1", "crawl"))


# --- assembly ----------------------------------------------------------------


def test_the_graph_compiles_with_every_node_wired() -> None:
    compiled = build_graph()
    nodes = set(compiled.get_graph().nodes)
    assert {"gate_precrawl", "crawl", "induce", "synthesize", "critic", "score"} <= nodes


def test_the_entry_point_is_the_gate_not_the_crawl() -> None:
    """If crawl were the entry point the gate would be decorative."""
    compiled = build_graph()
    graph = compiled.get_graph()
    reached_from_start = {
        edge.target for edge in graph.edges if edge.source == "__start__"
    }
    assert reached_from_start == {"gate_precrawl"}


# --- end to end, no model, no network ----------------------------------------


@pytest.mark.asyncio
async def test_the_whole_graph_runs_on_a_fixture_and_reports_progress(monkeypatch) -> None:
    """The wiring test that would have caught the graph being orphaned.

    Runs gate_precrawl -> crawl -> induce -> synthesize -> critic -> score end to
    end against a saved page, with the three model nodes stubbed so it needs
    neither Ollama nor the network. Asserts both that a score comes out and that
    progress arrived, because the config-injected callback is the part most
    likely to break silently: if LangGraph stops passing `config`, every node
    still runs and the client simply goes quiet.
    """
    from wasl.graph.nodes import critic as critic_node
    from wasl.graph.nodes import induce as induce_node
    from wasl.graph.nodes import synthesize as synthesize_node

    async def no_capabilities(state, **kwargs):
        return {"candidate_capabilities": []}

    async def no_verdicts(state, **kwargs):
        return {"accepted_capabilities": [], "rejections": []}

    monkeypatch.setattr(induce_node, "induce", no_capabilities)
    monkeypatch.setattr(synthesize_node, "synthesize", no_capabilities)
    monkeypatch.setattr(critic_node, "critique", no_verdicts)

    seen: list[ev.ScanEvent] = []

    async def emit(event: ev.ScanEvent) -> None:
        seen.append(event)

    compiled = build_graph()
    raw = await compiled.ainvoke(
        WaslState(job_id="j-e2e", root_url="rich_site", source="fixture"),
        {"configurable": {"thread_id": "j-e2e", "emit": emit}},
    )
    final = raw if isinstance(raw, WaslState) else WaslState(**raw)

    assert final.score is not None, "the graph produced no score"
    assert final.evidence, "the graph produced no evidence"

    nodes = {e.node for e in seen if e.node}
    assert "gate_precrawl" in nodes, "the gate did not report - is config injected?"
    assert {"crawl", "extract", "score"} <= nodes, f"missing progress from {nodes}"
