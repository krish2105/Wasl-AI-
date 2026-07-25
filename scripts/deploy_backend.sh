#!/usr/bin/env bash
#
# Deploy the Wasl backend to Fly.io.
#
#     fly auth login          # once — a browser sign-in, only you can do this
#     ./scripts/deploy_backend.sh
#
# Idempotent: safe to re-run. Every step checks whether it has already happened,
# so a partial failure can be resumed by running the script again rather than by
# unpicking what it did.
#
# WHAT THIS COSTS. Fly's free allowance does not cover this. The machine is
# shared-cpu-2x with 2 GB RAM, plus a 3 GB volume, plus Postgres and Redis.
# Expect a few dollars a month. The 2 GB is not padding — headless Chromium
# wants ~1 GB resident and a smaller machine OOMs partway through a crawl, which
# looks like a scan that silently stopped rather than an obvious failure.

set -euo pipefail

APP="${FLY_APP:-wasl-api}"
REGION="${FLY_REGION:-fra}"          # Frankfurt — closest to the UAE seed list
VOLUME="wasl_data"
FRONTEND="${WASL_FRONTEND_ORIGIN:-https://wasl-ai-eight.vercel.app}"

cd "$(dirname "$0")/.."

info() { printf '\n\033[1;34m→\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31m✗\033[0m %s\n\n' "$*" >&2; exit 1; }

# --- preflight ---------------------------------------------------------------

command -v fly >/dev/null 2>&1 || die "flyctl not on PATH. curl -sL https://fly.io/install.sh | sh"

fly auth whoami >/dev/null 2>&1 || die "Not signed in. Run: fly auth login"
ok "signed in as $(fly auth whoami 2>/dev/null)"

# --- app ---------------------------------------------------------------------

if fly apps list 2>/dev/null | grep -qw "$APP"; then
  ok "app $APP exists"
else
  info "creating app $APP"
  fly apps create "$APP" --machines
fi

# --- volume ------------------------------------------------------------------
#
# Not optional. Without it the crawl snapshot cache lives in the container's
# writable layer and vanishes on every deploy — which means re-crawling
# third-party sites that did not ask to be fetched twice. Caching is a
# politeness mechanism here as much as a performance one.

if fly volumes list -a "$APP" 2>/dev/null | grep -qw "$VOLUME"; then
  ok "volume $VOLUME exists"
else
  info "creating 3GB volume $VOLUME in $REGION"
  fly volumes create "$VOLUME" --size 3 --region "$REGION" -a "$APP" --yes
fi

# --- postgres ----------------------------------------------------------------
#
# The schema declares a pgvector column, so the database must have the
# extension. Neon and Fly Managed Postgres both do; a stock postgres image does
# not, and the first migration fails on CREATE EXTENSION.

if fly secrets list -a "$APP" 2>/dev/null | grep -q DATABASE_URL; then
  ok "DATABASE_URL already set"
else
  warn "DATABASE_URL is not set."
  cat <<'EOF'

  Provision Postgres, then set it:

    Neon (free tier, pgvector included — recommended):
      https://neon.tech → create project → copy the connection string
      fly secrets set DATABASE_URL="postgresql+psycopg://USER:PASS@HOST/DB?sslmode=require" -a wasl-api

    or Fly Managed Postgres (billable):
      fly mpg create --name wasl-db --region fra

  Then re-run this script.
EOF
  die "DATABASE_URL required"
fi

# --- redis -------------------------------------------------------------------

if fly secrets list -a "$APP" 2>/dev/null | grep -q REDIS_URL; then
  ok "REDIS_URL already set"
else
  warn "REDIS_URL is not set."
  cat <<'EOF'

  Provision Redis, then set it:

    Upstash via Fly (free tier available):
      fly ext redis create --name wasl-redis --region fra
      # prints the URL; then:
      fly secrets set REDIS_URL="rediss://..." -a wasl-api

    or Upstash directly: https://upstash.com

  Then re-run this script.
EOF
  die "REDIS_URL required"
fi

# --- crawler identity --------------------------------------------------------
#
# The crawler refuses to start without both of these, by design. A User-Agent
# advertising a page nobody can read is dishonest identification, and honest
# identification is the one rule the crawl ethics treat as non-negotiable.

if fly secrets list -a "$APP" 2>/dev/null | grep -q WASL_CRAWLER_INFO_URL; then
  ok "crawler identity already set"
else
  info "setting crawler identity and CORS origin"
  fly secrets set \
    WASL_CRAWLER_INFO_URL="${FRONTEND}/crawler" \
    WASL_OPT_OUT_EMAIL="${WASL_OPT_OUT_CONTACT:-https://github.com/krish2105/Wasl-AI-/issues}" \
    WASL_CORS_ORIGINS="${FRONTEND}" \
    -a "$APP" --stage
fi

# --- deploy ------------------------------------------------------------------
#
# Build context is the repository root: the image needs seeds/ as well as
# services/api/, and COPY cannot reach outside its context.

info "deploying (build ~4 min cold — Chromium is half the image)"
fly deploy -a "$APP" --config fly.toml --dockerfile services/api/Dockerfile --yes

# --- verify ------------------------------------------------------------------

URL="https://${APP}.fly.dev"
info "verifying $URL"

for attempt in $(seq 1 30); do
  if curl -fsS "$URL/health" >/dev/null 2>&1; then break; fi
  sleep 4
done

HEALTH="$(curl -fsS "$URL/health" 2>/dev/null || echo '')"
[ -n "$HEALTH" ] || die "no response from $URL/health — check: fly logs -a $APP"

echo "$HEALTH"

# crawler_identity_configured false means every crawl will be refused. Better to
# fail the deploy script loudly than to leave a deployment that looks healthy and
# declines all work.
case "$HEALTH" in
  *'"crawler_identity_configured":true'*) ok "crawler identity configured" ;;
  *) die "crawler_identity_configured is false — the API will refuse every crawl" ;;
esac
case "$HEALTH" in
  *'"status":"ok"'*) ok "health ok" ;;
  *) warn "health is degraded — check Postgres and Redis connectivity" ;;
esac

cat <<EOF

$(ok "deployed: $URL")

Point the frontend at it:

  cd apps/web
  vercel env add NEXT_PUBLIC_API_BASE_URL production   # $URL
  vercel --prod

The BackendNotice on the frontend probes /health at runtime, so it disappears on
its own once the API answers. Nothing else needs changing.

Review a crawl before running one:

  fly ssh console -a $APP -C "python -m wasl.crawler.cli https://example.com --dry-run"
EOF
