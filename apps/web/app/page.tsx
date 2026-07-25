import Link from "next/link";

import { MachineView } from "@/components/MachineView";

/**
 * Hero.
 *
 * The thesis is the machine/human gap, so it opens with that gap rather than a
 * claim about it. The URL input sits below the evidence, not above it — someone
 * arriving cold needs to understand what is being measured before being asked
 * to submit anything.
 */

const AXES = [
  { n: 1, name: "Machine-Readable Identity", pts: 15 },
  { n: 2, name: "Structured Data Coverage", pts: 20 },
  { n: 3, name: "Capability Exposure", pts: 25 },
  { n: 4, name: "Content Extractability", pts: 15 },
  { n: 5, name: "Transactional Integrity", pts: 15 },
  { n: 6, name: "Agent Governance & Safety", pts: 10 },
];

export default function Home(): React.ReactElement {
  return (
    <>
      <header className="mx-auto flex max-w-5xl items-baseline justify-between px-6 py-6">
        <span className="mono" style={{ letterSpacing: "0.18em" }}>
          WASL
        </span>
        <nav className="mono flex gap-6" style={{ color: "var(--paper-faint)" }}>
          <Link href="/leaderboard">leaderboard</Link>
          <Link href="/crawler">crawler</Link>
        </nav>
      </header>

      <main className="mx-auto max-w-5xl px-6 pb-24">
        <section className="pt-10 md:pt-16">
          <p className="eyebrow">Agent-readiness index</p>

          <h1 className="display mt-6" style={{ maxWidth: "16ch" }}>
            Most sites are
            <br />
            <span style={{ color: "var(--refused)" }}>invisible</span> to agents.
          </h1>

          <p className="lede mt-7">
            Wasl scores whether a business is legible to AI agents, then generates the MCP
            server that makes it legible. The score is a deterministic function over
            evidence — models propose capabilities and explain findings, but every claim
            cites the markup that justifies it, and anything uncited is refused.
          </p>

          <MachineView />
        </section>

        {/* --- the input, after the argument ------------------------------- */}
        <section className="mt-20" aria-labelledby="scan">
          <h2 id="scan" className="eyebrow">
            Scan a site
          </h2>
          <form className="mt-5 flex flex-col gap-3 sm:flex-row" action="/scan" method="get">
            <label htmlFor="url" className="sr-only">
              Site URL
            </label>
            <input
              id="url"
              name="url"
              type="url"
              required
              placeholder="https://example.ae"
              className="mono flex-1 px-4 py-3"
              style={{
                background: "var(--ink-800)",
                border: "var(--rule-strong)",
                color: "var(--paper)",
              }}
            />
            <button
              type="submit"
              className="mono px-6 py-3"
              style={{ background: "var(--signal)", color: "var(--ink-900)", fontWeight: 600 }}
            >
              Measure
            </button>
          </form>
          <p className="mono mt-3" style={{ color: "var(--paper-faint)" }}>
            Read-only · 0.5 req/s · robots-respecting ·{" "}
            <Link href="/crawler" style={{ color: "var(--signal)" }}>
              what the crawler does
            </Link>
          </p>
        </section>

        {/* --- the rubric --------------------------------------------------- */}
        <section className="mt-24" aria-labelledby="rubric">
          <h2 id="rubric" className="eyebrow">
            100 points, six axes
          </h2>
          <ul className="mt-6" style={{ borderTop: "var(--rule)" }}>
            {AXES.map((axis) => (
              <li
                key={axis.n}
                className="flex items-baseline gap-4 py-3"
                style={{ borderBottom: "var(--rule)" }}
              >
                <span className="mono" style={{ color: "var(--paper-faint)", width: "1.5rem" }}>
                  {axis.n}
                </span>
                <span className="flex-1">{axis.name}</span>
                <span className="mono" style={{ color: "var(--signal)" }}>
                  {axis.pts}
                </span>
              </li>
            ))}
          </ul>
          <p className="mono mt-5" style={{ color: "var(--paper-faint)", maxWidth: "var(--measure)" }}>
            A scan that reaches fewer than 8 pages, or that is robots-blocked on more than
            30% of them, reports LOW CONFIDENCE with the grade band suppressed. A
            confident-looking score on thin evidence is worse than no score.
          </p>
        </section>

        {/* --- the refusal, stated as a feature ----------------------------- */}
        <section className="mt-24" aria-labelledby="refuses">
          <h2 id="refuses" className="eyebrow" style={{ color: "var(--refused)" }}>
            What it refuses to do
          </h2>
          <div className="mt-6 grid gap-6 md:grid-cols-3">
            {[
              {
                title: "Score with a model",
                body: "No model call returns a number. The rubric is a pure function over evidence, in a package that cannot import the model layer — enforced by walking the import graph in CI.",
              },
              {
                title: "Ship an uncited capability",
                body: "A capability without evidence cannot be constructed. The critic rejects five named failure modes, and every rejection is published alongside the successes.",
              },
              {
                title: "Generate a write tool",
                body: "Read-only tools only. State-changing capabilities are detected and reported, never emitted — generating a booking tool for a site we do not control is how this becomes an incident.",
              },
            ].map((card) => (
              <article
                key={card.title}
                className="p-5"
                style={{ background: "var(--ink-800)", borderTop: "2px solid var(--refused)" }}
              >
                <h3 className="text-base font-semibold">{card.title}</h3>
                <p className="mt-3 text-sm" style={{ color: "var(--paper-dim)" }}>
                  {card.body}
                </p>
              </article>
            ))}
          </div>
        </section>

        <hr className="rule mt-24" />

        <footer className="mono mt-8" style={{ color: "var(--paper-faint)" }}>
          <p style={{ maxWidth: "var(--measure)" }}>
            Wasl AI is a research and portfolio project. Generated Agent Cards are
            unsigned and illustrative. Government entities are anonymised on the public
            leaderboard, and any entity is removed on request within 24 hours.
          </p>
          <p className="mt-5">
            <Link href="/crawler" style={{ color: "var(--signal)" }}>
              crawler policy
            </Link>
          </p>
        </footer>
      </main>
    </>
  );
}
