"""Graph nodes.

Deterministic nodes (`crawl`, `extract`, `score`) contain no model call.
Model nodes (`induce`, `synthesize`, `critic`) contain no scoring.
That separation is the architecture, and it is visible in the imports.
"""
