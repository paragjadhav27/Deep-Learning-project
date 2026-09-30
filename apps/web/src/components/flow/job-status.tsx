"use client";

import { LoaderCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import type { JobView, TargetAgeGroup } from "@/lib/api/client";
import { STAGE_LABELS, TARGET_GROUP_LABELS } from "@/lib/tools";

interface JobStatusProps {
  phase: "uploading" | "processing";
  job: JobView | null;
  target?: TargetAgeGroup | null;
  onCancel: () => void;
  cancelling: boolean;
}

export function JobStatus({ phase, job, target, onCancel, cancelling }: JobStatusProps) {
  const label =
    phase === "uploading"
      ? "Uploading and checking your photo"
      : (job?.stage && STAGE_LABELS[job.stage]) || "Waiting to start";
  const progress = phase === "uploading" ? 5 : Math.round((job?.progress ?? 0.05) * 100);
  return (
    <div className="space-y-4 rounded-xl border border-border bg-card p-5" aria-busy="true">
      <div className="flex items-center gap-3">
        <LoaderCircle className="size-5 animate-spin text-primary motion-reduce:animate-none" aria-hidden="true" />
        {/* Polite live region: announces each stage change once. */}
        <p className="font-medium" role="status" aria-live="polite">
          {label}
        </p>
      </div>
      {target ? (
        <p className="text-sm text-muted-foreground">
          Target age group:{" "}
          <strong className="font-medium text-foreground">{TARGET_GROUP_LABELS[target].label}</strong>{" "}
          (creative target)
        </p>
      ) : null}
      <Progress value={progress} aria-label="Progress" className="h-2" />
      <Button
        type="button"
        variant="outline"
        className="min-h-11"
        onClick={onCancel}
        disabled={cancelling}
      >
        {cancelling ? "Cancelling…" : "Cancel"}
      </Button>
    </div>
  );
}
