"""Evaluation harness.

Built before the frontend, deliberately. A team that builds the interface first
falls in love with it and ships a system it cannot defend.

Metrics fall into three classes and are treated completely differently:

    GATES      binary, non-negotiable, block the build. Target exactly 0 or 1.
    TUNING     continuous, optimised, reported honestly including when below target.
    OPERATING  latency, cost, stability — the ones that decide whether it can ship.

Numbers that depend on hand-labelled ground truth are reported as BLOCKED until
the labels exist, never estimated. A fabricated denominator is worse than a
missing metric because it looks like evidence.
"""
