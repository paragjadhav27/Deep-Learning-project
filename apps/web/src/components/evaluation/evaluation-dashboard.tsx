"use client";

import { CheckCircle2, CircleDashed, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { ChartKey, GroupChart, metricDomain } from "@/components/evaluation/group-chart";
import { DemoStatusNotice } from "@/components/site/demo-status";
import {
  ApiError,
  createApiClient,
  type Capabilities,
  type EvaluationsView,
  type EvaluationView,
  type GateCriterion,
} from "@/lib/api/client";
import {
  familyName,
  formatDate,
  formatLimit,
  formatValue,
  groupPhrase,
  STATUS_LABELS,
  TASK_NAMES,
  type EvaluationStatus,
} from "@/lib/evaluation";

const STATUS_ICONS = { passed: CheckCircle2, failed: XCircle, not_evaluated: CircleDashed } as const;
const STATUS_TONE: Record<EvaluationStatus, string> = {
  passed: "border-success/40 bg-success-subtle text-success",
  failed: "border-destructive/40 bg-destructive/10 text-destructive",
  not_evaluated: "border-border bg-muted text-muted-foreground",
};

export function StatusPill({ status }: { status: EvaluationStatus }) {
  const Icon = STATUS_ICONS[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${STATUS_TONE[status]}`}
    >
      <Icon className="size-3.5" aria-hidden="true" />
      {STATUS_LABELS[status]}
    </span>
  );
}

/** What is serving each tool right now, from GET /v1/models. */
function servingFor(caps: Capabilities | null, task: EvaluationView["task"]): string | null {
  if (!caps) return null;
  if (task === "face_detection") {
    const fd = caps.face_detection;
    return fd.enabled ? `${fd.model_id}@${fd.version}` : "Off";
  }
  const f = caps.features.find((x) => x.task === task);
  if (!f?.enabled || !f.model) return "Off";
  return `${f.model.id}${f.model.is_mock ? " (mock)" : ""}`;
}

export function EvaluationDashboard() {
  const client = useMemo(() => createApiClient(), []);
  const [data, setData] = useState<EvaluationsView | null>(null);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    client
      .evaluations(ctrl.signal)
      .then(setData)
      .catch((e: unknown) => {
        if (e instanceof ApiError) setError(e.message);
      });
    // Optional: only used to show what is serving now.
    client.capabilities(ctrl.signal).then(setCaps, () => undefined);
    return () => ctrl.abort();
  }, [client]);

  if (error) return <p role="alert">Couldn&apos;t load the evaluation results: {error}</p>;
  if (!data) return <p aria-busy="true">Loading evaluation results…</p>;

  const evals = data.evaluations;

  return (
    <div className="space-y-14">
      <section aria-labelledby="overview-title" className="space-y-4">
        <h2 id="overview-title" className="font-heading text-2xl font-semibold">
          Overview
        </h2>
        {caps ? <DemoStatusNotice caps={caps} /> : null}
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {evals.map((e) => {
            const scored = e.criteria.filter((c) => c.passed !== null);
            const passed = scored.filter((c) => c.passed).length;
            const serving = servingFor(caps, e.task);
            return (
              <li key={e.task} className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4">
                <div>
                  <p className="font-heading text-lg font-semibold">{TASK_NAMES[e.task]}</p>
                  <p className="text-sm text-muted-foreground">Candidate: {e.model_name}</p>
                </div>
                <StatusPill status={e.status} />
                <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-sm">
                  <dt className="text-muted-foreground">Limits met</dt>
                  <dd className="tabular-nums">
                    {scored.length ? `${passed} of ${e.criteria.length}` : `0 of ${e.criteria.length} measured`}
                  </dd>
                  {serving ? (
                    <>
                      <dt className="text-muted-foreground">Serving now</dt>
                      <dd className="min-w-0 break-words">
                        <code className="font-mono text-xs">{serving}</code>
                      </dd>
                    </>
                  ) : null}
                </dl>
                <a href={`#${e.task}`} className="mt-auto inline-flex min-h-11 items-center text-sm underline underline-offset-4">
                  Details<span className="sr-only">: {TASK_NAMES[e.task]}</span>
                </a>
              </li>
            );
          })}
        </ul>
      </section>

      <Method evals={evals} />

      {evals.map((e) => (
        <EvaluationSection key={e.task} evaluation={e} />
      ))}

      <section aria-labelledby="caveats-title" className="max-w-3xl space-y-3">
        <h2 id="caveats-title" className="font-heading text-2xl font-semibold">
          What these numbers don&apos;t tell you
        </h2>
        <ul className="list-disc space-y-2 pl-5 text-sm leading-relaxed">
          <li>
            Race and gender labels in FairFace are what annotators perceived. They are used only to
            check whether errors are spread evenly. FaceLens never predicts race, and its
            presentation output is not a gender identity.
          </li>
          <li>
            Race is only a rough proxy for skin tone. Results by Monk Skin Tone and by presentation
            style (glasses, head coverings, facial hair) still need a consented, annotated dataset.
          </li>
          <li>
            Age labels are 10-year bins, so the age error is distance to the bin, not error in
            years.
          </li>
          <li>
            MiVOLO v2&apos;s training data is undisclosed and may overlap FairFace, so its results
            may be optimistic.
          </li>
          <li>
            The aging evaluation will score attained age with MiVOLO v2, which failed its own
            gate. It doesn&apos;t measure whether the person stays recognisable.
          </li>
        </ul>
      </section>
    </div>
  );
}

function Method({ evals }: { evals: EvaluationView[] }) {
  const dated = evals.find((e) => e.evaluated_at && e.dataset);
  return (
    <section aria-labelledby="method-title" className="max-w-3xl space-y-3">
      <h2 id="method-title" className="font-heading text-2xl font-semibold">
        How we tested
      </h2>
      <p className="leading-relaxed">
        Each tool has limits that were written down on 25 September 2026, before any model was
        tested. A tool fails if <em>any</em> group falls outside a limit. Groups are compared by
        annotated race (7 groups), annotated gender (2) and annotated age (6 adult bands). Every
        number comes from a held-out test split that wasn&apos;t used for calibration, and comes with
        a 95% bootstrap confidence interval. A model that fails is refused when the service starts.
      </p>
      {dated ? (
        <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[max-content_1fr]">
          <dt className="font-medium">Dataset</dt>
          <dd>{dated.dataset} (CC BY 4.0)</dd>
          <dt className="font-medium">Run on</dt>
          <dd>{formatDate(dated.evaluated_at)}</dd>
          <dt className="font-medium">Full reports</dt>
          <dd>
            {evals
              .map((e) => e.report)
              .filter((r, i, all): r is string => r !== null && all.indexOf(r) === i)
              .map((r) => (
                <code key={r} className="mr-2 font-mono text-xs">
                  {r}
                </code>
              ))}
          </dd>
        </dl>
      ) : null}
    </section>
  );
}

function EvaluationSection({ evaluation: e }: { evaluation: EvaluationView }) {
  const titleId = `${e.task}-title`;
  return (
    <section id={e.task} aria-labelledby={titleId} className="scroll-mt-6 space-y-6">
      <header className="space-y-2 border-t border-border pt-8">
        <div className="flex flex-wrap items-center gap-3">
          <h2 id={titleId} className="font-heading text-2xl font-semibold">
            {TASK_NAMES[e.task]}: {e.model_name}
          </h2>
          <StatusPill status={e.status} />
        </div>
        <p className="text-sm text-muted-foreground">
          <code className="font-mono text-xs">{e.model_id}</code>
          {e.n ? ` · ${e.n.toLocaleString("en-GB")} ${e.task === "age_transformation" ? "runs" : "test images"}` : ""}
          {e.evaluated_at ? ` · ${formatDate(e.evaluated_at)}` : ""}
        </p>
        {e.status === "not_evaluated" ? (
          <p className="max-w-3xl">
            The limits below are set, and the evaluation script is ready, but it hasn&apos;t been
            run. Until it runs and passes, this model is refused and the tool uses a mock.
          </p>
        ) : null}
      </header>

      <GateTable evaluation={e} />

      {e.metrics.map((m) => {
        const domain = metricDomain(m);
        return (
          <div key={m.id} className="space-y-3">
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <h3 className="font-semibold">{m.label}</h3>
              <ChartKey metric={m} />
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              {m.families.map((f) => (
                <GroupChart key={f.family} metric={m} family={f} domain={domain} />
              ))}
            </div>
          </div>
        );
      })}
    </section>
  );
}

function ResultCell({ c }: { c: GateCriterion }) {
  if (c.passed === null) return <span className="text-muted-foreground">Not measured</span>;
  const Icon = c.passed ? CheckCircle2 : XCircle;
  return (
    <span className={`inline-flex items-center gap-1 font-medium ${c.passed ? "text-success" : "text-destructive"}`}>
      <Icon className="size-4" aria-hidden="true" />
      {c.passed ? "Pass" : "Fail"}
    </span>
  );
}

function GateTable({ evaluation: e }: { evaluation: EvaluationView }) {
  return (
    // Focusable so keyboard users can scroll it sideways on narrow screens.
    <div
      role="region"
      aria-label={`Release limits: ${TASK_NAMES[e.task]}`}
      tabIndex={0}
      className="overflow-x-auto rounded-xl border border-border bg-card"
    >
      <table className="w-full border-collapse text-sm">
        <caption className="px-2 pt-3 text-left font-semibold sm:px-4">Release limits</caption>
        <thead>
          <tr className="border-b border-border text-left text-muted-foreground">
            <th scope="col" className="px-2 py-2 sm:px-4 font-medium">Limit</th>
            <th scope="col" className="px-2 py-2 sm:px-4 font-medium">Required</th>
            <th scope="col" className="px-2 py-2 sm:px-4 font-medium">Measured (worst case)</th>
            <th scope="col" className="px-2 py-2 sm:px-4 font-medium">Result</th>
          </tr>
        </thead>
        <tbody>
          {e.criteria.map((c) => {
            const who = groupPhrase(c.worst_family, c.worst_group);
            return (
              <tr key={c.id} className="border-b border-border last:border-0 align-top">
                <th scope="row" className="px-2 py-2 sm:px-4 text-left font-normal">
                  {c.label}
                </th>
                <td className="px-2 py-2 sm:px-4 whitespace-nowrap tabular-nums">{formatLimit(c)}</td>
                <td className="px-2 py-2 sm:px-4">
                  {c.measured === null ? (
                    <span className="text-muted-foreground">—</span>
                  ) : (
                    <>
                      <span className="font-medium tabular-nums">{formatValue(c.measured, c.format)}</span>
                      {who ? <span className="text-muted-foreground">{` for ${who}`}</span> : null}
                      {c.by_family.length > 1 ? (
                        <span className="mt-0.5 block text-xs text-muted-foreground">
                          {c.by_family
                            .map((f) => `By ${familyName(f.family)}: ${formatValue(f.measured, c.format)}`)
                            .join(" · ")}
                        </span>
                      ) : null}
                    </>
                  )}
                </td>
                <td className="px-2 py-2 sm:px-4 whitespace-nowrap">
                  <ResultCell c={c} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
