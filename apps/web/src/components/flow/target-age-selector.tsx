"use client";

import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import type { TargetAgeGroup, TargetGroupView } from "@/lib/api/client";
import { TARGET_GROUP_LABELS } from "@/lib/tools";

/** Child and teen targets are never offered, so they aren't listed at all. */
const HIDDEN_GROUPS: ReadonlySet<TargetAgeGroup> = new Set(["child", "teen"]);

interface TargetAgeSelectorProps {
  groups: TargetGroupView[];
  value: TargetAgeGroup | null;
  onChange: (group: TargetAgeGroup) => void;
  disabled?: boolean;
  idPrefix?: string;
}

export function TargetAgeSelector({ groups, value, onChange, disabled, idPrefix = "target" }: TargetAgeSelectorProps) {
  const noteId = `${idPrefix}-note`;
  return (
    <fieldset className="space-y-3" disabled={disabled}>
      <legend className="font-semibold">Target age group</legend>
      <p id={noteId} className="text-sm text-muted-foreground">
        This is a creative target for an illustration. It isn&apos;t a prediction of how anyone
        looked or will look.
      </p>
      <RadioGroup
        value={value ?? ""}
        onValueChange={(v) => onChange(v as TargetAgeGroup)}
        aria-describedby={noteId}
        className="grid gap-2 sm:grid-cols-2"
        disabled={disabled}
      >
        {groups.filter((g) => !HIDDEN_GROUPS.has(g.group)).map((g) => {
          const id = `${idPrefix}-${g.group}`;
          const meta = TARGET_GROUP_LABELS[g.group];
          const reasonId = `${id}-reason`;
          return (
            <div
              key={g.group}
              data-unavailable={!g.available || undefined}
              className="flex gap-3 rounded-lg border border-border bg-card p-3 has-data-checked:border-primary has-data-checked:bg-secondary data-unavailable:bg-muted/60"
            >
              <RadioGroupItem
                id={id}
                value={g.group}
                disabled={!g.available || disabled}
                aria-describedby={g.available ? `${id}-hint` : reasonId}
                className="mt-0.5 size-5"
              />
              <div className="grid gap-0.5">
                <Label htmlFor={id} className="font-medium">
                  {meta.label}
                  {!g.available ? <span className="sr-only"> (unavailable)</span> : null}
                </Label>
                <p id={`${id}-hint`} className="text-sm text-muted-foreground">
                  {meta.hint}
                </p>
                {!g.available && g.reason ? (
                  <p id={reasonId} className="text-sm text-muted-foreground">
                    <span className="font-medium text-foreground">Unavailable: </span>
                    {g.reason}
                  </p>
                ) : null}
              </div>
            </div>
          );
        })}
      </RadioGroup>
    </fieldset>
  );
}
