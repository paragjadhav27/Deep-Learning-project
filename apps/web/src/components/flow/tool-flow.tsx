"use client";

import { Download, ImagePlus, RefreshCw, Scan, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";


import { AgeResult } from "@/components/flow/age-result";
import { BeforeAfter } from "@/components/flow/before-after";
import { DeleteSessionButton } from "@/components/flow/delete-session-button";
import { ErrorState } from "@/components/flow/error-state";
import { FramingControls, FramingPreview } from "@/components/flow/framing-editor";
import { JobStatus } from "@/components/flow/job-status";
import { MockBanner } from "@/components/flow/mock-banner";
import { PresentationResult } from "@/components/flow/presentation-result";
import { PrivacyNote } from "@/components/flow/privacy-note";
import { RetentionCountdown } from "@/components/flow/retention-countdown";
import { TargetAgeSelector } from "@/components/flow/target-age-selector";
import { UploadDropzone } from "@/components/flow/upload-dropzone";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ApiError,
  apiUrl,
  createApiClient,
  type Capabilities,
  type Consent,
  type JobView,
  type TargetAgeGroup,
} from "@/lib/api/client";
import { checkFile, decodeImage, DEFAULT_FRAMING, renderToJpeg, type Framing } from "@/lib/image";
import { runJob } from "@/lib/jobs";
import { TARGET_GROUP_LABELS, TOOLS, type ToolSlug } from "@/lib/tools";

type Phase = "setup" | "uploading" | "processing" | "result" | "failed" | "deleted";

interface Photo {
  url: string; // local blob: URL of the chosen file (never uploaded as-is)
  bitmap: ImageBitmap;
}

interface SessionInfo {
  id: string;
  token: string;
  expiresAt: string;
  beforeUrl: string; // local blob: URL of exactly what was uploaded
}

/** Remount ErrorState per distinct error so its countdown restarts. */
const errorKey = (e: ApiError) => `${e.code}:${e.requestId ?? ""}:${e.retryAfterSeconds ?? ""}`;

// There's no consent step in the UI: choosing a photo implies these.
const IMPLIED_CONSENT: Consent = { has_permission: true, is_adult: true, accepts_limitations: true };

export function ToolFlow({ slug }: { slug: ToolSlug }) {
  const tool = TOOLS[slug];
  const isAging = tool.task === "age_transformation";
  const client = useMemo(() => createApiClient(), []);

  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [capsError, setCapsError] = useState<ApiError | null>(null);
  const [photo, setPhoto] = useState<Photo | null>(null);
  const [framing, setFraming] = useState<Framing>(DEFAULT_FRAMING);
  const [showFraming, setShowFraming] = useState(false);
  const [target, setTarget] = useState<TargetAgeGroup | null>(null);
  const [phase, setPhase] = useState<Phase>("setup");
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [job, setJob] = useState<JobView | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [announcement, setAnnouncement] = useState("");

  const pollAbort = useRef<AbortController | null>(null);
  const phaseHeading = useRef<HTMLHeadingElement>(null);
  const firstRender = useRef(true);

  // ---- capabilities -------------------------------------------------------------
  const [capsAttempt, setCapsAttempt] = useState(0);
  useEffect(() => {
    const ctrl = new AbortController();
    client
      .capabilities(ctrl.signal)
      .then((c) => {
        setCaps(c);
        setCapsError(null);
      })
      .catch((e: unknown) => {
        if (e instanceof ApiError) setCapsError(e);
      });
    return () => ctrl.abort();
  }, [client, capsAttempt]);
  const retryCaps = () => {
    setCapsError(null);
    setCapsAttempt((n) => n + 1);
  };

  const feature = caps?.features.find((f) => f.task === tool.task);
  const model = feature?.model ?? null;

  // ---- focus management: move focus to the new step's heading ----------------------
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    phaseHeading.current?.focus();
  }, [phase]);

  // Release local object URLs and stop polling on unmount.
  const latest = useRef({ photo, session });
  useEffect(() => {
    latest.current = { photo, session };
  });
  useEffect(
    () => () => {
      pollAbort.current?.abort();
      if (latest.current.photo) URL.revokeObjectURL(latest.current.photo.url);
      if (latest.current.session) URL.revokeObjectURL(latest.current.session.beforeUrl);
    },
    [],
  );

  // ---- helpers -------------------------------------------------------------------
  const discardSession = useCallback(
    (s: SessionInfo | null) => {
      if (!s) return;
      URL.revokeObjectURL(s.beforeUrl);
      // Best effort: the server also deletes it at TTL expiry.
      client.deleteSession(s.id, s.token).catch(() => undefined);
    },
    [client],
  );

  function resetPhoto() {
    if (photo) URL.revokeObjectURL(photo.url);
    discardSession(session);
    setSession(null);
    setPhoto(null);
    setFraming(DEFAULT_FRAMING);
    setShowFraming(false);
    setJob(null);
  }

  async function onFile(file: File) {
    setError(null);
    if (!caps) return;
    const check = checkFile(file, caps.max_upload_bytes);
    if (!check.ok) {
      setError(new ApiError(check.code, "", false, 0));
      return;
    }
    let bitmap: ImageBitmap;
    try {
      bitmap = await decodeImage(file);
    } catch {
      setError(new ApiError("corrupt_image", "", false, 0));
      return;
    }
    if (bitmap.width < caps.min_image_side || bitmap.height < caps.min_image_side) {
      setError(new ApiError("image_too_small", "", false, 0));
      return;
    }
    resetPhoto();
    setPhoto({ url: URL.createObjectURL(file), bitmap });
    setPhase("setup");
    setAnnouncement("Photo selected. Review it below.");
  }

  function onFramingChange(next: Framing) {
    setFraming(next);
    // A different framing means different pixels: the old server copy is now stale.
    if (session) {
      discardSession(session);
      setSession(null);
    }
  }

  async function startJob(s: SessionInfo, targetGroup: TargetAgeGroup | null) {
    pollAbort.current?.abort();
    const ctrl = new AbortController();
    pollAbort.current = ctrl;
    setError(null);
    setJob(null);
    setPhase("processing");
    try {
      const final = await runJob({
        client,
        sessionId: s.id,
        token: s.token,
        task: tool.task,
        target: targetGroup ?? undefined,
        onUpdate: setJob,
        signal: ctrl.signal,
      });
      if (final.status === "succeeded") {
        setPhase("result");
        setAnnouncement("Your result is ready.");
      } else if (final.status === "failed" && final.error) {
        setError(new ApiError(final.error.code, final.error.message, final.error.retryable, 0));
        setPhase("failed");
      } else {
        setPhase("setup");
      }
    } catch (e) {
      if (ctrl.signal.aborted) return; // cancelled by the user
      setError(e instanceof ApiError ? e : new ApiError("internal_error", "", true, 0));
      setPhase("failed");
    }
  }

  async function submit() {
    if (!photo || !caps || (isAging && !target)) return;
    setError(null);
    if (session) return startJob(session, target);
    setPhase("uploading");
    try {
      const blob = await renderToJpeg(photo.bitmap, framing);
      const created = await client.createSession(blob, IMPLIED_CONSENT);
      const s: SessionInfo = {
        id: created.session_id,
        token: created.session_token,
        expiresAt: created.expires_at,
        beforeUrl: URL.createObjectURL(blob),
      };
      setSession(s);
      await startJob(s, target);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError("internal_error", "", true, 0));
      setPhase("setup");
    }
  }

  async function cancel() {
    setCancelling(true);
    pollAbort.current?.abort();
    try {
      if (job && session && (job.status === "queued" || job.status === "running")) {
        await client.cancelJob(job.job_id, session.token).catch(() => undefined);
      }
    } finally {
      setCancelling(false);
      setJob(null);
      setPhase("setup");
      setAnnouncement("Cancelled. Your photo is still selected.");
    }
  }

  async function deleteEverything() {
    pollAbort.current?.abort();
    if (session) {
      try {
        await client.deleteSession(session.id, session.token);
      } catch (e) {
        // Already gone (expired or deleted) is the outcome the user asked for.
        if (!(e instanceof ApiError && e.code === "session_not_found")) throw e;
      }
      URL.revokeObjectURL(session.beforeUrl);
    }
    if (photo) URL.revokeObjectURL(photo.url);
    setSession(null);
    setPhoto(null);
    setJob(null);
    setError(null);
    setFraming(DEFAULT_FRAMING);
    setPhase("deleted");
    setAnnouncement("Your photo and results were deleted.");
  }

  function startOver() {
    pollAbort.current?.abort();
    resetPhoto();
    setError(null);
    setPhase("setup");
  }

  async function download() {
    if (!session || !job) return;
    try {
      // Signed links are short-lived: fetch a fresh one at click time.
      const fresh = await client.getJob(job.job_id, session.token);
      const result = fresh.result;
      if (!result || !("image_url" in result)) return;
      const res = await fetch(apiUrl(result.image_url), { cache: "no-store" });
      if (!res.ok) throw new ApiError("result_not_found", "", false, res.status);
      const objectUrl = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = objectUrl;
      a.download = `facelens-synthetic-${result.target_age_group}.jpg`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError("network_error", "", true, 0));
    }
  }

  // ---- render --------------------------------------------------------------------
  const submitBlocker = !photo
    ? "Choose a photo first."
    : isAging && !target
      ? "Choose a target age group."
      : null;

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <p className="sr-only" role="status" aria-live="polite">
        {announcement}
      </p>

      <header className="max-w-3xl space-y-3">
        <p className="text-sm">
          <Link href="/#tools" className="text-muted-foreground underline-offset-4 hover:underline">
            All tools
          </Link>
        </p>
        <h1 className="font-heading text-3xl font-semibold sm:text-4xl">{tool.name}</h1>
        <p className="text-lg text-muted-foreground">{tool.whatItReturns}</p>
      </header>

      <div className="mt-8 grid gap-10 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-8">
          {capsError ? (
            <ErrorState error={capsError} onRetry={retryCaps} />
          ) : !caps ? (
            <p aria-busy="true" className="text-muted-foreground">
              Loading the tool…
            </p>
          ) : !feature?.enabled ? (
            <ErrorState error={new ApiError("feature_disabled", "", false, 403)} />
          ) : (
            <>
              {model?.is_mock ? <MockBanner modelId={model.id} /> : null}

              {phase === "setup" || phase === "failed" ? (
                <SetupStep
                  headingRef={phaseHeading}
                  phase={phase}
                  caps={caps}
                  photo={photo}
                  framing={framing}
                  onFramingChange={onFramingChange}
                  showFraming={showFraming}
                  onToggleFraming={() => setShowFraming((v) => !v)}
                  onFile={onFile}
                  onRemovePhoto={() => {
                    resetPhoto();
                    setError(null);
                    setAnnouncement("Photo removed.");
                  }}
                  isAging={isAging}
                  target={target}
                  onTarget={setTarget}
                  error={error}
                  onRetry={() => (session ? startJob(session, target) : submit())}
                  onStartOver={startOver}
                  submitLabel={session ? tool.action : `Upload and ${tool.action.toLowerCase()}`}
                  submitBlocker={submitBlocker}
                  onSubmit={submit}
                />
              ) : null}

              {phase === "uploading" || phase === "processing" ? (
                <section aria-labelledby="processing-title" className="space-y-4">
                  <h2 id="processing-title" ref={phaseHeading} tabIndex={-1} className="font-heading text-2xl font-semibold outline-none">
                    Working on it
                  </h2>
                  <JobStatus
                    phase={phase}
                    job={job}
                    target={isAging ? target : null}
                    onCancel={cancel}
                    cancelling={cancelling}
                  />
                </section>
              ) : null}

              {phase === "result" && job?.result && session ? (
                <section aria-labelledby="result-title" className="space-y-6">
                  <div className="flex flex-wrap items-center gap-3">
                    <h2 id="result-title" ref={phaseHeading} tabIndex={-1} className="font-heading text-2xl font-semibold outline-none">
                      Your result
                    </h2>
                    {job.model?.is_mock ? <Badge variant="outline">Placeholder (mock model)</Badge> : null}
                  </div>

                  <div className="rounded-xl border border-border bg-card p-5 sm:p-6">
                    {"range_years" in job.result ? <AgeResult result={job.result} /> : null}
                    {"outcome" in job.result ? <PresentationResult result={job.result} /> : null}
                    {"image_url" in job.result ? (
                      <div className="space-y-4">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge className="bg-accent text-accent-foreground">Synthetic image</Badge>
                          <p className="text-sm">
                            Creative target:{" "}
                            <strong>{TARGET_GROUP_LABELS[job.result.target_age_group].label}</strong>. This is
                            an illustration, not a prediction of appearance.
                          </p>
                        </div>
                        <BeforeAfter
                          beforeSrc={session.beforeUrl}
                          afterSrc={apiUrl(job.result.image_url)}
                          afterAlt={`Synthetic illustration edited toward the ${TARGET_GROUP_LABELS[job.result.target_age_group].label.toLowerCase()} age group`}
                        />
                        <Button type="button" variant="outline" className="min-h-11" onClick={download}>
                          <Download aria-hidden="true" />
                          Download synthetic image
                        </Button>
                      </div>
                    ) : null}
                  </div>

                  {error ? (
                    <ErrorState key={errorKey(error)} error={error} onRetry={download} onStartOver={startOver} />
                  ) : null}

                  {isAging && caps ? (
                    <div className="space-y-4 rounded-xl border border-border bg-card p-5">
                      <h3 className="font-semibold">Try a different target</h3>
                      <p className="text-sm text-muted-foreground">
                        Uses the photo you already uploaded, so there&apos;s no need to upload it again.
                      </p>
                      <TargetAgeSelector
                        idPrefix="regen"
                        groups={caps.target_age_groups}
                        value={target}
                        onChange={setTarget}
                      />
                      <Button type="button" className="min-h-11" onClick={() => startJob(session, target)} disabled={!target}>
                        <RefreshCw aria-hidden="true" />
                        Generate again
                      </Button>
                    </div>
                  ) : null}

                  <RetentionCountdown expiresAt={session.expiresAt} />
                  <div className="flex flex-wrap gap-3">
                    <DeleteSessionButton onConfirm={deleteEverything} />
                    <Button type="button" variant="outline" className="min-h-11" onClick={startOver}>
                      <ImagePlus aria-hidden="true" />
                      Try another photo
                    </Button>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Choosing &ldquo;Try another photo&rdquo; also deletes this photo and its results.
                  </p>
                  <PrivacyNote ttlSeconds={caps.session_ttl_seconds} variant="result" />
                </section>
              ) : null}

              {phase === "deleted" ? (
                <section aria-labelledby="deleted-title" className="space-y-4 rounded-xl border border-border bg-card p-6">
                  <h2 id="deleted-title" ref={phaseHeading} tabIndex={-1} className="font-heading text-2xl font-semibold outline-none">
                    Deleted
                  </h2>
                  <p>Your photo and all results have been removed from our servers.</p>
                  <Button type="button" className="min-h-11" onClick={() => setPhase("setup")}>
                    Start again
                  </Button>
                </section>
              ) : null}
            </>
          )}
        </div>

        <aside aria-labelledby="about-title" className="space-y-5 lg:sticky lg:top-6 lg:self-start">
          <h2 id="about-title" className="font-heading text-xl font-semibold">
            Limitations
          </h2>
          <ul className="list-disc space-y-2 pl-5 text-sm text-muted-foreground">
            {tool.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
          {model ? (
            <div className="rounded-lg border border-border p-4 text-sm">
              <p className="font-medium">Model</p>
              <p className="mt-1 text-muted-foreground">
                <code className="font-mono text-xs">
                  {model.id}@{model.version}
                </code>
                {model.is_mock ? " (mock)" : null}
              </p>
              <Link href="/model-cards" className="mt-2 inline-flex min-h-11 items-center underline underline-offset-4">
                Read the model card
              </Link>
            </div>
          ) : null}
          <Link href="/responsible-use" className="inline-flex min-h-11 items-center text-sm underline underline-offset-4">
            Responsible use guidelines
          </Link>
        </aside>
      </div>
    </div>
  );
}

interface SetupStepProps {
  headingRef: React.RefObject<HTMLHeadingElement | null>;
  phase: Phase;
  caps: Capabilities;
  photo: Photo | null;
  framing: Framing;
  onFramingChange: (f: Framing) => void;
  showFraming: boolean;
  onToggleFraming: () => void;
  onFile: (f: File) => void;
  onRemovePhoto: () => void;
  isAging: boolean;
  target: TargetAgeGroup | null;
  onTarget: (t: TargetAgeGroup) => void;
  error: ApiError | null;
  onRetry: () => void;
  onStartOver: () => void;
  submitLabel: string;
  submitBlocker: string | null;
  onSubmit: () => void;
}

function SetupStep({ headingRef, ...p }: SetupStepProps) {
  const fileInput = useRef<HTMLInputElement>(null);
  const replace = () => fileInput.current?.click();

  return (
    <section aria-labelledby="setup-title" className="space-y-8">
      <h2 id="setup-title" ref={headingRef} tabIndex={-1} className="sr-only outline-none">
        {p.phase === "failed" ? "Something went wrong" : "Set up"}
      </h2>

      <div className="space-y-4">
        <h3 className="font-heading text-xl font-semibold">Your photo</h3>
        {!p.photo ? (
          <UploadDropzone
            disabled={false}
            maxBytes={p.caps.max_upload_bytes}
            minSide={p.caps.min_image_side}
            onFile={p.onFile}
          />
        ) : (
          <div className="space-y-4 rounded-xl border border-border bg-card p-5">
            <FramingPreview
              src={p.photo.url}
              width={p.photo.bitmap.width}
              height={p.photo.bitmap.height}
              framing={p.framing}
              alt="Preview of the area of your photo that will be uploaded"
            />
            <div className="flex flex-wrap justify-center gap-2">
              <Button
                type="button"
                variant="outline"
                className="min-h-11"
                aria-expanded={p.showFraming}
                aria-controls="framing-controls"
                onClick={p.onToggleFraming}
              >
                <Scan aria-hidden="true" />
                {p.showFraming ? "Hide framing" : "Adjust framing"}
              </Button>
              <Button type="button" variant="outline" className="min-h-11" onClick={replace}>
                <ImagePlus aria-hidden="true" />
                Replace photo
              </Button>
              <Button type="button" variant="ghost" className="min-h-11" onClick={p.onRemovePhoto}>
                <X aria-hidden="true" />
                Remove photo
              </Button>
            </div>
            <input
              ref={fileInput}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className="sr-only"
              tabIndex={-1}
              aria-hidden="true"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) p.onFile(f);
                e.target.value = "";
              }}
            />
            {p.showFraming ? (
              <div id="framing-controls">
                <FramingControls framing={p.framing} onChange={p.onFramingChange} />
              </div>
            ) : null}
          </div>
        )}
        <PrivacyNote ttlSeconds={p.caps.session_ttl_seconds} variant="upload" />
      </div>

      {p.isAging ? (
        <div className="rounded-xl border border-border bg-card p-5 sm:p-6">
          <TargetAgeSelector groups={p.caps.target_age_groups} value={p.target} onChange={p.onTarget} />
        </div>
      ) : null}

      {p.error ? (
        <ErrorState
          key={errorKey(p.error)}
          error={p.error}
          onReplacePhoto={p.photo ? replace : undefined}
          onRetry={p.onRetry}
          onStartOver={p.onStartOver}
        />
      ) : null}

      <div className="space-y-2">
        <Button
          type="button"
          size="lg"
          className="min-h-12 px-6 text-base"
          disabled={p.submitBlocker !== null}
          aria-describedby={p.submitBlocker ? "submit-blocker" : undefined}
          onClick={p.onSubmit}
        >
          {p.submitLabel}
        </Button>
        {p.submitBlocker ? (
          <p id="submit-blocker" className="text-sm text-muted-foreground">
            {p.submitBlocker}
          </p>
        ) : null}
      </div>
    </section>
  );
}
