import * as React from "react";
import * as LabelPrimitive from "@radix-ui/react-label";
import { cn } from "@/lib/cn";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  helper?: string;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, label, error, helper, id, ...props }, ref) => {
    const inputId = id ?? React.useId();
    return (
      <div className="grid w-full gap-1.5">
        {label && (
          <LabelPrimitive.Root htmlFor={inputId} className="text-subhead font-medium text-fg">
            {label}
          </LabelPrimitive.Root>
        )}
        <input
          ref={ref}
          id={inputId}
          aria-invalid={!!error}
          aria-describedby={error || helper ? `${inputId}-desc` : undefined}
          className={cn(
            "flex h-9 w-full rounded-md border bg-surface px-3 py-2 text-callout text-fg",
            "border-border placeholder:text-fg-subtle",
            "outline-none transition-all duration-200",
            "hover:border-border-strong",
            "focus-visible:border-accent focus-visible:shadow-focus",
            "disabled:cursor-not-allowed disabled:opacity-40",
            error && "border-danger focus-visible:border-danger focus-visible:shadow-none",
            className
          )}
          {...props}
        />
        {(error || helper) && (
          <p id={`${inputId}-desc`} className={cn("text-footnote", error ? "text-danger" : "text-fg-subtle")}>
            {error ?? helper}
          </p>
        )}
      </div>
    );
  }
);
Input.displayName = "Input";
