import type { AgeEstimationResult } from "@/lib/api/client";

const SCALE_MIN = 10;
const SCALE_MAX = 90;
const pos = (years: number) =>
  `${((Math.min(Math.max(years, SCALE_MIN), SCALE_MAX) - SCALE_MIN) / (SCALE_MAX - SCALE_MIN)) * 100}%`;

/** Leads with the range, not the point estimate, so the uncertainty is the headline. */
export function AgeResult({ result }: { result: AgeEstimationResult }) {
  const [low, high] = result.range_years;
  const coverage = Math.round(result.interval_coverage * 100);
  return (
    <div className="space-y-5">
      <div>
        <p className="text-sm text-muted-foreground">Apparent age in this photo, as estimated by the model</p>
        <p className="font-heading text-4xl font-semibold" data-testid="age-range">
          About {low}–{high} years
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          The middle of the range is {result.estimate_years}. Treat the whole range as the answer,
          not the single number.
        </p>
      </div>

      <figure aria-hidden="true" className="space-y-1">
        <div className="relative h-8 rounded-full bg-muted">
          <div
            className="absolute inset-y-1 rounded-full bg-primary/35"
            style={{ left: pos(low), width: `calc(${pos(high)} - ${pos(low)})` }}
          />
          <div className="absolute inset-y-0 w-0.5 bg-primary" style={{ left: pos(result.estimate_years) }} />
        </div>
        <div className="flex justify-between text-xs text-muted-foreground">
          {[10, 30, 50, 70, 90].map((t) => (
            <span key={t}>{t}</span>
          ))}
        </div>
      </figure>

      <div className="rounded-lg bg-secondary p-4 text-sm text-secondary-foreground">
        <p className="font-medium">What this range means</p>
        <p className="mt-1">
          The range is calibrated on held-out test photos so that ranges like this overlap the age
          group chosen by human annotators about {coverage}% of the time. It hasn&apos;t been checked for
          your photo, and accuracy differs across skin tones, ages, and presentation styles (see the
          model card). This is not a verified or legal age.
        </p>
      </div>
    </div>
  );
}
