import Link from "next/link";

/**
 * Leaderboard shell.
 *
 * Deliberately empty until the batch crawl has run. Publishing placeholder
 * scores next to real company names — even obviously fake ones — is exactly the
 * kind of thing that gets screenshotted out of context.
 */
export default function Leaderboard(): React.ReactElement {
  return (
    <main className="mx-auto max-w-5xl px-6 py-16">
      <p className="eyebrow">Leaderboard</p>

      <h1 className="display mt-6" style={{ fontSize: "clamp(2rem, 5vw, 3.5rem)" }}>
        Not yet published.
      </h1>

      <p className="lede mt-6">
        The leaderboard ranks seeded companies by WARI score. It stays empty until the
        batch crawl has actually run — placeholder scores beside real company names are
        not worth shipping, even temporarily.
      </p>

      <div
        className="mt-10 p-5"
        style={{ background: "var(--ink-800)", borderLeft: "3px solid var(--signal)" }}
      >
        <p className="eyebrow">When it publishes</p>
        <ul className="mono mt-4 space-y-2" style={{ color: "var(--paper-dim)" }}>
          <li>Government and public-sector entities appear anonymised, by sector and band.</li>
          <li>Commercial entities are named.</li>
          <li>Any entity is removed on request, within 24 hours, without argument.</li>
          <li>Sites that block the crawler are shown as blocked — that is a finding, not a gap.</li>
        </ul>
      </div>

      <p className="mono mt-10">
        <Link href="/" style={{ color: "var(--signal)" }}>
          ← wasl.ai
        </Link>
      </p>
    </main>
  );
}
