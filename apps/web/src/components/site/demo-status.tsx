"use client";

import { FlaskConical } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { createApiClient, type Capabilities } from "@/lib/api/client";
import { TASK_NAMES, type EvaluationStatus } from "@/lib/evaluation";

const CANDIDATE_PHRASES: Record<EvaluationStatus, string> = {
  failed: "was evaluated and failed its fairness limits",
  not_evaluated: "hasn't been evaluated yet",
  passed: "passed but isn't enabled in this deployment",
};

/** Says which tools run on mocks, and why no real model is serving them. */
export function DemoStatusNotice({ caps, showLink = false }: { caps: Capabilities; showLink?: boolean }) {
  const mocks = caps.features.filter((f) => f.enabled && f.model?.is_mock);
  if (!mocks.length) return null;
  const total = caps.features.length;
  return (
    <div
      role="note"
      aria-label="Demo status"
      className="flex gap-3 rounded-lg border-2 border-warning/60 bg-warning-subtle p-4 text-sm"
    >
      <FlaskConical className="mt-0.5 size-5 shrink-0 text-warning" aria-hidden="true" />
      <div>
        <p>
          <strong className="text-warning">Demo status:</strong>{" "}
          {mocks.length === total ? `All ${total}` : `${mocks.length} of the ${total}`} tools run on
          mock models. Their results are placeholders that don&apos;t depend on your photo.
        </p>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {mocks.map((f) => (
            <li key={f.task}>
              {TASK_NAMES[f.task]}: the real candidate,{" "}
              {f.candidate
                ? `${f.candidate.model_name}, ${CANDIDATE_PHRASES[f.candidate.status]}`
                : "none, isn't available"}
              .
            </li>
          ))}
        </ul>
        {showLink ? (
          <Link href="/evaluation" className="mt-1 inline-flex min-h-11 items-center font-medium underline underline-offset-4">
            See the evaluation results
          </Link>
        ) : null}
      </div>
    </div>
  );
}

/** DemoStatusNotice that loads capabilities itself; renders nothing until they arrive or on error. */
export function LiveDemoStatus() {
  const client = useMemo(() => createApiClient(), []);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  useEffect(() => {
    const ctrl = new AbortController();
    client.capabilities(ctrl.signal).then(setCaps, () => undefined);
    return () => ctrl.abort();
  }, [client]);
  return caps ? <DemoStatusNotice caps={caps} showLink /> : null;
}
