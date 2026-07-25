"use client";

import { motion, useReducedMotion } from "motion/react";
import { useState } from "react";

import type { Axis, Check, Evidence } from "@/lib/scan";

import { EvidenceDrawer } from "./EvidenceDrawer";

/**
 * The six axes, expandable to individual checks.
 *
 * Every check that awarded points is clickable and opens the evidence that
 * justified it. That is the whole credibility argument made interactive: a
 * reviewer who doubts a number can reach the markup behind it in one click.
 *
 * Suppressed checks are visually distinct from failed ones. Collapsing "we could
 * not evaluate this" into "this scored zero" is the single most misleading thing
 * this component could do.
 */

export function AxisBreakdown({
  axes,
  evidence,
}: {
  axes: Axis[];
  evidence: Evidence[];
}): React.ReactElement {
  const [open, setOpen] = useState<number | null>(axes[0]?.number ?? null);
  const [drawer, setDrawer] = useState<Check | null>(null);
  const reduced = useReducedMotion();

  const byId = new Map(evidence.map((e) => [e.id, e]));

  return (
    <>
      <div style={{ borderTop: "var(--rule)" }}>
        {axes.map((axis) => {
          const expanded = open === axis.number;
          const pct = axis.max_points ? axis.points / axis.max_points : 0;

          return (
            <section key={axis.number} style={{ borderBottom: "var(--rule)" }}>
              <h3 className="m-0">
                <button
                  type="button"
                  onClick={() => setOpen(expanded ? null : axis.number)}
                  aria-expanded={expanded}
                  className="flex w-full items-center gap-4 py-4 text-left"
                  style={{ background: "none", border: 0, color: "inherit", cursor: "pointer" }}
                >
                  <span className="mono" style={{ color: "var(--paper-faint)", width: "1.2rem" }}>
                    {axis.number}
                  </span>
                  <span className="flex-1 font-medium">{axis.name}</span>

                  {/* Bar carries the ratio; the number carries the detail. */}
                  <span
                    aria-hidden
                    style={{
                      width: "6rem",
                      height: 4,
                      background: "var(--ink-600)",
                      position: "relative",
                    }}
                  >
                    <motion.span
                      initial={reduced ? false : { scaleX: 0 }}
                      animate={{ scaleX: pct }}
                      transition={{ duration: reduced ? 0 : 0.7, ease: [0.2, 0.7, 0.2, 1] }}
                      style={{
                        display: "block",
                        height: "100%",
                        background: pct > 0.6 ? "var(--measured)" : pct > 0 ? "var(--signal)" : "var(--refused)",
                        transformOrigin: "left",
                      }}
                    />
                  </span>

                  <span className="mono" style={{ width: "4.5rem", textAlign: "right" }}>
                    {axis.points}
                    <span style={{ color: "var(--paper-faint)" }}>/{axis.max_points}</span>
                  </span>
                  <span className="mono" style={{ color: "var(--paper-faint)" }} aria-hidden>
                    {expanded ? "−" : "+"}
                  </span>
                </button>
              </h3>

              {expanded && (
                <ul className="m-0 list-none px-0 pb-4 pl-9">
                  {axis.checks.map((check) => (
                    <CheckRow
                      key={check.check_id}
                      check={check}
                      onOpen={() => setDrawer(check)}
                    />
                  ))}
                </ul>
              )}
            </section>
          );
        })}
      </div>

      {drawer && (
        <EvidenceDrawer
          check={drawer}
          evidence={drawer.evidence_refs.map((id) => byId.get(id)).filter(Boolean) as Evidence[]}
          onClose={() => setDrawer(null)}
        />
      )}
    </>
  );
}

function CheckRow({ check, onOpen }: { check: Check; onOpen: () => void }) {
  const full = !check.suppressed && check.points_awarded === check.max_points;
  const partial = !check.suppressed && check.points_awarded > 0 && !full;

  const marker = check.suppressed ? "~" : full ? "+" : partial ? "±" : "−";
  const colour = check.suppressed
    ? "var(--paper-faint)"
    : full
      ? "var(--measured)"
      : partial
        ? "var(--signal)"
        : "var(--refused)";

  const clickable = check.evidence_refs.length > 0;

  const body = (
    <>
      <span className="mono" aria-hidden style={{ color: colour, width: "1rem" }}>
        {marker}
      </span>
      <span className="flex-1" style={{ color: check.suppressed ? "var(--paper-faint)" : "var(--paper-dim)" }}>
        {check.label}
        {check.suppressed && (
          <span className="mono" style={{ color: "var(--paper-faint)" }}>
            {" "}
            — not evaluated
          </span>
        )}
      </span>
      <span className="mono" style={{ color: colour, width: "3rem", textAlign: "right" }}>
        {check.suppressed ? "—" : `${check.points_awarded}/${check.max_points}`}
      </span>
      {clickable && (
        <span className="mono" style={{ color: "var(--signal)", width: "5.5rem", textAlign: "right" }}>
          {check.evidence_refs.length} evidence
        </span>
      )}
    </>
  );

  return (
    <li className="text-sm" style={{ borderTop: "var(--rule)" }}>
      {clickable ? (
        <button
          type="button"
          onClick={onOpen}
          className="flex w-full items-baseline gap-3 py-2.5 text-left"
          style={{ background: "none", border: 0, color: "inherit", cursor: "pointer" }}
        >
          {body}
        </button>
      ) : (
        <div className="flex items-baseline gap-3 py-2.5">{body}</div>
      )}
      {(check.suppressed_reason || check.detail) && (
        <p
          className="mono pb-2.5 pl-7"
          style={{ color: "var(--paper-faint)", maxWidth: "var(--measure)" }}
        >
          {check.suppressed_reason ?? check.detail}
        </p>
      )}
    </li>
  );
}
