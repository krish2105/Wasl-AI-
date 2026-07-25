import type { Metadata, Viewport } from "next";
import { Archivo, Inter, JetBrains_Mono } from "next/font/google";

import { SiteNav } from "@/components/ui/SiteNav";

import "./globals.css";
import { Providers } from "./providers";

/**
 * Three faces, three jobs.
 *
 * Archivo is a grotesque with enough width and weight to carry a display line
 * without tipping into fashion-serif territory. Inter reads at small sizes.
 * JetBrains Mono is not decoration here — evidence snippets, DOM selectors and
 * content-addressed IDs are the actual material of this product, and they need a
 * face where `l`, `1` and `I` are distinguishable.
 */
const archivo = Archivo({
  subsets: ["latin"],
  weight: ["600", "700", "800"],
  variable: "--font-archivo",
  display: "swap",
});

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://wasl-ai.vercel.app"),
  title: {
    default: "Wasl AI — agent-readiness index",
    template: "%s — Wasl AI",
  },
  description:
    "Scores whether a business is legible to AI agents on a 100-point index, then generates the MCP server that makes it legible. Deterministic scoring, cited evidence, published refusals.",
  applicationName: "Wasl AI",
  openGraph: {
    title: "Wasl AI — agent-readiness index",
    description:
      "Most sites are invisible to agents. Wasl measures how invisible, with evidence for every point.",
    type: "website",
  },
  icons: {
    icon: [{ url: "/icon.svg", type: "image/svg+xml" }],
    apple: [{ url: "/icon.svg" }],
  },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0b1620" },
    { media: "(prefers-color-scheme: light)", color: "#fbfaf8" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>): React.ReactElement {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${archivo.variable} ${inter.variable} ${jetbrains.variable}`}
    >
      <body className="min-h-screen antialiased">
        <Providers>
          <a href="#main" className="sr-only focus:not-sr-only">
            Skip to content
          </a>
          <SiteNav />
          <div id="main">{children}</div>
        </Providers>
      </body>
    </html>
  );
}
