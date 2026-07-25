"use client";

import { motion, useReducedMotion } from "motion/react";

import type { Demo } from "@/lib/scan";

/**
 * The signature comparison: same agent, same task, two interfaces.
 *
 * The design constraint that shapes this component is honesty. The backend runs
 * both arms for real and reports whatever happened — including the cases where
 * the raw page wins, or where both fail. So the UI cannot assume a winner: the
 * outcome styling is derived from the data, and the note explaining an
 * unflattering result is given the same prominence as a flattering one.
 *
 * A demo rigged to always win is worth less than an honest one that sometimes
 * doesn't, because a reviewer who spots the rigging discards everything else.
 */

export function SplitScreenDemo({ demo }: { demo: Demo }): React.ReactElement {
  const reduced = useReducedMotion();

  return (
    <section aria-labelledby="demo">
      <h2 id="demo" className="eyebrow">
        Same agent, same task, two interfaces
      </h2>

      <p className="mt-3" style={{ color: "var(--paper-dim)", maxWidth: "var(--measure)" }}>
        {demo.task}
      </p>

      <div
        className="mt-6 grid gap-px md:grid-cols-2"
        style={{ background: "var(--border)", border: "var(--rule)" }}
      >
        <Arm
          label="Against the raw page"
          sublabel="the HTTP response an agent receives, no tools"
          succeeded={demo.raw_succeeded}
          transcript={demo.raw_transcript}
          delay={0}
          reduced={!!reduced}
        />
        <Arm
          label="Against the generated MCP server"
          sublabel="read-only tools over the cached snapshot"
          succeeded={demo.mcp_succeeded}
          transcript={demo.mcp_transcript}
          delay={0.15}
          reduced={!!reduced}
        />
      </div>

      {demo.note && (
        <p
          className="mt-5 p-4 text-sm"
          style={{
            background: "var(--ink-800)",
            borderLeft: `3px solid ${
              demo.mcp_succeeded && !demo.raw_succeeded ? "var(--measured)" : "var(--signal)"
            }`,
            color: "var(--paper-dim)",
            maxWidth: "var(--measure)",
          }}
        >
          {demo.note}
        </p>
      )}

      <p className="mono mt-4" style={{ color: "var(--paper-faint)", maxWidth: "var(--measure)" }}>
        Both arms ran the same model against the same task. The tool call on the right
        executed for real against the crawl snapshot — it is not a scripted response, and
        when it fails, this panel says so.
      </p>
    </section>
  );
}

function Arm({
  label,
  sublabel,
  succeeded,
  transcript,
  delay,
  reduced,
}: {
  label: string;
  sublabel: string;
  succeeded: boolean;
  transcript: string;
  delay: number;
  reduced: boolean;
}) {
  const colour = succeeded ? "var(--measured)" : "var(--refused)";

  return (
    <motion.article
      className="flex flex-col p-5"
      style={{ background: "var(--ink-800)" }}
      initial={reduced ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: reduced ? 0 : 0.4, delay: reduced ? 0 : delay }}
    >
      <header className="flex items-baseline justify-between gap-3">
        <div>
          <p className="eyebrow" style={{ color: colour }}>
            {label}
          </p>
          <p className="mono mt-1" style={{ color: "var(--paper-faint)" }}>
            {sublabel}
          </p>
        </div>
        <span
          className="mono px-2 py-0.5"
          style={{ color: colour, border: `1px solid ${colour}`, whiteSpace: "nowrap" }}
        >
          {succeeded ? "completed" : "could not"}
        </span>
      </header>

      <pre
        className="mono mt-4 flex-1 overflow-x-auto whitespace-pre-wrap"
        style={{ color: "var(--paper-dim)", lineHeight: 1.6 }}
      >
        {transcript || "(no transcript)"}
      </pre>
    </motion.article>
  );
}
