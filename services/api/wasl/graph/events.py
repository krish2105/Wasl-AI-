"""Server-sent events: one per node, plus the counters that tick between them.

The streaming build-up carries most of the demo's weight, so the events are
deliberately fine-grained. A progress bar that jumps from 0 to 100 tells a user
nothing; a stream that names each detector as it fires, counts evidence as it
accumulates, and shows the critic refusing something in real time makes it
obvious the system is doing work rather than sleeping for effect.

Every event is small and JSON-serialisable. Heavy payloads — full evidence rows,
the whole score object — are fetched once at the end from the report endpoint
rather than pushed through the stream.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventType(StrEnum):
    JOB_START = "job_start"
    NODE_START = "node_start"
    NODE_COMPLETE = "node_complete"
    PROGRESS = "progress"
    EVIDENCE = "evidence"
    CAPABILITY = "capability"
    REJECTION = "rejection"
    SCORE = "score"
    ARTIFACT = "artifact"
    DEMO = "demo"
    ERROR = "error"
    DONE = "done"


# Display order and labels for the six pipeline stages the UI renders.
NODE_SEQUENCE: tuple[tuple[str, str], ...] = (
    ("crawl", "Fetching pages"),
    ("extract", "Extracting evidence"),
    ("induce", "Inducing capabilities"),
    ("synthesize", "Building tool schemas"),
    ("critic", "Reviewing claims"),
    ("score", "Scoring"),
    ("generate", "Generating artifacts"),
    ("demo", "Running the comparison"),
)


class ScanEvent(BaseModel):
    """One thing that happened, small enough to push down a wire."""

    model_config = ConfigDict(extra="forbid")

    type: EventType
    job_id: str
    node: str | None = None
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_sse(self) -> str:
        """Render as an SSE frame.

        The event name is set as well as the payload so a client can attach
        listeners per type rather than switching on a field.
        """
        payload = json.dumps(
            {
                "type": self.type.value,
                "job_id": self.job_id,
                "node": self.node,
                "message": self.message,
                "data": self.data,
                "at": self.at.isoformat(),
            }
        )
        return f"event: {self.type.value}\ndata: {payload}\n\n"


def node_start(job_id: str, node: str, message: str = "") -> ScanEvent:
    label = dict(NODE_SEQUENCE).get(node, node)
    return ScanEvent(
        type=EventType.NODE_START, job_id=job_id, node=node, message=message or label
    )


def node_complete(job_id: str, node: str, **data: Any) -> ScanEvent:
    return ScanEvent(type=EventType.NODE_COMPLETE, job_id=job_id, node=node, data=data)


def progress(job_id: str, node: str, message: str, **data: Any) -> ScanEvent:
    return ScanEvent(
        type=EventType.PROGRESS, job_id=job_id, node=node, message=message, data=data
    )


def error(job_id: str, message: str, node: str | None = None) -> ScanEvent:
    return ScanEvent(type=EventType.ERROR, job_id=job_id, node=node, message=message)


def done(job_id: str, **data: Any) -> ScanEvent:
    return ScanEvent(type=EventType.DONE, job_id=job_id, data=data)
