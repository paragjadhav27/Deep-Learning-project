"use client";

import { AlertTriangle } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import type { ApiError } from "@/lib/api/client";
import { errorCopy } from "@/lib/errors";

interface ErrorStateProps {
  error: ApiError;
  onReplacePhoto?: () => void;
  onRetry?: () => void;
  onStartOver?: () => void;
}

export function ErrorState({ error, onReplacePhoto, onRetry, onStartOver }: ErrorStateProps) {
  const copy = errorCopy(error.code);
  const waitSeconds = useCountdown(error.code === "rate_limited" ? (error.retryAfterSeconds ?? 30) : 0);

  return (
    <div
      role="alert"
      className="space-y-3 rounded-xl border-2 border-destructive/40 bg-destructive/5 p-5"
      data-error-code={error.code}
    >
      <div className="flex gap-3">
        <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden="true" />
        <div className="space-y-1">
          <p className="font-semibold">{copy.title}</p>
          <p className="text-sm">{copy.guidance ?? error.message}</p>
          {waitSeconds > 0 ? (
            <p className="text-sm text-muted-foreground">You can try again in {waitSeconds} seconds.</p>
          ) : null}
          {error.requestId ? (
            <p className="text-xs text-muted-foreground">
              Reference for support: <code className="font-mono">{error.requestId}</code>
            </p>
          ) : null}
        </div>
      </div>
      <div className="flex flex-wrap gap-2 pl-8">
        {copy.recovery === "replace_photo" && onReplacePhoto ? (
          <Button type="button" className="min-h-11" onClick={onReplacePhoto}>
            Choose a different photo
          </Button>
        ) : null}
        {(copy.recovery === "retry" || copy.recovery === "wait") && onRetry ? (
          <Button type="button" className="min-h-11" onClick={onRetry} disabled={waitSeconds > 0}>
            Try again
          </Button>
        ) : null}
        {copy.recovery === "start_over" && onStartOver ? (
          <Button type="button" className="min-h-11" onClick={onStartOver}>
            Start over
          </Button>
        ) : null}
      </div>
    </div>
  );
}

/** Seconds left until a fixed deadline set at mount (callers key this component per error). */
function useCountdown(seconds: number): number {
  const [deadline] = useState(() => Date.now() + seconds * 1000);
  const [now, setNow] = useState(() => Date.now());
  const done = now >= deadline;
  useEffect(() => {
    if (done) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [done]);
  return Math.max(0, Math.ceil((deadline - now) / 1000));
}
