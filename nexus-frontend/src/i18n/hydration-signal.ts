"use client";

// hydration-signal.ts — sinyal "hidrasi benar-benar selesai" untuk i18n.
//
// MASALAH YANG DIPERBAIKI (nyata, dev overlay merah):
// HTML yang dikirim server selalu memakai locale DEFAULT (`id`) — HTML statis
// dibekukan saat build. Klien lalu mendeteksi bahasa browser (`navigator.language`,
// mis. `en-US`) dan mengganti locale. Bila penggantian itu terjadi SAAT React
// masih menghidrasi (Next memakai Suspense + selective hydration, jadi subtree
// seperti Shell/Bubble chat dihidrasi belakangan), React menemukan teks server
// ("Chat Baru") berbeda dari teks klien ("New Chat") dan melaporkan
// `Hydration failed because the server rendered text didn't match the client`.
//
// Penggantian locale setelah SELURUH hidrasi selesai adalah update biasa dan
// tidak pernah dilaporkan sebagai mismatch. Karena React tidak mengekspos
// "hydration complete", sinyalnya dibuat sendiri: komponen terdalam tiap rute
// memanggil `markHydrated()` pada effect pertamanya (effect selalu berjalan
// SETELAH subtree-nya selesai dihidrasi).
export const HYDRATED_EVENT = "katalir:hydrated";

let hydrated = false;

/** Dipanggil sekali oleh komponen terdalam tiap rute. Idempoten. */
export function markHydrated(): void {
  if (hydrated) return;
  hydrated = true;
  try {
    window.dispatchEvent(new Event(HYDRATED_EVENT));
  } catch {
    /* lingkungan tanpa window: abaikan */
  }
}

export function isHydrated(): boolean {
  return hydrated;
}

/**
 * Jalankan `cb` saat hidrasi selesai (langsung bila sudah). Mengembalikan
 * fungsi pembatalan agar pemanggil bisa membersihkan listener.
 */
export function onHydrated(cb: () => void): () => void {
  if (hydrated) {
    cb();
    return () => {};
  }
  const handler = () => cb();
  window.addEventListener(HYDRATED_EVENT, handler, { once: true });
  return () => window.removeEventListener(HYDRATED_EVENT, handler);
}
