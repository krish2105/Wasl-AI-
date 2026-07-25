"""Graph state invariants.

The first test in this file is the one the whole grounding argument rests on: an
uncited capability cannot be constructed. Not "is rejected later", not "is
discouraged by the prompt" — cannot be built.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from wasl.graph.state import Budget, Capability, PageSummary, Rejection, ToolSchema, WaslState


def capability(**overrides) -> Capability:
    payload = {
        "name": "search_products",
        "verb": "search",
        "noun": "products",
        "description": "Search the catalogue.",
        "evidence_ids": ["abc123def4567890"],
    }
    payload.update(overrides)
    return Capability(**payload)


# --- the load-bearing validator ----------------------------------------------


def test_a_capability_without_evidence_cannot_be_constructed() -> None:
    with pytest.raises(ValidationError, match="without evidence is not a capability"):
        capability(evidence_ids=[])


def test_the_error_explains_why_rather_than_just_failing() -> None:
    with pytest.raises(ValidationError) as exc:
        capability(evidence_ids=[])
    assert "unrepresentable" in str(exc.value)


def test_a_cited_capability_constructs_fine() -> None:
    assert capability().evidence_ids == ["abc123def4567890"]


def test_names_are_normalised_to_snake_case() -> None:
    assert capability(name="Search Products").name == "search_products"
    assert capability(name="get-product-details").name == "get_product_details"


# --- state-change detection is independent of the model's claim ---------------


def test_an_explicitly_flagged_capability_is_state_changing() -> None:
    assert capability(state_changing=True).implies_state_change()


def test_a_state_changing_verb_is_caught_even_if_the_model_says_otherwise() -> None:
    """A model wanting its tool emitted has an incentive to mark it read-only."""
    assert capability(verb="book", state_changing=False).implies_state_change()
    assert capability(verb="cancel", state_changing=False).implies_state_change()


def test_a_state_changing_name_is_caught_too() -> None:
    assert capability(name="submit_enquiry", verb="get", state_changing=False).implies_state_change()


def test_read_only_capabilities_are_not_flagged() -> None:
    for verb in ("search", "get", "list", "check", "find", "browse"):
        assert not capability(verb=verb, name=f"{verb}_things").implies_state_change(), verb


# --- tool schema bounds ------------------------------------------------------


def test_a_described_and_bounded_string_parameter_is_fine() -> None:
    schema = ToolSchema(
        name="acme_search",
        description="Search.",
        parameters={"q": {"type": "string", "description": "Keywords", "maxLength": 200}},
    )
    assert schema.unbounded_parameters() == []


def test_a_string_parameter_with_no_length_bound_is_flagged() -> None:
    schema = ToolSchema(
        name="acme_search",
        description="Search.",
        parameters={"q": {"type": "string", "description": "Keywords"}},
    )
    assert schema.unbounded_parameters() == ["q"]


def test_a_string_parameter_with_no_description_is_flagged() -> None:
    schema = ToolSchema(
        name="acme_search",
        description="Search.",
        parameters={"q": {"type": "string", "maxLength": 100}},
    )
    assert schema.unbounded_parameters() == ["q"]


def test_an_enum_or_pattern_counts_as_a_bound() -> None:
    schema = ToolSchema(
        name="acme_list",
        description="List.",
        parameters={
            "sort": {"type": "string", "description": "Sort order", "enum": ["asc", "desc"]},
            "code": {"type": "string", "description": "Code", "pattern": "^[A-Z]{3}$"},
        },
    )
    assert schema.unbounded_parameters() == []


def test_non_string_parameters_need_no_length_bound() -> None:
    schema = ToolSchema(
        name="acme_list",
        description="List.",
        parameters={"limit": {"type": "integer", "description": "Max results", "maximum": 100}},
    )
    assert schema.unbounded_parameters() == []


# --- referential integrity ---------------------------------------------------


def test_dangling_references_are_reported() -> None:
    from wasl.graph.state import EvidenceRecord

    state = WaslState(
        job_id="j1",
        root_url="https://example.com",
        evidence=[
            EvidenceRecord(id="real0000000000aa", source_url="https://example.com", kind="form", raw="x", phase="pre_js")
        ],
        candidate_capabilities=[capability(evidence_ids=["real0000000000aa", "fake000000000000"])],
    )
    assert state.dangling_references() == ["fake000000000000"]


def test_no_dangling_references_when_every_citation_resolves() -> None:
    from wasl.graph.state import EvidenceRecord

    state = WaslState(
        job_id="j1",
        root_url="https://example.com",
        evidence=[
            EvidenceRecord(id="real0000000000aa", source_url="https://example.com", kind="form", raw="x", phase="pre_js")
        ],
        candidate_capabilities=[capability(evidence_ids=["real0000000000aa"])],
    )
    assert state.dangling_references() == []


# --- budget ------------------------------------------------------------------


def test_budget_reports_exhaustion_on_call_count() -> None:
    budget = Budget(max_model_calls=5, model_calls_used=5)
    assert budget.exhausted
    assert budget.calls_remaining == 0


def test_a_fresh_budget_is_not_exhausted() -> None:
    assert not Budget().exhausted


# --- derived state -----------------------------------------------------------


def test_degraded_is_true_only_when_every_ok_page_is_degraded() -> None:
    def page(degraded: bool, status: int = 200) -> PageSummary:
        return PageSummary(url="https://example.com", final_url="https://example.com",
                           status_code=status, degraded=degraded)

    all_degraded = WaslState(job_id="j", root_url="https://example.com",
                             pages=[page(True), page(True)])
    mixed = WaslState(job_id="j", root_url="https://example.com",
                      pages=[page(True), page(False)])

    assert all_degraded.degraded
    assert not mixed.degraded


def test_rejections_accumulate_rather_than_overwrite() -> None:
    """Rejections are the debugging surface and a product feature; never drop them."""
    state = WaslState(
        job_id="j",
        root_url="https://example.com",
        rejections=[
            Rejection(capability_name="a", rule_id="no_evidence", reason="x"),
            Rejection(capability_name="b", rule_id="state_changing", reason="y"),
        ],
    )
    assert len(state.rejections) == 2
