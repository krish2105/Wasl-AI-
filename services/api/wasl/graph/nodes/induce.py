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

MAX_EVIDENCE_ROWS = 60
MAX_CAPABILITIES = 12


async def induce(state: WaslState, store=None, router: ModelRouter | None = None) -> dict:
    """Propose candidate capabilities from evidence."""
    router = router or ModelRouter()

    with node_span("induce", job_id=state.job_id) as span:
        if store is None:
            return {"errors": ["induce: no evidence store supplied"]}

        relevant = [e for e in store.by_kind(*CAPABILITY_KINDS)]
        # Longest rows first: a full JSON-LD Product carries more capability
        # signal than a one-line link, and the context budget is finite.
        relevant.sort(key=lambda e: len(e.raw), reverse=True)

        if not relevant:
            logger.info("induce: no capability-bearing evidence; proposing nothing")
            return {"candidate_capabilities": []}

        wrapped = wrap_evidence_batch(relevant, max_items=MAX_EVIDENCE_ROWS)
        shown_ids = {e.id for e in relevant[:MAX_EVIDENCE_ROWS]}

        if wrapped.forged_delimiters:
            logger.warning(
                "induce: %d forged delimiter(s) neutralised in crawled content",
                wrapped.forged_delimiters,
            )
            span.set_attribute("wasl.injection.forged_delimiters", wrapped.forged_delimiters)

        prompt_file = load_prompt("induce")
        instruction = prompt_file.render(domain=state.domain or state.root_url, evidence="")
        prompt = build_prompt(instruction, wrapped)

        try:
            payload, spec = await router.complete_json(
                role=Role.INDUCE,
                prompt=prompt,
                job_id=state.job_id,
                prompt_name=prompt_file.id,
                prompt_sha=prompt_file.sha,
                max_tokens=3000,
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
