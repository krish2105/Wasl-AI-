"""The evidence model and store.

Content-addressing and referential integrity are load-bearing: the first gives
free deduplication and stable citations across runs, the second is the mechanism
behind the `citation_validity == 1.00` hard gate. Both are tested here rather
than assumed.
"""

from __future__ import annotations

import pytest

from wasl.crawler.evidence import (
    MAX_RAW_LENGTH,
    DanglingReferenceError,
    Evidence,
    EvidenceStore,
    compute_evidence_id,
    truncate_raw,
)


def make(raw: str = "<link rel=canonical>", **overrides) -> Evidence:
    payload = {
        "source_url": "https://example.com/a",
        "kind": "link",
        "selector": "link[rel=canonical]",
        "raw": raw,
        "phase": "pre_js",
    }
    payload.update(overrides)
    return Evidence(**payload)


# --- content addressing ------------------------------------------------------


def test_identical_content_yields_an_identical_id() -> None:
    assert make().id == make().id


def test_id_is_stable_across_processes() -> None:
    """Citations recorded yesterday must still resolve today, so no salting."""
    expected = compute_evidence_id(
        source_url="https://example.com/a",
        kind="link",
        selector="link[rel=canonical]",
        raw="<link rel=canonical>",
    )
    assert make().id == expected


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_url", "https://example.com/b"),
        ("kind", "meta"),
        ("selector", "meta[name=description]"),
        ("raw", "something else entirely"),
    ],
)
def test_changing_any_component_changes_the_id(field: str, value: str) -> None:
    assert make().id != make(**{field: value}).id


def test_id_cannot_be_overridden_to_something_that_does_not_describe_the_content() -> None:
    """An ID passed in is ignored — it is derived, not declared."""
    evidence = Evidence(
        id="deadbeefdeadbeef",
        source_url="https://example.com/a",
        kind="link",
        selector="link[rel=canonical]",
        raw="<link rel=canonical>",
        phase="pre_js",
    )
    assert evidence.id != "deadbeefdeadbeef"
    assert evidence.id == make().id


# --- verbatim discipline -----------------------------------------------------


def test_empty_evidence_is_rejected() -> None:
    with pytest.raises(ValueError, match="not evidence"):
        make(raw="   ")


def test_long_snippets_are_truncated_with_an_explicit_marker() -> None:
    """Never let a truncated snippet look like the whole of what was found."""
    result = truncate_raw("x" * (MAX_RAW_LENGTH + 500))
    assert len(result) < MAX_RAW_LENGTH + 100
    assert "truncated" in result
    assert str(MAX_RAW_LENGTH + 500) in result


def test_short_snippets_are_left_alone() -> None:
    assert truncate_raw("  hello  ") == "hello"


def test_evidence_is_immutable() -> None:
    evidence = make()
    with pytest.raises(ValueError):
        evidence.raw = "rewritten"  # type: ignore[misc]


# --- the store ---------------------------------------------------------------


def test_duplicate_evidence_collapses_to_one_row() -> None:
    """Two detectors finding the same canonical tag is normal, not an error."""
    store = EvidenceStore([make(), make()])
    assert len(store) == 1


def test_store_preserves_insertion_order() -> None:
    store = EvidenceStore([make(raw="first"), make(raw="second"), make(raw="third")])
    assert [e.raw for e in store] == ["first", "second", "third"]


def test_verify_references_reports_every_dangling_id() -> None:
    store = EvidenceStore([make(raw="real")])
    real_id = next(iter(store)).id

    dangling = store.verify_references([real_id, "0000000000000000", "1111111111111111"])

    assert dangling == ["0000000000000000", "1111111111111111"]


def test_verify_references_is_empty_when_every_citation_resolves() -> None:
    """This empty list is what citation_validity == 1.00 means."""
    store = EvidenceStore([make(raw="a"), make(raw="b")])
    assert store.verify_references([e.id for e in store]) == []


def test_require_raises_on_a_missing_reference() -> None:
    store = EvidenceStore([make()])
    with pytest.raises(DanglingReferenceError, match="cited evidence that was never collected"):
        store.require("0000000000000000")


def test_filters_by_kind_phase_and_url() -> None:
    store = EvidenceStore(
        [
            make(raw="a", kind="link", phase="pre_js"),
            make(raw="b", kind="jsonld", phase="post_js"),
            make(raw="c", kind="jsonld", phase="post_js", source_url="https://example.com/b"),
        ]
    )
    assert len(store.by_kind("jsonld")) == 2
    assert len(store.by_phase("pre_js")) == 1
    assert len(store.by_url("https://example.com/b")) == 1
    assert store.kind_counts() == {"jsonld": 2, "link": 1}


def test_membership_is_by_id() -> None:
    store = EvidenceStore([make()])
    assert make().id in store
    assert "0000000000000000" not in store
