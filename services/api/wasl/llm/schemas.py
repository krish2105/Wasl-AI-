"""JSON schemas that constrain model output structurally.

Asking a model to follow a six-field schema in prose works on a frontier model
and fails on a 7B one. The offline tier returned well-formed JSON in an invented
shape — `{"name", "description", "evidence"}` instead of the required
`{"name", "verb", "noun", "description", "evidence_ids"}` — so every proposal was
dropped by the validator and capability recall came out at 0.00.

Constraining the output is the same principle the rest of this codebase applies
to state: make the invalid shape unrepresentable rather than asking for the valid
one and checking afterwards.

Note what these schemas do NOT do: they guarantee shape, never truth. A model can
still emit a well-formed capability citing an evidence ID it invented, or a verb
the evidence does not support. That is the critic's job, and it still runs.
"""

from __future__ import annotations

from typing import Any

INDUCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["capabilities"],
    "properties": {
        "capabilities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "verb", "noun", "description", "evidence_ids"],
                "properties": {
                    "name": {"type": "string"},
                    # Constrained to the read-only verbs. A model cannot propose
                    # "book" or "buy" through this path at all — the state-changing
                    # critic rule remains as defence in depth, not as the only line.
                    "verb": {
                        "type": "string",
                        "enum": ["search", "get", "list", "check", "find", "browse"],
                    },
                    "noun": {"type": "string"},
                    "description": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "state_changing": {"type": "boolean"},
                    "reasoning": {"type": "string"},
                },
            },
        }
    },
}

SYNTHESIZE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tool": {
            "type": ["object", "null"],
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "parameters": {"type": "object"},
                "returns": {"type": "string"},
            },
        },
        "reason": {"type": "string"},
    },
}

CRITIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["verdict"],
    "properties": {
        "verdict": {"type": "string", "enum": ["accept", "reject"]},
        "rule_id": {
            "type": ["string", "null"],
            "enum": [
                "no_evidence",
                "evidence_mismatch",
                "unbounded_param",
                "state_changing",
                "injection_detected",
                None,
            ],
        },
        "reason": {"type": "string"},
    },
}

DEMO_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["succeeded", "answer"],
    "properties": {
        "succeeded": {"type": "boolean"},
        "answer": {"type": "string"},
        "found": {"type": "object"},
        "missing": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
    },
}
