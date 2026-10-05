/**
 * Formatting for evaluation results (GET /v1/evaluations and the `candidate` summaries in
 * GET /v1/models). Every number shown comes from the API; nothing here invents a figure.
 */
import type { EvaluationSummary, GateCriterion } from "@/lib/api/client";

type ValueFormat = GateCriterion["format"];
export type EvaluationStatus = EvaluationSummary["status"];

/**
 * Round half-up on the decimal value the report stores (0.6785 -> 67.9%), not on its
 * binary approximation (0.6785 * 100 = 67.8499...), so figures match the model cards.
 */
function fixed(value: number, digits: number): string {
  const scale = 10 ** digits;
  return (Math.round(Number((value * scale).toPrecision(12))) / scale).toFixed(digits);
}

export function formatValue(value: number, format: ValueFormat): string {
  switch (format) {
    case "percent": {
      const pct = value * 100;
      return `${fixed(pct, pct > 0 && pct < 1 ? 2 : 1)}%`;
    }
    case "pp":
      return `${fixed(value * 100, 1)} pp`;
    case "ratio":
      return `${fixed(value, 2)}×`;
    case "years":
      return `${fixed(value, 1)} years`;
    default:
      return fixed(value, 1);
  }
}

/** "≤ 1.50×" / "≥ 70.0%" */
export function formatLimit(c: Pick<GateCriterion, "comparator" | "limit" | "format">): string {
  return `${c.comparator === "max" ? "≤" : "≥"} ${formatValue(c.limit, c.format)}`;
}

const FAMILY_NAMES: Record<string, string> = {
  race: "annotated race",
  gender: "annotated gender",
  age_bin: "annotated age",
  young_adult: "young-adult target",
  older_adult: "older-adult target",
};

export function familyName(family: string): string {
  return FAMILY_NAMES[family] ?? family;
}

/** Plain-language group reference, e.g. "faces annotated as Black" or "the 40-49 age group". */
export function groupPhrase(family: string | null, group: string | null): string | null {
  if (!group) return null;
  if (family === "age_bin") return `the ${group.replace("-", "–")} age group`;
  if (family === "race" || family === "gender") return `faces annotated as ${group}`;
  return group;
}

/** "Worst group's range coverage: 67.9% for the 40–49 age group (limit ≥ 70.0%)" */
export function describeCriterion(c: GateCriterion): string {
  if (c.measured === null) return `${c.label} (limit ${formatLimit(c)}): not measured yet`;
  const who = groupPhrase(c.worst_family, c.worst_group);
  return `${c.label}: ${formatValue(c.measured, c.format)}${who ? ` for ${who}` : ""} (limit ${formatLimit(c)})`;
}

export function failedCriteria(e: Pick<EvaluationSummary, "criteria">): GateCriterion[] {
  return e.criteria.filter((c) => c.passed === false);
}

export const STATUS_LABELS: Record<EvaluationStatus, string> = {
  passed: "Passed release gates",
  failed: "Failed release gates",
  not_evaluated: "Not evaluated yet",
};

export const TASK_NAMES: Record<EvaluationSummary["task"], string> = {
  face_detection: "Face detection",
  age_estimation: "Age estimate",
  presentation_estimation: "Perceived presentation",
  age_transformation: "Age transformation preview",
};

export function formatDate(iso: string | null): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
}
