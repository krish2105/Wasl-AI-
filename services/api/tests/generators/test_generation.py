"""Generated artifacts, verified by actually importing them.

The suite is built around one principle: a generated server is only real if a
fresh interpreter can import it and list its tools. Everything else — nice
docstrings, plausible schemas — is decoration on top of that.

`test_a_generated_server_imports_and_exposes_tools` is the acceptance criterion
from the build spec, and it runs the real subprocess rather than mocking it.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from wasl.crawler.evidence import Evidence, EvidenceStore
from wasl.generators.agent_card import build_agent_card
from wasl.generators.llms_txt import build_llms_txt
from wasl.generators.mcp_server import generate_server, safe_identifier
from wasl.generators.packager import generate_all
from wasl.generators.verify import verify_server
from wasl.graph.state import Capability, PageSummary, ToolSchema


def capability(**overrides) -> Capability:
    payload = {
        "name": "search_products",
        "verb": "search",
        "noun": "products",
        "description": "Search the product catalogue by keyword.",
        "evidence_ids": ["abc123def4567890"],
        "accepted": True,
        "tool_schema": ToolSchema(
            name="acme_search_products",
            description="Search products. Use when the user names a product.",
            parameters={
                "query": {
                    "type": "string",
                    "description": "Search keywords, e.g. 'brass elbow'",
                    "required": True,
                    "maxLength": 200,
                }
            },
            returns="Matching products.",
        ),
    }
    payload.update(overrides)
    return Capability(**payload)


def store() -> EvidenceStore:
    return EvidenceStore(
        [
            Evidence(
                source_url="https://acme.example/catalogue",
                kind="form",
                selector="form#search",
                raw="GET form, purpose=search, 2 fields",
                phase="pre_js",
            )
        ]
    )


def pages() -> list[PageSummary]:
    return [
        PageSummary(
            url="https://acme.example/catalogue",
            final_url="https://acme.example/catalogue",
            status_code=200,
        )
    ]


# --- identifier safety -------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Search Products", "search_products"),
        ("search-products!", "search_products"),
        ("class", "class_"),
        ("123abc", "field_123abc"),
        ("", "field"),
    ],
)
def test_model_proposed_names_become_valid_identifiers(raw: str, expected: str) -> None:
    """A model can propose anything; what lands in the file must be valid Python."""
    assert safe_identifier(raw) == expected


# --- the ship gate -----------------------------------------------------------


async def test_a_generated_server_imports_and_exposes_tools(tmp_path: Path) -> None:
    """The build spec's acceptance criterion, run for real in a subprocess."""
    outcome = await generate_all(
        job_id="test-job",
        domain="acme.example",
        site_name="Acme",
        capabilities=[capability()],
        pages=pages(),
        store=store(),
        score={"total": 60, "max_possible": 100, "band": "Readable"},
        output_root=tmp_path,
    )

    assert outcome.verification.imported, outcome.verification.summary()
    assert outcome.verification.tool_count >= 1
    assert outcome.shipped


async def test_generated_tools_carry_descriptions_and_parameters(tmp_path: Path) -> None:
    outcome = await generate_all(
        job_id="test-job",
        domain="acme.example",
        site_name="Acme",
        capabilities=[capability()],
        pages=pages(),
        store=store(),
        score=None,
        output_root=tmp_path,
    )

    tool = outcome.verification.tools[0]
    assert tool["description"].strip()
    assert tool["parameters"]


async def test_a_broken_server_is_not_packaged(tmp_path: Path) -> None:
    """The gate must actually gate. A syntactically valid but unimportable file
    produces no ZIP, so nothing unverified can be downloaded."""
    directory = tmp_path / "broken"
    directory.mkdir()
    (directory / "server.py").write_text("import nonexistent_module_xyz\nmcp = None\n")

    result = await verify_server(directory / "server.py")

    assert not result.imported
    assert not result.ships
    assert "import failed" in " ".join(result.errors)


async def test_a_server_with_no_tools_does_not_ship(tmp_path: Path) -> None:
    """Importing is necessary but not sufficient — it has to be useful."""
    outcome = await generate_all(
        job_id="empty-job",
        domain="acme.example",
        site_name="Acme",
        capabilities=[],
        pages=pages(),
        store=store(),
        score=None,
        output_root=tmp_path,
    )

    assert outcome.verification.imported
    assert outcome.verification.tool_count == 0
    assert not outcome.shipped
    assert outcome.artifacts.zip_path is None


async def test_the_zip_contains_every_artifact(tmp_path: Path) -> None:
    outcome = await generate_all(
        job_id="test-job",
        domain="acme.example",
        site_name="Acme",
        capabilities=[capability()],
        pages=pages(),
        store=store(),
        score=None,
        output_root=tmp_path,
    )

    assert outcome.artifacts.zip_path
    with zipfile.ZipFile(outcome.artifacts.zip_path) as archive:
        names = set(archive.namelist())

    assert names == {
        "server.py",
        "snapshot.json",
        "agent-card.json",
        "llms.txt",
        "pyproject.toml",
        "README.md",
    }


# --- no state-changing tools -------------------------------------------------


def test_state_changing_capabilities_never_become_tools() -> None:
    """Generating a 'book the room' tool for a site we do not control is how a
    portfolio project becomes an incident."""
    booking = capability(
        name="book_room",
        verb="book",
        state_changing=True,
        tool_schema=ToolSchema(name="acme_book_room", description="Book a room."),
    )

    source, _ = generate_server(
        capabilities=[booking],
        domain="acme.example",
        site_name="Acme",
        score_line="60/100",
    )

    assert "acme_book_room" not in source
    assert "No tools were generated" in source


def test_no_emitted_tool_name_contains_a_mutating_verb() -> None:
    source, _ = generate_server(
        capabilities=[capability()],
        domain="acme.example",
        site_name="Acme",
        score_line="60/100",
    )
    for verb in ("book", "buy", "cancel", "submit", "pay", "order", "reserve", "delete"):
        assert f"def acme_{verb}_" not in source


# --- parameter clamping ------------------------------------------------------


def test_string_parameters_are_clamped_regardless_of_what_the_model_proposed() -> None:
    """Every tool parameter is a security boundary for whoever runs the server."""
    reckless = capability(
        tool_schema=ToolSchema(
            name="acme_search_products",
            description="Search.",
            parameters={
                "query": {
                    "type": "string",
                    "description": "Anything at all",
                    "required": True,
                    "maxLength": 10_000_000,
                }
            },
        )
    )
    source, _ = generate_server(
        capabilities=[reckless], domain="acme.example", site_name="Acme", score_line="60/100"
    )
    assert "max_length=500" in source
    assert "10000000" not in source


def test_pagination_is_added_even_when_the_model_omits_it() -> None:
    source, _ = generate_server(
        capabilities=[capability()], domain="acme.example", site_name="Acme", score_line="60/100"
    )
    assert "limit: int" in source
    assert "offset: int" in source


# --- agent card --------------------------------------------------------------


def test_the_agent_card_declares_itself_unofficial_and_unsigned() -> None:
    card = build_agent_card(
        capabilities=[capability()],
        domain="acme.example",
        site_name="Acme",
        server_name="acme_example_mcp",
    )
    assert card["x-wasl"]["unofficial"] is True
    assert card["x-wasl"]["signed"] is False
    assert "not a registered production agent" in card["x-wasl"]["disclaimer"]
    assert "unofficial" in card["name"].lower()


def test_the_card_declares_no_authentication_for_v1() -> None:
    card = build_agent_card(
        capabilities=[capability()], domain="acme.example", site_name="Acme", server_name="x"
    )
    assert card["securitySchemes"] == {}
    assert card["security"] == []


def test_skills_map_only_from_accepted_capabilities() -> None:
    """The card and the 'what we refused' panel must never contradict each other."""
    card = build_agent_card(
        capabilities=[capability(), capability(name="rejected_one", accepted=False)],
        domain="acme.example",
        site_name="Acme",
        server_name="x",
    )
    assert len(card["skills"]) == 1


def test_skills_carry_their_evidence() -> None:
    card = build_agent_card(
        capabilities=[capability()], domain="acme.example", site_name="Acme", server_name="x"
    )
    assert card["skills"][0]["x-wasl-evidence"] == ["abc123def4567890"]


def test_detected_state_changing_capabilities_are_reported_in_the_card() -> None:
    """Detected and reported, never emitted."""
    card = build_agent_card(
        capabilities=[capability(name="book_room", verb="book", accepted=False)],
        domain="acme.example",
        site_name="Acme",
        server_name="x",
    )
    assert "book_room" in card["x-wasl"]["state_changing_capabilities_detected"]


# --- llms.txt ----------------------------------------------------------------


def test_llms_txt_follows_the_convention() -> None:
    text = build_llms_txt(
        site_name="Acme", domain="acme.example", capabilities=[capability()], pages=pages()
    )
    assert text.startswith("# Acme")
    assert "\n> " in text


def test_llms_txt_lists_only_pages_that_were_actually_fetched() -> None:
    """An llms.txt promising pages that do not exist teaches agents to distrust it."""
    blocked = PageSummary(
        url="https://acme.example/secret",
        final_url="https://acme.example/secret",
        status_code=0,
        robots_blocked=True,
    )
    text = build_llms_txt(
        site_name="Acme",
        domain="acme.example",
        capabilities=[capability()],
        pages=[*pages(), blocked],
    )
    assert "/catalogue" in text
    assert "/secret" not in text


def test_llms_txt_says_it_is_a_proposal_not_a_publication() -> None:
    text = build_llms_txt(
        site_name="Acme", domain="acme.example", capabilities=[capability()], pages=pages()
    )
    assert "has not been published by Acme" in text


# --- provenance --------------------------------------------------------------


async def test_every_generated_tool_docstring_cites_its_evidence(tmp_path: Path) -> None:
    """The score and the tools must trace back to the same markup."""
    outcome = await generate_all(
        job_id="test-job",
        domain="acme.example",
        site_name="Acme",
        capabilities=[capability()],
        pages=pages(),
        store=store(),
        score=None,
        output_root=tmp_path,
    )
    source = (outcome.directory / "server.py").read_text()
    assert "EVIDENCE:" in source
    assert "abc123def4567890" in source


async def test_the_readme_records_the_verification_output(tmp_path: Path) -> None:
    outcome = await generate_all(
        job_id="test-job",
        domain="acme.example",
        site_name="Acme",
        capabilities=[capability()],
        pages=pages(),
        store=store(),
        score=None,
        output_root=tmp_path,
    )
    readme = (outcome.directory / "README.md").read_text()
    assert "VERIFIED" in readme
    assert "unofficial" in readme.lower()
