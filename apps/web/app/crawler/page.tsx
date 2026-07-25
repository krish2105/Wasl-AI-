import type { Metadata } from "next";

/**
 * The page the crawler's User-Agent points at.
 *
 * This is not marketing. Its reader is a sysadmin who found `WaslAI-Research` in
 * their logs at 2am and wants to know what it did and how to stop it. So the
 * opt-out is the first thing on the page, above the explanation, and the limits
 * are stated as facts with the source file named — a claim someone can check
 * beats a promise they have to trust.
 */

export const metadata: Metadata = {
  title: "Crawler policy",
  description:
    "What the WaslAI-Research crawler fetches, how often, and how to opt out. Read-only, robots-respecting, 0.5 requests per second.",
};

/**
 * Falls back to a real GitHub issues URL rather than a placeholder address.
 *
 * This page exists so a site operator can make the crawler stop. Printing
 * `opt-out@wasl-ai.example` would give them a channel that silently discards
 * their request — worse than offering none, because it looks like one. The
 * issues tracker is public, monitored and actually works.
 */
const OPT_OUT_EMAIL = process.env.NEXT_PUBLIC_OPT_OUT_EMAIL || null;
const OPT_OUT_ISSUES = "https://github.com/krish2105/Wasl-AI-/issues/new?title=Crawler%20opt-out";

const facts: Array<{ label: string; value: string; note: string }> = [
  { label: "method", value: "GET only", note: "No POST, PUT, PATCH or DELETE. Ever." },
  { label: "rate", value: "0.5 req/s", note: "One request every two seconds, per domain." },
  { label: "volume", value: "12 / 40 pages", note: "12 per interactive scan, 40 per batch crawl." },
  { label: "scheme", value: "https only", note: "Plain http is refused." },
  { label: "assets", value: "blocked", note: "Images, fonts and media are never downloaded." },
  { label: "auth", value: "never", note: "No login, no credentials, no session." },
];

const never: string[] = [
  "Authenticate, or attempt to.",
  "Submit a form. POST forms are recorded as markup and left alone.",
  "Fetch /checkout, /cart, /login, /signin, /register, /account, /payment or /admin — regardless of what robots.txt permits.",
  "Bypass a paywall, CAPTCHA, bot wall or rate limit. If you block us, we record that you blocked us and move on.",
  "Probe for rate limits. Headers are read only when a server volunteers them during an ordinary crawl.",
  "Collect personal data. If any is encountered incidentally, it is not stored.",
];

export default function CrawlerPolicy(): React.ReactElement {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16 md:py-24">
      <p className="eyebrow">Wasl AI · crawler policy</p>

      <h1 className="display mt-6" style={{ fontSize: "clamp(2rem, 5vw, 3.5rem)" }}>
        You found <span style={{ color: "var(--signal)" }}>WaslAI-Research</span> in
        your logs.
      </h1>

      <p className="lede mt-6">
        Here is exactly what it did, and how to make it stop.
      </p>

      {/* Opt-out first. The reader who needs this page most needs this box. */}
      <section
        className="mt-10 p-6"
        style={{ background: "var(--ink-800)", borderLeft: "3px solid var(--refused)" }}
        aria-labelledby="opt-out"
      >
        <h2 id="opt-out" className="eyebrow" style={{ color: "var(--refused)" }}>
          Opt out
        </h2>
        <p className="mt-3" style={{ maxWidth: "var(--measure)" }}>
          {OPT_OUT_EMAIL ? (
            <>
              Email{" "}
              <a
                href={`mailto:${OPT_OUT_EMAIL}?subject=Wasl%20AI%20crawler%20opt-out`}
                className="mono underline"
                style={{ color: "var(--text)" }}
              >
                {OPT_OUT_EMAIL}
              </a>{" "}
              with your domain.
            </>
          ) : (
            <>
              <a
                href={OPT_OUT_ISSUES}
                className="mono underline"
                style={{ color: "var(--text)" }}
                target="_blank"
                rel="noreferrer noopener"
              >
                Open an issue
              </a>{" "}
              with your domain. A dedicated opt-out mailbox is not live yet, and printing
              an address that discards your request would be worse than printing none.
            </>
          )}{" "}
          Removal is applied within 24 hours, is permanent, and also removes any published
          score. You do not need to give a reason and we will not ask for one.
        </p>
        <p className="mt-4 text-sm" style={{ color: "var(--paper-dim)" }}>
          Or block us in <code className="mono">robots.txt</code> — honoured on the next
          crawl:
        </p>
        <pre className="evidence mt-3">{`User-agent: WaslAI-Research
Disallow: /`}</pre>
      </section>

      {/* --- what it does ---------------------------------------------------- */}

      <section className="mt-16" aria-labelledby="limits">
        <h2 id="limits" className="eyebrow">
          Limits
        </h2>
        <p className="mt-3" style={{ color: "var(--paper-dim)", maxWidth: "var(--measure)" }}>
          These are constants in{" "}
          <code className="mono">services/api/wasl/crawler/policy.py</code>, not
          configuration. There is no setting, environment variable or API parameter that
          raises them.
        </p>

        <dl className="mt-8 grid gap-px" style={{ background: "var(--border-strong)" }}>
          {facts.map((fact) => (
            <div
              key={fact.label}
              className="grid gap-2 p-4 sm:grid-cols-[9rem_9rem_1fr] sm:items-baseline"
              style={{ background: "var(--ink-900)" }}
            >
              <dt className="mono" style={{ color: "var(--paper-faint)" }}>
                {fact.label}
              </dt>
              <dd className="mono" style={{ color: "var(--signal)" }}>
                {fact.value}
              </dd>
              <dd className="text-sm" style={{ color: "var(--paper-dim)" }}>
                {fact.note}
              </dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="mt-16" aria-labelledby="never">
        <h2 id="never" className="eyebrow">
          What it never does
        </h2>
        <ul className="mt-6 space-y-4">
          {never.map((item) => (
            <li
              key={item}
              className="pl-5 text-sm"
              style={{
                color: "var(--paper-dim)",
                borderLeft: "1px solid var(--refused)",
                maxWidth: "var(--measure)",
              }}
            >
              {item}
            </li>
          ))}
        </ul>
      </section>

      {/* The counter-intuitive bit, given its own space because site operators
          consistently assume the opposite. */}
      <section className="mt-16" aria-labelledby="robots">
        <h2 id="robots" className="eyebrow">
          robots.txt
        </h2>
        <p className="mt-3" style={{ maxWidth: "var(--measure)" }}>
          <code className="mono">robots.txt</code> is authoritative. Disallowed paths are
          not fetched.
        </p>
        <p
          className="mt-5 p-5 text-base"
          style={{
            background: "var(--ink-800)",
            borderLeft: "3px solid var(--measured)",
            maxWidth: "var(--measure)",
          }}
        >
          <strong style={{ color: "var(--measured)" }}>
            A disallow does not lower your score.
          </strong>{" "}
          Wasl scores whether a site has made a legible decision about agent access. An
          explicit <code className="mono">User-agent: GPTBot / Disallow: /</code> stanza
          scores exactly the same as one that allows it — both are clear. Silence scores
          nothing. You are never penalised for telling automated clients to go away.
        </p>
      </section>

      <section className="mt-16" aria-labelledby="scope">
        <h2 id="scope" className="eyebrow">
          Which sites are crawled
        </h2>
        <p className="mt-3" style={{ color: "var(--paper-dim)", maxWidth: "var(--measure)" }}>
          Only two categories: domains on a reviewed list committed in the repository at{" "}
          <code className="mono">seeds/seed_urls.yaml</code>, and a domain a user submits
          through the web interface for a site they are checking themselves. There is no
          open crawl and no off-domain link following.
        </p>
        <p className="mt-4" style={{ color: "var(--paper-dim)", maxWidth: "var(--measure)" }}>
          An exclusion registry is checked <em>before</em> the allowlist, so an opt-out
          cannot be overridden by a later seed-list entry.
        </p>
      </section>

      <section className="mt-16" aria-labelledby="published">
        <h2 id="published" className="eyebrow">
          Published results
        </h2>
        <ul className="mt-6 space-y-3 text-sm" style={{ color: "var(--paper-dim)" }}>
          <li>Government and public-sector entities are anonymised by default.</li>
          <li>Commercial entities are named.</li>
          <li>Any entity is removed on request, within 24 hours, without argument.</li>
          <li>
            We publish scores, findings and short evidence snippets. We do not republish
            substantial content from any site.
          </li>
        </ul>
      </section>

      <hr className="rule mt-16" />

      <footer className="mt-8 text-sm" style={{ color: "var(--paper-faint)" }}>
        <p style={{ maxWidth: "var(--measure)" }}>
          Wasl AI is a research and portfolio project. It does not resell data. Not legal
          advice — this page describes what the software does, which is verifiable from
          the source.
        </p>
        <p className="mono mt-6">
          <a href="/" style={{ color: "var(--signal)" }}>
            ← back to wasl
          </a>
        </p>
      </footer>
    </main>
  );
}
