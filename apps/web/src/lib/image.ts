/**
 * Client-side photo preparation. The chosen photo is decoded, optionally cropped, scaled
 * down, and re-encoded on the device, so EXIF (including GPS) and the original filename
 * never leave the browser. The server sanitizes again regardless (defense in depth).
 */

export const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp"] as const;
export const OUTPUT_MAX_SIDE = 2048;

export interface Framing {
  /** 1 = whole photo; up to 4 = zoomed in. */
  zoom: number;
  /** Horizontal and vertical position of the crop window's centre, 0–1. */
  x: number;
  y: number;
}

export const DEFAULT_FRAMING: Framing = { zoom: 1, x: 0.5, y: 0.5 };

export interface Rect {
  sx: number;
  sy: number;
  sw: number;
  sh: number;
}

/** The source rectangle for a framing. Keeps the photo's aspect ratio and stays in bounds. */
export function cropRect(width: number, height: number, framing: Framing): Rect {
  const zoom = Math.min(4, Math.max(1, framing.zoom));
  const sw = width / zoom;
  const sh = height / zoom;
  const clamp = (v: number, max: number) => Math.min(Math.max(v, 0), max);
  const sx = clamp(framing.x * width - sw / 2, width - sw);
  const sy = clamp(framing.y * height - sh / 2, height - sh);
  return { sx, sy, sw, sh };
}

/** Output size: the crop scaled so its longest side is at most `maxSide`. */
export function outputSize(rect: Rect, maxSide = OUTPUT_MAX_SIDE): { w: number; h: number } {
  const scale = Math.min(1, maxSide / Math.max(rect.sw, rect.sh));
  return { w: Math.max(1, Math.round(rect.sw * scale)), h: Math.max(1, Math.round(rect.sh * scale)) };
}

export type LocalCheck =
  | { ok: true }
  | { ok: false; code: "invalid_file_type" | "file_too_large" };

export function checkFile(file: File, maxBytes: number): LocalCheck {
  if (!(ACCEPTED_TYPES as readonly string[]).includes(file.type)) {
    return { ok: false, code: "invalid_file_type" };
  }
  // Allow some headroom: the photo is re-encoded (usually smaller) before upload.
  if (file.size > maxBytes * 3) return { ok: false, code: "file_too_large" };
  return { ok: true };
}

export async function decodeImage(file: Blob): Promise<ImageBitmap> {
  // "from-image" applies EXIF orientation, so what users see is what gets uploaded.
  return createImageBitmap(file, { imageOrientation: "from-image" });
}

export async function renderToJpeg(
  bitmap: ImageBitmap,
  framing: Framing,
  quality = 0.92,
): Promise<Blob> {
  const rect = cropRect(bitmap.width, bitmap.height, framing);
  const { w, h } = outputSize(rect);
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas is not available");
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(bitmap, rect.sx, rect.sy, rect.sw, rect.sh, 0, 0, w, h);
  return new Promise((resolve, reject) =>
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("Could not encode image"))),
      "image/jpeg",
      quality,
    ),
  );
}

export function formatBytes(bytes: number): string {
  return bytes >= 1024 * 1024
    ? `${Math.round(bytes / (1024 * 1024))} MB`
    : `${Math.round(bytes / 1024)} KB`;
}
