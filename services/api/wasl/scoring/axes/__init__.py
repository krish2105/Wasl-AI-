"""One module per axis. Every check is a pure function over evidence.

Shared conventions used by all six:

- A check returns exactly one `CheckResult`, always — including when it finds
  nothing. A silent check is indistinguishable from a broken one.
- `evidence_refs` holds the IDs of evidence the award rests on. A check that
  awards points with no refs is a bug, caught by a test.
- `detail` is written for a human reading the report, not for a log.
- Nothing here imports from `wasl.llm`, and a test enforces that.
"""

from wasl.scoring.axes import (
    capability,
    extractability,
    governance,
    identity,
    structured_data,
    transactional,
)

AXES = (
    (1, "Machine-Readable Identity", identity.evaluate, 15),
    (2, "Structured Data Coverage", structured_data.evaluate, 20),
    (3, "Capability Exposure", capability.evaluate, 25),
    (4, "Content Extractability", extractability.evaluate, 15),
    (5, "Transactional Integrity", transactional.evaluate, 15),
    (6, "Agent Governance & Safety", governance.evaluate, 10),
)

__all__ = ["AXES"]
