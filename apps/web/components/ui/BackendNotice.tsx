"use client";

import { useEffect, useState } from "react";

import { API_BASE_URL } from "@/lib/api";

import { SplitIcon } from "./Icons";

/**
 * Explains, on the deployed site, why scanning is not available here.
 *
 * The API needs Playwright, Postgres, Redis and long-lived SSE connections, none
 * of which fit a serverless frontend host. So the public deployment is the
 * frontend alone, and the honest thing is to say that plainly in the place a
 * visitor would otherwise hit a failed fetch.
 *
 * Probes `/health` rather than reading a build-time flag: someone running the
 * API locally against this same UI should get the working product, not a notice
 * telling them it is unavailable.
 */

type Status = "checking" | "up" | "down";

export function BackendNotice(): React.ReactElement | null {
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 4000);

    fetch(`${API_BASE_URL}/health`, { signal: controller.signal })
      .then((r) => setStatus(r.ok ? "up" : "down"))
      .catch(() => setStatus("down"))
      .finally(() => window.clearTimeout(timer));

    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, []);

  if (status !== "down") return null;

  return (
    <aside
      className="card mt-10 p-6"
      style={{ borderLeft: "3px solid var(--band-emerging)" }}
      aria-labelledby="backend-notice"
    >
      <div className="flex items-start gap-4">
        <span
          className="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center"
          style={{
            background: "var(--signal-soft)",
            color: "var(--band-emerging)",
            borderRadius: 3,
          }}
        >
          <SplitIcon size={17} />
        </span>

        <div>
          <h2 id="backend-notice" className="eyebrow" style={{ color: "var(--band-emerging)" }}>
            Scanning runs locally, not here
          </h2>

          <p className="mt-3 text-sm" style={{ color: "var(--text-dim)", maxWidth: "var(--measure)" }}>
            This deployment is the interface only. The scan pipeline needs headless Chromium,
            Postgres, Redis and long-lived SSE connections — a serverless frontend host is the
            wrong shape for all four, and pretending otherwise would mean a demo that breaks
            the first time someone clicks it.
          </p>

          <p className="mt-3 text-sm" style={{ color: "var(--text-dim)", maxWidth: "var(--measure)" }}>
            Everything below works offline against saved fixtures — the whole pipeline, every
            validator, every critic rule. Only the network is skipped.
          </p>

          <pre className="evidence mt-4">{`git clone https://github.com/krish2105/Wasl-AI-.git && cd Wasl-AI-
docker compose up -d
cd services/api && uv sync && uv run uvicorn wasl.main:app --reload

# then, with no API key of any kind:
uv run python -m wasl.eval.run
uv run python -m wasl.graph.cli --fixture rich_site`}</pre>

          <p className="mono mt-4" style={{ color: "var(--text-faint)" }}>
            The pages that do not need a backend —{" "}
            <a href="/crawler" style={{ color: "var(--signal)" }}>
              the crawler policy
            </a>{" "}
            and the rubric above — are fully live.
          </p>
        </div>
      </div>
    </aside>
  );
}
