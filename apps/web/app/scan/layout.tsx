import type { Metadata } from "next";

/**
 * Metadata holder for the scan route.
 *
 * `app/scan/page.tsx` is a client component because it reads search params and
 * redirects, and Next only reads a `metadata` export from server components.
 * The layout is the nearest server boundary, so the title lives here rather
 * than being silently dropped.
 */

export const metadata: Metadata = {
  title: "Scan a site",
  description:
    "Submit a URL for an agent-readiness scan. Read-only, 0.5 requests per second, robots-respecting.",
};

export default function ScanLayout({
  children,
}: {
  children: React.ReactNode;
}): React.ReactElement {
  return <>{children}</>;
}
