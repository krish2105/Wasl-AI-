import type { MetadataRoute } from "next";

/**
 * Wasl scores sites on whether they publish a legible robots.txt with an
 * explicit stance on AI crawlers. Shipping without one would be a poor look.
 *
 * The stance here is deliberate and permissive: this is a public research
 * project and there is nothing on it worth withholding from an agent. What it
 * demonstrates is the shape Axis 1 rewards — a named stanza rather than silence.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      { userAgent: "*", allow: "/" },
      // Named explicitly. Under our own rubric, an explicit stanza scores;
      // silence does not — regardless of whether it allows or disallows.
      { userAgent: "GPTBot", allow: "/" },
      { userAgent: "ClaudeBot", allow: "/" },
      { userAgent: "PerplexityBot", allow: "/" },
      { userAgent: "Google-Extended", allow: "/" },
      { userAgent: "CCBot", allow: "/" },
    ],
    sitemap: "https://wasl-ai-eight.vercel.app/sitemap.xml",
  };
}
