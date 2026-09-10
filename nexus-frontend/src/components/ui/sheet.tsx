"use client";

import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/cn";

export function Sheet({
  open,
  onOpenChange,
  title,
  description,
  children,
  side = "right",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  side?: "right" | "bottom";
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-[70] bg-black/40 backdrop-blur-sm data-[state=open]:animate-fade-in" />
        <DialogPrimitive.Content
          role="dialog"
          aria-modal="true"
          className={cn(
            "fixed z-[80] bg-surface text-fg shadow-lg focus:outline-none",
            "data-[state=open]:animate-fade-up",
            side === "right" &&
              "inset-y-0 right-0 h-full w-full max-w-md border-l border-border p-6",
            side === "bottom" &&
              "inset-x-0 bottom-0 max-h-[85vh] rounded-t-lg border-t border-border p-6"
          )}
        >
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <DialogPrimitive.Title className="text-title3">{title}</DialogPrimitive.Title>
              {description && (
                <DialogPrimitive.Description className="mt-1 text-footnote text-fg-muted">
                  {description}
                </DialogPrimitive.Description>
              )}
            </div>
            <DialogPrimitive.Close
              aria-label="Tutup"
              className="rounded-sm p-1 text-fg-muted transition-colors hover:bg-bg-subtle hover:text-fg focus-visible:shadow-focus"
            >
              <X className="h-4 w-4" strokeWidth={1.75} aria-hidden />
            </DialogPrimitive.Close>
          </div>
          <div className="overflow-y-auto">{children}</div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
