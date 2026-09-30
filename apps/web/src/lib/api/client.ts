/**
 * Typed client for the FaceLens API (v1). Types are generated from the API's OpenAPI
 * schema (`npm run gen:api`); never hand-edit ./schema.d.ts.
 *
 * All calls go to the same origin under /v1: the load balancer (production) or the
 * next.config.ts rewrite (development) routes them to FastAPI.
 */
import type { components } from "./schema";

type Schemas = components["schemas"];
export type Capabilities = Schemas["CapabilitiesView"];
export type SessionCreated = Schemas["SessionCreated"];
export type JobView = Schemas["JobView"];
export type Task = Schemas["Task"];
export type TargetAgeGroup = Schemas["TargetAgeGroup"];
export type TargetGroupView = Schemas["TargetGroupView"];
export type AgeEstimationResult = Schemas["AgeEstimationResult"];
export type PresentationEstimationResult = Schemas["PresentationEstimationResult"];
export type AgeTransformationResult = Schemas["AgeTransformationResult"];
export type ApiErrorCode = Schemas["ErrorBody"]["code"];
/** Client-side conditions that never come from the API. */
export type ClientErrorCode = "network_error" | "job_poll_timeout";
export type ErrorCode = ApiErrorCode | ClientErrorCode;

export interface Consent {
  has_permission: boolean;
  is_adult: boolean;
  accepts_limitations: boolean;
}

export const API_BASE = "";

/** Turn an API-relative path (e.g. a signed image link) into a browser URL. */
export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export class ApiError extends Error {
  constructor(
    readonly code: ErrorCode,
    message: string,
    readonly retryable: boolean,
    readonly status: number,
    readonly retryAfterSeconds: number | null = null,
    readonly requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Fetch = typeof fetch;

export interface ApiClientOptions {
  fetch?: Fetch;
  base?: string;
}

export function createApiClient({ fetch: f = fetch, base = API_BASE }: ApiClientOptions = {}) {
  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    let res: Response;
    try {
      res = await f(`${base}${path}`, { ...init, cache: "no-store" });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") throw err;
      throw new ApiError(
        "network_error",
        "We couldn't reach the service. Check your connection and try again.",
        true,
        0,
      );
    }
    if (res.status === 204) return undefined as T;
    const body: unknown = await res.json().catch(() => null);
    if (!res.ok) throw toApiError(res, body);
    return body as T;
  }

  const sessionHeaders = (token: string) => ({ "X-Session-Token": token });

  return {
    capabilities: (signal?: AbortSignal) => request<Capabilities>("/v1/models", { signal }),

    createSession(image: Blob, consent: Consent, signal?: AbortSignal) {
      const form = new FormData();
      // A neutral filename: the original name never leaves the device.
      form.append("image", image, "photo.jpg");
      form.append("consent", JSON.stringify(consent));
      return request<SessionCreated>("/v1/sessions", { method: "POST", body: form, signal });
    },

    createJob(
      sessionId: string,
      token: string,
      task: Task,
      targetAgeGroup?: TargetAgeGroup,
      signal?: AbortSignal,
    ) {
      const body =
        task === "age_transformation"
          ? { task, params: { target_age_group: targetAgeGroup } }
          : { task };
      return request<JobView>(`/v1/sessions/${encodeURIComponent(sessionId)}/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...sessionHeaders(token) },
        body: JSON.stringify(body),
        signal,
      });
    },

    getJob: (jobId: string, token: string, signal?: AbortSignal) =>
      request<JobView>(`/v1/jobs/${encodeURIComponent(jobId)}`, {
        headers: sessionHeaders(token),
        signal,
      }),

    cancelJob: (jobId: string, token: string) =>
      request<JobView>(`/v1/jobs/${encodeURIComponent(jobId)}`, {
        method: "DELETE",
        headers: sessionHeaders(token),
      }),

    deleteSession: (sessionId: string, token: string) =>
      request<void>(`/v1/sessions/${encodeURIComponent(sessionId)}`, {
        method: "DELETE",
        headers: sessionHeaders(token),
      }),
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;

function toApiError(res: Response, body: unknown): ApiError {
  const retryAfterHeader = res.headers.get("Retry-After");
  const retryAfter = retryAfterHeader ? Number.parseInt(retryAfterHeader, 10) : null;
  const err = (body as { error?: Partial<Schemas["ErrorBody"]> } | null)?.error;
  if (err?.code && err.message) {
    return new ApiError(
      err.code,
      err.message,
      Boolean(err.retryable),
      res.status,
      Number.isFinite(retryAfter) ? retryAfter : null,
      err.request_id ?? null,
    );
  }
  // Non-API response (e.g. proxy error page): don't surface raw content.
  return new ApiError(
    res.status >= 500 ? "internal_error" : "http_error",
    "Something went wrong on our side. Please try again.",
    res.status >= 500,
    res.status,
  );
}
