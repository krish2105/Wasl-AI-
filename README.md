# Wasl AI

**Scores whether a business is legible to AI agents, then generates the MCP server that makes it legible.**

Paste a public company URL. Wasl crawls it politely, scores its agent-readiness on a defined
100-point index across six axes, and emits a runnable MCP server, an A2A Agent Card and a proposed
`llms.txt` from the capabilities it can actually evidence.

> **Build status: Phases 0–6 complete.** Crawler, deterministic rubric, agent graph, generators
> and the evaluation harness all run. Frontend is Phase 7; the public leaderboard is Phase 8.
>
> Every number in the evaluation table below was written there by `wasl.eval.run`. None was
> typed by hand, and metrics without ground truth report `BLOCKED` rather than an estimate.

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
_Golden set: 30 sites (0 hand-labelled) · model `ollama/qwen2.5:7b` · run 2026-07-25._

| Metric | Class | Result | Target | Status |
|---|---|---:|---:|---|
| Citation validity | gate | `1.000` | `==1` | ✅ PASS |
| Hallucinated-capability rate | gate | `0.000` | `==0` | ✅ PASS |
| State-changing tools emitted | gate | `0.000` | `==0` | ✅ PASS |
| Generated server import rate | gate | `1.000` | `==1` | ✅ PASS |
| Capability precision | tuning | `—` | `>=0.9` | ⏸ BLOCKED |
| Capability recall | tuning | `—` | `>=0.7` | ⏸ BLOCKED |
| Band accuracy (exact) | tuning | `—` | `>=0.7` | ⏸ BLOCKED |
| Band accuracy (±1 band) | tuning | `—` | `—` | ⏸ BLOCKED |
| Injection detection recall | tuning | `1.000` | `>=0.9` | ✅ PASS |
| Score stability (max delta) | operating | `0.0` | `<=4` | ✅ PASS |
| Latency p95 | operating | `62.6` | `<=90` | ✅ PASS |
| Cost per scan | operating | `0.00` | `==0` | ✅ PASS |

**Blocked metrics are not estimated.** `capability_precision`, `capability_recall`, `band_accuracy_exact`, `band_accuracy_within_1` require hand-labelled ground truth in `seeds/golden/labels.yaml`. The system must never generate its own labels — that would make the evaluation circular and every number above meaningless.

> Scans run against saved HTML fixtures, not live sites: the crawler refuses to start until WASL_CRAWLER_INFO_URL and WASL_OPT_OUT_EMAIL point at a live page and a real mailbox. Every model call, validator and critic rule is the production one; only the network is skipped.

> Capability precision/recall and band accuracy are BLOCKED. They need seeds/golden/labels.yaml filled in by hand — the system must never generate its own ground truth, or the eval is circular.

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

Stated before anyone else finds them.

**Four metrics are unmeasured.** Capability precision, capability recall and band accuracy need
30 hand-labelled sites, and the labels do not exist yet. They report `BLOCKED`, not an estimate.
The system must never generate its own ground truth — that makes the evaluation circular and
every other number in the table meaningless.

**Scans currently run against saved fixtures, not live sites.** The crawler refuses to start
until `WASL_CRAWLER_INFO_URL` and `WASL_OPT_OUT_EMAIL` point at a live page and a real mailbox.
That refusal is deliberate and tested: a User-Agent advertising a URL nobody can read is dishonest
identification. Every model call, validator and critic rule in those runs is the production one —
only the network is skipped.

**The latency figure is not a live-scan figure.** A cold interactive crawl adds roughly 44 seconds
of pure rate-limit throttle (12 pages plus 10 site probes at 0.5 req/s) before any model work.

**Score stability is measured at its deterministic floor.** Against fixtures it is exactly 0,
because the rubric is a pure function. That tests reproducibility of the scoring code, not
variance introduced by a live crawl discovering different pages on different days.

**Injection recall is measured against payloads written alongside the patterns that catch them.**
It validates that the scanner searches the right hiding places — hidden elements, comments,
attributes, encoding — not that it generalises to payloads nobody anticipated.

**The split-screen demo's MCP arm currently fails on the offline model tier.** Asked to read a
product out of tool results, `qwen2.5:7b` returns a fluent, plausible, entirely invented answer.
The demo detects this — every claimed value is checked against the material the arm was shown, and
an untraceable answer is counted as a failure — so the panel reports the fabrication rather than
rendering it as a win. The failure is the local model's, not the pipeline's, and a Groq or Gemini
key is expected to clear it. Until then the demo honestly shows the raw page winning on
server-rendered fixtures.

**"Required property" is Wasl's definition, not schema.org's.** schema.org defines no required
properties; taken literally, Axis 2's validity check is unfalsifiable. The operational definition
lives in `services/api/wasl/scoring/schema_required.yaml` with its reasoning.

**Text-in-image is a proxy.** No OCR is performed. Axis 4 measures the ratio of content imagery to
machine-readable text and its alt-text coverage, which catches the failure the check exists for
without claiming a precision it does not have.

**About a fifth of the seed list blocks automated clients**, including six of the thirty golden
sites. Those scans will be thin, and the confidence rule will suppress their bands — which is the
correct outcome, but it means the golden set's effective size is smaller than 30 for some metrics.

---

## Licence and scope

A portfolio and research project. Generated Agent Cards are unsigned and illustrative — they do not
represent registered production agents. Nothing in this repository constitutes legal advice about
crawling, and no real citizen, customer or employee data is used anywhere in it.
