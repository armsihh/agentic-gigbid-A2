// Typed API client. `schema.d.ts` is GENERATED from FastAPI's OpenAPI schema (npm run gen:api) - do not hand-edit.
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export const api = createClient<paths>({ baseUrl: "", credentials: "include" });

export type Schemas = components["schemas"];
export type JobRow = Schemas["JobRow"];
export type JobDetail = Schemas["JobDetail"];
export type Studio = Schemas["Studio"];
export type RunOut = Schemas["RunOut"];
export type Me = Schemas["Me"];
export type Health = Schemas["Health"];

/** Unwrap an openapi-fetch result: throw a readable error on failure. */
export async function must<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await p;
  if (error !== undefined || data === undefined) {
    const detail = (error as { detail?: unknown })?.detail;
    const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : "";
    throw new ApiError(response.status, msg || response.statusText || "request failed");
  }
  return data;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}
