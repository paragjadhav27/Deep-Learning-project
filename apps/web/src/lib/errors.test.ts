import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { ERROR_COPY, errorCopy } from "@/lib/errors";

const openapi = JSON.parse(
  readFileSync(resolve(__dirname, "../../../api/openapi.json"), "utf-8"),
) as { components: { schemas: { ErrorCode: { enum: string[] } } } };

describe("error copy", () => {
  it("covers every error code the API can return", () => {
    const apiCodes = openapi.components.schemas.ErrorCode.enum;
    const missing = apiCodes.filter((c) => !(c in ERROR_COPY));
    expect(missing).toEqual([]);
  });

  it("gives face-policy errors a way forward", () => {
    for (const code of ["no_face_detected", "multiple_faces_detected", "face_too_small"] as const) {
      expect(ERROR_COPY[code].recovery).toBe("replace_photo");
      expect(ERROR_COPY[code].guidance).toBeTruthy();
    }
    expect(ERROR_COPY.multiple_faces_detected.guidance).toMatch(/Adjust framing/);
  });

  it("marks transient failures as retryable in the UI", () => {
    for (const code of ["model_error", "inference_timeout", "network_error", "job_poll_timeout"] as const) {
      expect(ERROR_COPY[code].recovery).toBe("retry");
    }
    expect(ERROR_COPY.rate_limited.recovery).toBe("wait");
    expect(ERROR_COPY.session_not_found.recovery).toBe("start_over");
  });

  it("falls back safely for unknown codes", () => {
    expect(errorCopy("something_new" as never)).toBe(ERROR_COPY.internal_error);
  });
});
