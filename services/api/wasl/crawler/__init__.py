"""The crawler: everything that touches the open web.

Reading someone else's website without asking is a privilege, and the rules that
keep it one live in this package rather than in documentation. The rate limit and
the page caps are module constants in `policy`, not settings, specifically so
that no caller, config file or environment variable can raise them.
"""
