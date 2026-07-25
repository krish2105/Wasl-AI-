"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useRef } from "react";

import type { Check, Evidence } from "@/lib/scan";

/**
 * The evidence drawer: click a sub-score, see the exact markup behind it.
 *
 * This component is the project's central claim made touchable. Everything else
 * asserts that scores are grounded; this is where a sceptic checks. So the
 * snippet is shown verbatim and untruncated, with its source URL, its DOM
 * selector, and which capture phase it came from — pre-JS or post-JS, which for
 * this product is a meaningful distinction rather than a technicality.
 *
 * Standard dialog obligations: focus moves in, Escape closes, the backdrop
 * closes, and focus is not trapped in a way that strands a keyboard user.
 */

export function EvidenceDrawer({
  check,
  evidence,
  onClose,
}: {
  check: Check;
  evidence: Evidence[];
  onClose: () => void;
}): React.ReactElement {
  const reduced = useReducedMotion();
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose]);

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-50 flex justify-end"
        initial={reduced ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.18 }}
      >
        <button
          type="button"
          aria-label="Close evidence"
          onClick={onClose}
          className="absolute inset-0"
          style={{ background: "rgba(5,11,16,0.72)", border: 0, cursor: "pointer" }}
        />

        <motion.div
          ref={panelRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby="evidence-title"
          className="relative flex h-full w-full max-w-2xl flex-col overflow-y-auto"
          style={{ background: "var(--ink-900)", borderLeft: "var(--rule-strong)" }}
          initial={reduced ? false : { x: 32, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 32, opacity: 0 }}
          transition={{ duration: reduced ? 0 : 0.26, ease: [0.2, 0.7, 0.2, 1] }}
        >
          <header
            className="sticky top-0 flex items-start justify-between gap-6 p-6"
            style={{ background: "var(--ink-900)", borderBottom: "var(--rule)" }}
          >
            <div>
              <p className="eyebrow">Evidence</p>
              <h2 id="evidence-title" className="mt-2 text-lg font-semibold">
                {check.label}
              </h2>
              <p className="mono mt-2" style={{ color: "var(--paper-faint)" }}>
                {check.check_id} ·{" "}
                {check.suppressed
                  ? "not evaluated"
                  : `${check.points_awarded}/${check.max_points} points`}
              </p>
            </div>
            <button
              ref={closeRef}
              type="button"
              onClick={onClose}
              className="mono px-3 py-1"
              style={{ background: "var(--ink-700)", border: 0, color: "var(--paper)", cursor: "pointer" }}
            >
              close
            </button>
          </header>

          <div className="p-6">
            {(check.suppressed_reason || check.detail) && (
              <p style={{ color: "var(--paper-dim)", maxWidth: "var(--measure)" }}>
                {check.suppressed_reason ?? check.detail}
              </p>
            )}

            <p className="eyebrow mt-8">
              {evidence.length} source{evidence.length === 1 ? "" : "s"}
            </p>

            {evidence.length === 0 && (
              <p className="mono mt-3" style={{ color: "var(--paper-faint)" }}>
                This check cited no evidence — which for an awarded check would be a bug,
                and is why the eval harness gates on citation validity.
              </p>
            )}

            <ol className="m-0 mt-4 list-none space-y-6 p-0">
              {evidence.map((item) => (
                <li key={item.id}>
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <span className="mono" style={{ color: "var(--signal)" }}>
                      {item.id}
                    </span>
                    <span className="mono" style={{ color: "var(--paper-faint)" }}>
                      {item.kind}
                    </span>
                    <span
                      className="mono"
                      style={{
                        color: item.phase === "post_js" ? "var(--band-emerging)" : "var(--paper-faint)",
                      }}
                      title={
                        item.phase === "post_js"
                          ? "Found only after JavaScript ran"
                          : "Present in the raw response"
                      }
                    >
                      {item.phase}
                    </span>
                  </div>

                  {item.selector && (
                    <p className="mono mt-1" style={{ color: "var(--paper-faint)", wordBreak: "break-all" }}>
                      {item.selector}
                    </p>
                  )}

                  <pre className="evidence mt-2">{item.raw}</pre>

                  <a
                    href={item.source_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="mono mt-2 inline-block"
                    style={{ color: "var(--signal)", wordBreak: "break-all" }}
                  >
                    {item.source_url} ↗
                  </a>
                </li>
              ))}
            </ol>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
