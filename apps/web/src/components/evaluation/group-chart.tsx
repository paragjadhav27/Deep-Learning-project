import { XCircle } from "lucide-react";

import type { EvaluationMetric } from "@/lib/api/client";
import { formatValue } from "@/lib/evaluation";

type Family = EvaluationMetric["families"][number];

export interface Domain {
  lo: number;
  hi: number;
}

/** One shared x-scale per metric, so its family panels can be compared side by side. */
export function metricDomain(metric: EvaluationMetric): Domain {
  const values: number[] = [];
  for (const f of metric.families) {
    for (const g of f.groups) values.push(g.value, ...(g.ci95 ?? []));
  }
  if (metric.overall !== null) values.push(metric.overall);
  if (metric.gate_threshold !== null) values.push(metric.gate_threshold);
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.08;
  lo -= pad;
  hi += pad;
  if (metric.format === "percent" || metric.format === "years") lo = Math.max(0, lo);
  if (metric.format === "percent") hi = Math.min(1, hi);
  return { lo, hi };
}

function crosses(metric: EvaluationMetric, value: number): boolean {
  const t = metric.gate_threshold;
  if (t === null) return false;
  return metric.higher_is_better ? value < t : value > t;
}

/**
 * Per-group estimate with its 95% bootstrap CI, as a table whose middle column is a dot
 * plot. The numbers are always in text; the plot is a visual aid (aria-hidden).
 */
export function GroupChart({ metric, family, domain }: { metric: EvaluationMetric; family: Family; domain: Domain }) {
  const pos = (v: number) => `${(((v - domain.lo) / (domain.hi - domain.lo)) * 100).toFixed(2)}%`;
  const fmt = (v: number) => formatValue(v, metric.format);
  return (
    <figure
      aria-label={`${metric.label}, by ${family.label.toLowerCase()}`}
      className="min-w-0 rounded-lg border border-border bg-card p-3"
    >
      <figcaption className="mb-2 text-sm font-medium">{family.label}</figcaption>
      <table className="w-full table-fixed border-collapse text-xs">
        <colgroup>
          <col className="w-[7.25rem]" />
          <col />
          <col className="w-[4.75rem]" />
        </colgroup>
        <thead className="sr-only">
          <tr>
            <th scope="col">Group</th>
            <th scope="col">Plot</th>
            <th scope="col">Value (95% confidence interval)</th>
          </tr>
        </thead>
        <tbody>
          {family.groups.map((g) => {
            const over = crosses(metric, g.value);
            const ci = g.ci95 ? ` (95% CI ${fmt(g.ci95[0])}–${fmt(g.ci95[1])})` : "";
            return (
              <tr
                key={g.group}
                title={`${g.group}: ${fmt(g.value)}${ci}, n = ${g.n.toLocaleString("en-GB")}`}
                className="hover:bg-muted/60"
              >
                <th scope="row" className="truncate py-1 pr-2 text-left font-normal">
                  {g.group}
                </th>
                <td aria-hidden="true" className="py-1">
                  <div className="relative h-5">
                    {metric.overall !== null ? (
                      <div
                        className="absolute inset-y-0 border-l border-dashed border-muted-foreground/70"
                        style={{ left: pos(metric.overall) }}
                      />
                    ) : null}
                    {metric.gate_threshold !== null ? (
                      <div
                        className="absolute inset-y-0 border-l-2 border-destructive"
                        style={{ left: pos(metric.gate_threshold) }}
                      />
                    ) : null}
                    {g.ci95 ? (
                      <div
                        className="absolute top-1/2 h-0.5 -translate-y-1/2 rounded-full bg-primary/45"
                        style={{ left: pos(g.ci95[0]), width: `calc(${pos(g.ci95[1])} - ${pos(g.ci95[0])})` }}
                      />
                    ) : null}
                    <div
                      className="absolute top-1/2 size-2.5 -translate-1/2 rounded-full bg-primary ring-2 ring-card"
                      style={{ left: pos(g.value) }}
                    />
                  </div>
                </td>
                <td className="py-1 pl-2 text-right whitespace-nowrap tabular-nums">
                  <span className="inline-flex items-center justify-end gap-1">
                    {over ? (
                      <>
                        <XCircle className="size-3.5 shrink-0 text-destructive" aria-hidden="true" />
                        <span className="sr-only">Beyond the release limit: </span>
                      </>
                    ) : null}
                    {fmt(g.value)}
                  </span>
                  <span className="sr-only">{`${ci}, ${g.n} images`}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </figure>
  );
}

/** Key for the marks used by GroupChart; text stays in text colours. */
export function ChartKey({ metric }: { metric: EvaluationMetric }) {
  return (
    <ul aria-hidden="true" className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
      <li className="flex items-center gap-1.5">
        <span className="relative inline-block h-3 w-6">
          <span className="absolute top-1/2 h-0.5 w-full -translate-y-1/2 rounded-full bg-primary/45" />
          <span className="absolute top-1/2 left-1/2 size-2.5 -translate-1/2 rounded-full bg-primary" />
        </span>
        Group estimate with 95% CI
      </li>
      {metric.overall !== null ? (
        <li className="flex items-center gap-1.5">
          <span className="inline-block h-3 border-l border-dashed border-muted-foreground" />
          Overall {formatValue(metric.overall, metric.format)}
        </li>
      ) : null}
      {metric.gate_threshold !== null ? (
        <li className="flex items-center gap-1.5">
          <span className="inline-block h-3 border-l-2 border-destructive" />
          Release limit {formatValue(metric.gate_threshold, metric.format)}
        </li>
      ) : null}
    </ul>
  );
}
