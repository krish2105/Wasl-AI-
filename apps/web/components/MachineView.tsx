"use client";

import { useEffect, useState } from "react";

/**
 * The signature moment: the pre-JS / post-JS delta, rendered rather than described.
 *
 * This is the measurement at the heart of Wasl — the gap between what a machine
 * receives and what a person sees. Showing it directly is a stronger opening
 * than a headline claiming it exists.
 *
 * The left pane holds what an agent without a browser actually gets from a
 * hydration-only site: a root div and a bundle reference. The right pane holds
 * what a person sees. The reader draws the conclusion themselves.
 *
 * Under `prefers-reduced-motion` both panes render resolved immediately — the
 * comparison is the point, not the transition.
 */

const MACHINE_LINES = [
  "<!doctype html>",
  '<html lang="en">',
  "  <head>",
  "    <title>Marsa Properties</title>",
  '    <script defer src="/main.8f2c91.js">',
  "  </head>",
  "  <body>",
  '    <div id="root"></div>',
  "    <noscript>You need to enable",
  "      JavaScript to run this app.</noscript>",
  "  </body>",
  "</html>",
];

const HUMAN_BLOCKS = [
  { kind: "title", text: "Waterfront Apartments in Dubai Marina" },
  { kind: "body", text: "3 listings · verified by the brokerage · updated daily" },
  { kind: "card", text: "2 Bedroom, Marina Gate Tower 1 — AED 2,850,000" },
  { kind: "card", text: "1 Bedroom, Bluewaters Residences 4 — AED 2,100,000" },
  { kind: "card", text: "3 Bedroom, JBR Sadaf 6 — AED 4,400,000" },
];

export function MachineView(): React.ReactElement {
  const [revealed, setRevealed] = useState(0);

  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setRevealed(HUMAN_BLOCKS.length);
      return;
    }
    const timers = HUMAN_BLOCKS.map((_, index) =>
      window.setTimeout(() => setRevealed((n) => Math.max(n, index + 1)), 420 + index * 130),
    );
    return () => timers.forEach(window.clearTimeout);
  }, []);

  return (
    <figure className="m-0 mt-14">
      <div
        className="grid gap-px md:grid-cols-2"
        style={{ background: "rgba(237,233,227,0.12)", border: "var(--rule)" }}
      >
        {/* --- what an agent receives -------------------------------------- */}
        <div className="p-5" style={{ background: "var(--ink-800)" }}>
          <p className="eyebrow" style={{ color: "var(--refused)" }}>
            What an agent receives
          </p>
          <pre
            className="mono mt-4 overflow-x-auto"
            style={{ color: "var(--paper-faint)", lineHeight: 1.65 }}
          >
            {MACHINE_LINES.join("\n")}
          </pre>
          <p className="mono mt-4" style={{ color: "var(--refused)" }}>
            0 products · 0 prices · 0 identifiers
          </p>
        </div>

        {/* --- what a person sees ------------------------------------------ */}
        <div className="p-5" style={{ background: "var(--ink-800)" }}>
          <p className="eyebrow" style={{ color: "var(--measured)" }}>
            What a person sees
          </p>
          <div className="mt-4 space-y-3" style={{ minHeight: "13rem" }}>
            {HUMAN_BLOCKS.map((block, index) => (
              <p
                key={block.text}
                className={index < revealed ? "resolve" : ""}
                style={{
                  opacity: index < revealed ? 1 : 0,
                  animationDelay: `${index * 60}ms`,
                  fontSize: block.kind === "title" ? "1.05rem" : "0.85rem",
                  fontWeight: block.kind === "title" ? 600 : 400,
                  color:
                    block.kind === "card"
                      ? "var(--paper-dim)"
                      : block.kind === "body"
                        ? "var(--paper-faint)"
                        : "var(--paper)",
                  paddingLeft: block.kind === "card" ? "0.75rem" : 0,
                  borderLeft: block.kind === "card" ? "1px solid var(--ink-500)" : "none",
                }}
              >
                {block.text}
              </p>
            ))}
          </div>
          <p className="mono mt-4" style={{ color: "var(--measured)" }}>
            3 listings · 3 prices · 0 identifiers
          </p>
        </div>
      </div>

      <figcaption
        className="mono mt-4"
        style={{ color: "var(--paper-faint)", maxWidth: "var(--measure)" }}
      >
        Same URL, same moment. The left pane is the raw HTTP response; the right is the
        DOM after hydration. Wasl measures the ratio between them — 0.02 here — and that
        single number says more about agent-readiness than any other signal on the page.
      </figcaption>
    </figure>
  );
}
