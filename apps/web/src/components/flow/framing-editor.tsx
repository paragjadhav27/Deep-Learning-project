"use client";

import { RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { cropRect, DEFAULT_FRAMING, type Framing } from "@/lib/image";

interface FramingPreviewProps {
  src: string;
  width: number;
  height: number;
  framing: Framing;
  alt: string;
}

/** Shows exactly the region that will be uploaded, using CSS only (no canvas redraws). */
export function FramingPreview({ src, width, height, framing, alt }: FramingPreviewProps) {
  const r = cropRect(width, height, framing);
  const scale = width / r.sw;
  return (
    <div
      className="relative mx-auto w-full max-w-sm overflow-hidden rounded-lg bg-muted"
      style={{ aspectRatio: `${width} / ${height}` }}
    >
      {/* A local blob: URL; next/image would add nothing and must never cache user photos. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={alt}
        className="absolute max-w-none select-none"
        draggable={false}
        style={{
          width: `${scale * 100}%`,
          left: `${(-r.sx / r.sw) * 100}%`,
          top: `${(-r.sy / r.sh) * 100}%`,
        }}
      />
    </div>
  );
}

interface FramingControlsProps {
  framing: Framing;
  onChange: (f: Framing) => void;
}

export function FramingControls({ framing, onChange }: FramingControlsProps) {
  const zoomed = framing.zoom > 1.001;
  const pct = (v: number) => `${Math.round(v * 100)}%`;
  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        Zoom in and reposition to crop out other people or bring the face closer. Only the area
        shown above is uploaded.
      </p>
      <div className="grid gap-2">
        <span className="text-sm font-medium">Zoom</span>
        <Slider
          min={1}
          max={4}
          step={0.05}
          value={[framing.zoom]}
          thumbLabels={["Zoom"]}
          getValueText={(v) => `${Math.round(v * 100)} percent`}
          onValueChange={([zoom]) => onChange({ ...framing, zoom: zoom ?? 1 })}
        />
      </div>
      <div className="grid gap-2">
        <span className="text-sm font-medium">Horizontal position</span>
        <Slider
          min={0}
          max={1}
          step={0.01}
          disabled={!zoomed}
          value={[framing.x]}
          thumbLabels={["Horizontal position"]}
          getValueText={(v) => `${pct(v)} from left`}
          onValueChange={([x]) => onChange({ ...framing, x: x ?? 0.5 })}
        />
      </div>
      <div className="grid gap-2">
        <span className="text-sm font-medium">Vertical position</span>
        <Slider
          min={0}
          max={1}
          step={0.01}
          disabled={!zoomed}
          value={[framing.y]}
          thumbLabels={["Vertical position"]}
          getValueText={(v) => `${pct(v)} from top`}
          onValueChange={([y]) => onChange({ ...framing, y: y ?? 0.5 })}
        />
      </div>
      <Button type="button" variant="outline" className="min-h-11" onClick={() => onChange(DEFAULT_FRAMING)}>
        <RotateCcw aria-hidden="true" />
        Reset framing
      </Button>
    </div>
  );
}
