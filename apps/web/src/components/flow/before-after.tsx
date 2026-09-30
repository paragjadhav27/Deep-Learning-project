"use client";

import { useId, useState } from "react";

import { Button } from "@/components/ui/button";

interface BeforeAfterProps {
  beforeSrc: string;
  afterSrc: string;
  afterAlt: string;
}

/* Both images are either local blob: URLs or short-lived signed API links. next/image
   would proxy and cache them on the server, which must never happen for user photos. */
/* eslint-disable @next/next/no-img-element */

/** Before/after comparison: a keyboard-operable slider, plus a side-by-side mode. */
export function BeforeAfter({ beforeSrc, afterSrc, afterAlt }: BeforeAfterProps) {
  const [position, setPosition] = useState(50);
  const [sideBySide, setSideBySide] = useState(false);
  const sliderId = useId();

  if (sideBySide) {
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <figure className="space-y-1">
            <img src={beforeSrc} alt="Your original photo" className="w-full rounded-lg" />
            <figcaption className="text-center text-sm text-muted-foreground">Original</figcaption>
          </figure>
          <figure className="space-y-1">
            <img src={afterSrc} alt={afterAlt} className="w-full rounded-lg" />
            <figcaption className="text-center text-sm text-muted-foreground">Synthetic illustration</figcaption>
          </figure>
        </div>
        <Button type="button" variant="outline" className="min-h-11" onClick={() => setSideBySide(false)}>
          Compare with a slider
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="relative mx-auto w-full max-w-md overflow-hidden rounded-lg bg-muted">
        <img src={afterSrc} alt={afterAlt} className="block w-full" />
        <img
          src={beforeSrc}
          alt="Your original photo"
          className="absolute inset-0 h-full w-full object-cover"
          style={{ clipPath: `inset(0 ${100 - position}% 0 0)` }}
        />
        <div
          aria-hidden="true"
          className="absolute inset-y-0 w-0.5 bg-white shadow-[0_0_0_1px_rgba(0,0,0,0.4)]"
          style={{ left: `${position}%` }}
        />
        <span aria-hidden="true" className="absolute top-2 left-2 rounded bg-black/70 px-2 py-0.5 text-xs text-white">
          Original
        </span>
        <span aria-hidden="true" className="absolute top-2 right-2 rounded bg-black/70 px-2 py-0.5 text-xs text-white">
          Synthetic
        </span>
      </div>
      <div className="mx-auto grid max-w-md gap-1">
        <label htmlFor={sliderId} className="text-sm font-medium">
          Comparison: drag or use the arrow keys
        </label>
        <input
          id={sliderId}
          type="range"
          min={0}
          max={100}
          step={1}
          value={position}
          onChange={(e) => setPosition(Number(e.target.value))}
          aria-valuetext={`${position}% original, ${100 - position}% synthetic`}
          className="h-6 w-full accent-[var(--primary)]"
        />
      </div>
      <Button type="button" variant="outline" className="min-h-11" onClick={() => setSideBySide(true)}>
        Show side by side
      </Button>
    </div>
  );
}
