"""Checkpointing degrades, it does not fail.

The valuable assertion here is the negative one: when Postgres is unreachable the
scan still runs. Resume is a recovery convenience; refusing to start a scan
because the recovery path is unavailable would trade a rare inconvenience for a
constant one.

The DSN test looks trivial and is not. Settings carries the SQLAlchemy spelling
`postgresql+psycopg://` because SQLAlchemy needs the dialect suffix to choose a
driver, and psycopg rejects that same string. The failure mode is a connection
error that reads exactly like the database being down, which is the most
expensive kind of wrong.
"""

import pytest

from wasl.graph.checkpoint import active_checkpointer, open_checkpointer, psycopg_dsn


# --- dsn ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "sqlalchemy_url",
    [
        "postgresql+psycopg://u:p@localhost:5432/wasl",
        "postgresql+asyncpg://u:p@localhost:5432/wasl",
        "postgresql+psycopg2://u:p@localhost:5432/wasl",
    ],
)
def test_the_dialect_suffix_is_stripped_for_psycopg(sqlalchemy_url: str) -> None:
    dsn = psycopg_dsn(sqlalchemy_url)
    assert dsn == "postgresql://u:p@localhost:5432/wasl"
    assert "+" not in dsn.split("@")[0]


def test_a_plain_url_is_left_alone() -> None:
    plain = "postgresql://u:p@localhost:5432/wasl"
    assert psycopg_dsn(plain) == plain


def test_credentials_survive_the_conversion() -> None:
    """A mangled password is indistinguishable from a wrong one at the socket."""
    dsn = psycopg_dsn("postgresql+psycopg://user:p%40ss+word@host:5432/db")
    assert "user:p%40ss+word@host" in dsn


# --- degradation -------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unreachable_database_yields_none_rather_than_raising() -> None:
    """Port 1 is reserved and nothing listens on it."""
    async with open_checkpointer("postgresql://u:p@127.0.0.1:1/nope", connect_timeout=0.4) as saver:
        assert saver is None


@pytest.mark.asyncio
async def test_a_nonsense_url_yields_none_rather_than_raising() -> None:
    async with open_checkpointer("not-a-database-url-at-all", connect_timeout=0.4) as saver:
        assert saver is None


@pytest.mark.asyncio
async def test_the_active_checkpointer_is_cleared_on_exit() -> None:
    """A stale saver pointing at a closed pool is worse than no saver."""
    async with open_checkpointer("postgresql://u:p@127.0.0.1:1/nope", connect_timeout=0.4):
        pass
    assert active_checkpointer() is None


def test_there_is_no_checkpointer_outside_the_application_lifespan() -> None:
    """Eval runs and tests build the graph directly; None is the correct answer."""
    assert active_checkpointer() is None


# --- the graph accepts it either way -----------------------------------------


def test_the_graph_compiles_without_a_checkpointer() -> None:
    from wasl.graph.build import build_graph

    assert build_graph(checkpointer=None) is not None


@pytest.mark.asyncio
async def test_a_scan_still_runs_with_checkpointing_unavailable(monkeypatch) -> None:
    """The whole point. No Postgres, no resume, but the scan completes."""
    from wasl.graph.build import build_graph
    from wasl.graph.nodes import critic as critic_node
    from wasl.graph.nodes import induce as induce_node
    from wasl.graph.nodes import synthesize as synthesize_node
    from wasl.graph.state import WaslState

    async def nothing(state, **kwargs):
        return {"candidate_capabilities": []}

    async def no_verdicts(state, **kwargs):
        return {"accepted_capabilities": [], "rejections": []}

    monkeypatch.setattr(induce_node, "induce", nothing)
    monkeypatch.setattr(synthesize_node, "synthesize", nothing)
    monkeypatch.setattr(critic_node, "critique", no_verdicts)

    compiled = build_graph(checkpointer=active_checkpointer())
    raw = await compiled.ainvoke(
        WaslState(job_id="j-nocp", root_url="rich_site", source="fixture"),
        {"configurable": {"thread_id": "j-nocp"}},
    )
    final = raw if isinstance(raw, WaslState) else WaslState(**raw)
    assert final.score is not None


# --- resume, against a real Postgres -----------------------------------------
#
# `infra`-marked: skipped loudly without `docker compose up -d` rather than
# quietly passing. A checkpointer test that never touches Postgres would assert
# nothing about the only thing the checkpointer is for.


@pytest.mark.infra
@pytest.mark.asyncio
async def test_a_failed_scan_resumes_without_crawling_again(
    require_infra, monkeypatch
) -> None:
    """The entire justification for the langgraph-checkpoint-postgres deviation.

    Kills the run at the critic, then resumes it. The assertion that matters is
    the crawl counter: re-crawling is not a local operation, and a resume that
    silently re-fetches somebody else's pages would be worse than no resume,
    because it would look like it worked.
    """
    import os

    from wasl.graph.build import build_graph
    from wasl.graph.nodes import crawl as crawl_node
    from wasl.graph.nodes import critic as critic_node
    from wasl.graph.nodes import induce as induce_node
    from wasl.graph.nodes import synthesize as synthesize_node
    from wasl.graph.state import WaslState

    crawls = {"n": 0}
    real_crawl = crawl_node.crawl

    async def counting_crawl(state):
        crawls["n"] += 1
        return await real_crawl(state)

    async def nothing(state, **kwargs):
        return {"candidate_capabilities": []}

    async def explode(state, **kwargs):
        raise RuntimeError("critic died mid-run")

    async def no_verdicts(state, **kwargs):
        return {"accepted_capabilities": [], "rejections": []}

    monkeypatch.setattr(crawl_node, "crawl", counting_crawl)
    monkeypatch.setattr(induce_node, "induce", nothing)
    monkeypatch.setattr(synthesize_node, "synthesize", nothing)
    monkeypatch.setattr(critic_node, "critique", explode)

    # A fresh thread per run, so a re-run of the suite does not resume the last one.
    thread = f"test-resume-{os.getpid()}"

    async with open_checkpointer(os.environ["DATABASE_URL"]) as saver:
        assert saver is not None, "infra fixture said Postgres was up"
        graph = build_graph(checkpointer=saver)
        config = {"configurable": {"thread_id": thread}}

        with pytest.raises(RuntimeError, match="critic died"):
            await graph.ainvoke(
                WaslState(job_id=thread, root_url="rich_site", source="fixture"), config
            )

        snapshot = await graph.aget_state(config)
        assert snapshot.next == ("critic",), "did not stop where it died"
        assert snapshot.values["evidence"], "evidence was not persisted"
        crawled_once = crawls["n"]

        # Resume: passing None continues from the checkpoint rather than restarting.
        monkeypatch.setattr(critic_node, "critique", no_verdicts)
        raw = await graph.ainvoke(None, config)
        final = raw if isinstance(raw, WaslState) else WaslState(**raw)

    assert final.score is not None, "the resumed run produced no score"
    assert crawls["n"] == crawled_once == 1, (
        f"resume re-crawled: {crawls['n']} crawls, expected 1"
    )


@pytest.mark.infra
@pytest.mark.asyncio
async def test_state_survives_the_round_trip_as_its_own_types(require_infra) -> None:
    """Deserialised rows must come back as our models, not bare dicts.

    The serializer carries an explicit allowlist. Getting it wrong does not raise
    — it returns dicts, and the first symptom is an AttributeError several nodes
    later in a resumed run.
    """
    import os

    from wasl.graph.build import build_graph
    from wasl.graph.nodes import critic as critic_node
    from wasl.graph.nodes import induce as induce_node
    from wasl.graph.nodes import synthesize as synthesize_node
    from wasl.graph.state import EvidenceRecord, PageSummary, WaslState

    async def nothing(state, **kwargs):
        return {"candidate_capabilities": []}

    async def no_verdicts(state, **kwargs):
        return {"accepted_capabilities": [], "rejections": []}

    induce_node.induce = nothing  # type: ignore[assignment]
    synthesize_node.synthesize = nothing  # type: ignore[assignment]
    critic_node.critique = no_verdicts  # type: ignore[assignment]

    thread = f"test-roundtrip-{os.getpid()}"
    async with open_checkpointer(os.environ["DATABASE_URL"]) as saver:
        graph = build_graph(checkpointer=saver)
        config = {"configurable": {"thread_id": thread}}
        await graph.ainvoke(
            WaslState(job_id=thread, root_url="rich_site", source="fixture"), config
        )
        values = (await graph.aget_state(config)).values

    assert isinstance(values["evidence"][0], EvidenceRecord)
    assert isinstance(values["pages"][0], PageSummary)
