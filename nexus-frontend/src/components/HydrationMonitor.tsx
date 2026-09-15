"use client";

import { useEffect } from "react";

/**
 * Monitor pemulihan hydration (hydration-guardian skill, oakoss/agent-skills).
 *
 * Next.js tidak mengekspos opsi `onRecoverableError` milik React 19, jadi sinyal
 * ditangkap dari dua jalur yang benar-benar dipakai React untuk melaporkan
 * recoverable error:
 *   1. `reportError(error)` — default React 19 `onRecoverableError` memakai
 *      global ini bila ada; ia meng-dispatch ErrorEvent di window sehingga
 *      tertangkap `addEventListener("error")`.
 *   2. `console.error(...)` — jalur fallback React (dev) untuk pesan
 *      "Hydration failed because ..."/"did not match ...".
 *
 * Tidak mengubah perilaku aplikasi: hanya mencatat. Nol render output.
 */
const HYDRATION_MARKERS = ["hydrat", "did not match", "server rendered"];

function looksLikeHydration(text: string): boolean {
  const t = text.toLowerCase();
  return HYDRATION_MARKERS.some((m) => t.includes(m));
}

/**
 * console.error asli, di-capture SEKALI di module scope.
 *
 * Kenapa tidak di dalam effect: kalau capture + patch dilakukan per-mount,
 * mount kedua mengambil `console.error` yang SUDAH dipatch milik mount pertama.
 * Setiap laporan lalu turun satu frame lebih dalam (patched -> patched -> ...)
 * dan jumlah frame tumbuh tiap mount → "Maximum call stack size exceeded".
 * Module scope dijamin dieksekusi sekali per bundle/page load.
 */
let nativeError: typeof console.error | null = null;
let installed = false;

/** Dedupe lintas-mount: React bisa melaporkan error yang sama berkali-kali. */
const seen = new Set<string>();

function install(): void {
  if (installed || typeof window === "undefined") return;
  installed = true;
  nativeError = console.error.bind(console);

  // Jalur 1: ErrorEvent. React 19 memakai `reportError()` (default
  // onRecoverableError) saat tersedia -> memicu ErrorEvent di window.
  window.addEventListener("error", (event: ErrorEvent) => {
    const text = `${event.message ?? ""} ${event.error?.stack ?? ""}`;
    if (looksLikeHydration(text)) {
      // TODO: teruskan ke Sentry/LogRocket bila nanti terpasang.
      nativeError?.("[Hydration-Recovered]", {
        message: event.message,
        source: event.filename,
        line: event.lineno,
        column: event.colno,
        error: event.error,
      });
    }
  });

  // Jalur 2: console.error React (dev) — dipakai saat global reportError absen.
  // Re-entrancy guard: laporan monitor WAJIB lewat `nativeError`. Kalau lewat
  // console.error yang sudah dipatch, payload berisi "Hydration failed..." ->
  // cocok pola -> rekursi tak terbatas.
  let reporting = false;

  const patched: typeof console.error = (...args: unknown[]) => {
    const text = args
      .map((a) => (typeof a === "string" ? a : a instanceof Error ? a.message : ""))
      .join(" ");
    if (!reporting && looksLikeHydration(text)) {
      const key = text.slice(0, 180);
      if (!seen.has(key)) {
        seen.add(key);
        reporting = true;
        try {
          // TODO: teruskan ke Sentry/LogRocket bila nanti terpasang.
          nativeError?.("[Hydration-Recovered]", { args });
        } finally {
          reporting = false;
        }
      }
    }
    nativeError?.(...args);
  };

  console.error = patched;
}

export function HydrationMonitor() {
  useEffect(() => {
    // Jalur 1: ErrorEvent (reportError / runtime error React).
    // Idempoten: `install()` juga sudah dipanggil di module scope (lihat bawah).
    install();
  }, []);

  return null;
}

/**
 * JANGAN pindahkan ke dalam useEffect.
 *
 * Hydration error dilaporkan React SEBELUM effect mana pun berjalan (effect
 * dieksekusi setelah komit pertama). Install yang hanya di dalam effect akan
 * selalu telat: patch console.error baru terpasang saat hydration sudah selesai,
 * sehingga mismatch-nya lolos tanpa catatan — persis kasus yang ingin dicegah.
 * Module scope dievaluasi saat bundle client dimuat, yaitu sebelum
 * hydrateRoot() dijalankan, jadi jalur reportError & console.error sudah
 * terpasang lebih dulu. (Referensi hydration-guardian merekomendasikan
 * `onRecoverableError`; Next.js tidak mengeksposnya, jadi alternatif
 * pra-hydration terdekat adalah module scope ini.)
 */
install();