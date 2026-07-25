"""Induce node. The model earns its keep here, and only here.

Turning raw evidence into a hypothesis about what a business can *do* is genuine
reasoning over unstructured input — exactly the job a language model is good at
and a regex is not.

Everything around that call is constraint:

- All evidence goes through `untrusted.wrap_evidence_batch`. Nothing reaches the
  model unwrapped.
- Every proposed capability must cite evidence IDs, enforced by a Pydantic
  validator at construction, so an uncited one cannot be built.
- Cited IDs are checked against what the model was actually shown. A model that
  invents a plausible-looking hex ID gets caught here rather than downstream.
- Proposals are candidates. The critic decides, and the score never reads them.
"""

from __future__ import annotations

import logging

from pydantic import ValidationError

from wasl.graph.state import Capability, WaslState
from wasl.llm.prompts.registry import load as load_prompt
from wasl.llm.router import ModelRouter, Role
from wasl.llm.schemas import INDUCE_SCHEMA
from wasl.llm.untrusted import build_prompt, wrap_evidence_batch
from wasl.obs.tracing import node_span, reasoning_span

logger = logging.getLogger(__name__)

# Evidence kinds worth showing the induce node. Rendering ratios and media
# balance are scoring inputs, not capability signals, and including them would
# spend context on rows that cannot support a capability.
CAPABILITY_KINDS = (
    "openapi",
    "wellknown",
    "form",
    "identifier",
    "jsonld",
    "microdata",
    "llmstxt",
    "sitemap",
    "link",
    "text",
)

# Selector markers meaning "we looked and found nothing". These are scoring
# inputs, not capability signals — nothing can be induced from an absence. Worse,
# feeding a model twenty "not found" rows makes it mirror the input shape and
# return an audit summary instead of capabilities, which is exactly what happened
# on the first real golden sites.
ABSENCE_MARKERS = (
    "#absent", "#no-spec", "#none", "#unavailable", "#clean", "#not-a-manifest",
    "#not-markdown", "#not-a-spec", "#unreachable", "#insufficient-content",
    "#unparseable", "#silent-on-automation",
)

MAX_EVIDENCE_ROWS = 60

# Bound the prompt by SIZE, not just row count. Rows cap at 4,000 characters
# each, so 60 of them is up to 240k characters — roughly 60k tokens into a model
# with a 32k window. The window silently overflows and the model returns nothing.
#
# That is not hypothetical: capability recall was 0.00 across the first three
# golden sites, with zero rejections, because induce never proposed anything to
# reject. The fixtures never caught it — they yield ~35 short rows of clean
# synthetic markup, where real sites yield 150-250 long ones.
MAX_EVIDENCE_CHARS = 40_000
MAX_ROW_CHARS = 900

MAX_CAPABILITIES = 12


def _budgeted(evidence: list) -> list:
    """Take evidence rows until the character budget is spent.

    Rows arrive longest-first, so this keeps the highest-signal ones. Each is
    truncated to MAX_ROW_CHARS: a JSON-LD Product blob's first 900 characters
    carry its @type and key properties, which is what a capability claim rests
    on. The rest is padding as far as induction is concerned.
    """
    from wasl.crawler.evidence import Evidence

    selected: list[Evidence] = []
    spent = 0

    for item in evidence:
        if len(selected) >= MAX_EVIDENCE_ROWS or spent >= MAX_EVIDENCE_CHARS:
            break
        raw = item.raw[:MAX_ROW_CHARS]
        spent += len(raw)
        selected.append(item if len(item.raw) <= MAX_ROW_CHARS else item.model_copy(update={"raw": raw}))

    return selected


async def induce(state: WaslState, store=None, router: ModelRouter | None = None) -> dict:
    """Propose candidate capabilities from evidence."""
    router = router or ModelRouter()

    with node_span("induce", job_id=state.job_id) as span:
        if store is None:
            return {"errors": ["induce: no evidence store supplied"]}

        relevant = [
            e
            for e in store.by_kind(*CAPABILITY_KINDS)
            if not any(marker in (e.selector or "") for marker in ABSENCE_MARKERS)
        ]
        # Longest rows first: a full JSON-LD Product carries more capability
        # signal than a one-line link, and the context budget is finite.
        relevant.sort(key=lambda e: len(e.raw), reverse=True)

        if not relevant:
            logger.info("induce: no capability-bearing evidence; proposing nothing")
            return {"candidate_capabilities": []}

        budgeted = _budgeted(relevant)
        wrapped = wrap_evidence_batch(budgeted)
        shown_ids = {e.id for e in budgeted}

        span.set_attribute("wasl.induce.evidence_rows", len(budgeted))
        span.set_attribute("wasl.induce.prompt_chars", len(wrapped.text))

        if wrapped.forged_delimiters:
            logger.warning(
                "induce: %d forged delimiter(s) neutralised in crawled content",
                wrapped.forged_delimiters,
            )
            span.set_attribute("wasl.injection.forged_delimiters", wrapped.forged_delimiters)

        prompt_file = load_prompt("induce")
        instruction = prompt_file.render(domain=state.domain or state.root_url, evidence="")
        # The schema is ~2,000 characters up-page by the time the model reaches
        # the end of the evidence, and it drifts. Restating it last — after the
        # standing instruction, so the untrusted block stays bracketed by it — is
        # what holds the response to the required shape.
        prompt = build_prompt(
            instruction,
            wrapped,
            reminder=(
                "Now return ONLY the JSON object specified above, of the form "
                '{"capabilities": [...]}. Each capability MUST cite evidence_ids '
                "drawn from the evidence above. If the evidence supports no "
                'capability, return {"capabilities": []} — that is a valid answer. '
                "Do not return a summary, an audit, or any other shape."
            ),
        )

        try:
            payload, spec = await router.complete_json(
                role=Role.INDUCE,
                prompt=prompt,
                job_id=state.job_id,
                prompt_name=prompt_file.id,
                prompt_sha=prompt_file.sha,
                max_tokens=3000,
                    json_schema=INDUCE_SCHEMA,
            )
        except Exception as exc:
            logger.error("induce failed: %s", exc)
            return {"errors": [f"induce: {type(exc).__name__}: {exc}"]}

        raw_capabilities = payload.get("capabilities") or []
        if not isinstance(raw_capabilities, list):
            return {"errors": ["induce: model returned a non-list under 'capabilities'"]}

        capabilities: list[Capability] = []
        errors: list[str] = []

        for entry in raw_capabilities[:MAX_CAPABILITIES]:
            if not isinstance(entry, dict):
                continue

            cited = [str(x) for x in (entry.get("evidence_ids") or []) if x]

            # A model inventing a plausible hex ID is the failure mode this
            # catches. Uncited capabilities are rejected by the validator below;
            # mis-cited ones would otherwise slip through looking legitimate.
            hallucinated = [eid for eid in cited if eid not in shown_ids]
            if hallucinated:
                errors.append(
                    f"induce: capability {entry.get('name')!r} cited evidence never shown to it: "
                    f"{hallucinated}"
                )
                cited = [eid for eid in cited if eid in shown_ids]

            if not cited:
                errors.append(
                    f"induce: capability {entry.get('name')!r} had no resolvable evidence and "
                    "was dropped before construction"
                )
                continue

            try:
                capabilities.append(
                    Capability(
                        name=str(entry.get("name", "")),
                        verb=str(entry.get("verb", "")).strip().lower(),
                        noun=str(entry.get("noun", "")).strip().lower(),
                        description=str(entry.get("description", "")).strip(),
                        evidence_ids=cited,
                        reasoning=str(entry.get("reasoning", "")).strip(),
                        state_changing=bool(entry.get("state_changing", False)),
                    )
                )
            except ValidationError as exc:
                errors.append(f"induce: rejected malformed capability {entry.get('name')!r}: {exc}")

        with reasoning_span("induce.proposed", job_id=state.job_id) as reason:
            reason.set_attribute("wasl.capabilities.proposed", len(capabilities))
            reason.set_attribute("wasl.evidence.shown", len(shown_ids))
            reason.set_attribute("wasl.model", spec.model)

        logger.info(
            "induce: %d candidate(s) from %d evidence rows via %s",
            len(capabilities),
            len(shown_ids),
            spec.provider,
        )

        return {"candidate_capabilities": capabilities, "errors": errors}
