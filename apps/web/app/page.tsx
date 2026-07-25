import Link from "next/link";

import { MachineView } from "@/components/MachineView";
import { ArrowRightIcon, EvidenceIcon, ShieldIcon, SplitIcon } from "@/components/ui/Icons";

/**
 * Hero.
 *
 * The thesis is the machine/human gap, so the page opens with that gap rather
 * than a claim about it. The URL input sits below the evidence, not above it —
 * someone arriving cold needs to understand what is being measured before being
 * asked to submit anything.
 */

const AXES = [
  { n: 1, name: "Machine-Readable Identity", pts: 15, note: "robots, sitemap, llms.txt, canonicals" },
  { n: 2, name: "Structured Data Coverage", pts: 20, note: "schema.org entities and their validity" },
  { n: 3, name: "Capability Exposure", pts: 25, note: "specs, manifests, stable discovery URLs" },
  { n: 4, name: "Content Extractability", pts: 15, note: "server-rendered vs hydration-only" },
  { n: 5, name: "Transactional Integrity", pts: 15, note: "stable IDs, structured pricing, forms" },
  { n: 6, name: "Agent Governance & Safety", pts: 10, note: "agent-aware terms, injection surface" },
];

const REFUSALS = [
  {
    Icon: SplitIcon,
    title: "Score with a model",
    body: "No model call returns a number. The rubric is a pure function over evidence, in a package that cannot import the model layer — enforced by walking the import graph in CI.",
  },
  {
    Icon: EvidenceIcon,
    title: "Ship an uncited capability",
    body: "A capability without evidence cannot be constructed. The critic rejects five named failure modes, and every rejection is published beside the successes.",
  },
  {
    Icon: ShieldIcon,
    title: "Generate a write tool",
    body: "Read-only tools only. State-changing capabilities are detected and reported, never emitted — generating a booking tool for a site we do not control is how this becomes an incident.",
  },
];

export default function Home(): React.ReactElement {
  return (
    <main className="mx-auto max-w-6xl px-6 pb-28">
      {/* --- hero --------------------------------------------------------- */}
      <section className="pt-16 md:pt-24">
        <p className="eyebrow">Agent-readiness index</p>

        <h1 className="display mt-6" style={{ maxWidth: "17ch" }}>
          Most sites are{" "}
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

      {/* --- the input, after the argument -------------------------------- */}
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
            className="input flex-1"
          />
          <button type="submit" className="btn btn-primary justify-center">
            Measure
            <ArrowRightIcon size={15} />
          </button>
        </form>
        <p className="mono mt-3" style={{ color: "var(--text-faint)" }}>
          Read-only · 0.5 req/s · robots-respecting ·{" "}
          <Link href="/crawler" style={{ color: "var(--signal)" }}>
            what the crawler does
          </Link>
        </p>
      </section>

      {/* --- the rubric ---------------------------------------------------- */}
      <section className="mt-28" aria-labelledby="rubric">
        <h2 id="rubric" className="eyebrow">
          100 points, six axes
        </h2>
        <ul className="m-0 mt-6 list-none p-0" style={{ borderTop: "1px solid var(--border)" }}>
          {AXES.map((axis) => (
            <li
              key={axis.n}
              className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-3.5"
              style={{ borderBottom: "1px solid var(--border)" }}
            >
              <span className="mono" style={{ color: "var(--text-faint)", width: "1.5rem" }}>
                {axis.n}
              </span>
              <span style={{ minWidth: "15rem", fontWeight: 500 }}>{axis.name}</span>
              <span className="mono flex-1" style={{ color: "var(--text-faint)" }}>
                {axis.note}
              </span>
              <span className="mono" style={{ color: "var(--signal)" }}>
                {axis.pts}
              </span>
            </li>
          ))}
        </ul>
        <p
          className="mono mt-5"
          style={{ color: "var(--text-faint)", maxWidth: "var(--measure)" }}
        >
          A scan that reaches fewer than 8 pages, or that is robots-blocked on more than
          30% of them, reports LOW CONFIDENCE with the grade band suppressed. A
          confident-looking score on thin evidence is worse than no score.
        </p>
      </section>

      {/* --- the refusal, stated as a feature ------------------------------ */}
      <section className="mt-28" aria-labelledby="refuses">
        <h2 id="refuses" className="eyebrow" style={{ color: "var(--refused)" }}>
          What it refuses to do
        </h2>
        <div className="mt-6 grid gap-5 md:grid-cols-3">
          {REFUSALS.map(({ Icon, title, body }) => (
            <article key={title} className="card p-5" style={{ boxShadow: "var(--shadow-raised)" }}>
              <span
                className="inline-flex h-9 w-9 items-center justify-center"
                style={{
                  background: "var(--refused-soft)",
                  color: "var(--refused)",
                  borderRadius: 3,
                }}
              >
                <Icon size={17} />
              </span>
              <h3 className="mt-4 text-base font-semibold">{title}</h3>
              <p className="mt-2 text-sm" style={{ color: "var(--text-dim)" }}>
                {body}
              </p>
            </article>
          ))}
        </div>
      </section>

      <hr className="rule mt-28" />

      <footer className="mono mt-8" style={{ color: "var(--text-faint)" }}>
        <p style={{ maxWidth: "var(--measure)" }}>
          Wasl AI is a research and portfolio project. Generated Agent Cards are unsigned
          and illustrative. Government entities are anonymised on the public leaderboard,
          and any entity is removed on request within 24 hours.
        </p>
        <p className="mt-5 flex gap-5">
          <Link href="/crawler" style={{ color: "var(--signal)" }}>
            crawler policy
          </Link>
          <a
            href="https://github.com/krish2105/Wasl-AI-"
            style={{ color: "var(--signal)" }}
            target="_blank"
            rel="noreferrer noopener"
          >
            source
          </a>
        </p>
      </footer>
    </main>
  );
}
