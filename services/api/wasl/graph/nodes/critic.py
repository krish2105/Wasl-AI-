"""Critic node: enumerable rejection criteria, not "ask the model if it's sure".

A real critic applies **named rules** and produces a structured rejection with a
reason a human can read. If you cannot list the criteria, you do not have a
critic — you have a second opinion.

Four of the five rules are checked **deterministically in code**, before any model
call:

    no_evidence          the ID does not exist in the evidence store
    state_changing       the verb or name implies a mutation
    unbounded_param      the schema has a free-text field with no bound
    injection_detected   the cited evidence is itself an injection finding

Only `evidence_mismatch` — does this evidence actually support this claim? —
genuinely needs a model, because it is a semantic judgement. Doing it this way
means most rejections are reproducible without a model at all, and the one that
is not is clearly labelled.

Rejections are capped at 3 rounds and then the capability is **dropped**, never
silently downgraded into the output. Every rejection persists in state and is
shown in the UI.
"""

from __future__ import annotations

import logging

from wasl.graph.state import Capability, Rejection, WaslState
from wasl.llm.prompts.registry import load as load_prompt
from wasl.llm.router import ModelRouter, Role
from wasl.llm.schemas import CRITIC_SCHEMA
from wasl.llm.untrusted import build_prompt, wrap_evidence_batch
from wasl.obs.tracing import node_span, reasoning_span

logger = logging.getLogger(__name__)

MAX_CRITIC_ROUNDS = 3


def check_deterministic(
    capability: Capability, evidence_by_id: dict, injection_ids: set[str]
) -> Rejection | None:
    """The four rules that need no model. Returns a Rejection, or None to continue."""

    missing = [eid for eid in capability.evidence_ids if eid not in evidence_by_id]
    if missing:
        return Rejection(
            capability_name=capability.name,
            rule_id="no_evidence",
            reason=(
                f"Cites evidence that does not exist: {missing}. Every capability must "
                "resolve to evidence actually collected during the crawl."
            ),
            evidence_ids=capability.evidence_ids,
        )

    if capability.implies_state_change():
        return Rejection(
            capability_name=capability.name,
            rule_id="state_changing",
            reason=(
                f"'{capability.verb}' implies a state-changing action. This capability is "
                "reported as detected but no tool is generated for it — Wasl is read-only "
                "against sites it does not control."
            ),
            evidence_ids=capability.evidence_ids,
        )

    if capability.tool_schema:
        unbounded = capability.tool_schema.unbounded_parameters()
        if unbounded:
            return Rejection(
                capability_name=capability.name,
                rule_id="unbounded_param",
                reason=(
                    f"Tool parameters {unbounded} are free text with no description or length "
                    "bound. Every tool parameter is a security boundary for whoever runs the "
                    "generated server."
                ),
                evidence_ids=capability.evidence_ids,
            )

    tainted = [eid for eid in capability.evidence_ids if eid in injection_ids]
    if tainted:
        return Rejection(
            capability_name=capability.name,
            rule_id="injection_detected",
            reason=(
                f"Cited evidence {tainted} contains instruction-like text. This capability may "
                "be something an attacker planted in the page rather than something the site "
                "offers."
            ),
            evidence_ids=capability.evidence_ids,
        )

    return None


async def critique(
    state: WaslState, store=None, router: ModelRouter | None = None
) -> dict:
    """Accept or reject every candidate. Rejections are final after the round cap."""
    router = router or ModelRouter()

    with node_span("critic", job_id=state.job_id) as span:
        evidence_by_id = {e.id: e for e in (store or [])}
        injection_ids = {
            e.id
            for e in (store.by_kind("injection") if store else [])
            if (e.selector or "") != "injection#clean"
        }

        accepted: list[Capability] = []
        rejections: list[Rejection] = []
        errors: list[str] = []
        round_number = state.critic_rounds + 1
        prompt_file = load_prompt("critic")

        for capability in state.candidate_capabilities:
            deterministic = check_deterministic(capability, evidence_by_id, injection_ids)
            if deterministic is not None:
                rejections.append(
                    deterministic.model_copy(
                        update={"critic_round": round_number, "final": round_number >= MAX_CRITIC_ROUNDS}
                    )
                )
                continue

            # Only the semantic question is left for the model.
            if state.budget.exhausted:
                errors.append(f"critic: budget exhausted before {capability.name!r}")
                continue

            cited = [evidence_by_id[eid] for eid in capability.evidence_ids if eid in evidence_by_id]
            wrapped = wrap_evidence_batch(cited, max_items=8)

            instruction = prompt_file.render(
                name=capability.name,
                verb=capability.verb,
                noun=capability.noun,
                description=capability.description,
                evidence_ids=capability.evidence_ids,
                tool_schema=(
                    capability.tool_schema.model_dump_json() if capability.tool_schema else "none"
                ),
                evidence="",
            )

            try:
                payload, _ = await router.complete_json(
                    role=Role.CRITIC,
                    prompt=build_prompt(instruction, wrapped),
                    job_id=state.job_id,
                    prompt_name=prompt_file.id,
                    prompt_sha=prompt_file.sha,
                    max_tokens=600,
                    json_schema=CRITIC_SCHEMA,
                )
            except Exception as exc:
                # A critic that fails open would defeat its own purpose, so an
                # unreachable model means the capability does not ship.
                errors.append(f"critic {capability.name!r}: {type(exc).__name__}: {exc}")
                rejections.append(
                    Rejection(
                        capability_name=capability.name,
                        rule_id="evidence_mismatch",
                        reason=(
                            "The critic could not be reached, so this capability was not "
                            "verified. Unverified capabilities are dropped rather than shipped."
                        ),
                        critic_round=round_number,
                        final=True,
                        evidence_ids=capability.evidence_ids,
                    )
                )
                continue

            verdict = str(payload.get("verdict", "")).strip().lower()
            if verdict == "accept":
                accepted.append(
                    capability.model_copy(update={"accepted": True, "critic_rounds": round_number})
                )
                continue

            rule = str(payload.get("rule_id") or "evidence_mismatch")
            if rule not in {
                "no_evidence",
                "evidence_mismatch",
                "unbounded_param",
                "state_changing",
                "injection_detected",
            }:
                rule = "evidence_mismatch"

            rejections.append(
                Rejection(
                    capability_name=capability.name,
                    rule_id=rule,  # type: ignore[arg-type]
                    reason=str(payload.get("reason", "")).strip() or "No reason given.",
                    critic_round=round_number,
                    final=round_number >= MAX_CRITIC_ROUNDS,
                    evidence_ids=capability.evidence_ids,
                )
            )

        with reasoning_span("critic.verdicts", job_id=state.job_id) as reason:
            reason.set_attribute("wasl.capabilities.accepted", len(accepted))
            reason.set_attribute("wasl.capabilities.rejected", len(rejections))
            reason.set_attribute("wasl.critic.round", round_number)

        span.set_attribute("wasl.critic.round", round_number)
        logger.info(
            "critic round %d: %d accepted, %d rejected",
            round_number,
            len(accepted),
            len(rejections),
        )

        return {
            "accepted_capabilities": accepted,
            "rejections": rejections,
            "critic_rounds": round_number,
            "errors": errors,
        }
