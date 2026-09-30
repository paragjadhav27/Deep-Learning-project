import type { Metadata } from "next";

import { ProsePage } from "@/components/site/prose-page";

export const metadata: Metadata = {
  title: "Privacy and data retention",
  description: "How FaceLens handles photos: what is stored, for how long, and how to delete it.",
};

export default function PrivacyPage() {
  return (
    <ProsePage
      title="Privacy and data retention"
      intro="FaceLens is built to keep as little as possible, for as short a time as possible. This page describes what the software does. It isn't a legal privacy notice, which the operator of a deployment must provide."
    >
      <section>
        <h2>What we collect</h2>
        <ul>
          <li>The photo you choose, after it has been re-encoded on your device. This removes location and camera metadata, and the original file name is never sent.</li>
          <li>Your three consent confirmations, recorded only as a version number of the consent text.</li>
          <li>No account, name, email address, or tracking cookies.</li>
        </ul>
      </section>
      <section>
        <h2>How long we keep it</h2>
        <ul>
          <li><strong>Photos and results:</strong> deleted automatically about one hour after upload, or immediately when you choose <em>Delete photo and results</em>. Storage also has an independent 1-day deletion rule as a backstop.</li>
          <li><strong>Technical records</strong> (which model version ran, how long it took, error codes): kept for 30 days to keep the service working. They contain no image, no face data, and no results.</li>
        </ul>
      </section>
      <section>
        <h2>What we never do</h2>
        <ul>
          <li>Identify people, or compare faces across photos.</li>
          <li>Infer anything beyond the one estimate you asked for.</li>
          <li>Write images, file names, or results to logs.</li>
          <li>Use your photos to train models.</li>
        </ul>
      </section>
      <section>
        <h2>Security</h2>
        <p>
          Photos are stored privately and encrypted at rest. They are reachable only with a secret
          that exists in your browser tab, or through links that expire after five minutes.
        </p>
      </section>
    </ProsePage>
  );
}
