import { FlaskConical } from "lucide-react";

/**
 * Shown whenever the serving model is a mock. The API reports `is_mock`; this banner makes
 * sure no placeholder output is ever mistaken for real inference.
 */
export function MockBanner({ modelId }: { modelId: string }) {
  return (
    <div
      role="note"
      aria-label="Demonstration mode"
      className="flex gap-3 rounded-lg border-2 border-warning/60 bg-warning-subtle p-4 text-sm"
    >
      <FlaskConical className="mt-0.5 size-5 shrink-0 text-warning" aria-hidden="true" />
      <div>
        <p className="font-semibold text-warning">Demonstration mode: placeholder results</p>
        <p className="mt-1 text-foreground">
          This tool is running a mock model (<code className="font-mono text-xs">{modelId}</code>)
          while a licensed, evaluated model is being reviewed. Results are placeholders that
          don&apos;t depend on the face in your photo.
        </p>
      </div>
    </div>
  );
}

/**
 * Shown when a real model is serving that has NOT passed its pre-registered fairness and
 * accuracy gates. The API only allows this in development with an explicit override;
 * the UI must never present such a model as if it were validated.
 */
export function UnevaluatedBanner({ modelId, evaluated }: { modelId: string; evaluated: boolean }) {
  return (
    <div
      role="note"
      aria-label="Model has not passed evaluation"
      className="flex gap-3 rounded-lg border-2 border-destructive/50 bg-destructive/5 p-4 text-sm"
    >
      <FlaskConical className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden="true" />
      <div>
        <p className="font-semibold text-destructive">
          {evaluated
            ? "Development only: this model failed its fairness evaluation"
            : "Development only: this model has not been evaluated yet"}
        </p>
        <p className="mt-1 text-foreground">
          <code className="font-mono text-xs">{modelId}</code> is a real model.{" "}
          {evaluated
            ? "Its measured accuracy differs between groups by more than our release limits, so results may be less accurate for some people."
            : "Its accuracy and fairness across groups have not been measured yet."}{" "}
          It&apos;s running here only for local testing; see the model card for details.
        </p>
      </div>
    </div>
  );
}
