"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { SplitScreenDemo } from "@/components/demo/SplitScreenDemo";
import { CapabilityGraph2D } from "@/components/graph/CapabilityGraph2D";
import { LiveScan } from "@/components/scan/LiveScan";
import { AxisBreakdown } from "@/components/score/AxisBreakdown";
import { RadialScore } from "@/components/score/RadialScore";
import { RefusedPanel } from "@/components/score/RefusedPanel";
import { type Report, artifactsUrl, getReport } from "@/lib/scan";

/**
 * One route, two phases: the live scan, then the report it produced.
 *
 * They share a URL deliberately. The scan is not a loading screen for the
 * report — it is the part that shows the work, and it stays linkable and
 * re-readable afterwards through the "activity" toggle.
 */
export default function ScanPage({
  params,
}: {
  params: { jobId: string };
}): React.ReactElement {
  const { jobId } = params;
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showActivity, setShowActivity] = useState(true);

  const load = useCallback(async () => {
    try {
      setReport(await getReport(jobId));
      setShowActivity(false);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not load the report.");
    }
  }, [jobId]);

  // A page opened after the scan finished should show the report, not replay.
  useEffect(() => {
    getReport(jobId)
      .then((r) => {
        setReport(r);
        setShowActivity(false);
      })
      .catch(() => {
        /* still running — the stream will drive it */
      });
  }, [jobId]);

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <header className="flex flex-wrap items-baseline justify-between gap-4">
        <div>
          <Link href="/" className="mono" style={{ color: "var(--paper-faint)" }}>
            ← wasl
          </Link>
          <h1 className="display mt-3" style={{ fontSize: "clamp(1.6rem, 4vw, 2.6rem)" }}>
            {report?.domain ?? "Scanning…"}
          </h1>
          <p className="mono mt-2" style={{ color: "var(--paper-faint)" }}>
            job {jobId}
            {report && ` · ${report.seconds}s`}
            {report?.source === "fixture" && (
              <span
                className="ml-3 px-2"
                style={{ border: "1px solid var(--band-emerging)", color: "var(--band-emerging)" }}
              >
                fixture
              </span>
            )}
          </p>
        </div>

        {report && (
          <button
            type="button"
            onClick={() => setShowActivity((v) => !v)}
            className="mono px-4 py-2"
            style={{
              background: "var(--ink-700)",
              border: 0,
              color: "var(--paper)",
              cursor: "pointer",
            }}
          >
            {showActivity ? "show report" : "show activity"}
          </button>
        )}
      </header>

      {report?.source === "fixture" && (
        <p
          className="mono mt-6 p-3"
          style={{
            background: "var(--ink-800)",
            borderLeft: "3px solid var(--band-emerging)",
            color: "var(--paper-dim)",
            maxWidth: "var(--measure)",
          }}
        >
          Scanned from a saved fixture, not a live site. Every model call, validator and
          critic rule below is the production one — only the network was skipped.
        </p>
      )}

      {error && (
        <p className="mono mt-8" style={{ color: "var(--refused)" }}>
          {error}
        </p>
      )}

      <section className="mt-10">
        {showActivity ? (
          <LiveScan jobId={jobId} onComplete={load} />
        ) : report ? (
          <ReportView report={report} />
        ) : null}
      </section>
    </main>
  );
}

function ReportView({ report }: { report: Report }): React.ReactElement {
  const { score } = report;

  return (
    <div className="space-y-20">
      {score ? (
        <section className="grid gap-12 md:grid-cols-[auto_1fr] md:items-start">
          <RadialScore score={score} />

          <div>
            {score.confidence === "low" && score.confidence_reason && (
              <div
                className="mb-6 p-4"
                style={{ background: "var(--ink-800)", borderLeft: "3px solid var(--refused)" }}
                role="note"
              >
                <p className="eyebrow" style={{ color: "var(--refused)" }}>
                  Low confidence
                </p>
                <p className="mt-2 text-sm" style={{ color: "var(--paper-dim)" }}>
                  {score.confidence_reason} The number is shown; the grade band is not,
                  because a confident headline on thin evidence is worse than none.
                </p>
              </div>
            )}

            {score.degraded && (
              <div
                className="mb-6 p-4"
                style={{ background: "var(--ink-800)", borderLeft: "3px solid var(--band-emerging)" }}
                role="note"
              >
                <p className="eyebrow" style={{ color: "var(--band-emerging)" }}>
                  Degraded capture
                </p>
                <p className="mt-2 text-sm" style={{ color: "var(--paper-dim)" }}>
                  Captured without a browser, so the pre-JS/post-JS comparison was never
                  observed. Rendering-dependent checks are excluded from the total rather
                  than scored zero.
                </p>
              </div>
            )}

            <AxisBreakdown axes={score.axes} evidence={report.evidence} />
          </div>
        </section>
      ) : (
        <p className="mono" style={{ color: "var(--refused)" }}>
          No score was produced for this scan.
        </p>
      )}

      {/* --- capabilities --------------------------------------------------- */}
      <section aria-labelledby="capabilities">
        <h2 id="capabilities" className="eyebrow" style={{ color: "var(--measured)" }}>
          Capabilities accepted
        </h2>
        {report.accepted_capabilities.length === 0 ? (
          <p className="mono mt-4" style={{ color: "var(--paper-faint)" }}>
            None survived review.
          </p>
        ) : (
          <ul className="m-0 mt-5 list-none p-0" style={{ borderTop: "var(--rule)" }}>
            {report.accepted_capabilities.map((capability) => (
              <li key={capability.name} className="py-4" style={{ borderBottom: "var(--rule)" }}>
                <div className="flex flex-wrap items-baseline gap-3">
                  <span className="mono" style={{ color: "var(--measured)" }}>
                    {capability.name}
                  </span>
                  {capability.tool_schema && (
                    <span className="mono" style={{ color: "var(--paper-faint)" }}>
                      → {capability.tool_schema.name}(
                      {Object.keys(capability.tool_schema.parameters ?? {}).join(", ")})
                    </span>
                  )}
                </div>
                <p className="mt-2 text-sm" style={{ color: "var(--paper-dim)", maxWidth: "var(--measure)" }}>
                  {capability.description}
                </p>
                <p className="mono mt-2" style={{ color: "var(--signal)" }}>
                  cites {capability.evidence_ids.join(", ")}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <RefusedPanel rejections={report.rejections} />

      {/* --- provenance ----------------------------------------------------- */}
      <section aria-labelledby="provenance">
        <h2 id="provenance" className="eyebrow">
          Provenance
        </h2>
        <div className="mt-5">
          <CapabilityGraph2D
            evidence={report.evidence}
            capabilities={report.accepted_capabilities}
            pageCount={report.pages.length}
          />
        </div>
      </section>

      {report.demo && <SplitScreenDemo demo={report.demo} />}

      {/* --- artifacts ------------------------------------------------------ */}
      <section aria-labelledby="artifacts">
        <h2 id="artifacts" className="eyebrow">
          Generated artifacts
        </h2>
        {report.artifacts?.downloadable ? (
          <>
            <p className="mt-3" style={{ color: "var(--paper-dim)", maxWidth: "var(--measure)" }}>
              The server imported in a clean subprocess and exposed{" "}
              {report.artifacts.tool_count} tool
              {report.artifacts.tool_count === 1 ? "" : "s"}. Nothing is offered for
              download until it does.
            </p>
            <a
              href={artifactsUrl(report.job_id)}
              className="mono mt-5 inline-block px-5 py-3"
              style={{ background: "var(--signal)", color: "var(--ink-900)", fontWeight: 600 }}
            >
              Download the bundle
            </a>
          </>
        ) : (
          <>
            <p className="mt-3" style={{ color: "var(--paper-dim)", maxWidth: "var(--measure)" }}>
              Nothing is offered for download — the generated server did not pass
              verification.
            </p>
            {report.artifacts?.summary && (
              <pre className="evidence mt-4">{report.artifacts.summary}</pre>
            )}
          </>
        )}
      </section>
    </div>
  );
}
