"""Wasl AI — agent-readiness scoring and MCP server generation.

Why this package exists: businesses are being told to "become agentic" while
their websites remain unreadable to agents. Wasl is the diagnostic for that gap
(the WARI index) and the generator that closes it (an MCP server built from
capabilities the site can actually evidence).

The organising principle, enforced structurally rather than by convention:
deterministic logic is code, and language models do retrieval, decomposition and
explanation only. `wasl.scoring` imports nothing from `wasl.llm`.
"""

__version__ = "0.1.0"
