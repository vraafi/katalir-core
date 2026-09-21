"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { DEFAULT_LOCALE, LOCALES, STORAGE_KEY, messages, type Locale, type Messages } from "./messages";
import { isHydrated, markHydrated, onHydrated } from "./hydration-signal";

type Params = Record<string, string | number>;

function getPath(obj: unknown, key: string): unknown {
  let cur: unknown = obj;
  for (const part of key.split(".")) {
    if (cur == null || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[part];
  }
  return cur;
}

function applyTemplate(s: string, params?: Params): string {
  if (!params) return s;
  return s.replace(/\{(\w+)\}/g, (m, k: string) => (k in params ? String(params[k]) : m));
}

interface I18nValue {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: string, params?: Params) => string;
  formatDate: (d: Date | string | number) => string;
  formatNumber: (n: number, opts?: Intl.NumberFormatOptions) => string;
  mounted: boolean;
}

const I18nContext = createContext<I18nValue | null>(null);

function detectLocale(): Locale {
  if (typeof navigator === "undefined") return DEFAULT_LOCALE;
  const lang = (navigator.language || "").toLowerCase();
  if (lang.startsWith("en")) return "en";
  return "id";
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(DEFAULT_LOCALE);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    // Terapkan locale terdeteksi SETELAH hidrasi selesai (bukan langsung di
    // effect ini). SSR selalu memakai DEFAULT_LOCALE; mengganti teks sebelum
    // subtree selesai dihidrasi membuat React melaporkan hydration mismatch
    // (dev: overlay merah). `onHydrated` menunggu sinyal dari komponen
    // terdalam tiap rute, dengan timeout sebagai jaring pengaman bila penanda
    // tidak terpasang (mis. rute baru yang lupa).
    let cancel = () => {};
    let fallback: ReturnType<typeof setTimeout> | undefined;
    const apply = () => {
      try {
        const stored = window.localStorage.getItem(STORAGE_KEY);
        const initial: Locale =
          stored === "id" || stored === "en" ? stored : detectLocale();
        setLocaleState(initial);
        document.documentElement.lang = initial;
      } catch {
        setLocaleState(detectLocale());
      }
    };
    cancel = onHydrated(apply);
    // Jaring pengaman: hanya bila penanda tidak pernah datang (rute baru yang
    // lupa memasang HydrationReady). SENGAJA tidak menerapkan locale sebelum
    // dokumen selesai dimuat: pada dev DINGIN, kompilasi+hidrasi bisa > 2,5 s dan
    // timer buta justru mengganti teks di TENGAH hidrasi — persis yang memicu
    // mismatch (terbukti: load pertama setelah `next dev` restart masih 2 hit,
    // load berikutnya 0). Menunggu `load` selalu lebih aman daripada waktu tetap.
    fallback = setTimeout(() => {
      if (isHydrated()) return;
      const run = () => {
        if (isHydrated()) return;
        markHydrated();
        apply();
      };
      if (document.readyState === "complete") {
        run();
      } else {
        window.addEventListener("load", () => setTimeout(run, 300), { once: true });
      }
    }, 8000);
    setMounted(true);
    return () => {
      cancel();
      clearTimeout(fallback);
    };
  }, []);

  const setLocale = useCallback((l: Locale) => {
    if (!LOCALES.includes(l)) return;
    setLocaleState(l);
    try {
      window.localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* abaikan: mode privat */
    }
    if (typeof document !== "undefined") document.documentElement.lang = l;
  }, []);

  const t = useCallback(
    (key: string, params?: Params): string => {
      const v = getPath(messages[locale] as Messages, key);
      if (typeof v === "string") return applyTemplate(v, params);
      // Fallback ke default locale sebelum menyerah menampilkan key.
      const fb = getPath(messages[DEFAULT_LOCALE] as Messages, key);
      if (typeof fb === "string") return applyTemplate(fb, params);
      return key;
    },
    [locale]
  );

  const formatDate = useCallback(
    (d: Date | string | number): string => {
      const date = d instanceof Date ? d : new Date(d);
      const tag = locale === "en" ? "en-US" : "id-ID";
      return new Intl.DateTimeFormat(tag, {
        day: "numeric",
        month: "long",
        year: "numeric",
      }).format(date);
    },
    [locale]
  );

  const formatNumber = useCallback(
    (n: number, opts?: Intl.NumberFormatOptions): string => {
      const tag = locale === "en" ? "en-US" : "id-ID";
      return new Intl.NumberFormat(tag, opts).format(n);
    },
    [locale]
  );

  const value = useMemo<I18nValue>(
    () => ({ locale, setLocale, t, formatDate, formatNumber, mounted }),
    [locale, setLocale, t, formatDate, formatNumber, mounted]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n harus dipakai di dalam <I18nProvider>");
  return ctx;
}
