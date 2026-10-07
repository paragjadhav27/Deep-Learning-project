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
          The age and perceived-presentation model (MiVOLO v2) was evaluated on the FairFace test
          split across annotated race, perceived gender, and age bands. It missed some of the fairness
          limits we set in advance, so it runs here as a non-commercial experiment rather than an
          approved release. The aging model (SAM) hasn&apos;t been evaluated yet. Evaluation by skin
          tone (Monk Skin Tone scale) and presentation style still needs a consented, annotated dataset.
        </p>
      </section>
    </ProsePage>
  );
}
