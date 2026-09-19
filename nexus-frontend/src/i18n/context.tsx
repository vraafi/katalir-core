"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { DEFAULT_LOCALE, LOCALES, STORAGE_KEY, messages, type Locale, type Messages } from "./messages";

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
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      const initial: Locale =
        stored === "id" || stored === "en" ? stored : detectLocale();
      setLocaleState(initial);
      document.documentElement.lang = initial;
    } catch {
      setLocaleState(detectLocale());
    }
    setMounted(true);
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
