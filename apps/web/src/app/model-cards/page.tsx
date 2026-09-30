import type { Metadata } from "next";

import { ModelCardsLive } from "@/components/site/model-cards-live";
import { ProsePage } from "@/components/site/prose-page";

export const metadata: Metadata = {
  title: "Model cards",
  description: "Which models FaceLens runs, their licenses, status, and known limitations.",
};

export default function ModelCardsPage() {
  return (
    <ProsePage
      title="Model cards"
      intro="The models currently serving each tool, reported live by the service. We quote only results we have measured ourselves."
    >
      <ModelCardsLive />
      <section>
        <h2>Evaluation status</h2>
        <p>
          Fairness evaluation across skin tones (Monk Skin Tone scale), age bands, and presentation
          styles is planned before any real estimator is enabled. Until then, tools either run clearly
          labelled mock models or are switched off.
        </p>
      </section>
    </ProsePage>
  );
}
