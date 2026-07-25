"use client";

import { motion, useReducedMotion } from "motion/react";

import { BAND_COLOUR, type Score } from "@/lib/scan";

/**
 * The score, as an instrument dial.
 *
 * Two things this has to get right, both of which a generic gauge would fumble:
 *
 * A **suppressed band** must read as "we declined to say", not as a bad grade.
 * So the arc renders in a neutral tone with a dashed track, and the reason is
 * shown rather than hidden behind a tooltip.
 *
 * A **reduced denominator** must be visible. When checks are suppressed the
 * total is out of less than 100, and quietly showing "67" without the "/97"
 * would overstate the measurement.
 *
 * No layout shift on reveal: the SVG reserves its full size immediately and only
 * the stroke animates.
 */

const SIZE = 260;
const STROKE = 14;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
// Three-quarter dial — a full circle reads as a loading spinner.
const SWEEP = 0.75;

export function RadialScore({ score }: { score: Score }): React.ReactElement {
  const reduced = useReducedMotion();
  const suppressed = score.band === null;
  const fraction = Math.max(0, Math.min(1, score.percentage / 100));

  const colour = suppressed
    ? "var(--paper-faint)"
    : (BAND_COLOUR[score.band ?? ""] ?? "var(--signal)");

  return (
    <figure className="m-0 flex flex-col items-center">
      <svg
        width={SIZE}
        height={SIZE}
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="img"
        aria-label={`WARI score ${score.total} out of ${score.max_possible}${
          suppressed ? ", grade band suppressed" : `, band ${score.band}`
        }`}
        style={{ transform: "rotate(135deg)" }}
      >
        {/* Track. A dashed track signals "measurement incomplete" before you
            read a word; a solid one means the dial is fully calibrated. */}
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          stroke="var(--ink-600)"
          strokeWidth={STROKE}
          strokeLinecap="butt"
          strokeDasharray={
            suppressed ? "5 9" : `${CIRCUMFERENCE * SWEEP} ${CIRCUMFERENCE}`
          }
        />
        <motion.circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          stroke={colour}
          strokeWidth={STROKE}
          strokeLinecap="butt"
          strokeDasharray={`${CIRCUMFERENCE} ${CIRCUMFERENCE}`}
          initial={reduced ? false : { strokeDashoffset: CIRCUMFERENCE }}
          animate={{ strokeDashoffset: CIRCUMFERENCE * (1 - fraction * SWEEP) }}
          transition={{ duration: reduced ? 0 : 1.1, ease: [0.2, 0.7, 0.2, 1] }}
        />
      </svg>

      {/* Absolutely positioned readout would risk layout shift; stack instead. */}
      <figcaption className="-mt-40 flex flex-col items-center text-center">
        <span
          className="mono"
          style={{ fontSize: "3rem", lineHeight: 1, color: "var(--paper)" }}
        >
          {score.total}
        </span>
        <span className="mono mt-1" style={{ color: "var(--paper-faint)" }}>
          / {score.max_possible}
        </span>
        <span
          className="eyebrow mt-5"
          style={{ color: suppressed ? "var(--paper-faint)" : colour, letterSpacing: "0.2em" }}
        >
          {suppressed ? "band suppressed" : score.band}
        </span>
      </figcaption>

      {score.max_possible !== 100 && (
        <p className="mono mt-14 text-center" style={{ color: "var(--paper-faint)", maxWidth: "26rem" }}>
          Denominator reduced from 100: checks that could not be evaluated are excluded
          rather than scored zero.
        </p>
      )}
    </figure>
  );
}
