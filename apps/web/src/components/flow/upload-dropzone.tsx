"use client";

import { ImageUp } from "lucide-react";
import { useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { ACCEPTED_TYPES, formatBytes } from "@/lib/image";

interface UploadDropzoneProps {
  disabled: boolean;
  disabledReason?: string;
  maxBytes: number;
  minSide: number;
  onFile: (file: File) => void;
}

export function UploadDropzone({ disabled, disabledReason, maxBytes, minSide, onFile }: UploadDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const reqsId = useId();
  const reasonId = useId();

  function take(files: FileList | null) {
    const file = files?.[0];
    if (file && !disabled) onFile(file);
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        take(e.dataTransfer.files);
      }}
      data-dragging={dragging || undefined}
      data-disabled={disabled || undefined}
      className="flex flex-col items-center gap-3 rounded-xl border-2 border-dashed border-input bg-card px-6 py-10 text-center transition-colors data-dragging:border-primary data-dragging:bg-secondary data-disabled:bg-muted/40"
    >
      <ImageUp className="size-8 text-primary" aria-hidden="true" />
      <p className="font-medium">Drag a photo here, or</p>
      <Button
        type="button"
        size="lg"
        className="min-h-11 px-5"
        disabled={disabled}
        aria-describedby={`${reqsId}${disabled && disabledReason ? ` ${reasonId}` : ""}`}
        onClick={() => inputRef.current?.click()}
      >
        Choose a photo
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED_TYPES.join(",")}
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        data-testid="photo-input"
        disabled={disabled}
        onChange={(e) => {
          take(e.target.files);
          e.target.value = ""; // allow choosing the same file again after an error
        }}
      />
      <p id={reqsId} className="text-sm text-muted-foreground">
        JPEG, PNG, or WebP · up to {formatBytes(maxBytes)} · at least {minSide}×{minSide} pixels ·
        one clearly visible face
      </p>
      {disabled && disabledReason ? (
        <p id={reasonId} className="text-sm font-medium text-warning">
          {disabledReason}
        </p>
      ) : null}
    </div>
  );
}
