import * as React from "react";
import { cn } from "@/lib/cn";

export interface SelectProps
  extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
  options: { value: string; label: string; disabled?: boolean }[];
}

export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, label, error, id, options, ...props }, ref) => {
    const selectId = id ?? React.useId();
    return (
      <div className="grid w-full gap-1.5">
        {label && (
          <label htmlFor={selectId} className="text-subhead font-medium text-fg">
            {label}
          </label>
        )}
        <select
          ref={ref}
          id={selectId}
          aria-invalid={!!error}
          className={cn(
            "flex h-9 w-full appearance-none rounded-md border bg-surface px-3 py-2 pr-8 text-callout text-fg",
            "border-border placeholder:text-fg-subtle",
            "outline-none transition-all duration-200",
            "hover:border-border-strong",
            "focus-visible:border-accent focus-visible:shadow-focus",
            "disabled:cursor-not-allowed disabled:opacity-40",
            error && "border-danger focus-visible:border-danger focus-visible:shadow-none",
            className
          )}
          style={{
            backgroundImage:
              "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' fill='none' stroke='%23a1a1aa' stroke-width='2'><path d='m4 6 4 4 4-4'/></svg>\")",
            backgroundRepeat: "no-repeat",
            backgroundPosition: "right 0.5rem center",
          }}
          {...props}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value} disabled={o.disabled}>
            {o.label}
            </option>
          ))}
        </select>
        {error && <p className="text-footnote text-danger">{error}</p>}
      </div>
    );
  }
);
Select.displayName = "Select";