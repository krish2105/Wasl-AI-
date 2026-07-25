"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { BackendNotice } from "@/components/ui/BackendNotice";
import { startScan } from "@/lib/scan";

/**
 * Submission handoff: takes ?url= or ?fixture=, starts a job, redirects to it.
 *
 * The refusal path matters more than the happy one here. A crawler with no
 * configured identity declines to run, and that is a designed behaviour rather
 * than an outage — so it gets an explanation and a way forward, not a stack
 * trace.
 */

const FIXTURES = [
  { id: "rich_site", label: "structured supplier", hint: "JSON-LD, GET search, stable IDs" },
  { id: "spa_site", label: "hydration-only listings", hint: "empty pre-JS DOM, infinite scroll" },
  { id: "thin_site", label: "brochureware", hint: "no structured data, POST-only form" },
];

function StartScan(): React.ReactElement {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const url = params.get("url");
  const fixture = params.get("fixture");

  useEffect(() => {
    if (!url && !fixture) return;
    setBusy(true);
    startScan(url ? { url } : { fixture: fixture ?? undefined })
      .then((job) => router.replace(`/scan/${job.job_id}`))
      .catch((exc) => {
        setError(exc instanceof Error ? exc.message : "Could not start the scan.");
        setBusy(false);
      });
  }, [url, fixture, router]);

  if (busy) {
    return (
      <p className="mono" style={{ color: "var(--paper-dim)" }}>
        starting…
      </p>
    );
  }

  return (
    <>
      {error && (
        <div
          className="mb-10 p-5"
          style={{ background: "var(--ink-800)", borderLeft: "3px solid var(--refused)" }}
          role="alert"
        >
          <p className="eyebrow" style={{ color: "var(--refused)" }}>
            Scan not started
          </p>
          <p className="mono mt-3" style={{ color: "var(--paper-dim)" }}>
            {error}
          </p>
        </div>
      )}

      <BackendNotice />

      <p className="lede mt-10">
        Live scanning is disabled until the crawler can identify itself honestly — a
        User-Agent advertising a page nobody can read is not acceptable identification, so
        the crawler refuses to start without one.
      </p>

      <p className="mono mt-4" style={{ color: "var(--paper-faint)", maxWidth: "var(--measure)" }}>
        Set WASL_CRAWLER_INFO_URL and WASL_OPT_OUT_EMAIL to enable it.
      </p>

      <h2 className="eyebrow mt-14">Scan a saved fixture instead</h2>
      <p className="mt-3" style={{ color: "var(--paper-dim)", maxWidth: "var(--measure)" }}>
        The full pipeline runs — every model call, validator and critic rule is the
        production one. Only the network is skipped.
      </p>

      <ul className="m-0 mt-6 list-none p-0" style={{ borderTop: "var(--rule)" }}>
        {FIXTURES.map((f) => (
          <li key={f.id} style={{ borderBottom: "var(--rule)" }}>
            <button
              type="button"
              onClick={() => router.push(`/scan?fixture=${f.id}`)}
              className="flex w-full items-baseline gap-4 py-4 text-left"
              style={{ background: "none", border: 0, color: "inherit", cursor: "pointer" }}
            >
              <span className="mono flex-1" style={{ color: "var(--signal)" }}>
                {f.label}
              </span>
              <span className="mono" style={{ color: "var(--paper-faint)" }}>
                {f.hint}
              </span>
              <span aria-hidden style={{ color: "var(--paper-faint)" }}>
                →
              </span>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}

export default function ScanEntry(): React.ReactElement {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <p className="eyebrow">Scan</p>
      <h1 className="display mt-5" style={{ fontSize: "clamp(1.8rem, 4vw, 3rem)" }}>
        Start a measurement.
      </h1>
      <div className="mt-8">
        <Suspense fallback={<p className="mono">loading…</p>}>
          <StartScan />
        </Suspense>
      </div>
    </main>
  );
}
