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
 *
 * FASE 3: selain sinyal JS (`markHydrated`), penanda ini juga menulis
 * `data-hydrated="true"` pada `<html>`. Alasannya konkret dan ditemukan dari
 * kegagalan tes: markup yang sudah dirender SERVER terlihat identik dengan
 * markup yang sudah dihidrasi, sehingga tes E2E bisa mengklik tombol SEBELUM
 * handler React terpasang — kliknya hilang tanpa error, dan tes melaporkan
 * "tombol tidak bekerja" padahal aplikasi belum sempat hidup. Atribut ini
 * memberi titik tunggu yang bisa diamati Playwright
 * (`html[data-hydrated="true"]`), dan tidak mengubah tampilan.
 */
export function HydrationReady() {
  useEffect(() => {
    try {
      document.documentElement.dataset.hydrated = "true";
    } catch {
      /* abaikan */
    }
    markHydrated();
  }, []);
  return null;
}
