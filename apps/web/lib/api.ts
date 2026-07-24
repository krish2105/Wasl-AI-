/**
 * Typed client for the Wasl FastAPI backend.
 *
 * Responses are parsed through Zod rather than cast. The backend is a separate
 * process on a separate deploy cadence, so `as SomeType` would be a lie the
 * compiler happily believes — a schema mismatch should surface here, loudly,
 * rather than as `undefined` three components deep.
 */

import { z } from "zod";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export const healthSchema = z.object({
  status: z.enum(["ok", "degraded"]),
  version: z.string(),
  environment: z.string(),
  checks: z.record(
    z.object({
      ok: z.boolean(),
      detail: z.string(),
    }),
  ),
  crawler_identity_configured: z.boolean(),
  playwright_available: z.boolean(),
});

export type Health = z.infer<typeof healthSchema>;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly path: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Fetch a JSON endpoint and validate it against a schema.
 *
 * A 501 is a real answer from this API, not a transport failure — several routes
 * are deliberately unimplemented until their phase lands — so it raises an
 * ApiError carrying the status rather than being swallowed.
 */
export async function apiFetch<T>(
  path: string,
  schema: z.ZodType<T>,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...init?.headers },
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body: unknown = await response.json();
      if (typeof body === "object" && body !== null && "detail" in body) {
        detail = String((body as { detail: unknown }).detail);
      }
    } catch {
      // Non-JSON error body; the status text is the best we have.
    }
    throw new ApiError(detail, response.status, path);
  }

  return schema.parse(await response.json());
}

export function getHealth(): Promise<Health> {
  return apiFetch("/health", healthSchema);
}
