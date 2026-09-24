"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import {
  CANVAS_THEME_STORAGE_KEY,
  DEFAULT_CANVAS_THEME,
  isCanvasThemeId,
  themeOf,
  type CanvasTheme,
  type CanvasThemeId,
} from "./canvas-themes";

/**
 * Provider tema kanvas (FASE 3).
 *
 * Urutan prioritas tema saat mount:
 *   1. `?canvasTheme=<id>` (URL) — dipakai screenshot/E2E supaya tema bisa
 *      ditentukan TANPA menyentuh localStorage lebih dulu. Tidak dipersist
 *      (URL = override sesaat), tapi `setTheme()` berikutnya mempersist.
 *   2. `localStorage[katalir.canvasTheme]` — preferensi user.
 *   3. default `midnight`.
 *
 * PENTING (hidrasi): tema awal = nilai yang sama di server & klien (default),
 * lalu efek pertama menaikkan ke nilai tersimpan. Kalau nilai localStorage
 * dibaca saat render pertama, markup server & klien berbeda -> hydration
 * mismatch. Karena itu `mounted` dipakai dan atribut DOM baru ditulis di efek.
 *
 * GAP YANG DIDOKUMENTASIKAN (bukan bug tersembunyi): misi meminta persist juga
 * ke "Supabase profile". Backend repo ini TIDAK punya endpoint preferensi UI
 * (`/me` hanya { email, tier }), dan menambah kolom baru = schema migration.
 * Migrasi schema adalah keputusan strategis yang TIDAK ada di misi, jadi TIDAK
 * dilakukan di sesi ini; `syncToProfile()` disediakan sebagai titik sambung
 * yang aman (no-op + catatan) supaya FASE 4 tinggal mengisi implementasinya.
 */
interface CanvasThemeContextValue {
  themeId: CanvasThemeId;
  theme: CanvasTheme;
  setTheme: (id: CanvasThemeId) => void;
  /** true setelah efek mount berjalan (UI boleh menampilkan pilihan tersimpan). */
  mounted: boolean;
}

const Ctx = createContext<CanvasThemeContextValue | undefined>(undefined);

/** Tulis tema ke `<html data-canvas-theme>` — penopang semua token CSS. */
function applyToDom(id: CanvasThemeId) {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-canvas-theme", id);
}

/**
 * Persist tema ke profil (Supabase, lewat backend) — FASE 4.
 *
 * Sebelumnya fungsi ini no-op karena belum ada endpoint preferensi. Sekarang
 * endpoint ada (`PUT /preferences`), jadi:
 *   - localStorage TETAP sumber utama (instan, offline-safe, tidak butuh login);
 *   - sinkronisasi profil bersifat best-effort: gagal (401/offline/tabel belum
 *     ada) TIDAK boleh mengganggu pemilihan tema — pemanggil tidak menunggu,
 *     dan error ditelan dengan sengaja.
 */
export function syncToProfile(id: CanvasThemeId): void {
  if (typeof window === "undefined") return;
  void (async () => {
    try {
      const { data } = await supabase.auth.getSession();
      if (!data.session?.access_token) return;
      const res = await apiFetch("/preferences", {
        method: "PUT",
        body: JSON.stringify({ prefs: { canvasTheme: id } }),
        timeoutMs: 8000,
      });
      if (!res.ok) return; // 401 (belum login) / 404 (tabel belum ada): abaikan
    } catch {
      /* offline / backend mati: preferensi lokal tetap berlaku */
    }
  })();
}

/**
 * Ambil tema tersimpan dari profil bila localStorage kosong (perangkat baru).
 * Mengembalikan `null` bila tidak ada / gagal — pemanggil memakai default.
 */
export async function fetchThemeFromProfile(): Promise<CanvasThemeId | null> {
  try {
    // Profil bersifat privat. Jangan melakukan request bila browser belum punya
    // sesi; ini mencegah 401 dari tema kanvas pada route publik.
    const { data } = await supabase.auth.getSession();
    if (!data.session?.access_token) return null;
    const res = await apiFetch("/preferences", { timeoutMs: 8000 });
    if (!res.ok) return null;
    const payload = (await res.json()) as { prefs?: { canvasTheme?: unknown } };
    const theme = payload?.prefs?.canvasTheme;
    return isCanvasThemeId(theme) ? theme : null;
  } catch {
    return null;
  }
}

export function CanvasThemeProvider({ children }: { children: ReactNode }) {
  const params = useSearchParams();
  const themeFromUrl = params.get("canvasTheme");

  const [themeId, setThemeId] = useState<CanvasThemeId>(DEFAULT_CANVAS_THEME);
  const [mounted, setMounted] = useState(false);

  // Terapkan tema ke DOM: nilai awal sinkron (server-safe), lalu naikkan ke
  // nilai tersimpan pada efek pertama.
  useEffect(() => {
    let next: CanvasThemeId = DEFAULT_CANVAS_THEME;
    let fromLocal: CanvasThemeId | null = null;
    if (isCanvasThemeId(themeFromUrl)) {
      next = themeFromUrl;
    } else {
      try {
        const saved = window.localStorage.getItem(CANVAS_THEME_STORAGE_KEY);
        if (isCanvasThemeId(saved)) {
          next = saved;
          fromLocal = saved;
        }
      } catch {
        /* localStorage diblokir (private mode) -> pakai default, jangan crash */
      }
    }
    setThemeId(next);
    applyToDom(next);
    setMounted(true);

    // FASE 4: perangkat baru (localStorage kosong) -> ambil tema dari profil.
    // Best-effort: kalau gagal/ belum login, tetap pakai default. Tidak boleh
    // memblokir render pertama (karena itu tidak di-await di atas).
    if (!fromLocal && !isCanvasThemeId(themeFromUrl)) {
      void fetchThemeFromProfile().then((remote) => {
        if (!remote) return;
        setThemeId(remote);
        applyToDom(remote);
      });
    }
  }, [themeFromUrl]);

  const setTheme = useCallback((id: CanvasThemeId) => {
    if (!isCanvasThemeId(id)) return;
    setThemeId(id);
    applyToDom(id);
    try {
      window.localStorage.setItem(CANVAS_THEME_STORAGE_KEY, id);
    } catch {
      /* abaikan: persistensi opsional */
    }
    syncToProfile(id);
  }, []);

  const value = useMemo<CanvasThemeContextValue>(
    () => ({ themeId, theme: themeOf(themeId), setTheme, mounted }),
    [themeId, setTheme, mounted]
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCanvasTheme(): CanvasThemeContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useCanvasTheme must be used within CanvasThemeProvider");
  return v;
}
