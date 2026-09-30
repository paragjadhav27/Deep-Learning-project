import { ApiError, type ApiClient, type JobView, type TargetAgeGroup, type Task } from "@/lib/api/client";

const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

export function isTerminal(job: JobView): boolean {
  return TERMINAL.has(job.status);
}

export interface RunJobOptions {
  client: ApiClient;
  sessionId: string;
  token: string;
  task: Task;
  target?: TargetAgeGroup;
  onUpdate: (job: JobView) => void;
  signal: AbortSignal;
  /** Give up polling after this long (the server enforces its own inference timeout). */
  deadlineMs?: number;
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
  now?: () => number;
}

export function abortableSleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(signal.reason);
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(signal.reason);
      },
      { once: true },
    );
  });
}

/**
 * Create a job and poll it to a terminal state with gentle backoff (400 ms up to 2 s).
 * Resolves with the final JobView; failed jobs resolve too (the caller shows job.error).
 */
export async function runJob({
  client,
  sessionId,
  token,
  task,
  target,
  onUpdate,
  signal,
  deadlineMs = 120_000,
  sleep = abortableSleep,
  now = Date.now,
}: RunJobOptions): Promise<JobView> {
  const started = now();
  let job = await client.createJob(sessionId, token, task, target, signal);
  onUpdate(job);
  let delay = 400;
  while (!isTerminal(job)) {
    if (now() - started > deadlineMs) {
      throw new ApiError("job_poll_timeout", "This is taking longer than expected.", true, 0);
    }
    await sleep(delay, signal);
    job = await client.getJob(job.job_id, token, signal);
    onUpdate(job);
    delay = Math.min(2000, Math.round(delay * 1.5));
  }
  return job;
}
