import { describe, expect, it } from "vitest";

import { checkFile, cropRect, DEFAULT_FRAMING, outputSize } from "@/lib/image";

describe("cropRect", () => {
  it("is the whole image at zoom 1", () => {
    expect(cropRect(800, 600, DEFAULT_FRAMING)).toEqual({ sx: 0, sy: 0, sw: 800, sh: 600 });
  });

  it("keeps the aspect ratio and centres the window", () => {
    expect(cropRect(800, 600, { zoom: 2, x: 0.5, y: 0.5 })).toEqual({ sx: 200, sy: 150, sw: 400, sh: 300 });
  });

  it("never leaves the image bounds", () => {
    const r = cropRect(800, 600, { zoom: 2, x: 1, y: 0 });
    expect(r).toEqual({ sx: 400, sy: 0, sw: 400, sh: 300 });
    const clampedZoom = cropRect(800, 600, { zoom: 99, x: 0.5, y: 0.5 });
    expect(clampedZoom.sw).toBe(200); // max zoom is 4
  });
});

describe("outputSize", () => {
  it("scales down so the longest side is at most 2048", () => {
    expect(outputSize({ sx: 0, sy: 0, sw: 4000, sh: 3000 })).toEqual({ w: 2048, h: 1536 });
  });
  it("never upscales", () => {
    expect(outputSize({ sx: 0, sy: 0, sw: 300, sh: 200 })).toEqual({ w: 300, h: 200 });
  });
});

describe("checkFile", () => {
  const file = (type: string, size: number) => new File([new Uint8Array(size)], "f", { type });
  it("accepts the supported types", () => {
    for (const t of ["image/jpeg", "image/png", "image/webp"]) {
      expect(checkFile(file(t, 10), 1000)).toEqual({ ok: true });
    }
  });
  it("rejects other types, including SVG and GIF", () => {
    expect(checkFile(file("image/svg+xml", 10), 1000)).toEqual({ ok: false, code: "invalid_file_type" });
    expect(checkFile(file("image/gif", 10), 1000)).toEqual({ ok: false, code: "invalid_file_type" });
  });
  it("rejects files far beyond the limit before decoding", () => {
    expect(checkFile(file("image/jpeg", 3001), 1000)).toEqual({ ok: false, code: "file_too_large" });
  });
});
