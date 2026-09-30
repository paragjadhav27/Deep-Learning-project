import { Lock } from "lucide-react";
import Link from "next/link";

interface PrivacyNoteProps {
  ttlSeconds: number;
  variant: "upload" | "result";
}

/** Retention facts shown next to upload and results, not only on the policy page. */
export function PrivacyNote({ ttlSeconds, variant }: PrivacyNoteProps) {
  const minutes = Math.round(ttlSeconds / 60);
  return (
    <aside
      aria-label="Privacy and retention"
      className="flex gap-3 rounded-lg border border-border bg-muted/50 p-4 text-sm text-muted-foreground"
    >
      <Lock className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden="true" />
      <div className="space-y-1">
        {variant === "upload" ? (
          <p>
            Location and camera metadata are removed <strong className="font-medium text-foreground">on your device</strong>{" "}
            before upload, and the file name is never sent. The photo is used only for this tool
            and is deleted automatically after <strong className="font-medium text-foreground">{minutes} minutes</strong>.
          </p>
        ) : (
          <p>
            Your photo and results will be deleted automatically after{" "}
            <strong className="font-medium text-foreground">{minutes} minutes</strong>, or straight
            away if you choose <em>Delete photo and results</em>. We keep no copy and no account.
          </p>
        )}
        <p>
          <Link href="/privacy" className="underline underline-offset-4 hover:text-foreground">
            How we handle photos
          </Link>
        </p>
      </div>
    </aside>
  );
}
