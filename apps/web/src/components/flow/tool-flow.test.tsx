import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToolFlow } from "@/components/flow/tool-flow";

// jsdom has no createImageBitmap/canvas: stub only the pixel work.
vi.mock("@/lib/image", async (orig) => {
  const actual = await orig<typeof import("@/lib/image")>();
  return {
    ...actual,
    decodeImage: vi.fn().mockResolvedValue({ width: 512, height: 512, close() {} }),
    renderToJpeg: vi.fn().mockResolvedValue(new Blob(["jpeg"], { type: "image/jpeg" })),
  };
});

const CAPS = {
  api_version: "v1",
  consent_version: "2026-09-v1",
  face_detection: { enabled: true, model_id: "yunet", version: "2026may", license: "MIT", source_url: null, min_face_side: 64, policy: "One face." },
  features: [
    { task: "age_estimation", enabled: true, model: { id: "mock-age-estimator", version: "0.1.0", is_mock: true, license: "n/a", source_url: null, intended_use: "dev", limitations: [] } },
    { task: "presentation_estimation", enabled: true, model: null },
    { task: "age_transformation", enabled: true, model: null },
  ],
  target_age_groups: [],
  presentation_uncertain_threshold: 0.75,
  session_ttl_seconds: 3600,
  max_upload_bytes: 10485760,
  accepted_formats: ["image/jpeg"],
  min_image_side: 128,
  max_image_side: 4096,
};

const SESSION = {
  session_id: "s_1",
  session_token: "tok",
  expires_at: new Date(Date.now() + 3600_000).toISOString(),
  image: { width: 512, height: 512, format: "jpeg", metadata_stripped: true, url: "/v1/sessions/s_1/image", url_expires_at: "" },
  face_check: { status: "single_face" },
};

const JOB_OK = {
  job_id: "j_1",
  session_id: "s_1",
  task: "age_estimation",
  params: {},
  status: "succeeded",
  progress: 1,
  stage: null,
  created_at: "",
  finished_at: "",
  result: { estimate_years: 34, range_years: [28, 40], interval_coverage: 0.8, disclaimer_code: "age_estimate_v1" },
  error: null,
  model: { id: "mock-age-estimator", version: "0.1.0", is_mock: true },
};

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  URL.createObjectURL = vi.fn(() => "blob:local");
  URL.revokeObjectURL = vi.fn();
});

function route(handlers: Record<string, (init: RequestInit) => Response>) {
  fetchMock.mockImplementation(async (url: string, init: RequestInit = {}) => {
    const key = `${init.method ?? "GET"} ${url}`;
    const handler = Object.entries(handlers).find(([k]) => key.startsWith(k))?.[1];
    if (!handler) throw new Error(`unexpected request ${key}`);
    return handler(init);
  });
}

async function choosePhoto() {
  const user = userEvent.setup();
  const choose = await screen.findByRole("button", { name: /choose a photo/i });
  expect(choose).toBeEnabled();
  await user.upload(screen.getByTestId("photo-input"), new File(["img"], "IMG_1234.jpg", { type: "image/jpeg" }));
  return user;
}

describe("ToolFlow (age estimate)", () => {
  it("runs upload → result → delete, with the mock clearly labelled", async () => {
    route({
      "GET /v1/models": () => json(200, CAPS),
      "POST /v1/sessions/s_1/jobs": () => json(202, JOB_OK),
      "POST /v1/sessions": () => json(201, SESSION),
      "DELETE /v1/sessions/s_1": () => new Response(null, { status: 204 }),
    });
    render(<ToolFlow slug="age" />);
    expect(await screen.findByRole("note", { name: /demonstration mode/i })).toHaveTextContent(/placeholder/i);

    const user = await choosePhoto();
    await user.click(screen.getByRole("button", { name: /upload and estimate age/i }));

    const heading = await screen.findByRole("heading", { name: /your result/i });
    await waitFor(() => expect(heading).toHaveFocus()); // focus follows the flow
    expect(screen.getByTestId("age-range")).toHaveTextContent("About 28–40 years");
    expect(screen.getByText(/placeholder \(mock model\)/i)).toBeInTheDocument();
    expect(screen.getByText(/delete automatically in about 60 minutes/i)).toBeInTheDocument();

    // The original filename never leaves the device.
    const upload = fetchMock.mock.calls.find(([u, i]) => u === "/v1/sessions" && i?.method === "POST")!;
    expect(((upload[1].body as FormData).get("image") as File).name).toBe("photo.jpg");

    await user.click(screen.getByRole("button", { name: /delete photo and results/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /delete now/i }));
    expect(await screen.findByRole("heading", { name: /deleted/i })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/v1/sessions/s_1",
      expect.objectContaining({ method: "DELETE", headers: { "X-Session-Token": "tok" } }),
    );
  });

  it("keeps the photo and explains a multiple-faces rejection", async () => {
    route({
      "GET /v1/models": () => json(200, CAPS),
      "POST /v1/sessions": () =>
        json(422, { error: { code: "multiple_faces_detected", message: "More than one face.", retryable: false } }),
    });
    render(<ToolFlow slug="age" />);
    const user = await choosePhoto();
    await user.click(screen.getByRole("button", { name: /upload and estimate age/i }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/more than one face/i);
    expect(within(alert).getByRole("button", { name: /different photo/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /adjust framing/i })).toBeInTheDocument();
  });

  it("shows a failed job with a retry that reuses the uploaded photo", async () => {
    let attempts = 0;
    route({
      "GET /v1/models": () => json(200, CAPS),
      "POST /v1/sessions/s_1/jobs": () =>
        ++attempts === 1
          ? json(202, { ...JOB_OK, status: "failed", result: null, error: { code: "model_error", message: "x", retryable: true } })
          : json(202, JOB_OK),
      "POST /v1/sessions": () => json(201, SESSION),
    });
    render(<ToolFlow slug="age" />);
    const user = await choosePhoto();
    await user.click(screen.getByRole("button", { name: /upload and estimate age/i }));
    await user.click(await screen.findByRole("button", { name: /try again/i }));
    expect(await screen.findByRole("heading", { name: /your result/i })).toBeInTheDocument();
    const uploads = fetchMock.mock.calls.filter(([u, i]) => u === "/v1/sessions" && i?.method === "POST");
    expect(uploads).toHaveLength(1);
  });

  it("offers retry when the service can't be reached", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<ToolFlow slug="age" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn.t reach the service/i);
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });
});
