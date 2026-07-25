"""The demo's claim verification.

This exists because the demo caught itself lying. Asked to find a product in a
fixture describing brass pipe fittings, a 7B model returned "Wireless Bluetooth
Headphones, $29.99, prod-123456" — well-formed, plausible, and entirely
fabricated. The split-screen panel rendered it as a success.

A demo that shows invented data is worse than no demo, in a project whose whole
argument is that claims must trace back to evidence. So every claimed value is
now checked against the material the arm was actually shown, and an unverifiable
answer is a failure regardless of how confident the model was.
"""

from __future__ import annotations

from wasl.graph.nodes.demo import verify_claims

SOURCE = """
<untrusted_web_content source="evidence" url="https://nadisupply.example/catalogue">
[kind=jsonld selector=json-ld#Product]
{
  "@type": "Product",
  "name": "Brass Compression Elbow 22mm",
  "sku": "NSC-BCE-22",
  "productID": "884213",
  "offers": {"price": "14.50", "priceCurrency": "AED"}
}
</untrusted_web_content-abc123>
"""


def test_claims_present_in_the_source_verify() -> None:
    unverifiable = verify_claims(
        {"name": "Brass Compression Elbow 22mm", "price": "AED 14.50", "identifier": "884213"},
        SOURCE,
    )
    assert unverifiable == []


def test_the_actual_hallucination_that_prompted_this_test_is_caught() -> None:
    """Verbatim from the run that exposed the problem."""
    unverifiable = verify_claims(
        {"name": "Wireless Bluetooth Headphones", "price": "$29.99", "identifier": "prod-123456"},
        SOURCE,
    )
    assert len(unverifiable) == 3
    assert any("Wireless Bluetooth Headphones" in item for item in unverifiable)


def test_a_partially_invented_answer_is_still_caught() -> None:
    """Getting the name right does not launder an invented identifier."""
    unverifiable = verify_claims(
        {"name": "Brass Compression Elbow 22mm", "identifier": "SKU-99999"},
        SOURCE,
    )
    assert len(unverifiable) == 1
    assert "identifier" in unverifiable[0]


def test_reformatted_values_still_verify() -> None:
    """'AED 14.50' and '14.50' are the same fact; only fabrication should fail."""
    assert verify_claims({"price": "14.50 AED"}, SOURCE) == []
    assert verify_claims({"price": "AED14.50"}, SOURCE) == []


def test_empty_and_placeholder_values_are_not_treated_as_claims() -> None:
    """Saying "I could not find the price" is a correct answer, not a lie."""
    assert verify_claims({"name": "", "price": None, "identifier": "n/a"}, SOURCE) == []


def test_no_claims_at_all_verifies() -> None:
    assert verify_claims({}, SOURCE) == []


def test_case_and_punctuation_do_not_cause_false_failures() -> None:
    assert verify_claims({"name": "brass compression elbow 22mm!"}, SOURCE) == []
