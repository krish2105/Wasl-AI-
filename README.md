# Wasl AI

**Scores whether a business is legible to AI agents, then generates the MCP server that makes it legible.**

Paste a public company URL. Wasl crawls it politely, scores its agent-readiness on a defined
100-point index across six axes, and emits a runnable MCP server, an A2A Agent Card and a proposed
`llms.txt` from the capabilities it can actually evidence.

> **Build status: Phase 1 of 8 — skeleton and infrastructure.**
> The eval table below is empty because the harness has not run yet. It will be written here
> automatically by `wasl.eval.run`, and no number appears in this README that was typed by hand.

---

## The design rule everything follows

> **Deterministic logic is code. Language models do retrieval, decomposition and explanation only.**

The model never emits a score. Scoring is a pure function over extracted evidence, in
`services/api/wasl/scoring/`, a package that imports nothing from `wasl/llm/`. A test asserts this:
run a full scan with the model nodes disabled and the score is byte-identical.

What the model *does* do is propose candidate capabilities from the DOM evidence. Every proposal
must cite the evidence that justifies it, enforced by a Pydantic validator rather than a prompt.
A critic node rejects uncited, hallucinated, unsafe and state-changing candidates against five
named criteria, and the rejections are shown in the UI — a tool that displays what it refused to
generate is more trustworthy than one that shows only its successes.

---

## The WARI index

100 points across six axes. Every check is a pure function returning
`(points_awarded, max_points, evidence_refs, confidence)`.

| Axis | Points | Measures |
|---|---:|---|
| 1 · Machine-Readable Identity | 15 | robots.txt, agent stanzas, sitemap, `llms.txt`, canonicals |
| 2 · Structured Data Coverage | 20 | schema.org JSON-LD presence, entity coverage, validity |
| 3 · Capability Exposure | 25 | OpenAPI specs, MCP endpoints, stable discovery URLs |
| 4 · Content Extractability | 15 | server-rendered vs hydration-only, semantics, pagination |
| 5 · Transactional Integrity | 15 | stable identifiers, structured pricing, labelled forms |
| 6 · Agent Governance & Safety | 10 | agent-aware ToS, rate-limit headers, injection surface |

**Bands:** 0–24 Invisible · 25–44 Emerging · 45–64 Readable · 65–84 Agent-Ready · 85–100 Agent-Native

A scan that reached fewer than 8 pages, or that was robots-blocked on more than 30% of them, is
reported `LOW CONFIDENCE` with the band suppressed. A confident-looking score on thin evidence is
worse than no score.

---

## Evaluation

<!-- EVAL_TABLE_START -->
_Not yet run. `wasl.eval.run` writes this section from Phase 6 onward; the golden set is
hand-labelled by a human and the harness refuses to run against an unfilled scaffold._
<!-- EVAL_TABLE_END -->

---

## Architecture

<!-- ARCH_DIAGRAM_START -->
_Written in Phase 8 from `docs/architecture.md`._
<!-- ARCH_DIAGRAM_END -->

---

## Crawler ethics

Wasl reads the open web. That is a privilege, and it comes with rules that are enforced in code
rather than left to good intentions:

- **`robots.txt` is authoritative.** A disallow is recorded as evidence — a finding about how the
  site treats agents, never an obstacle to route around.
- **Read-only. GET requests only.** No authentication, no form submission, no checkout, no
  state-changing request of any kind. Cart, login, account and payment paths are refused regardless
  of what robots.txt permits.
- **0.5 requests/second per domain**, hard-coded, not configurable by the caller. 12 pages per
  interactive scan, 40 per batch crawl, never more.
- **Allowlist, not open crawl.** Only domains in `seeds/seed_urls.yaml` or a domain a user submits
  for their own property. An exclusion registry is checked *before* the allowlist and always wins.
- **Honest identification.** A real User-Agent pointing at a live page that explains what the
  crawler does and how to opt out. The crawler refuses to start if that URL is not configured.
- **Opt-out honoured within 24 hours**, at the contact published on that page.
- **Never probe for rate limits.** Axis 6's rate-limit signal is read passively from headers seen
  during the normal polite crawl. Hammering a site to earn a scoring signal is forbidden.
- **Government and public-sector entities are anonymised** on the public leaderboard.

Full policy: `docs/crawler-policy.md` (Phase 8).

---

## Getting started

Requires Docker, [`uv`](https://docs.astral.sh/uv/) and [`pnpm`](https://pnpm.io/).

```bash
cp .env.example .env          # then fill in WASL_CRAWLER_INFO_URL and WASL_OPT_OUT_EMAIL
docker compose up -d          # postgres+pgvector, redis
```

```bash
cd services/api && uv sync && uv run alembic upgrade head && uv run uvicorn wasl.main:app --reload
```

```bash
cd apps/web && pnpm install && pnpm dev
```

Traces are optional and heavy — bring Langfuse up only when you want them:

```bash
docker compose --profile obs up -d
```

---

## Stack

Next.js 14 · TypeScript · Tailwind · Motion v12 · React Three Fiber · Lenis · shadcn/ui ·
Python 3.11 · FastAPI · LangGraph · Pydantic v2 · Playwright · PostgreSQL 15 + pgvector · Redis ·
LiteLLM (Groq → Gemini → Cerebras → Ollama) · MCP Python SDK · OpenTelemetry → Langfuse

**Zero paid API keys.** Every model provider is a free tier, with a local Ollama fallback.

---

## Limitations

Written honestly in Phase 8 once there are measured numbers to be honest about. Placeholder claims
do not go here.

---

## Licence and scope

A portfolio and research project. Generated Agent Cards are unsigned and illustrative — they do not
represent registered production agents. Nothing in this repository constitutes legal advice about
crawling, and no real citizen, customer or employee data is used anywhere in it.
