# Deployment

Two pieces, deployed separately, because they have incompatible requirements.

| | Frontend | Backend |
|---|---|---|
| Host | Vercel | Fly.io / Render |
| Needs | CDN, edge | Chromium, persistent disk, long-lived connections |
| Live | https://wasl-ai-eight.vercel.app | not yet deployed |

The split is not an accident of tooling. The backend needs headless Chromium
(~1 GB RAM), a filesystem that survives redeploys for the crawl cache, and
connections held open for the length of a scan so the SSE stream is not cut
mid-run. No serverless frontend host provides any of the three.

---

## Backend

### Build

The build context is the **repository root**, not `services/api` — the image
needs `seeds/` as well, and `COPY` cannot reach outside its context:

```bash
docker build -f services/api/Dockerfile -t wasl-api .
```

~1.9 GB, ~4 minutes cold. Chromium alone is about half of it.

### Run

```bash
docker run -d -p 8000:8000 \
  -e DATABASE_URL="postgresql+psycopg://user:pass@host:5432/wasl" \
  -e REDIS_URL="redis://:pass@host:6379/0" \
  -e WASL_CRAWLER_INFO_URL="https://wasl-ai-eight.vercel.app/crawler" \
  -e WASL_OPT_OUT_EMAIL="https://github.com/krish2105/Wasl-AI-/issues" \
  -e WASL_CORS_ORIGINS="https://wasl-ai-eight.vercel.app" \
  -v wasl_data:/data \
  wasl-api
```

### Required environment

| Variable | Why |
|---|---|
| `DATABASE_URL` | Postgres with pgvector. Neon's free tier is enough. |
| `REDIS_URL` | Upstash free tier is enough. |
| `WASL_CRAWLER_INFO_URL` | **The crawler refuses to start without it.** Must resolve to a live page describing what it does. |
| `WASL_OPT_OUT_EMAIL` | An email address *or* an https URL to a monitored channel. Also required. |
| `WASL_CORS_ORIGINS` | Comma-separated. Never `*` — this API spends a real, rate-limited crawl budget, and a wildcard lets any page on the internet spend it. |

Model provider keys (`GROQ_API_KEY`, `GOOGLE_API_KEY`, `CEREBRAS_API_KEY`) are
all optional and all free tier. With none set, the router falls through to a
local Ollama and the pipeline still runs — that is the design, not a fallback of
last resort.

### Sizing

**2 GB RAM minimum.** Headless Chromium wants ~1 GB resident. A 512 MB instance
does not fail cleanly; it OOMs partway through a crawl, which looks like a scan
that silently stopped.

Render's free tier and Fly's smallest machine cannot run this. That is a real
cost of needing a browser rather than a configuration problem to solve, and it
is why the public deployment is the frontend alone.

### The volume matters

`/data` holds the crawl snapshot cache. Without a persistent volume it lives in
the container's writable layer and vanishes on every redeploy — which means
re-crawling third-party sites that did not ask to be fetched twice. Caching is a
politeness mechanism here as much as a performance one.

### One worker, deliberately

Jobs are held in memory and the SSE stream reads from that same process. A
second uvicorn worker would serve half the event streams from a process that
knows nothing about the job. Scale out only after `wasl/queue.py` has a consumer
and job state moves to Redis.

---

## Fly.io

```bash
fly launch --no-deploy --copy-config
fly volumes create wasl_data --size 3 --region fra
fly secrets set \
  DATABASE_URL="..." \
  REDIS_URL="..." \
  WASL_CRAWLER_INFO_URL="https://wasl-ai-eight.vercel.app/crawler" \
  WASL_OPT_OUT_EMAIL="https://github.com/krish2105/Wasl-AI-/issues" \
  WASL_CORS_ORIGINS="https://wasl-ai-eight.vercel.app"
fly deploy
```

`fly.toml` sets `auto_stop_machines = false` on purpose: a scan runs for a minute
or more and streams the whole way, so suspending the machine between requests
would kill live scans and drop the in-memory job store with them.

## Render

Push `render.yaml` and create a Blueprint. Set the five `sync: false` variables
in the dashboard.

---

## After deploying

Point the frontend at it and redeploy:

```bash
cd apps/web
vercel env add NEXT_PUBLIC_API_BASE_URL production   # https://wasl-api.fly.dev
vercel --prod
```

The `BackendNotice` on the frontend probes `/health` at runtime, so it
disappears on its own once the API answers. Nothing else needs changing.

---

## Verification

```bash
curl -s https://<your-api>/health | jq
```

`crawler_identity_configured` must be `true`, or the deployment will refuse
every crawl:

```json
{
  "status": "ok",
  "checks": { "database": {"ok": true}, "redis": {"ok": true} },
  "crawler_identity_configured": true,
  "playwright_available": true
}
```

Then confirm Chromium actually launches in the container, which a health check
does not cover:

```bash
docker exec <container> python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True); print(b.version); b.close()"
```

And review a crawl before running one — `--dry-run` fetches robots.txt and the
probe set, then prints the full intent without touching a single page:

```bash
docker exec <container> python -m wasl.crawler.cli https://example.com --dry-run
```
