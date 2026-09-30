import { describe, expect, it, vi } from "vitest";

import type { ApiClient, JobView } from "@/lib/api/client";
import { runJob } from "@/lib/jobs";

const job = (status: JobView["status"], extra: Partial<JobView> = {}): JobView =>
  ({
    job_id: "j_1",
    session_id: "s_1",
    task: "age_estimation",
    params: {},
    status,
    progress: status === "succeeded" ? 1 : 0.4,
    stage: status === "running" ? "estimating" : null,
    created_at: "2026-09-25T00:00:00Z",
    finished_at: null,
    ...extra,
  }) as JobView;

function fakeClient(sequence: JobView[]) {
  const [first, ...rest] = sequence;
  return {
    createJob: vi.fn().mockResolvedValue(first),
    getJob: vi.fn().mockImplementation(() => Promise.resolve(rest.shift() ?? sequence.at(-1))),
  } as unknown as ApiClient & { createJob: ReturnType<typeof vi.fn>; getJob: ReturnType<typeof vi.fn> };
}

describe("runJob", () => {
  it("polls with backoff until the job finishes", async () => {
    const client = fakeClient([job("queued"), job("running"), job("running"), job("succeeded")]);
    const sleeps: number[] = [];
    const updates: string[] = [];
    const final = await runJob({
      client,
      sessionId: "s_1",
      token: "t",
      task: "age_estimation",
      onUpdate: (j) => updates.push(j.status),
      signal: new AbortController().signal,
      sleep: async (ms) => void sleeps.push(ms),
    });
    expect(final.status).toBe("succeeded");
    expect(updates).toEqual(["queued", "running", "running", "succeeded"]);
    expect(sleeps).toEqual([400, 600, 900]);
  });

  it("returns immediately when the job finished synchronously", async () => {
    const client = fakeClient([job("succeeded")]);
    await runJob({
      client,
      sessionId: "s_1",
      token: "t",
      task: "age_estimation",
      onUpdate: () => {},
      signal: new AbortController().signal,
      sleep: async () => {},
    });
    expect(client.getJob).not.toHaveBeenCalled();
  });

  it("resolves failed jobs so the caller can show the error", async () => {
    const failed = job("failed", {
      error: { code: "no_face_detected", message: "No face", retryable: false },
    });
    const final = await runJob({
      client: fakeClient([job("queued"), failed]),
      sessionId: "s_1",
      token: "t",
      task: "age_estimation",
      onUpdate: () => {},
      signal: new AbortController().signal,
      sleep: async () => {},
    });
    expect(final.error?.code).toBe("no_face_detected");
  });

  it("gives up after the deadline with a retryable error", async () => {
    let t = 0;
    const err = await runJob({
      client: fakeClient([job("running")]),
      sessionId: "s_1",
      token: "t",
      task: "age_estimation",
      onUpdate: () => {},
      signal: new AbortController().signal,
      deadlineMs: 1000,
      now: () => (t += 400),
      sleep: async () => {},
    }).catch((e: unknown) => e);
    expect(err).toMatchObject({ code: "job_poll_timeout", retryable: true });
  });

  it("stops polling when aborted", async () => {
    const ctrl = new AbortController();
    const client = fakeClient([job("running")]);
    const p = runJob({
      client,
      sessionId: "s_1",
      token: "t",
      task: "age_estimation",
      onUpdate: () => ctrl.abort(),
      signal: ctrl.signal,
    });
    await expect(p).rejects.toBeDefined();
    expect(client.getJob).not.toHaveBeenCalled();
  });
});
