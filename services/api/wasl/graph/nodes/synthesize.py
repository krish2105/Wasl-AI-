"""Synthesize node: capability -> MCP tool JSON Schema.

Short, structured, high-volume — the profile the fast tier of the chain suits.

State-changing capabilities are skipped here rather than filtered later. They are
still reported to the user as *detected*, which is useful information about the
site, but a tool is never generated for them. Emitting a "book the room" tool for
a site we do not control is how a portfolio project becomes an incident.
"""

from __future__ import annotations

import logging
import re

from wasl.graph.state import Capability, ToolSchema, WaslState
from wasl.llm.prompts.registry import load as load_prompt
from wasl.llm.router import ModelRouter, Role
from wasl.llm.untrusted import build_prompt, wrap_evidence_batch
from wasl.obs.tracing import node_span

logger = logging.getLogger(__name__)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def tool_prefix(domain: str) -> str:
    """A snake_case prefix from the domain, per mcp-builder naming conventions.

    Prefixed so a generated server can sit alongside others without its tool
    names colliding.
    """
    base = domain.lower().split(":")[0]
    for suffix in (".com", ".ae", ".net", ".org", ".io", ".ai", ".co", ".gov"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    base = base.replace("www.", "")
    cleaned = _NON_ALNUM.sub("_", base).strip("_")
    return cleaned or "site"


async def synthesize(
    state: WaslState, store=None, router: ModelRouter | None = None
) -> dict:
    """Attach a tool schema to each read-only candidate capability."""
    router = router or ModelRouter()
    prefix = tool_prefix(state.domain or state.root_url)

    with node_span("synthesize", job_id=state.job_id):
        if not state.candidate_capabilities:
            return {"candidate_capabilities": []}

        prompt_file = load_prompt("synthesize")
        updated: list[Capability] = []
        errors: list[str] = []

        for capability in state.candidate_capabilities:
            if capability.implies_state_change():
                # Detected and reported, never emitted. The critic records the
                # formal rejection so it appears in the UI panel.
                logger.info("synthesize: skipping state-changing %r", capability.name)
                updated.append(capability)
                continue

            if state.budget.exhausted:
                errors.append(f"synthesize: budget exhausted before {capability.name!r}")
                updated.append(capability)
                continue

            cited = [e for e in (store or []) if e.id in set(capability.evidence_ids)]
            wrapped = wrap_evidence_batch(cited, max_items=8)

            instruction = prompt_file.render(
                name=capability.name,
                verb=capability.verb,
                noun=capability.noun,
                description=capability.description,
                prefix=prefix,
                evidence="",
            )

            try:
                payload, _ = await router.complete_json(
                    role=Role.SYNTHESIZE,
                    prompt=build_prompt(instruction, wrapped),
                    job_id=state.job_id,
                    prompt_name=prompt_file.id,
                    prompt_sha=prompt_file.sha,
                    max_tokens=1200,
                )
            except Exception as exc:
                errors.append(f"synthesize {capability.name!r}: {type(exc).__name__}: {exc}")
                updated.append(capability)
                continue

            tool = payload.get("tool")
            if not isinstance(tool, dict):
                updated.append(capability)
                continue

            parameters = tool.get("parameters")
            try:
                schema = ToolSchema(
                    name=str(tool.get("name") or f"{prefix}_{capability.verb}_{capability.noun}"),
                    description=str(tool.get("description", "")).strip(),
                    parameters=parameters if isinstance(parameters, dict) else {},
                    returns=str(tool.get("returns", "")).strip(),
                )
            except Exception as exc:
                errors.append(f"synthesize {capability.name!r}: malformed tool schema: {exc}")
                updated.append(capability)
                continue

            updated.append(capability.model_copy(update={"tool_schema": schema}))

        with_schema = sum(1 for c in updated if c.tool_schema)
        logger.info("synthesize: %d of %d capabilities have a tool schema", with_schema, len(updated))

        return {"candidate_capabilities": updated, "errors": errors}
