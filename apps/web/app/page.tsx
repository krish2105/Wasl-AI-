/**
 * Phase 1 placeholder.
 *
 * The real hero — kinetic headline, URL input, example chips, one orchestrated
 * entrance — is built in Phase 7, after the frontend-design direction pass. This
 * page exists so `pnpm dev` serves something and the shell is verifiably wired,
 * not to sketch the design early.
 */
export default function Home(): React.ReactElement {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-6 px-6 py-24">
      <p className="text-sm uppercase tracking-widest opacity-50">Wasl AI</p>
      <h1 className="text-4xl font-semibold leading-tight">
        Scores whether a business is legible to AI agents, then generates the MCP
        server that makes it legible.
      </h1>
      <p className="text-base opacity-70">
        Phase 1 of 8 — skeleton and infrastructure. The interface is built in
        Phase 7, after the evaluation harness exists.
      </p>
      <div className="rounded-lg border border-white/10 p-4 text-sm opacity-60">
        <p className="mb-2 font-medium opacity-100">Build order</p>
        <p>
          Crawler and evidence extraction, then the deterministic scoring rubric,
          then the agent graph, then the generators, then the eval harness — and
          only then the UI. Building the interface first is how you end up with a
          system you cannot defend.
        </p>
      </div>
    </main>
  );
}
