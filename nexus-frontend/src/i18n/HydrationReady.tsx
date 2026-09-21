"use client";

import { useEffect } from "react";
import { markHydrated } from "./hydration-signal";

/**
 * Penanda hidrasi (runtime, tanpa UI).
 *
 * Dipasang di KOMPONEN TERDALAM setiap rute. Alasannya: effect React berjalan
 * setelah subtree tempat ia berada selesai dihidrasi. Menaruhnya di root layout
 * tidak cukup — dengan Suspense + selective hydration, effect root bisa berjalan
 * sebelum subtree (Shell/chat) selesai dihidrasi, dan penggantian locale di
 * rentang itu memicu hydration mismatch (lihat `hydration-signal.ts`).
 */
export function HydrationReady() {
  useEffect(() => {
    markHydrated();
  }, []);
  return null;
}
