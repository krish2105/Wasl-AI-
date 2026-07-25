# =============================================================================
# Wasl AI — backend
# =============================================================================
#
# BUILD CONTEXT IS THE REPOSITORY ROOT, not this directory:
#
#     docker build -f services/api/Dockerfile -t wasl-api .
#
# because the image needs `seeds/` as well as `services/api/`, and COPY cannot
# reach outside its context.
#
# WHY NOT THE OFFICIAL PLAYWRIGHT IMAGE:
#
# The first version of this file used mcr.microsoft.com/playwright/python. It
# produced a 5.25 GB image that then failed to start, and both faults share a
# root cause worth writing down.
#
#   Size    — that image ships Chromium, Firefox AND WebKit. Wasl uses Chromium
#             only, so two thirds of the download is dead weight.
#   Failure — its `-noble` tag is Ubuntu 24.04 with Python 3.12. This project
#             pins 3.11, so a venv built on a 3.11 base referenced an interpreter
#             the runtime did not have: `exec /app/.venv/bin/uvicorn: no such
#             file or directory`, at container start rather than at build.
#
# Building on python:3.11-slim and letting Playwright install its own system
# dependencies fixes both: one interpreter throughout, one browser, ~1 GB.
#
# MEMORY: headless Chromium wants ~1 GB resident. A 512 MB instance OOMs
# mid-crawl. Size for 2 GB.
# =============================================================================

# Must match the playwright version in uv.lock, or `playwright install` fetches
# a browser build the library then refuses to drive.
ARG PYTHON_VERSION=3.11-slim-bookworm

# --- builder -----------------------------------------------------------------
FROM python:${PYTHON_VERSION} AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Same path as the runtime, deliberately. A venv is not relocatable: its console
# scripts carry an absolute shebang, so a venv built at /build/.venv and copied
# to /app/.venv yields `playwright: not found` — the script is there, the
# interpreter its shebang names is not.
WORKDIR /app

# Dependencies first, without the project, so this layer survives code edits.
COPY services/api/pyproject.toml services/api/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY services/api/wasl ./wasl
COPY services/api/alembic.ini ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- runtime -----------------------------------------------------------------
FROM python:${PYTHON_VERSION} AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PLAYWRIGHT_BROWSERS_PATH=/home/wasl/.cache/ms-playwright \
    WASL_ENV=production \
    WASL_PLAYWRIGHT_AVAILABLE=true \
    WASL_DATA_DIR=/data

WORKDIR /app

# The user is created BEFORE anything is copied, so ownership is set by COPY
# rather than fixed afterwards. `chown -R` over the venv and the browser bundle
# rewrote every file into a fresh layer and cost 1.6 GB on its own — the single
# largest thing in the first working build of this image.
RUN useradd --create-home --uid 10001 wasl \
    && mkdir -p /data/cache /data/artifacts /data/reference \
    && chown -R wasl:wasl /data

COPY --from=builder --chown=wasl:wasl /app/.venv /app/.venv
COPY --from=builder --chown=wasl:wasl /app/wasl /app/wasl
COPY --from=builder --chown=wasl:wasl /app/alembic.ini /app/alembic.ini

# Seeds are the crawl allowlist and the exclusion registry — policy, not optional
# data. The crawler refuses any domain absent from this file.
# wasl.crawler.policy.repo_root() finds it by walking up for seeds/seed_urls.yaml,
# which resolves to /app/seeds from /app/wasl/crawler/.
COPY --chown=wasl:wasl seeds /app/seeds

# Root, for apt only. `install-deps` pulls the ~40 system libraries Chromium
# needs (nss, atk, cups, drm, xkbcommon, pango, cairo, alsa …) from Playwright's
# own package list, which tracks Debian renames so this file does not have to.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && python -m playwright install-deps chromium \
    && rm -rf /var/lib/apt/lists/*

USER wasl

# Downloaded as the unprivileged user, into a directory it already owns. Only
# the headless shell: every launch in this codebase is headless=True, and the
# full Chromium bundle is ~350 MB of UI that never renders.
RUN python -m playwright install chromium-headless-shell

EXPOSE 8000

# Hits the real dependency check, so an unreachable Postgres or Redis marks the
# container unhealthy rather than letting it accept traffic it cannot serve.
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# One worker, deliberately. Jobs are held in memory and the SSE stream reads from
# that same process, so a second worker would serve half the event streams from a
# process that knows nothing about the job. Scale out only after wasl/queue.py
# has a consumer and job state moves to Redis.
CMD ["uvicorn", "wasl.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--timeout-keep-alive", "120"]
