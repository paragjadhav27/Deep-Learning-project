import type { PresentationEstimationResult } from "@/lib/api/client";

const HEADLINES: Record<PresentationEstimationResult["outcome"], string> = {
  feminine_presenting: "The model perceives this photo's presentation as more feminine-presenting",
  masculine_presenting: "The model perceives this photo's presentation as more masculine-presenting",
  uncertain: "The model is uncertain about this photo's presentation",
};

/**
 * Language rule: always "the model perceives this photo…", never "you are / this person is".
 * The result describes appearance to a model, not identity.
 */
export function PresentationResult({ result }: { result: PresentationEstimationResult }) {
  const masc = result.scores.masculine_presenting;
  const threshold = Math.round(result.uncertain_threshold * 100);
  const bandLeft = 100 - threshold;
  return (
    <div className="space-y-5">
      <p className="font-heading text-2xl font-semibold sm:text-3xl" data-testid="presentation-outcome">
        {HEADLINES[result.outcome]}
      </p>

      <figure className="space-y-2">
        <div aria-hidden="true" className="relative h-8 rounded-full bg-muted">
          {/* Uncertain zone: neither side reaches the confidence threshold. */}
          <div
            className="absolute inset-y-0 bg-accent"
            style={{ left: `${bandLeft}%`, width: `${threshold - bandLeft}%` }}
          />
          <div
            className="absolute inset-y-0 w-1 -translate-x-1/2 rounded bg-primary"
            style={{ left: `${masc * 100}%` }}
          />
        </div>
        <div aria-hidden="true" className="flex justify-between text-xs text-muted-foreground">
          <span>More feminine-presenting</span>
          <span>Uncertain</span>
          <span>More masculine-presenting</span>
        </div>
        <figcaption className="text-sm text-muted-foreground">
          Model scores: feminine-presenting {Math.round(result.scores.feminine_presenting * 100)}%,
          masculine-presenting {Math.round(masc * 100)}%. Anything below {threshold}% on both sides
          is reported as uncertain.
        </figcaption>
      </figure>

      <div className="rounded-lg bg-secondary p-4 text-sm text-secondary-foreground">
        <p className="font-medium">This is not about who someone is</p>
        <p className="mt-1">
          This describes how a model reads the presentation in one photo, from things like hair,
          makeup, and facial hair. It says nothing about a person&apos;s gender identity or sex. People
          of every gender present in all kinds of ways. The model was trained on two categories only,
          so it can&apos;t represent that range and is often uncertain.
        </p>
      </div>
    </div>
  );
}
