"use client";

import { Clock } from "lucide-react";
import { useEffect, useState } from "react";

/** "Deletes automatically in N minutes". Updates quietly, with no live region, to avoid noise. */
export function RetentionCountdown({ expiresAt }: { expiresAt: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 15_000);
    return () => clearInterval(timer);
  }, []);
  const minutes = Math.max(0, Math.ceil((Date.parse(expiresAt) - now) / 60_000));
  return (
    <p className="flex items-center gap-2 text-sm text-muted-foreground">
      <Clock className="size-4" aria-hidden="true" />
      {minutes > 0
        ? `Your photo and results delete automatically in about ${minutes} minute${minutes === 1 ? "" : "s"}.`
        : "Your photo and results have expired and are being deleted."}
    </p>
  );
}
