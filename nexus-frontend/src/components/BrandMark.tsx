  "use client";

import Image from "next/image";
import { cn } from "@/lib/cn";

export function BrandMark({ className, compact = false, ...props }: { className?: string; compact?: boolean; "data-testid"?: string }) {
  return (
    <span {...props} className={cn("inline-flex items-center gap-2 font-semibold tracking-tight", className)}>
      <Image src="/katalir-logo.png" alt="Katalir" width={32} height={32} className="h-8 w-8 rounded-lg object-cover" priority />
      {!compact && <span>Katalir</span>}
    </span>
  );
}
