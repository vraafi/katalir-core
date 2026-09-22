"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
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
 * Titik sambung persist server-side. Sengaja TIDAK memanggil endpoint apa pun
 * dulu: belum ada endpoint preferensi (lihat catatan di atas), dan memanggil
 * endpoint yang tidak ada hanya menghasilkan 404 + error konsol di tiap klik.
 */
export function syncToProfile(_id: CanvasThemeId): void {
  /* no-op by design — lihat dokumentasi gap di docblock provider. */
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
    if (isCanvasThemeId(themeFromUrl)) {
      next = themeFromUrl;
    } else {
      try {
        const saved = window.localStorage.getItem(CANVAS_THEME_STORAGE_KEY);
        if (isCanvasThemeId(saved)) next = saved;
      } catch {
        /* localStorage diblokir (private mode) -> pakai default, jangan crash */
      }
    }
    setThemeId(next);
    applyToDom(next);
    setMounted(true);
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
