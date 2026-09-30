import type { ErrorCode } from "@/lib/api/client";

/** What the UI offers after an error. */
export type Recovery = "replace_photo" | "retry" | "start_over" | "wait" | "none";

export interface ErrorCopy {
  title: string;
  /** Guidance shown under the title. When absent, the API's own message is used. */
  guidance?: string;
  recovery: Recovery;
}

/**
 * User-facing copy for every error the app can hit. `Record<ErrorCode, …>` makes the
 * compiler fail when the API adds a code (types are generated from OpenAPI) and it
 * has no copy here.
 */
export const ERROR_COPY: Record<ErrorCode, ErrorCopy> = {
  invalid_file_type: {
    title: "That file type isn't supported",
    guidance: "Choose a JPEG, PNG, or WebP photo.",
    recovery: "replace_photo",
  },
  file_too_large: {
    title: "That file is too large",
    guidance: "Choose a smaller photo, or crop this one before uploading.",
    recovery: "replace_photo",
  },
  image_too_small: {
    title: "That photo is too small",
    guidance: "Use a photo at least 128 pixels on each side.",
    recovery: "replace_photo",
  },
  image_too_large: {
    title: "That photo's dimensions are too large",
    guidance: "Choose a smaller photo.",
    recovery: "replace_photo",
  },
  corrupt_image: {
    title: "We couldn't read that photo",
    guidance: "The file may be damaged. Try exporting it again or choose another photo.",
    recovery: "replace_photo",
  },
  consent_required: {
    title: "Please confirm the statements above",
    guidance: "All three confirmations are needed before a photo can be uploaded.",
    recovery: "none",
  },
  no_face_detected: {
    title: "We couldn't find a face",
    guidance:
      "Try a clear, well-lit photo where the face is visible and facing the camera. Sunglasses, heavy shadows, or strong angles can make this harder.",
    recovery: "replace_photo",
  },
  multiple_faces_detected: {
    title: "We found more than one face",
    guidance:
      "These tools work on one person at a time. Use \"Adjust framing\" to crop other people out, or choose a different photo.",
    recovery: "replace_photo",
  },
  face_too_small: {
    title: "The face is too small in this photo",
    guidance: "Use \"Adjust framing\" to zoom in on the face, or choose a closer photo.",
    recovery: "replace_photo",
  },
  unsupported_target_age_group: {
    title: "That target age group isn't available",
    recovery: "none",
  },
  feature_disabled: {
    title: "This tool is currently unavailable",
    guidance: "Please try again later.",
    recovery: "none",
  },
  rate_limited: {
    title: "Please wait a moment",
    guidance: "You've made several requests in a short time.",
    recovery: "wait",
  },
  session_not_found: {
    title: "This session has ended",
    guidance:
      "Photos and results are deleted automatically after a short time. Please start again with your photo.",
    recovery: "start_over",
  },
  job_not_found: {
    title: "This session has ended",
    guidance: "Please start again with your photo.",
    recovery: "start_over",
  },
  result_not_found: {
    title: "This result is no longer available",
    guidance: "It may have been deleted or expired.",
    recovery: "start_over",
  },
  job_not_cancellable: {
    title: "This request already finished",
    recovery: "none",
  },
  adults_only: {
    title: "We can't process this photo",
    guidance: "These tools only support photos of adults.",
    recovery: "replace_photo",
  },
  model_error: {
    title: "The model couldn't process this photo",
    guidance: "This is usually temporary. You can try again.",
    recovery: "retry",
  },
  inference_timeout: {
    title: "Processing took too long",
    guidance: "This is usually temporary. You can try again.",
    recovery: "retry",
  },
  job_poll_timeout: {
    title: "This is taking longer than expected",
    guidance: "You can try again. Your photo is still stored until it expires or you delete it.",
    recovery: "retry",
  },
  validation_error: {
    title: "Something about that request wasn't valid",
    recovery: "start_over",
  },
  network_error: {
    title: "We couldn't reach the service",
    guidance: "Check your connection and try again.",
    recovery: "retry",
  },
  internal_error: {
    title: "Something went wrong on our side",
    guidance: "Please try again.",
    recovery: "retry",
  },
  not_found: { title: "Not found", recovery: "start_over" },
  method_not_allowed: { title: "Something went wrong", recovery: "start_over" },
  http_error: { title: "Something went wrong", guidance: "Please try again.", recovery: "retry" },
};

export function errorCopy(code: ErrorCode): ErrorCopy {
  return ERROR_COPY[code] ?? ERROR_COPY.internal_error;
}
