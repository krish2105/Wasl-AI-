"use client";

import { motion, useReducedMotion } from "motion/react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

/**
 * Theme toggle: a sun that draws itself and a moon that draws itself.
 *
 * The transition is a path-length draw rather than a crossfade, which reads as
 * an instrument re-calibrating rather than a widget flipping — consistent with
 * the rest of the interface. Under `prefers-reduced-motion` both morphs become
 * instant state changes.
 *
 * Renders a fixed-size placeholder before mount. `resolvedTheme` is unknown
 * during SSR, and rendering the wrong icon then correcting it produces both a
 * hydration warning and a visible flicker in the corner of every page.
 */
export function ThemeToggle({ className = "" }: { className?: string }): React.ReactElement {
  const { setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const reduced = useReducedMotion();

  useEffect(() => setMounted(true), []);

  const isDark = mounted ? resolvedTheme !== "light" : true;
  const duration = reduced ? 0 : 0.55;

  if (!mounted) {
    return (
      <span
        className={`inline-flex h-9 w-9 items-center justify-center ${className}`}
        aria-hidden
        style={{ border: "1px solid var(--border)", borderRadius: 3 }}
      />
    );
  }

  return (
    <button
      type="button"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      title={isDark ? "Light theme" : "Dark theme"}
      className={`inline-flex h-9 w-9 items-center justify-center transition-colors ${className}`}
      style={{
        background: "transparent",
        border: "1px solid var(--border)",
        borderRadius: 3,
        color: "var(--text-dim)",
        cursor: "pointer",
      }}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
        {/* sun: core plus eight rays, drawn on the way to light */}
        <motion.circle
          cx="12"
          cy="12"
          r="4.2"
          stroke="currentColor"
          strokeWidth="1.7"
          animate={{ scale: isDark ? 0 : 1, opacity: isDark ? 0 : 1 }}
          transition={{ duration }}
          style={{ transformOrigin: "center" }}
        />
        {[
          "M12 2.4v2.2",
          "M12 19.4v2.2",
          "M2.4 12h2.2",
          "M19.4 12h2.2",
          "M5.2 5.2l1.55 1.55",
          "M17.25 17.25l1.55 1.55",
          "M5.2 18.8l1.55-1.55",
          "M17.25 6.75l1.55-1.55",
        ].map((d, i) => (
          <motion.path
            key={d}
            d={d}
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinecap="round"
            animate={{ pathLength: isDark ? 0 : 1, opacity: isDark ? 0 : 1 }}
            transition={{ duration, delay: reduced ? 0 : 0.035 * i }}
          />
        ))}

        {/* moon: one path, drawn on the way to dark */}
        <motion.path
          d="M20.5 13.4A8.6 8.6 0 1 1 10.6 3.5a6.7 6.7 0 0 0 9.9 9.9z"
          stroke="currentColor"
          strokeWidth="1.7"
          strokeLinecap="round"
          strokeLinejoin="round"
          animate={{ pathLength: isDark ? 1 : 0, opacity: isDark ? 1 : 0 }}
          transition={{ duration }}
        />
      </svg>
    </button>
  );
}
