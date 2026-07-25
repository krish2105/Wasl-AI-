import { RULE_LABEL, type Rejection } from "@/lib/scan";

/**
 * What we refused to generate.
 *
 * Given equal weight to the accepted capabilities, not tucked into a details
 * element. A system that shows what it declined is more credible than one that
 * shows only successes, and this panel is the cheapest credibility in the
 * product — but only if it is visible enough to be read.
 *
 * An empty state still renders. "Nothing was refused" is a real result, and
 * hiding the panel entirely would make a reviewer wonder whether the critic ran.
 */

export function RefusedPanel({ rejections }: { rejections: Rejection[] }): React.ReactElement {
  return (
    <section aria-labelledby="refused">
      <h2 id="refused" className="eyebrow" style={{ color: "var(--refused)" }}>
        What we refused to generate
      </h2>

      {rejections.length === 0 ? (
        <p className="mono mt-4" style={{ color: "var(--paper-faint)", maxWidth: "var(--measure)" }}>
          The critic accepted every candidate on this scan. Nothing was refused — which is
          reported rather than left blank, so it is clear the review ran.
        </p>
      ) : (
        <>
          <p className="mt-3" style={{ color: "var(--paper-dim)", maxWidth: "var(--measure)" }}>
            Each of these was proposed and then rejected against a named rule. They are
            not in the generated server, the Agent Card or the llms.txt.
          </p>

          <ul className="m-0 mt-6 list-none p-0" style={{ borderTop: "var(--rule)" }}>
            {rejections.map((rejection, index) => (
              <li
                key={`${rejection.capability_name}-${index}`}
                className="py-4"
                style={{ borderBottom: "var(--rule)" }}
              >
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="mono" style={{ color: "var(--paper)" }}>
                    {rejection.capability_name}
                  </span>
                  <span
                    className="mono px-2"
                    style={{
                      color: "var(--refused)",
                      border: "1px solid var(--refused)",
                      fontSize: "0.68rem",
                    }}
                  >
                    {rejection.rule_id}
                  </span>
                  {rejection.final && (
                    <span className="mono" style={{ color: "var(--paper-faint)" }}>
                      final
                    </span>
                  )}
                </div>

                <p className="mono mt-1" style={{ color: "var(--paper-faint)" }}>
                  {RULE_LABEL[rejection.rule_id] ?? rejection.rule_id}
                </p>

                <p className="mt-2 text-sm" style={{ color: "var(--paper-dim)", maxWidth: "var(--measure)" }}>
                  {rejection.reason}
                </p>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
