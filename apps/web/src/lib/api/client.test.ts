import { describe, expect, it, vi } from "vitest";

import { ApiError, createApiClient } from "@/lib/api/client";

const CONSENT = { has_permission: true, is_adult: true, accepts_limitations: true };

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

describe("api client", () => {
  it("uploads with a neutral filename and JSON consent", async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse(201, { session_id: "s_1" }));
    const api = createApiClient({ fetch });
    await api.createSession(new Blob(["x"], { type: "image/jpeg" }), CONSENT);

    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe("/v1/sessions");
    expect(init.method).toBe("POST");
    const form = init.body as FormData;
    expect((form.get("image") as File).name).toBe("photo.jpg");
    expect(JSON.parse(form.get("consent") as string)).toEqual(CONSENT);
  });

  it("sends the session token as a header, never in the URL", async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse(202, { job_id: "j_1" }));
    const api = createApiClient({ fetch });
    await api.createJob("s_1", "secret-token", "age_transformation", "older_adult");

    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe("/v1/sessions/s_1/jobs");
    expect(url).not.toContain("secret-token");
    expect(init.headers["X-Session-Token"]).toBe("secret-token");
    expect(JSON.parse(init.body)).toEqual({
      task: "age_transformation",
      params: { target_age_group: "older_adult" },
    });
  });

  it("parses API errors including Retry-After", async () => {
    const fetch = vi.fn().mockResolvedValue(
      jsonResponse(
        429,
        { error: { code: "rate_limited", message: "Too many", retryable: true, request_id: "r1" } },
        { "Retry-After": "17" },
      ),
    );
    const err = await createApiClient({ fetch })
      .capabilities()
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({
      code: "rate_limited",
      retryable: true,
      status: 429,
      retryAfterSeconds: 17,
      requestId: "r1",
    });
  });

  it("never surfaces raw non-API error bodies", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response("<html>Bad Gateway</html>", { status: 502 }));
    const err = (await createApiClient({ fetch })
      .capabilities()
      .catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBe("internal_error");
    expect(err.message).not.toContain("html");
  });

  it("maps network failures to a retryable error", async () => {
    const fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    const err = (await createApiClient({ fetch })
      .capabilities()
      .catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBe("network_error");
    expect(err.retryable).toBe(true);
  });

  it("treats 204 on delete as success", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    await expect(createApiClient({ fetch }).deleteSession("s_1", "t")).resolves.toBeUndefined();
    expect(fetch.mock.calls[0]![1].method).toBe("DELETE");
  });
});
