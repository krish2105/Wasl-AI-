"""Graph state.

Two principles from the architecture, both structural rather than advisory:

**Invalid states are unrepresentable.** `Capability.evidence_ids` has a validator
that raises on an empty list. There is no path by which an uncited capability
exists in memory, let alone reaches a user. That validator is worth more than any
amount of prompt engineering telling the model to cite its sources.

**Accumulate, never overwrite.** Rejections, errors and failed critic rounds stay
in state. They are the debugging surface, and in this project they are also a
product feature — the "what we refused to generate" panel reads straight off
`rejections`.

State is serialisable so LangGraph can checkpoint it to Postgres. A scan that
dies at node six resumes at node six rather than re-crawling, which matters
because re-crawling means real requests to a real third party.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CriticRule = Literal[
    "no_evidence",
    "evidence_mismatch",
    "unbounded_param",
    "state_changing",
    "injection_detected",
]

READ_ONLY_VERBS = frozenset({"search", "get", "list", "check", "find", "browse", "read", "lookup"})

STATE_CHANGING_MARKERS = frozenset(
    {
        "book", "buy", "purchase", "order", "reserve", "cancel", "submit", "pay",
        "checkout", "create", "delete", "update", "register", "subscribe", "apply",
        "send", "post", "add", "remove", "modify", "schedule", "enrol", "enroll",
    }
)


class Budget(BaseModel):
    """Hard limits carried in state. Retrofitting these into a live graph is miserable."""

    model_config = ConfigDict(extra="forbid")

    max_critic_rounds: int = 3
    max_model_calls: int = 60
    max_seconds: int = 300
    model_calls_used: int = 0
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def calls_remaining(self) -> int:
        return max(0, self.max_model_calls - self.model_calls_used)

    @property
    def seconds_elapsed(self) -> float:
        return (datetime.now(UTC) - self.started_at).total_seconds()

    @property
    def exhausted(self) -> bool:
        return self.calls_remaining <= 0 or self.seconds_elapsed > self.max_seconds


class PageSummary(BaseModel):
    """A crawled page, reduced to what downstream nodes need.

    Bodies stay on disk in the snapshot cache. Carrying megabytes of third-party
    HTML through every checkpoint would make resume slower than re-crawling.
    """

    model_config = ConfigDict(extra="forbid")

    url: str
    final_url: str
    status_code: int
    robots_blocked: bool = False
    degraded: bool = False
    pre_js_chars: int = 0
    post_js_chars: int = 0
    fetch_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.fetch_error is None and 200 <= self.status_code < 300


class EvidenceRecord(BaseModel):
    """Serialisable form of a crawler Evidence row."""

    model_config = ConfigDict(extra="forbid")

    id: str
    source_url: str
    kind: str
    selector: str | None = None
    raw: str
    phase: str


class ToolSchema(BaseModel):
    """An MCP tool definition proposed for a capability."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    returns: str = ""

    def unbounded_parameters(self) -> list[str]:
        """Free-text parameters with no description or no length bound.

        A critic rejection rule reads this. An unbounded string parameter in a
        generated tool is an injection surface for whoever runs the server.
        """
        offenders: list[str] = []
        for name, spec in self.parameters.items():
            if not isinstance(spec, dict):
                offenders.append(name)
                continue
            if spec.get("type") != "string":
                continue
            if not str(spec.get("description", "")).strip():
                offenders.append(name)
            elif "maxLength" not in spec and "enum" not in spec and "pattern" not in spec:
                offenders.append(name)
        return offenders


class Capability(BaseModel):
    """Something the site can do, as proposed by the induce node.

    `evidence_ids` cannot be empty. That is the whole point of this class.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    verb: str
    noun: str
    description: str
    evidence_ids: list[str]
    reasoning: str = ""
    state_changing: bool = False
    tool_schema: ToolSchema | None = None
    accepted: bool = False
    critic_rounds: int = 0

    @field_validator("evidence_ids")
    @classmethod
    def must_be_grounded(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError(
                "A capability without evidence is not a capability. "
                "Make the invalid state unrepresentable, not merely discouraged."
            )
        return value

    @field_validator("name")
    @classmethod
    def must_be_snake_case(cls, value: str) -> str:
        cleaned = value.strip().lower().replace(" ", "_").replace("-", "_")
        if not cleaned:
            raise ValueError("Capability name cannot be empty.")
        return cleaned

    def implies_state_change(self) -> bool:
        """Whether this looks state-changing regardless of what the model claimed.

        Checked independently of the `state_changing` flag: a model that wants a
        tool emitted has an incentive to mark it read-only, so the verb and name
        are inspected directly.
        """
        if self.state_changing:
            return True
        if self.verb.lower() in STATE_CHANGING_MARKERS:
            return True
        tokens = set(self.name.lower().split("_"))
        return bool(tokens & STATE_CHANGING_MARKERS)


class Rejection(BaseModel):
    """A capability the critic refused, and why. Surfaced in the UI."""

    model_config = ConfigDict(extra="forbid")

    capability_name: str
    rule_id: CriticRule
    reason: str
    critic_round: int = 1
    final: bool = False
    evidence_ids: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    """A security observation about the crawled site."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["injection", "tool_boundary"]
    category: str = ""
    severity: Literal["info", "low", "medium", "high"] = "info"
    description: str
    evidence_ids: list[str] = Field(default_factory=list)


class DemoResult(BaseModel):
    """Outcome of the raw-site vs generated-server A/B.

    Both arms are recorded verbatim including the case where the raw arm wins.
    A comparison that can only come out one way is not evidence of anything.
    """

    model_config = ConfigDict(extra="forbid")

    task: str
    raw_succeeded: bool = False
    raw_transcript: str = ""
    raw_steps: int = 0
    mcp_succeeded: bool = False
    mcp_transcript: str = ""
    mcp_steps: int = 0
    note: str = ""


class GeneratedArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_path: str | None = None
    agent_card_path: str | None = None
    llms_txt_path: str | None = None
    zip_path: str | None = None
    tool_count: int = 0
    verified: bool = False
    verification_output: str = ""


def _append(left: list, right: list) -> list:
    """Reducer: state accumulates rather than overwriting."""
    return [*left, *right]


class WaslState(BaseModel):
    """The whole scan."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    job_id: str
    root_url: str
    domain: str = ""
    budget_name: str = "interactive"
    user_submitted: bool = False

    # "fixture" replays a saved page from disk and sends no request. It lives in
    # state rather than being decided by the caller because the graph is the
    # execution path, and a resumed scan has to know it must not reach for the
    # network on a leg the original run served from disk.
    source: Literal["url", "fixture"] = "url"

    pages: list[PageSummary] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)

    candidate_capabilities: list[Capability] = Field(default_factory=list)
    accepted_capabilities: list[Capability] = Field(default_factory=list)
    rejections: Annotated[list[Rejection], _append] = Field(default_factory=list)
    critic_rounds: int = 0

    score: dict[str, Any] | None = None
    artifacts: GeneratedArtifacts | None = None
    security_findings: Annotated[list[Finding], _append] = Field(default_factory=list)
    demo_result: DemoResult | None = None

    budget: Budget = Field(default_factory=Budget)
    errors: Annotated[list[str], _append] = Field(default_factory=list)
    awaiting_confirmation: str | None = None

    # --- derived ------------------------------------------------------------

    @property
    def pages_ok(self) -> int:
        return sum(1 for p in self.pages if p.ok)

    @property
    def pages_robots_blocked(self) -> int:
        return sum(1 for p in self.pages if p.robots_blocked)

    @property
    def degraded(self) -> bool:
        ok = [p for p in self.pages if p.ok]
        return bool(ok) and all(p.degraded for p in ok)

    def evidence_ids(self) -> set[str]:
        return {e.id for e in self.evidence}

    def dangling_references(self) -> list[str]:
        """Cited evidence IDs that do not exist. Must always be empty."""
        known = self.evidence_ids()
        cited = {
            eid
            for capability in [*self.candidate_capabilities, *self.accepted_capabilities]
            for eid in capability.evidence_ids
        }
        return sorted(cited - known)
