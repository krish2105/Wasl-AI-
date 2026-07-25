"""The LangGraph pipeline: crawl -> extract -> induce -> synthesize -> critic -> score.

The topology encodes the architecture rule. Deterministic nodes (`crawl`,
`extract`, `score`) and model nodes (`induce`, `synthesize`, `critic`) are
separate, and the flow of information between them is one-directional: model
nodes read evidence, and the scoring node does not read model output.
"""
