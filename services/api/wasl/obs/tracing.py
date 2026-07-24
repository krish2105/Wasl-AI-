"""OpenTelemetry setup and span helpers, following GenAI semantic conventions.

Why the helpers exist rather than raw `start_as_current_span` calls everywhere:
the value of a trace is in its consistency. If one node names an attribute
`model` and another names it `gen_ai.request.model`, the trace is decoration
rather than data. These four helpers are the only sanctioned way to open a span,
so the vocabulary stays fixed.

The four span kinds map to the four things worth reconstructing after a run:

- `model_call`  — what we asked a model, which model, and what it cost
- `tool_call`   — what a generated tool did
- `node`        — which graph node ran, and how state changed
- `reasoning`   — the plan, the action, the observation, the next decision.
                  This is where plan drift and wrong-branch selection become
                  visible, and a single model-call span cannot show it.

Export is optional. With no OTLP endpoint configured, spans are still created
and simply go nowhere — so instrumentation never becomes a reason a scan fails.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode

from wasl.config import Settings, get_settings

logger = logging.getLogger(__name__)

_TRACER_NAME = "wasl"
_configured = False


def _langfuse_headers(settings: Settings) -> dict[str, str]:
    """Basic-auth header Langfuse's OTLP endpoint expects."""
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return {}
    token = base64.b64encode(
        f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode()
    ).decode()
    return {"Authorization": f"Basic {token}"}


def configure_tracing(settings: Settings | None = None) -> None:
    """Install the global tracer provider. Idempotent.

    A missing or unreachable collector is not an error. Traces are diagnostic;
    losing them must never take a scan down with them.
    """
    global _configured
    if _configured:
        return

    settings = settings or get_settings()
    resource = Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": _version(),
            "deployment.environment": settings.env,
        }
    )
    provider = TracerProvider(resource=resource)

    if settings.otel_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(
                        endpoint=settings.otel_endpoint,
                        headers=_langfuse_headers(settings),
                    )
                )
            )
            logger.info("OTLP span export enabled: %s", settings.otel_endpoint)
        except Exception:  # pragma: no cover - exporter wiring is environmental
            logger.warning("OTLP exporter unavailable; spans will not be exported", exc_info=True)
    else:
        logger.info("No OTEL_EXPORTER_OTLP_ENDPOINT set; spans created but not exported")

    trace.set_tracer_provider(provider)
    _configured = True


def _version() -> str:
    from wasl import __version__

    return __version__


def get_tracer() -> trace.Tracer:
    return trace.get_tracer(_TRACER_NAME)


def _record_exception(span: Span, exc: BaseException) -> None:
    span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR, str(exc)))


@contextmanager
def node_span(name: str, *, job_id: str, **attributes: Any) -> Iterator[Span]:
    """One LangGraph node execution."""
    with get_tracer().start_as_current_span(f"wasl.node.{name}") as span:
        span.set_attribute("wasl.node.name", name)
        span.set_attribute("wasl.job.id", job_id)
        for key, value in attributes.items():
            span.set_attribute(f"wasl.{key}", value)
        try:
            yield span
        except BaseException as exc:
            _record_exception(span, exc)
            raise


@contextmanager
def model_span(
    *,
    operation: str,
    system: str,
    model: str,
    job_id: str,
    prompt_name: str | None = None,
    prompt_sha: str | None = None,
) -> Iterator[Span]:
    """One model call, named per the GenAI semantic conventions.

    `prompt_name` and `prompt_sha` are recorded because prompts are versioned
    files, and a metric produced under one prompt version is not comparable to
    one produced under another. The eval report reads these back.
    """
    with get_tracer().start_as_current_span(f"{operation} {model}") as span:
        span.set_attribute("gen_ai.operation.name", operation)
        span.set_attribute("gen_ai.system", system)
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("wasl.job.id", job_id)
        if prompt_name:
            span.set_attribute("wasl.prompt.name", prompt_name)
        if prompt_sha:
            span.set_attribute("wasl.prompt.sha", prompt_sha)
        try:
            yield span
        except BaseException as exc:
            _record_exception(span, exc)
            raise


def record_model_usage(
    span: Span,
    *,
    response_model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    finish_reason: str | None = None,
) -> None:
    """Attach response-side GenAI attributes to an open model span."""
    if response_model:
        span.set_attribute("gen_ai.response.model", response_model)
    if input_tokens is not None:
        span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
    if output_tokens is not None:
        span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
    if finish_reason:
        span.set_attribute("gen_ai.response.finish_reasons", [finish_reason])


@contextmanager
def tool_span(name: str, *, job_id: str, **attributes: Any) -> Iterator[Span]:
    """One tool execution."""
    with get_tracer().start_as_current_span(f"execute_tool {name}") as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", name)
        span.set_attribute("wasl.job.id", job_id)
        for key, value in attributes.items():
            span.set_attribute(f"wasl.{key}", value)
        try:
            yield span
        except BaseException as exc:
            _record_exception(span, exc)
            raise


@contextmanager
def reasoning_span(step: str, *, job_id: str, **attributes: Any) -> Iterator[Span]:
    """A decision point: plan, action, observation, next choice.

    Deliberately separate from `model_span`. A model span shows what was asked
    and answered; a reasoning span shows what the system decided to do about it.
    Only the second one makes plan drift visible.
    """
    with get_tracer().start_as_current_span(f"wasl.reasoning.{step}") as span:
        span.set_attribute("wasl.reasoning.step", step)
        span.set_attribute("wasl.job.id", job_id)
        for key, value in attributes.items():
            span.set_attribute(f"wasl.{key}", value)
        try:
            yield span
        except BaseException as exc:
            _record_exception(span, exc)
            raise
