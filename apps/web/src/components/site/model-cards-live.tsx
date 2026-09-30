"use client";

import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { ApiError, createApiClient, type Capabilities } from "@/lib/api/client";
import { TOOLS, TOOL_ORDER } from "@/lib/tools";

export function ModelCardsLive() {
  const client = useMemo(() => createApiClient(), []);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    client
      .capabilities(ctrl.signal)
      .then(setCaps)
      .catch((e: unknown) => {
        if (e instanceof ApiError) setError(e.message);
      });
    return () => ctrl.abort();
  }, [client]);

  if (error) return <p role="alert">Couldn&apos;t load model information: {error}</p>;
  if (!caps) return <p aria-busy="true">Loading model information…</p>;

  const fd = caps.face_detection;
  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-border bg-card p-5">
        <h2>Face detection</h2>
        <p className="text-sm text-muted-foreground">
          {fd.enabled ? (
            <>
              <code className="font-mono">
                {fd.model_id}@{fd.version}
              </code>{" "}
              · license {fd.license} · minimum face size {fd.min_face_side}px
            </>
          ) : (
            "Face detection is turned off in this development environment."
          )}
        </p>
        <p className="text-sm">{fd.policy}</p>
      </section>
      {TOOL_ORDER.map((slug) => {
        const tool = TOOLS[slug];
        const feature = caps.features.find((f) => f.task === tool.task);
        const m = feature?.model;
        return (
          <section key={slug} className="rounded-xl border border-border bg-card p-5">
            <div className="flex flex-wrap items-center gap-2">
              <h2>{tool.name}</h2>
              {!feature?.enabled ? <Badge variant="outline">Off</Badge> : null}
              {m?.is_mock ? <Badge className="bg-warning-subtle text-warning">Mock model</Badge> : null}
            </div>
            {m ? (
              <dl className="mt-3 grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[max-content_1fr]">
                <dt className="font-medium">Model</dt>
                <dd>
                  <code className="font-mono">
                    {m.id}@{m.version}
                  </code>
                </dd>
                <dt className="font-medium">License</dt>
                <dd>{m.license}</dd>
                <dt className="font-medium">Intended use</dt>
                <dd>{m.intended_use}</dd>
                <dt className="font-medium">Limitations</dt>
                <dd>
                  <ul>
                    {m.limitations.map((l) => (
                      <li key={l}>{l}</li>
                    ))}
                  </ul>
                </dd>
              </dl>
            ) : (
              <p className="text-sm text-muted-foreground">No model is serving this tool.</p>
            )}
          </section>
        );
      })}
    </div>
  );
}
