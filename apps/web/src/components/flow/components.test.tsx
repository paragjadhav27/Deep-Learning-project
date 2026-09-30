import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AgeResult } from "@/components/flow/age-result";
import { BeforeAfter } from "@/components/flow/before-after";
import { ConsentPanel, isConsentComplete } from "@/components/flow/consent-panel";
import { ErrorState } from "@/components/flow/error-state";
import { PresentationResult } from "@/components/flow/presentation-result";
import { TargetAgeSelector } from "@/components/flow/target-age-selector";
import { ApiError, type Consent, type TargetGroupView } from "@/lib/api/client";

describe("ConsentPanel", () => {
  it("requires all three confirmations", async () => {
    let value: Consent = { has_permission: false, is_adult: false, accepts_limitations: false };
    const onChange = vi.fn((v: Consent) => (value = v));
    const { rerender } = render(<ConsentPanel value={value} onChange={onChange} />);
    for (const name of [/permission/i, /18 or older/i, /uncertain and illustrative/i]) {
      await userEvent.click(screen.getByRole("checkbox", { name }));
      rerender(<ConsentPanel value={value} onChange={onChange} />);
    }
    expect(isConsentComplete(value)).toBe(true);
    // Each checkbox has a description wired up for screen readers.
    expect(screen.getByRole("checkbox", { name: /18 or older/i })).toHaveAccessibleDescription(
      /children or teenagers/i,
    );
  });
});

describe("TargetAgeSelector", () => {
  const groups: TargetGroupView[] = [
    { group: "child", available: false, reason: "Turned off pending review." },
    { group: "teen", available: false, reason: "Turned off pending review." },
    { group: "young_adult", available: true, reason: null },
    { group: "middle_aged_adult", available: true, reason: null },
    { group: "older_adult", available: true, reason: null },
  ];

  it("explains unavailable groups and blocks selecting them", async () => {
    const onChange = vi.fn();
    render(<TargetAgeSelector groups={groups} value={null} onChange={onChange} />);
    const child = screen.getByRole("radio", { name: /child/i });
    expect(child).toBeDisabled();
    expect(child).toHaveAccessibleDescription(/pending review/i);
    await userEvent.click(screen.getByRole("radio", { name: /older adult/i }));
    expect(onChange).toHaveBeenCalledWith("older_adult");
    expect(screen.getByText(/isn.t a prediction/i)).toBeInTheDocument();
  });
});

describe("result copy", () => {
  it("leads the age result with the range", () => {
    render(
      <AgeResult
        result={{ estimate_years: 34, range_years: [28, 40], interval_coverage: 0.8, disclaimer_code: "age_estimate_v1" }}
      />,
    );
    expect(screen.getByTestId("age-range")).toHaveTextContent("About 28–40 years");
    expect(screen.getByText(/not a verified or legal age/i)).toBeInTheDocument();
  });

  it.each([
    ["feminine_presenting", 0.9, 0.1],
    ["masculine_presenting", 0.1, 0.9],
    ["uncertain", 0.55, 0.45],
  ] as const)("presentation result (%s) never states identity", (outcome, f, m) => {
    const { container } = render(
      <PresentationResult
        result={{
          outcome,
          scores: { feminine_presenting: f, masculine_presenting: m },
          uncertain_threshold: 0.75,
          disclaimer_code: "presentation_estimate_v1",
        }}
      />,
    );
    const text = container.textContent ?? "";
    expect(text).toMatch(/model (perceives|is uncertain)/i);
    expect(text).toMatch(/nothing about a person.s gender identity or sex/i);
    expect(text).not.toMatch(/\byou are\b|\bthis person is\b|\b(is|are) (a )?(male|female|man|woman)\b/i);
  });
});

describe("ErrorState", () => {
  it("offers the right recovery action", () => {
    const onReplacePhoto = vi.fn();
    render(
      <ErrorState error={new ApiError("multiple_faces_detected", "", false, 422)} onReplacePhoto={onReplacePhoto} />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/more than one face/i);
    fireEvent.click(screen.getByRole("button", { name: /different photo/i }));
    expect(onReplacePhoto).toHaveBeenCalled();
  });

  it("disables retry during a rate-limit wait", () => {
    render(
      <ErrorState error={new ApiError("rate_limited", "Too many", true, 429, 20)} onRetry={() => {}} />,
    );
    expect(screen.getByRole("button", { name: /try again/i })).toBeDisabled();
    expect(screen.getByText(/try again in 20 seconds/i)).toBeInTheDocument();
  });

  it("shows the request id for support but no internal detail", () => {
    render(<ErrorState error={new ApiError("model_error", "Boom", true, 502, null, "req-123")} onRetry={() => {}} />);
    expect(screen.getByText("req-123")).toBeInTheDocument();
    expect(screen.queryByText("Boom")).not.toBeInTheDocument(); // curated copy wins
  });
});

describe("BeforeAfter", () => {
  it("is keyboard-operable with meaningful value text", () => {
    render(<BeforeAfter beforeSrc="blob:a" afterSrc="/api/x" afterAlt="Synthetic illustration" />);
    const slider = screen.getByRole("slider", { name: /comparison/i });
    expect(slider).toHaveAttribute("aria-valuetext", "50% original, 50% synthetic");
    fireEvent.change(slider, { target: { value: "80" } });
    expect(slider).toHaveAttribute("aria-valuetext", "80% original, 20% synthetic");
    fireEvent.click(screen.getByRole("button", { name: /side by side/i }));
    expect(screen.getByRole("img", { name: "Synthetic illustration" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /original photo/i })).toBeInTheDocument();
  });
});

describe("UnevaluatedBanner", () => {
  it("distinguishes a failed evaluation from a missing one", async () => {
    const { UnevaluatedBanner } = await import("@/components/flow/mock-banner");
    const { rerender } = render(<UnevaluatedBanner modelId="mivolo-v2-face" evaluated />);
    const note = screen.getByRole("note", { name: /not passed evaluation/i });
    expect(note).toHaveTextContent(/failed its fairness evaluation/i);
    expect(note).toHaveTextContent("mivolo-v2-face");
    rerender(<UnevaluatedBanner modelId="sam-ffhq-aging" evaluated={false} />);
    expect(note).toHaveTextContent(/has not been evaluated yet/i);
  });
});
