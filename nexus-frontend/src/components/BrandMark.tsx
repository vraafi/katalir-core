  "use client";

import Image from "next/image";
import { cn } from "@/lib/cn";

export function BrandMark({
  className,
  compact = false,
  wordmarkClassName,
  ...props
}: {
  className?: string;
  compact?: boolean;
  /** Kelas untuk teks "Katalir". Dipakai header chat untuk menyembunyikan
   *  wordmark di layar sempit (`hidden sm:inline`) — di 320-390px logo +
   *  wordmark + lima kontrol kanan tidak muat, dan karena grup kanan
   *  `shrink-0`, teks wordmark menimpa tombol tema (terlihat di screenshot).
   *  Logo tetap tampil sehingga identitas merek tidak hilang. */
  wordmarkClassName?: string;
  "data-testid"?: string;
}) {
  return (
    <span {...props} className={cn("inline-flex items-center gap-2 font-semibold tracking-tight", className)}>
      {/* alt="" is deliberate, not an oversight. The word Katalir renders right
          next to this image, so alt="Katalir" makes a screen reader announce
          "Katalir, Katalir". axe calls this image-redundant-alt: the image is
          decorative precisely because the adjacent text names it. */}
      <Image src="/katalir-logo.png" alt="" width={32} height={32} className="h-8 w-8 rounded-lg object-cover" priority />
      {!compact && <span className={wordmarkClassName}>Katalir</span>}
    </span>
  );
}
