import type { Metadata } from "next";

import { EvaluationDashboard } from "@/components/evaluation/evaluation-dashboard";

export const metadata: Metadata = {
  title: "Evaluation results",
  description:
    "Measured accuracy and fairness of each candidate model against limits set before testing, by group, with confidence intervals.",
};

export default function EvaluationPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
      <h1 className="font-heading text-3xl font-semibold sm:text-4xl">Evaluation results</h1>
      <p className="mt-4 max-w-3xl text-lg text-muted-foreground">
        Before a real model can serve a tool, it has to meet accuracy and fairness limits for every
        group we can measure. This page shows each candidate&apos;s measured results, including the
        ones that failed. It is reported live by the service.
      </p>
      <div className="mt-10">
        <EvaluationDashboard />
      </div>
    </div>
  );
}
