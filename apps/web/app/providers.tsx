"use client";

import { ThemeProvider } from "next-themes";

/**
 * `value` maps the theme name to a class rather than relying on the default,
 * because next-themes writes `light`/`dark` and Tailwind's class strategy plus
 * our own `.light` / `.dark` token blocks both need the explicit name on <html>.
 *
 * `disableTransitionOnChange` stops every border and text colour on the page
 * from animating at once during a swap — the body handles the shell transition
 * on its own, and letting the rest follow looks like a rendering fault.
 *
 * `defaultTheme="system"` rather than `"dark"`: `enableSystem` only permits the
 * system option, it does not select it, so an explicit default silently wins on
 * a first visit. The dark palette is still the one designed first — it is just
 * no longer imposed on someone whose OS says otherwise. A stored choice from the
 * toggle continues to override the system, which is the behaviour a person
 * expects after having picked one.
 *
 * This also settles a disagreement with the browser: `viewport.themeColor` in
 * layout.tsx is keyed on `prefers-color-scheme`, so a light-OS visitor used to
 * get light browser chrome wrapped around a dark page.
 */
export function Providers({ children }: { children: React.ReactNode }): React.ReactElement {
  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
      value={{ light: "light", dark: "dark" }}
    >
      {children}
    </ThemeProvider>
  );
}
