"use client";

import { motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";

import { NODES, type ScanEvent, eventsUrl } from "@/lib/scan";

/**
 * The live scan.
 *
 * The streaming build-up is where "it is really doing something" comes from, so
 * this deliberately does not batch: each node appears as it fires, counters tick
 * as evidence accumulates, and refusals show up in red the moment the critic
 * makes them. A progress bar that jumps 0 → 100 would be easier and would
 * communicate nothing.
 *
 * The log is capped and the tail is what's shown — an unbounded list of 40+
 * detector lines pushes the interesting part off screen.
 */

type NodeState = "pending" | "running" | "done";

const MAX_LOG = 60;

export function LiveScan({
  jobId,
  onComplete,
}: {
  jobId: string;
  onComplete: () => void;
}): React.ReactElement {
  const reduced = useReducedMotion();
  const [nodeStates, setNodeStates] = useState<Record<string, NodeState>>({});
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [log, setLog] = useState<ScanEvent[]>([]);
  const [failure, setFailure] = useState<string | null>(null);
  const [finished, setFinished] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const source = new EventSource(eventsUrl(jobId));

    const push = (event: ScanEvent) =>
      setLog((prev) => [...prev, event].slice(-MAX_LOG));

    const on = (name: string, handler: (e: ScanEvent) => void) =>
      source.addEventListener(name, (raw) => {
        const event = JSON.parse((raw as MessageEvent).data) as ScanEvent;
        handler(event);
      });

    on("node_start", (event) => {
      if (event.node) setNodeStates((s) => ({ ...s, [event.node!]: "running" }));
      push(event);
    });

    on("node_complete", (event) => {
      if (event.node) setNodeStates((s) => ({ ...s, [event.node!]: "done" }));
      setCounts((c) => ({ ...c, ...(event.data as Record<string, number>) }));
      push(event);
    });

    on("progress", push);
    on("capability", push);
    on("rejection", push);
    on("artifact", push);
    on("error", (event) => {
      setFailure(event.message);
      push(event);
    });

    on("score", (event) => {
      const data = event.data as { total?: number; max_possible?: number };
      setCounts((c) => ({ ...c, score: data.total ?? 0, score_max: data.max_possible ?? 100 }));
      push(event);
    });

    on("done", () => {
      setFinished(true);
      source.close();
      // Small beat so the last node visibly lands before the report replaces it.
      window.setTimeout(onComplete, reduced ? 0 : 700);
    });

    source.onerror = () => {
      // EventSource retries on its own; only surface a hard failure once the
      // stream is closed for good.
      if (source.readyState === EventSource.CLOSED) {
        setFailure((f) => f ?? "The event stream closed unexpectedly.");
      }
    };

    return () => source.close();
  }, [jobId, onComplete, reduced]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [log]);

  return (
    <div className="grid gap-10 md:grid-cols-[minmax(0,20rem)_1fr]">
      {/* --- the pipeline --------------------------------------------------- */}
      <ol className="m-0 list-none p-0">
        {NODES.map((node, index) => {
          const state = nodeStates[node.id] ?? "pending";
          return (
            <li
              key={node.id}
              className="flex items-baseline gap-3 py-2.5"
              style={{ borderBottom: "var(--rule)" }}
            >
              <span
                className="mono"
                style={{ width: "1.4rem", color: "var(--paper-faint)" }}
                aria-hidden
              >
                {String(index + 1).padStart(2, "0")}
              </span>
              <span
                aria-hidden
                style={{
                  width: 8,
                  height: 8,
                  flexShrink: 0,
                  borderRadius: "50%",
                  background:
                    state === "done"
                      ? "var(--measured)"
                      : state === "running"
                        ? "var(--signal)"
                        : "var(--ink-500)",
                  boxShadow: state === "running" ? "0 0 0 4px rgba(77,168,218,0.18)" : "none",
                }}
              />
              <span
                className="flex-1"
                style={{
                  color: state === "pending" ? "var(--paper-faint)" : "var(--paper)",
                  fontWeight: state === "running" ? 600 : 400,
                }}
              >
                {node.label}
                <span className="sr-only"> — {state}</span>
              </span>
              {state === "done" && <NodeCount node={node.id} counts={counts} />}
            </li>
          );
        })}
      </ol>

      {/* --- counters and the log ------------------------------------------ */}
      <div>
        <div className="grid grid-cols-2 gap-px sm:grid-cols-4" style={{ background: "rgba(237,233,227,0.12)" }}>
          <Counter label="pages" value={counts.pages} />
          <Counter label="evidence" value={counts.evidence} />
          <Counter label="accepted" value={counts.accepted} tone="measured" />
          <Counter label="refused" value={counts.refused} tone="refused" />
        </div>

        {failure && (
          <div
            className="mt-6 p-4"
            style={{ background: "var(--ink-800)", borderLeft: "3px solid var(--refused)" }}
            role="alert"
          >
            <p className="eyebrow" style={{ color: "var(--refused)" }}>
              Scan stopped
            </p>
            <p className="mono mt-2" style={{ color: "var(--paper-dim)" }}>
              {failure}
            </p>
          </div>
        )}

        <div
          ref={logRef}
          className="mono mt-6 overflow-y-auto p-4"
          style={{
            background: "var(--ink-800)",
            border: "var(--rule)",
            height: "22rem",
            color: "var(--paper-dim)",
          }}
          aria-live="polite"
          aria-label="Scan activity"
        >
          {log.length === 0 && <p style={{ color: "var(--paper-faint)" }}>waiting for the first event…</p>}
          {log.map((event, index) => (
            <motion.p
              key={`${event.at}-${index}`}
              initial={reduced ? false : { opacity: 0, y: 3 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.18 }}
              className="py-0.5"
              style={{ color: lineColour(event) }}
            >
              <span style={{ color: "var(--paper-faint)" }}>{event.node ?? "—"} </span>
              {lineText(event)}
            </motion.p>
          ))}
          {finished && (
            <p className="pt-2" style={{ color: "var(--measured)" }}>
              done — opening the report
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function NodeCount({ node, counts }: { node: string; counts: Record<string, number> }) {
  const map: Record<string, string | undefined> = {
    crawl: counts.pages !== undefined ? `${counts.pages} pages` : undefined,
    extract: counts.evidence !== undefined ? `${counts.evidence} rows` : undefined,
    induce: counts.candidates !== undefined ? `${counts.candidates}` : undefined,
    synthesize: counts.schemas !== undefined ? `${counts.schemas}` : undefined,
    critic:
      counts.accepted !== undefined ? `${counts.accepted}✓ ${counts.refused ?? 0}✗` : undefined,
    score: counts.score !== undefined ? `${counts.score}/${counts.score_max}` : undefined,
  };
  const text = map[node];
  return text ? (
    <span className="mono" style={{ color: "var(--paper-faint)" }}>
      {text}
    </span>
  ) : null;
}

function Counter({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | undefined;
  tone?: "measured" | "refused";
}) {
  const colour =
    tone === "measured" ? "var(--measured)" : tone === "refused" ? "var(--refused)" : "var(--signal)";
  return (
    <div className="p-4" style={{ background: "var(--ink-900)" }}>
      <p className="eyebrow">{label}</p>
      <p
        className="mono mt-1"
        style={{ fontSize: "1.6rem", color: value ? colour : "var(--paper-faint)" }}
      >
        {value ?? "—"}
      </p>
    </div>
  );
}

function lineColour(event: ScanEvent): string {
  if (event.type === "rejection") return "var(--refused)";
  if (event.type === "error") return "var(--refused)";
  if (event.type === "capability") return "var(--measured)";
  if (event.type === "node_start") return "var(--paper)";
  return "var(--paper-dim)";
}

function lineText(event: ScanEvent): string {
  switch (event.type) {
    case "node_start":
      return `→ ${event.message}`;
    case "node_complete":
      return `✓ ${Object.entries(event.data)
        .map(([k, v]) => `${k}=${String(v)}`)
        .join(" ")}`;
    case "capability":
      return `+ capability ${event.message}`;
    case "rejection":
      return `✗ refused ${event.message} — ${String(event.data.rule_id ?? "")}`;
    case "score": {
      const d = event.data as { total?: number; max_possible?: number; band?: string | null };
      return `score ${d.total}/${d.max_possible} ${d.band ?? "(band suppressed)"}`;
    }
    case "artifact":
      return event.message;
    case "error":
      return `! ${event.message}`;
    default:
      return event.message;
  }
}
