"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";

/** Kunci penanda bahwa user sudah pernah berpindah halaman di dalam app. */
export const INTERNAL_NAV_KEY = "hasInternalNav";

/**
 * useBack — tombol "kembali" yang tidak pernah melempar user ke situs lain.
 *
 * Masalah yang diselesaikan: `router.back()` tanpa pengaman akan
 * mengembalikan user ke halaman SEBELUM app, misalnya Google atau tab
 * dokumen. Itu terjadi nyata pada orang yang membuka /settings lewat
 * deep-link atau refresh, yang persis kasus yang paling sering dikeluhkan.
 *
 * Aturannya:
 *  - ada navigasi internal di sesi ini DAN history punya isinya -> back
 *  - selain itu -> fallback (default /chat untuk user yang sudah login)
 *
 * `window.history.length > 1` saja TIDAK cukup, karena history browser
 * bisa hanya berisi satu entri meski user datang dari luar; itu sebabnya
 * penanda di sessionStorage ikut dipakai.
 */
export function useBack(fallback: string) {
  const router = useRouter();

  return useCallback(() => {
    let internal = false;
    try {
      internal = sessionStorage.getItem(INTERNAL_NAV_KEY) === "true";
    } catch {
      // Storage diblokir (private mode / iframe): cenderung ke fallback,
      // yang lebih aman daripada mengirim user keluar dari app.
    }

    if (internal && window.history.length > 1) {
      router.back();
      return;
    }
    router.push(fallback);
  }, [router, fallback]);
}

/**
 * Menandai navigasi internal. Dipasang satu kali di root layout.
 * Render pertama sengaja TIDAK menandai apa pun, supaya hasil refresh yang
 * yang membuka halaman langsung tidak dianggap "sudah pernah pindah".
 */
export function useMarkInternalNav() {
  return useCallback(() => {
    try {
      sessionStorage.setItem(INTERNAL_NAV_KEY, "true");
    } catch {
      // diam-diam: storage opsional, bukan pemblokir fitur
    }
  }, []);
}
