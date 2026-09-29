"use client";

import { useEffect, useRef } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { INTERNAL_NAV_KEY } from "@/hooks/useBack";

/**
 * Penanda navigasi internal, dipasang satu kali di root layout.
 *
 * Yang dicatat hanya PERUBAHAN rute, bukan render pertama. Tanpa itu,
 * user yang membuka /settings lewat refresh atau deep-link akan
 * teranggap "sudah pernah berpindah halaman", dan tombol Back akan
 * memakai router.back() -- yang bisa mengembalikan user ke Google.
 */
export function NavigationTracker() {
  const pathname = usePathname();
  const search = useSearchParams();
  const first = useRef(true);

  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    try {
      sessionStorage.setItem(INTERNAL_NAV_KEY, "true");
    } catch {
      // storage diblokir: tombol Back akan jatuh ke fallback, masih aman
    }
  }, [pathname, search]);

  return null;
}
