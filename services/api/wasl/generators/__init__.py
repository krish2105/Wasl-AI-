"""Artifact generation: FastMCP server, A2A Agent Card, llms.txt.

Everything emitted here describes a site we do not control, which shapes two
rules that are not negotiable:

**Read-only tools only.** A generated "book the room" tool pointed at somebody
else's booking system is how a portfolio project becomes an incident.

**Cached by default.** Generated servers read from the crawl snapshot unless run
with `--live`. Running someone's generated server should not send traffic to the
site it was generated from.
"""
