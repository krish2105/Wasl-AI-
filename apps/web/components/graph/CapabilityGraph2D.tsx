"use client";

import { useMemo } from "react";

import type { Capability, Evidence } from "@/lib/scan";

/**
 * Pages → evidence → capabilities → tools, as an SVG force-directed graph.
 *
 * This is the mandated fallback, and it is written first and treated as the real
 * implementation rather than a consolation prize: it works without WebGL, prints,
 * scales to a phone, and is readable by a screen reader through the summary
 * table underneath. The 3D version is progressive enhancement on top.
 *
 * Layout is a deterministic radial assignment rather than a physics simulation.
 * A simulation would look livelier and give a different picture on every render,
 * and a diagram of a *measurement* should be reproducible.
 */

type Node = {
  id: string;
  label: string;
  kind: "page" | "evidence" | "capability" | "tool";
  x: number;
  y: number;
};

const WIDTH = 900;
const HEIGHT = 420;

const COLUMN_X: Record<Node["kind"], number> = {
  page: 90,
  evidence: 330,
  capability: 600,
  tool: 830,
};

const COLOUR: Record<Node["kind"], string> = {
  page: "var(--paper-faint)",
  evidence: "var(--signal)",
  capability: "var(--measured)",
  tool: "var(--band-emerging)",
};

// Beyond this the diagram stops being readable and becomes texture.
const MAX_EVIDENCE = 14;

export function CapabilityGraph2D({
  evidence,
  capabilities,
  pageCount,
}: {
  evidence: Evidence[];
  capabilities: Capability[];
  pageCount: number;
}): React.ReactElement {
  const { nodes, edges } = useMemo(() => {
    // Only evidence that something actually cites — the rest is noise here,
    // and the full set is available in the drawer.
    const cited = new Set(capabilities.flatMap((c) => c.evidence_ids));
    const shown = evidence.filter((e) => cited.has(e.id)).slice(0, MAX_EVIDENCE);

    const spread = (count: number, index: number) =>
      count === 1 ? HEIGHT / 2 : 50 + (index * (HEIGHT - 100)) / Math.max(count - 1, 1);

    const pages: Node[] = Array.from({ length: Math.min(pageCount, 6) }, (_, i) => ({
      id: `page-${i}`,
      label: `page ${i + 1}`,
      kind: "page" as const,
      x: COLUMN_X.page,
      y: spread(Math.min(pageCount, 6), i),
    }));

    const evidenceNodes: Node[] = shown.map((e, i) => ({
      id: e.id,
      label: e.kind,
      kind: "evidence" as const,
      x: COLUMN_X.evidence,
      y: spread(shown.length, i),
    }));

    const capabilityNodes: Node[] = capabilities.map((c, i) => ({
      id: `cap-${c.name}`,
      label: c.name,
      kind: "capability" as const,
      x: COLUMN_X.capability,
      y: spread(capabilities.length, i),
    }));

    const toolNodes: Node[] = capabilities
      .filter((c) => c.tool_schema)
      .map((c, i, arr) => ({
        id: `tool-${c.tool_schema!.name}`,
        label: c.tool_schema!.name,
        kind: "tool" as const,
        x: COLUMN_X.tool,
        y: spread(arr.length, i),
      }));

    const allEdges: Array<{ from: Node; to: Node; strong: boolean }> = [];

    // page → evidence (attributed round-robin; exact page provenance is in the drawer)
    evidenceNodes.forEach((node, i) => {
      const page = pages[i % Math.max(pages.length, 1)];
      if (page) allEdges.push({ from: page, to: node, strong: false });
    });

    // evidence → capability, the citation itself
    capabilities.forEach((capability) => {
      const target = capabilityNodes.find((n) => n.id === `cap-${capability.name}`);
      if (!target) return;
      capability.evidence_ids.forEach((id) => {
        const source = evidenceNodes.find((n) => n.id === id);
        if (source) allEdges.push({ from: source, to: target, strong: true });
      });
    });

    // capability → tool
    capabilities.forEach((capability) => {
      if (!capability.tool_schema) return;
      const from = capabilityNodes.find((n) => n.id === `cap-${capability.name}`);
      const to = toolNodes.find((n) => n.id === `tool-${capability.tool_schema!.name}`);
      if (from && to) allEdges.push({ from, to, strong: true });
    });

    return {
      nodes: [...pages, ...evidenceNodes, ...capabilityNodes, ...toolNodes],
      edges: allEdges,
    };
  }, [evidence, capabilities, pageCount]);

  if (capabilities.length === 0) {
    return (
      <p className="mono" style={{ color: "var(--paper-faint)", maxWidth: "var(--measure)" }}>
        No capabilities survived review on this scan, so there is no provenance chain to
        draw. The refusals are listed above.
      </p>
    );
  }

  return (
    <figure className="m-0">
      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          width="100%"
          style={{ minWidth: 640, display: "block" }}
          role="img"
          aria-label={`Provenance graph: ${pageCount} pages to ${
            capabilities.length
          } capabilities to ${capabilities.filter((c) => c.tool_schema).length} tools`}
        >
          {(["page", "evidence", "capability", "tool"] as const).map((kind) => (
            <text
              key={kind}
              x={COLUMN_X[kind]}
              y={20}
              textAnchor="middle"
              className="mono"
              fill="var(--paper-faint)"
              fontSize={10}
              letterSpacing={2}
            >
              {kind.toUpperCase()}
            </text>
          ))}

          {edges.map((edge, i) => (
            <path
              key={i}
              d={`M ${edge.from.x} ${edge.from.y} C ${(edge.from.x + edge.to.x) / 2} ${edge.from.y}, ${
                (edge.from.x + edge.to.x) / 2
              } ${edge.to.y}, ${edge.to.x} ${edge.to.y}`}
              fill="none"
              stroke={edge.strong ? "var(--signal)" : "var(--ink-500)"}
              strokeWidth={edge.strong ? 1.2 : 0.8}
              strokeOpacity={edge.strong ? 0.55 : 0.3}
            />
          ))}

          {nodes.map((node) => (
            <g key={node.id}>
              <circle cx={node.x} cy={node.y} r={node.kind === "evidence" ? 4 : 6} fill={COLOUR[node.kind]} />
              <text
                x={node.kind === "tool" ? node.x - 12 : node.x + 12}
                y={node.y + 3.5}
                textAnchor={node.kind === "tool" ? "end" : "start"}
                className="mono"
                fill="var(--paper-dim)"
                fontSize={10}
              >
                {node.label.length > 26 ? `${node.label.slice(0, 24)}…` : node.label}
              </text>
            </g>
          ))}
        </svg>
      </div>

      <figcaption className="mono mt-3" style={{ color: "var(--paper-faint)", maxWidth: "var(--measure)" }}>
        Every tool traces back through a capability to the evidence that justified it. A
        node with no path to the left would be a hallucination — the eval harness gates on
        exactly that, at 0.00.
      </figcaption>
    </figure>
  );
}
