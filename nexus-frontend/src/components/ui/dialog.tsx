"use client";

import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/cn";

/**
 * A centred modal dialog.
 *
 * Follows the same house style as `sheet.tsx` (design tokens rather than raw
 * colours, `animate-fade-up` on open, the same close-button treatment) so the
 * login modal reads as part of this app rather than a shadcn import dropped on
 * top. `shadcn add dialog` was NOT run: the project already depends on
 * `@radix-ui/react-dialog` and has its own `ui/` convention, and a second,
 * differently-themed dialog would have fought `sheet.tsx` for the same overlay.
 */
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  className,
  closeLabel,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
  /** Accessible name for the close control. Passed in so it can be localised. */
  closeLabel: string;
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-[90] bg-black/50 backdrop-blur-sm data-[state=open]:animate-fade-in" />
        <DialogPrimitive.Content
          role="dialog"
          aria-modal="true"
          data-testid="dialog-content"
          className={cn(
            // Centred with translate utilities, which need `transform` to be
            // free. The open animation therefore runs on the INNER wrapper
            // below, never on this element.
            //
            // Both mistakes here are real, not hypothetical:
            //  - Animating this element overrode the translate utilities
            //    (keyframes and utilities both emit `transform`; the keyframe
            //    won), snapping the dialog to the 50%/50% corner with no
            //    offset - ~224px off centre.
            //  - `h-fit` with auto margins did not clamp the height, so tall
            //    content pushed the submit button and the mode toggle below
            //    the fold, making them unclickable in a 720px-tall viewport.
            "fixed left-1/2 top-1/2 z-[100] w-[calc(100vw-2rem)] max-w-md",
            "-translate-x-1/2 -translate-y-1/2",
            // Clamp + scroll so a short viewport can always reach every control.
            "max-h-[calc(100dvh-2rem)] overflow-y-auto",
            "rounded-2xl border border-border bg-surface p-6 text-fg shadow-lg focus:outline-none",
            className
          )}
        >
          <div data-testid="dialog-inner" className="data-[state=open]:animate-fade-up">
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
              aria-label={closeLabel}
              className="rounded-sm p-1 text-fg-muted transition-colors hover:bg-bg-subtle hover:text-fg focus-visible:shadow-focus"
            >
              <X className="h-4 w-4" strokeWidth={1.75} aria-hidden />
            </DialogPrimitive.Close>
          </div>
          {children}
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
