"""LiteLLM router with a free-tier fallback chain ending at local Ollama.

The constraint shaping this module is "zero paid API keys". That is not a
cost-saving detail — it is what makes the project reproducible by anyone who
clones it, and it means the fallback chain has to be real rather than decorative.

    Groq        fast, generous free tier — the default for short structured calls
    Gemini      1M context free tier — used where a whole site's evidence must fit
    Cerebras    overflow when the first two are rate-limited
    Ollama      local, no key, no quota — the floor the system never drops below

The last link matters most. With no keys configured at all, every call routes to
Ollama and the pipeline still runs end to end. A demo that requires someone
else's quota to work is not a demo you can rely on.

Small local models produce JSON that is *nearly* valid depressingly often —
fenced in markdown, prefaced with "Here is the JSON:", trailing commas. Rather
than pretend otherwise, `parse_json_response` repairs the common cases and
reports honestly when it cannot.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from wasl.config import Settings, get_settings
from wasl.obs.tracing import model_span, record_model_usage

logger = logging.getLogger(__name__)


class Role(StrEnum):
    """What a call is for. Determines which model in the chain suits it."""

    INDUCE = "induce"          # long context: all of a site's evidence at once
    SYNTHESIZE = "synthesize"  # short, structured, high volume
    CRITIC = "critic"          # short, structured, needs care
    EXPLAIN = "explain"        # prose, user-facing
    DEMO = "demo"              # agent loop in the split-screen demo


@dataclass(frozen=True, slots=True)
class ModelSpec:
    provider: str
    model: str
    requires_key: str | None
    context_tokens: int

    @property
    def litellm_name(self) -> str:
        return self.model


# Pinned. The eval report records which of these produced its numbers, because a
# metric without a model version attached is not reproducible.
CHAIN: dict[Role, tuple[ModelSpec, ...]] = {
    Role.INDUCE: (
        ModelSpec("google", "gemini/gemini-2.0-flash", "GOOGLE_API_KEY", 1_000_000),
        ModelSpec("groq", "groq/llama-3.3-70b-versatile", "GROQ_API_KEY", 128_000),
        ModelSpec("cerebras", "cerebras/llama-3.3-70b", "CEREBRAS_API_KEY", 128_000),
        ModelSpec("ollama", "ollama_chat/qwen2.5:7b", None, 32_000),
    ),
    Role.SYNTHESIZE: (
        ModelSpec("groq", "groq/llama-3.3-70b-versatile", "GROQ_API_KEY", 128_000),
        ModelSpec("cerebras", "cerebras/llama-3.3-70b", "CEREBRAS_API_KEY", 128_000),
        ModelSpec("google", "gemini/gemini-2.0-flash", "GOOGLE_API_KEY", 1_000_000),
        ModelSpec("ollama", "ollama_chat/qwen2.5:7b", None, 32_000),
    ),
    Role.CRITIC: (
        ModelSpec("groq", "groq/llama-3.3-70b-versatile", "GROQ_API_KEY", 128_000),
        ModelSpec("google", "gemini/gemini-2.0-flash", "GOOGLE_API_KEY", 1_000_000),
        ModelSpec("cerebras", "cerebras/llama-3.3-70b", "CEREBRAS_API_KEY", 128_000),
        ModelSpec("ollama", "ollama_chat/qwen2.5:7b", None, 32_000),
    ),
    Role.EXPLAIN: (
        ModelSpec("groq", "groq/llama-3.3-70b-versatile", "GROQ_API_KEY", 128_000),
        ModelSpec("google", "gemini/gemini-2.0-flash", "GOOGLE_API_KEY", 1_000_000),
        ModelSpec("ollama", "ollama_chat/qwen2.5:7b", None, 32_000),
    ),
    Role.DEMO: (
        ModelSpec("groq", "groq/llama-3.3-70b-versatile", "GROQ_API_KEY", 128_000),
        ModelSpec("ollama", "ollama_chat/qwen2.5:7b", None, 32_000),
    ),
}


class AllProvidersFailed(RuntimeError):
    """Every model in the chain failed, including the local fallback."""


@dataclass
class Usage:
    """Token and call accounting for one scan. Feeds the cost-per-scan metric."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    by_provider: dict[str, int] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    def record(self, provider: str, *, input_tokens: int, output_tokens: int) -> None:
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.by_provider[provider] = self.by_provider.get(provider, 0) + 1

    @property
    def cost_usd(self) -> float:
        """Zero by construction: every provider in the chain is a free tier or local.

        Reported as a measured constraint rather than an estimate. If this ever
        returns non-zero, a paid model got into the chain and that is a bug.
        """
        return 0.0


_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def parse_json_response(raw: str) -> dict[str, Any]:
    """Extract a JSON object from a model response, repairing common damage.

    Small local models wrap JSON in markdown, preface it with commentary, and
    leave trailing commas. Repairing that is not cheating — it is accepting that
    the fallback tier is a 7B model and making the pipeline work there anyway.
    """
    if not raw or not raw.strip():
        raise ValueError("Model returned an empty response.")

    text = raw.strip()

    fenced = _JSON_FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    # Take the outermost object if there is prose either side.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        text = text[start : end + 1]

    text = _TRAILING_COMMA.sub(r"\1", text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Could not parse JSON from the model response: {exc}. "
            f"First 200 chars: {raw[:200]!r}"
        ) from exc

    if not isinstance(parsed, dict):
        raise ValueError(f"Expected a JSON object, got {type(parsed).__name__}.")
    return parsed


class ModelRouter:
    """Routes a call down the chain until one provider answers."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self.usage = Usage()

    def _key_for(self, spec: ModelSpec) -> str | None:
        if spec.requires_key is None:
            return None
        return {
            "GROQ_API_KEY": self._settings.groq_api_key,
            "GOOGLE_API_KEY": self._settings.google_api_key,
            "CEREBRAS_API_KEY": self._settings.cerebras_api_key,
        }.get(spec.requires_key) or None

    def available(self, role: Role) -> tuple[ModelSpec, ...]:
        """The chain for a role, skipping providers with no configured key."""
        return tuple(
            spec for spec in CHAIN[role] if spec.requires_key is None or self._key_for(spec)
        )

    def describe_chain(self, role: Role) -> str:
        available = self.available(role)
        if not available:
            return f"{role.value}: NO PROVIDER AVAILABLE"
        return f"{role.value}: " + " -> ".join(f"{s.provider}/{s.model.split('/')[-1]}" for s in available)

    async def complete(
        self,
        *,
        role: Role,
        prompt: str,
        job_id: str = "-",
        prompt_name: str | None = None,
        prompt_sha: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        json_mode: bool = True,
    ) -> tuple[str, ModelSpec]:
        """Run a completion, walking the chain on failure. Returns (text, model used)."""
        chain = self.available(role)
        if not chain:
            raise AllProvidersFailed(
                f"No provider available for {role.value}. Configure a free-tier key, or "
                "start Ollama locally (the chain's floor requires no key at all)."
            )

        errors: list[str] = []
        for spec in chain:
            try:
                text = await self._call(
                    spec,
                    prompt=prompt,
                    role=role,
                    job_id=job_id,
                    prompt_name=prompt_name,
                    prompt_sha=prompt_sha,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )
                return text, spec
            except Exception as exc:
                message = f"{spec.provider}/{spec.model}: {type(exc).__name__}: {exc}"
                logger.warning("provider failed, falling through — %s", message)
                errors.append(message)
                self.usage.failures.append(message)

        raise AllProvidersFailed(
            f"Every provider failed for {role.value}:\n  " + "\n  ".join(errors)
        )

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def _call(
        self,
        spec: ModelSpec,
        *,
        prompt: str,
        role: Role,
        job_id: str,
        prompt_name: str | None,
        prompt_sha: str | None,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> str:
        import litellm

        litellm.suppress_debug_info = True

        kwargs: dict[str, Any] = {
            "model": spec.litellm_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        key = self._key_for(spec)
        if key:
            kwargs["api_key"] = key
        if spec.provider == "ollama":
            kwargs["api_base"] = self._settings.ollama_base_url
        if json_mode and spec.provider in {"groq", "google", "ollama"}:
            kwargs["response_format"] = {"type": "json_object"}

        with model_span(
            operation="chat",
            system=spec.provider,
            model=spec.model,
            job_id=job_id,
            prompt_name=prompt_name,
            prompt_sha=prompt_sha,
        ) as span:
            response = await litellm.acompletion(**kwargs)

            content = response.choices[0].message.content or ""
            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(usage, "completion_tokens", 0) or 0

            record_model_usage(
                span,
                response_model=getattr(response, "model", spec.model),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=getattr(response.choices[0], "finish_reason", None),
            )
            self.usage.record(
                spec.provider, input_tokens=input_tokens, output_tokens=output_tokens
            )

        if not content.strip():
            raise ValueError("Model returned empty content.")
        return content

    async def complete_json(self, **kwargs: Any) -> tuple[dict[str, Any], ModelSpec]:
        """Complete and parse. The repair path is in `parse_json_response`."""
        text, spec = await self.complete(**kwargs)
        return parse_json_response(text), spec
