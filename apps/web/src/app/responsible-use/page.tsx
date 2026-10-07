import type { Metadata } from "next";

import { ProsePage } from "@/components/site/prose-page";

export const metadata: Metadata = {
  title: "Responsible use",
  description: "What FaceLens estimates mean, what they don't, and where they must never be used.",
};

export default function ResponsibleUsePage() {
  return (
    <ProsePage
      title="Responsible use"
      intro="Face-attribute models are often wrong, and not wrong equally for everyone. These guidelines are part of the product, not fine print."
    >
      <section>
        <h2>Never use FaceLens for decisions about people</h2>
        <p>
          Results must not be used for hiring, policing, access control, age verification or
          eligibility, healthcare, insurance, credit, education, or any other decision that affects
          someone. FaceLens is not designed, tested, or suitable for any of these.
        </p>
      </section>
      <section>
        <h2>Age estimates are uncertain</h2>
        <p>
          The age tool estimates how old someone <em>appears</em> in one photo. Lighting, makeup,
          facial hair, pose, and image quality can move the estimate by years. That&apos;s why it
          reports a range. It is not a verified age.
        </p>
      </section>
      <section>
        <h2>Presentation is not identity</h2>
        <p>
          The perceived-presentation tool describes how a model reads a photo&apos;s appearance. It
          says nothing about a person&apos;s gender identity or sex, and it can&apos;t. The model was trained
          on two categories only, which don&apos;t represent how people actually present. It often
          answers &ldquo;uncertain&rdquo;, and that&apos;s an honest answer.
        </p>
      </section>
      <section>
        <h2>Aging previews are synthetic</h2>
        <p>
          Generated images are artificial illustrations toward a creative target. They aren&apos;t
          predictions of how anyone looked or will look. They are marked as synthetic, visibly and in
          the file. Don&apos;t use them to impersonate or mislead anyone.
        </p>
      </section>
      <section>
        <h2>Adults only, and only with permission</h2>
        <p>
          Upload photos only of yourself or of adults who have agreed. Photos of children and
          teenagers aren&apos;t supported, and the aging preview only offers adult target ages.
        </p>
      </section>
      <section>
        <h2>Fairness</h2>
        <p>
          We report measured performance across skin tones, ages, and presentation styles in the model
          cards, and make no accuracy claims we haven&apos;t measured.
        </p>
      </section>
    </ProsePage>
  );
}
