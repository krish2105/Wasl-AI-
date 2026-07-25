import type { MetadataRoute } from "next";

/**
 * Only the four routes that exist without a backend. `/scan/[jobId]` is
 * per-job and ephemeral, so listing it would advertise URLs that 404 — which is
 * exactly the sitemap failure Axis 1 penalises other sites for.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const base = "https://wasl-ai-eight.vercel.app";
  const lastModified = new Date();

  return [
    { url: base, lastModified, changeFrequency: "weekly", priority: 1 },
    { url: `${base}/crawler`, lastModified, changeFrequency: "monthly", priority: 0.8 },
    { url: `${base}/scan`, lastModified, changeFrequency: "weekly", priority: 0.6 },
    { url: `${base}/leaderboard`, lastModified, changeFrequency: "weekly", priority: 0.6 },
  ];
}
