"""Persistence layer.

Why this exists: a scan is a long-running, resumable, auditable process. Every
claim Wasl makes about a site has to be reconstructable months later from what
was actually observed, which means the evidence spine is stored, not derived at
render time.
"""
