/**
 * Types and helpers for the scan API.
 *
 * Schemas are permissive at the edges (`.passthrough()`, optional fields) but
 * strict about the things the UI actually renders. The backend is a separate
 * deploy; a new field it adds should not blank the report, but a missing score
 * should surface loudly rather than as `undefined` three components deep.
 */

import { z } from "zod";

import { API_BASE_URL, apiFetch } from "./api";

export const checkSchema = z.object({
  check_id: z.string(),
  label: z.string(),
  points_awarded: z.number(),
  max_points: z.number(),
  evidence_refs: z.array(z.string()).default([]),
  suppressed: z.boolean().default(false),
  suppressed_reason: z.string().nullable().default(null),
  detail: z.string().default(""),
});

export const axisSchema = z.object({
  number: z.number(),
  name: z.string(),
  points: z.number(),
  max_points: z.number(),
  counted_max: z.number(),
  checks: z.array(checkSchema),
});

export const scoreSchema = z.object({
  total: z.number(),
  max_possible: z.number(),
  percentage: z.number(),
  band: z.string().nullable(),
  confidence: z.string(),
  confidence_reason: z.string().nullable(),
  degraded: z.boolean().default(false),
  rubric_version: z.string().default("1.0"),
  axes: z.array(axisSchema),
});

export const evidenceSchema = z.object({
  id: z.string(),
  kind: z.string(),
  source_url: z.string(),
  selector: z.string().nullable(),
  raw: z.string(),
  phase: z.string(),
});

export const capabilitySchema = z
  .object({
    name: z.string(),
    verb: z.string(),
    noun: z.string(),
    description: z.string(),
    evidence_ids: z.array(z.string()),
    tool_schema: z
      .object({
        name: z.string(),
        description: z.string(),
        parameters: z.record(z.unknown()).default({}),
      })
      .nullable()
      .optional(),
  })
  .passthrough();

export const rejectionSchema = z
  .object({
    capability_name: z.string(),
    rule_id: z.string(),
    reason: z.string(),
    final: z.boolean().default(false),
  })
  .passthrough();

export const demoSchema = z.object({
  task: z.string(),
  raw_succeeded: z.boolean(),
  raw_transcript: z.string(),
  mcp_succeeded: z.boolean(),
  mcp_transcript: z.string(),
  note: z.string().default(""),
});

export const reportSchema = z.object({
  job_id: z.string(),
  target: z.string(),
  domain: z.string(),
  source: z.enum(["live", "fixture"]),
  status: z.string(),
  seconds: z.number(),
  score: scoreSchema.nullable(),
  pages: z.array(z.record(z.unknown())).default([]),
  evidence: z.array(evidenceSchema).default([]),
  accepted_capabilities: z.array(capabilitySchema).default([]),
  rejections: z.array(rejectionSchema).default([]),
  demo: demoSchema.nullable(),
  artifacts: z
    .object({
      verified: z.boolean(),
      tool_count: z.number(),
      summary: z.string(),
      downloadable: z.boolean(),
    })
    .optional(),
  errors: z.array(z.string()).default([]),
});

export type Report = z.infer<typeof reportSchema>;
export type Score = z.infer<typeof scoreSchema>;
export type Axis = z.infer<typeof axisSchema>;
export type Check = z.infer<typeof checkSchema>;
export type Evidence = z.infer<typeof evidenceSchema>;
export type Capability = z.infer<typeof capabilitySchema>;
export type Rejection = z.infer<typeof rejectionSchema>;
export type Demo = z.infer<typeof demoSchema>;

export type ScanEvent = {
  type: string;
  job_id: string;
  node: string | null;
  message: string;
  data: Record<string, unknown>;
  at: string;
};

/** Mirrors NODE_SEQUENCE in wasl/graph/events.py. Keep the two in step. */
export const NODES: Array<{ id: string; label: string }> = [
  { id: "gate_precrawl", label: "Checking crawl permission" },
  { id: "crawl", label: "Fetching pages" },
  { id: "extract", label: "Extracting evidence" },
  { id: "induce", label: "Inducing capabilities" },
  { id: "synthesize", label: "Building tool schemas" },
  { id: "critic", label: "Reviewing claims" },
  { id: "score", label: "Scoring" },
  { id: "generate", label: "Generating artifacts" },
  { id: "demo", label: "Running the comparison" },
];

export const BAND_COLOUR: Record<string, string> = {
  Invisible: "var(--band-invisible)",
  Emerging: "var(--band-emerging)",
  Readable: "var(--band-readable)",
  "Agent-Ready": "var(--band-ready)",
  "Agent-Native": "var(--band-native)",
};

/** Human-readable label for each critic rejection rule. */
export const RULE_LABEL: Record<string, string> = {
  no_evidence: "cited evidence that does not exist",
  evidence_mismatch: "evidence does not support the claim",
  unbounded_param: "unbounded tool parameter",
  state_changing: "would change state on a third-party site",
  injection_detected: "cited evidence contains injected instructions",
};

export function startScan(body: {
  url?: string;
  fixture?: string;
  /** Clears gate_pregenerate. Without it the backend pauses before writing artifacts. */
  acknowledge_generation?: boolean;
}) {
  return apiFetch(
    "/api/scan",
    z.object({ job_id: z.string(), source: z.string(), target: z.string() }),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function getReport(jobId: string): Promise<Report> {
  return apiFetch(`/api/scan/${jobId}`, reportSchema);
}

export function eventsUrl(jobId: string): string {
  return `${API_BASE_URL}/api/scan/${jobId}/events`;
}

export function artifactsUrl(jobId: string): string {
  return `${API_BASE_URL}/api/scan/${jobId}/artifacts.zip`;
}
