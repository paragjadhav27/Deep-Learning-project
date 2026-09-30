"use client";

import { Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

interface DeleteSessionButtonProps {
  onConfirm: () => Promise<void>;
}

export function DeleteSessionButton({ onConfirm }: DeleteSessionButtonProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && setOpen(o)}>
      <DialogTrigger asChild>
        <Button type="button" variant="destructive" className="min-h-11">
          <Trash2 aria-hidden="true" />
          Delete photo and results
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete your photo and results now?</DialogTitle>
          <DialogDescription>
            This removes the photo and every result from our servers straight away. You
            can&apos;t undo it.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline" className="min-h-11" disabled={busy}>
              Keep for now
            </Button>
          </DialogClose>
          <Button
            type="button"
            className="min-h-11 bg-destructive text-white hover:bg-destructive/90"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onConfirm();
                setOpen(false);
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Deleting…" : "Delete now"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
