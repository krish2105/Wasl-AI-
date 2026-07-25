"""The split-screen demo: the same agent, the same task, two interfaces.

This is the project's most persuasive artifact and also its easiest to fake, so
the design is built around not faking it.

**Both arms get the same model, the same task, the same prompt template.** The
only difference is what they are handed: arm A gets the raw pre-JS HTML an agent
actually receives; arm B gets the generated tool schemas and can execute one
real lookup against the cached snapshot.

**Arm B's tool call really executes.** It runs the same lookup the generated
server runs — not a canned response. If the snapshot has nothing useful, arm B
fails, and that gets reported.

**Whatever happens is what is shown.** If the raw arm succeeds, the UI says the
raw arm succeeded. A comparison that can only come out one way is not evidence,
and a demo rigged to always win is worth less than an honest one that sometimes
doesn't — because a reviewer who spots the rigging discards everything else too.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from wasl.graph.state import Capability, DemoResult, WaslState
from wasl.llm.prompts.registry import load as load_prompt
from wasl.llm.router import ModelRouter, Role
from wasl.llm.untrusted import build_prompt, wrap, wrap_evidence_batch
from wasl.obs.tracing import node_span

logger = logging.getLogger(__name__)

DEFAULT_TASK = (
    "Find one product, listing or service offered on this site. Report its name, "
    "its price if it has one, and any stable identifier (SKU, product ID or "
    "listing ID) that could be used to refer to it again later."
)

# Enough raw HTML to be a fair trial, bounded so the local model's context holds.
MAX_RAW_CHARS = 12_000


def _describe_tools(capabilities: list[Capability]) -> str:
    lines: list[str] = []
    for capability in capabilities:
        if not capability.tool_schema:
            continue
        schema = capability.tool_schema
        params = ", ".join(
            f"{name} ({spec.get('type', 'string')})"
            for name, spec in (schema.parameters or {}).items()
            if isinstance(spec, dict)
        )
        lines.append(f"- {schema.name}({params}) — {schema.description}")
    return "\n".join(lines) or "(no tools available)"


def _execute_tool(store, query: str, limit: int = 8) -> list[dict[str, Any]]:
    """Run the same lookup a generated tool runs, against the same evidence.

    Deliberately the real code path rather than a stubbed response: if this
    returns nothing useful, arm B fails and the demo reports that it failed.
    """
    results: list[dict[str, Any]] = []
    needle = (query or "").lower().strip()

    for evidence in store:
        if evidence.kind in {"rendering", "media", "injection", "header"}:
            continue
        haystack = f"{evidence.kind} {evidence.selector or ''} {evidence.raw}".lower()
        if not needle or needle in haystack:
            results.append(
                {
                    "id": evidence.id,
                    "kind": evidence.kind,
                    "selector": evidence.selector,
                    "content": evidence.raw[:900],
                }
            )
        if len(results) >= limit:
            break
    return results


def _normalise(text: str) -> str:
    """Strip punctuation and case so 'AED 14.50' matches '14.50'."""
    return "".join(ch for ch in text.lower() if ch.isalnum() or ch.isspace())


def verify_claims(found: dict[str, Any], source_text: str) -> list[str]:
    """Return the claimed values that do not appear in what the arm was shown.

    Without this the demo is exactly the failure mode the rest of the project
    exists to prevent. A 7B model asked to "find a product" will happily invent
    "Wireless Bluetooth Headphones, $29.99" when the material in front of it says
    "Brass Compression Elbow 22mm" — the answer is well-formed, plausible, and
    entirely fabricated.

    Checking each claimed value against the source is the same discipline the
    critic applies to capabilities: an assertion that cannot be traced back to
    the material is not an answer, it is a guess with good grammar.
    """
    haystack = _normalise(source_text)
    unverifiable: list[str] = []

    for key, value in (found or {}).items():
        text = str(value or "").strip()
        if not text or text.lower() in {"n/a", "none", "unknown", "null", "-"}:
            continue

        # Split on letter/digit boundaries as well as whitespace, so "AED14.50"
        # yields "1450" and matches a source that wrote "14.50". Without this the
        # check fires on formatting rather than on fabrication.
        tokens = [t for t in re.findall(r"[a-z]+|\d+", _normalise(text)) if len(t) >= 3]
        if not tokens:
            continue

        # The longest token, not any token: "prod-123456" contains "prod", which
        # appears inside "productID" in almost any product markup, and matching on
        # that would verify an invented identifier.
        probe = max(tokens, key=len)
        if probe not in haystack:
            unverifiable.append(f"{key}={text!r}")

    return unverifiable


async def _run_arm(
    *,
    router: ModelRouter,
    job_id: str,
    task: str,
    arm_description: str,
    wrapped,
) -> tuple[bool, str, dict[str, Any]]:
    """One arm. Returns (succeeded, transcript, parsed payload).

    `succeeded` requires both that the model claimed success AND that its claims
    are traceable to the material it was given.
    """
    prompt_file = load_prompt("demo_task")
    instruction = prompt_file.render(task=task, arm_description=arm_description)

    try:
        payload, spec = await router.complete_json(
            role=Role.DEMO,
            prompt=build_prompt(instruction, wrapped),
            job_id=job_id,
            prompt_name=prompt_file.id,
            prompt_sha=prompt_file.sha,
            max_tokens=800,
        )
    except Exception as exc:
        return False, f"The agent could not complete a call: {type(exc).__name__}: {exc}", {}

    claimed = bool(payload.get("succeeded"))
    found = payload.get("found") or {}
    missing = payload.get("missing") or []

    unverifiable = verify_claims(found if isinstance(found, dict) else {}, wrapped.text)
    succeeded = claimed and not unverifiable

    lines = [payload.get("answer", "").strip() or "(no answer given)"]
    if isinstance(found, dict) and any(found.values()):
        lines.append("")
        for key, value in found.items():
            if value:
                lines.append(f"  {key}: {value}")
    if missing:
        lines.append("")
        lines.append(f"  could not determine: {', '.join(str(m) for m in missing)}")
    if payload.get("reasoning"):
        lines.append("")
        lines.append(f"  {payload['reasoning']}")

    if unverifiable:
        lines.append("")
        lines.append("  ── NOT VERIFIED ──")
        lines.append(
            "  These values do not appear anywhere in the material this arm was given, "
            "so they were invented rather than read:"
        )
        for item in unverifiable:
            lines.append(f"    {item}")
        lines.append(
            "  Counted as a failure. An answer that cannot be traced back to its source "
            "is not an answer."
        )

    return succeeded, "\n".join(lines), payload


async def run_demo(
    state: WaslState,
    *,
    store=None,
    raw_html: str = "",
    router: ModelRouter | None = None,
    task: str = DEFAULT_TASK,
) -> dict:
    """Run both arms and report whatever actually happened."""
    router = router or ModelRouter()

    with node_span("demo", job_id=state.job_id) as span:
        accepted = [c for c in state.accepted_capabilities if c.tool_schema]

        # --- arm A: the raw site, as an agent receives it --------------------
        raw_wrapped = wrap(
            raw_html[:MAX_RAW_CHARS] or "(the response body was empty)",
            source_url=state.root_url,
            kind="raw_page",
        )
        raw_ok, raw_transcript, _ = await _run_arm(
            router=router,
            job_id=state.job_id,
            task=task,
            arm_description=(
                "The raw HTTP response body for this page, exactly as a client that does "
                "not execute JavaScript receives it. No tools are available."
            ),
            wrapped=raw_wrapped,
        )

        # --- arm B: the generated MCP server ---------------------------------
        if not accepted:
            mcp_ok, mcp_transcript = False, (
                "No tools were generated for this site — every candidate capability was "
                "refused by the critic. There is nothing for this arm to use."
            )
        else:
            # One real tool execution against the snapshot, then the model answers.
            tool_results = _execute_tool(store or [], query="")
            wrapped_results = wrap_evidence_batch(
                [e for e in (store or []) if e.id in {r["id"] for r in tool_results}],
                max_items=8,
            )
            mcp_ok, mcp_transcript, _ = await _run_arm(
                router=router,
                job_id=state.job_id,
                task=task,
                arm_description=(
                    "A generated MCP server exposing these read-only tools:\n"
                    f"{_describe_tools(accepted)}\n\n"
                    f"You called a tool and it returned {len(tool_results)} structured "
                    "record(s), shown below."
                ),
                wrapped=wrapped_results,
            )
            mcp_transcript = (
                f"tool call → {accepted[0].tool_schema.name}\n"
                f"returned {len(tool_results)} record(s)\n\n{mcp_transcript}"
            )

        # --- the honest note -------------------------------------------------
        if mcp_ok and not raw_ok:
            note = (
                "The generated interface succeeded where the raw page did not. That gap "
                "is the whole argument for this project."
            )
        elif raw_ok and mcp_ok:
            note = (
                "Both arms succeeded. This site is already server-rendered enough that an "
                "agent can read it directly — the generated server adds structure, not access."
            )
        elif raw_ok and not mcp_ok:
            note = (
                "The raw page succeeded and the generated server did not. Reported as it "
                "happened: the generator did not improve on the site here."
            )
        else:
            note = (
                "Neither arm succeeded. The evidence gathered was not sufficient for this "
                "task, which is a finding about the crawl rather than about the site."
            )

        span.set_attribute("wasl.demo.raw_succeeded", raw_ok)
        span.set_attribute("wasl.demo.mcp_succeeded", mcp_ok)
        logger.info("demo: raw=%s mcp=%s", raw_ok, mcp_ok)

        return {
            "demo_result": DemoResult(
                task=task,
                raw_succeeded=raw_ok,
                raw_transcript=raw_transcript,
                raw_steps=1,
                mcp_succeeded=mcp_ok,
                mcp_transcript=mcp_transcript,
                mcp_steps=2 if accepted else 0,
                note=note,
            )
        }
