"use client";

import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import type { Consent } from "@/lib/api/client";

const ITEMS: { key: keyof Consent; label: string; description: string }[] = [
  {
    key: "has_permission",
    label: "I have permission to upload this photo",
    description: "It's a photo of me, or the person in it has agreed to this use.",
  },
  {
    key: "is_adult",
    label: "The person in the photo and I are both 18 or older",
    description: "These tools don't support photos of children or teenagers.",
  },
  {
    key: "accepts_limitations",
    label: "I understand results are uncertain and illustrative",
    description:
      "They're not facts about the person and must not be used for any decision about them.",
  },
];

export function isConsentComplete(c: Consent): boolean {
  return c.has_permission && c.is_adult && c.accepts_limitations;
}

interface ConsentPanelProps {
  value: Consent;
  onChange: (next: Consent) => void;
  disabled?: boolean;
}

export function ConsentPanel({ value, onChange, disabled = false }: ConsentPanelProps) {
  return (
    <fieldset className="space-y-4" disabled={disabled}>
      <legend className="mb-1 font-semibold">Before you choose a photo, please confirm:</legend>
      {ITEMS.map((item) => {
        const id = `consent-${item.key}`;
        return (
          <div key={item.key} className="flex gap-3">
            <Checkbox
              id={id}
              checked={value[item.key]}
              disabled={disabled}
              aria-describedby={`${id}-desc`}
              onCheckedChange={(checked) => onChange({ ...value, [item.key]: checked === true })}
              className="mt-0.5 size-5"
            />
            <div className="grid gap-1">
              <Label htmlFor={id} className="leading-snug font-medium">
                {item.label}
              </Label>
              <p id={`${id}-desc`} className="text-sm text-muted-foreground">
                {item.description}
              </p>
            </div>
          </div>
        );
      })}
    </fieldset>
  );
}
