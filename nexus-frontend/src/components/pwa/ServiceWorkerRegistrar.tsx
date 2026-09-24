"use client";

/**
 * ServiceWorkerRegistrar — FASE 6 (PWA, opsional).
 *
 * HANYA didaftarkan di build produksi. Alasannya bukan kehati-hatian berlebihan:
 * service worker meng-cache HTML, dan di dev/harness E2E itu berarti tes bisa
 * membaca halaman BASI (persis kelas bug "hijau palsu" yang sedang kami hindari).
 * Di produksi pun strateginya network-first untuk navigasi (lihat `public/sw.js`).
 */
import { useEffect } from "react";

export function ServiceWorkerRegistrar() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return;
    if (!("serviceWorker" in navigator)) return;
    const id = window.setTimeout(() => {
      void navigator.serviceWorker.register("/sw.js").catch(() => {
        /* offline/HTTP bukan https: diabaikan, app tetap jalan tanpanya */
      });
    }, 1500); // tunda: jangan bersaing dengan render pertama
    return () => window.clearTimeout(id);
  }, []);
  return null;
}
