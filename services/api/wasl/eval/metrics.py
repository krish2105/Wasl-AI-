"""Metric definitions and their targets.

Each metric declares its class, its target, and — crucially — whether it can be
computed from what is currently available. A metric whose ground truth does not
exist yet reports `BLOCKED`, with the reason, rather than a plausible number.

The distinction between a gate and a tuning metric is not cosmetic. A gate at
0.98 is a build failure; a tuning metric at 0.73 against a 0.70 target is a good
day. Conflating them is the most common evaluation mistake there is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class MetricClass(StrEnum):
    GATE = "gate"
    TUNING = "tuning"
    OPERATING = "operating"


class Status(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BELOW = "BELOW"
    BLOCKED = "BLOCKED"
    # Computed, but over too few samples to support the claim. "1.000" on a
    # denominator of one is not an accuracy figure, and letting it render as
    # PASS is the "94% accurate on 8 examples" failure with extra steps.
    INSUFFICIENT = "THIN"


# Below this many samples a tuning metric reports THIN regardless of its value.
MIN_SAMPLES_FOR_A_CLAIM = 10


@dataclass(frozen=True, slots=True)
class MetricSpec:
    key: str
    label: str
    metric_class: MetricClass
    target: float | None
    comparison: str  # ">=" | "<=" | "==" | "info"
    description: str

    def evaluate(self, value: float | None) -> Status:
        if value is None:
            return Status.BLOCKED
        if self.target is None or self.comparison == "info":
            return Status.PASS

        met = {
            ">=": value >= self.target,
            "<=": value <= self.target,
            "==": abs(value - self.target) < 1e-9,
        }[self.comparison]

        if met:
            return Status.PASS
        # A missed gate is a build failure. A missed tuning target is a number
        # you publish and explain.
        return Status.FAIL if self.metric_class is MetricClass.GATE else Status.BELOW

    def target_text(self) -> str:
        if self.target is None or self.comparison == "info":
            return "—"
        return f"{self.comparison}{self.target:g}"


SPECS: tuple[MetricSpec, ...] = (
    # --- gates ---------------------------------------------------------------
    MetricSpec(
        "hallucinated_capability_rate",
        "Hallucinated-capability rate",
        MetricClass.GATE,
        0.0,
        "==",
        "Accepted capabilities whose cited evidence does not exist on re-audit. "
        "A false capability is far more damaging to a user than a missed one.",
    ),
    MetricSpec(
        "citation_validity",
        "Citation validity",
        MetricClass.GATE,
        1.0,
        "==",
        "Evidence references that resolve to real extracted evidence.",
    ),
    MetricSpec(
        "generated_server_import_rate",
        "Generated server import rate",
        MetricClass.GATE,
        1.0,
        "==",
        "Generated servers that import in a clean subprocess and expose tools.",
    ),
    MetricSpec(
        "state_changing_tool_rate",
        "State-changing tools emitted",
        MetricClass.GATE,
        0.0,
        "==",
        "Tools generated for operations that would change state on a third-party site.",
    ),
    # --- tuning --------------------------------------------------------------
    #
    # The three label-dependent metrics are named `judge_labelled_*` because the
    # golden set is currently model-authored. Under that condition they measure
    # agreement with the labelling model, not correctness, and a name that hid
    # the distinction would be the most misleading thing in this file.
    #
    # `wasl.eval.run` switches these back to the plain names automatically when
    # seeds/golden/labels.yaml declares label_source: human.
    MetricSpec(
        "judge_labelled_capability_precision",
        "Capability precision*",
        MetricClass.TUNING,
        0.90,
        ">=",
        "Accepted capabilities the labeller confirms exist. *Labels are "
        "model-authored, so this measures agreement with the labelling model.",
    ),
    MetricSpec(
        "judge_labelled_capability_recall",
        "Capability recall*",
        MetricClass.TUNING,
        0.70,
        ">=",
        "Labelled capabilities the system found. *Model-authored labels.",
    ),
    MetricSpec(
        "judge_labelled_band_accuracy_exact",
        "Band accuracy, exact*",
        MetricClass.TUNING,
        0.70,
        ">=",
        "Predicted band equals the labelled band. *Model-authored labels.",
    ),
    MetricSpec(
        "judge_labelled_band_accuracy_within_1",
        "Band accuracy, ±1*",
        MetricClass.TUNING,
        None,
        "info",
        "Predicted band within one band of the labelled band. *Model-authored labels.",
    ),
    MetricSpec(
        "injection_detection_recall",
        "Injection detection recall",
        MetricClass.TUNING,
        0.90,
        ">=",
        "Seeded injection payloads caught by the scanner.",
    ),
    # --- operating -----------------------------------------------------------
    MetricSpec(
        "score_stability_max_delta",
        "Score stability (max delta)",
        MetricClass.OPERATING,
        4.0,
        "<=",
        "Largest score difference across repeated runs on identical input.",
    ),
    MetricSpec(
        "latency_p95_seconds",
        "Latency p95",
        MetricClass.OPERATING,
        90.0,
        "<=",
        "End-to-end scan wall time, 95th percentile.",
    ),
    MetricSpec(
        "cost_per_scan_usd",
        "Cost per scan",
        MetricClass.OPERATING,
        0.0,
        "==",
        "Marginal cost per scan. Zero by construction — every provider is a free "
        "tier or a local model.",
    ),
)

BY_KEY = {spec.key: spec for spec in SPECS}


@dataclass
class MetricResult:
    spec: MetricSpec
    value: float | None
    detail: str = ""
    blocked_reason: str = ""
    # Denominator this value was computed over. None means "not sample-based"
    # (a gate over every artifact, a latency percentile).
    samples: int | None = None

    @property
    def status(self) -> Status:
        if (
            self.value is not None
            and self.samples is not None
            and self.samples < MIN_SAMPLES_FOR_A_CLAIM
            and self.spec.metric_class is MetricClass.TUNING
        ):
            return Status.INSUFFICIENT
        return self.spec.evaluate(self.value)

    @property
    def value_text(self) -> str:
        if self.value is None:
            return "—"
        if self.spec.key.endswith("_seconds"):
            return f"{self.value:.1f}"
        if self.spec.key.endswith("_usd"):
            return f"{self.value:.2f}"
        if self.spec.key.endswith("_delta"):
            return f"{self.value:.1f}"
        return f"{self.value:.3f}"


@dataclass
class EvalReport:
    """A whole evaluation run."""

    results: list[MetricResult] = field(default_factory=list)
    golden_set_size: int = 0
    golden_labelled: int = 0
    model: str = ""
    prompt_shas: dict[str, str] = field(default_factory=dict)
    run_date: str = ""
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    labels_are_model_authored: bool = False

    def of_class(self, metric_class: MetricClass) -> list[MetricResult]:
        return [r for r in self.results if r.spec.metric_class is metric_class]

    @property
    def gates_pass(self) -> bool:
        """A blocked or thin gate is not a passing gate."""
        return all(r.status is Status.PASS for r in self.of_class(MetricClass.GATE))

    @property
    def thin(self) -> list[MetricResult]:
        return [r for r in self.results if r.status is Status.INSUFFICIENT]

    @property
    def blocked(self) -> list[MetricResult]:
        return [r for r in self.results if r.status is Status.BLOCKED]


# --- metric computations -----------------------------------------------------


def citation_validity(cited_ids: list[str], known_ids: set[str]) -> tuple[float, list[str]]:
    """Fraction of citations that resolve. Returns (value, dangling ids)."""
    if not cited_ids:
        return 1.0, []
    dangling = [eid for eid in cited_ids if eid not in known_ids]
    return (len(cited_ids) - len(dangling)) / len(cited_ids), dangling


def hallucinated_capability_rate(capabilities, known_ids: set[str]) -> tuple[float, list[str]]:
    """Accepted capabilities with at least one unresolvable citation.

    Re-audited against the evidence store rather than trusting the critic — this
    is the gate, so it must not depend on the component it is checking.
    """
    accepted = [c for c in capabilities if getattr(c, "accepted", False)]
    if not accepted:
        return 0.0, []
    offenders = [
        c.name for c in accepted if any(eid not in known_ids for eid in c.evidence_ids)
    ]
    return len(offenders) / len(accepted), offenders


def state_changing_tool_rate(capabilities) -> tuple[float, list[str]]:
    """Emitted tools that would change state. Must be zero."""
    with_tools = [
        c for c in capabilities if getattr(c, "accepted", False) and getattr(c, "tool_schema", None)
    ]
    if not with_tools:
        return 0.0, []
    offenders = [c.name for c in with_tools if c.implies_state_change()]
    return len(offenders) / len(with_tools), offenders


def injection_recall(expected_pattern_ids: set[str], found_pattern_ids: set[str]) -> tuple[float, list[str]]:
    if not expected_pattern_ids:
        return 1.0, []
    missed = sorted(expected_pattern_ids - found_pattern_ids)
    return len(expected_pattern_ids & found_pattern_ids) / len(expected_pattern_ids), missed


def score_stability(totals: list[int]) -> float:
    return float(max(totals) - min(totals)) if totals else 0.0


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(round((p / 100) * (len(ordered) - 1))), len(ordered) - 1)
    return ordered[index]


def capability_precision_recall(
    predicted: list[str], labelled: list[str]
) -> tuple[float, float]:
    """Set-based precision and recall over normalised capability names.

    Normalisation is deliberately crude — lowercase, underscores to spaces — and
    the granularity rule in labels.yaml is what actually makes these comparable
    across sites. No amount of string matching fixes inconsistent labelling.
    """

    def normalise(items: list[str]) -> set[str]:
        return {" ".join(i.lower().replace("_", " ").split()) for i in items if i}

    got, want = normalise(predicted), normalise(labelled)
    if not got and not want:
        return 1.0, 1.0
    precision = len(got & want) / len(got) if got else 0.0
    recall = len(got & want) / len(want) if want else 1.0
    return precision, recall


BAND_ORDER = ["Invisible", "Emerging", "Readable", "Agent-Ready", "Agent-Native"]


def band_distance(predicted: str | None, labelled: str | None) -> int | None:
    if not predicted or not labelled:
        return None
    try:
        return abs(BAND_ORDER.index(predicted) - BAND_ORDER.index(labelled))
    except ValueError:
        return None
