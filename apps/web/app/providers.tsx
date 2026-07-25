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
 */
export function Providers({ children }: { children: React.ReactNode }): React.ReactElement {
  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="dark"
      enableSystem
      disableTransitionOnChange
      value={{ light: "light", dark: "dark" }}
    >
      {children}
    </ThemeProvider>
  );
}
