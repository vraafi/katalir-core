// models.ts — tipe + helper untuk ModelSelector composer.
// PRINSIP: daftar model BUKAN dari sini — dari GET /models (discovery live
// backend via genai.Client models.list, cache 1 jam). CHAT_MODELS_FALLBACK
// hanya loading-fallback sebelum query server resolve (bukan allowlist).

export interface ChatModel {
  id: string;
  name: string;
  provider: string;
  tier: "free" | "plus";
  hint?: string;
  /** Dikunci server: model plus untuk user non-plus (GET /models). Model
   *  paid-only TIDAK lagi sampai ke sini — difilter di backend TUGAS 1. */
  locked?: boolean;
}

export const CHAT_MODELS_FALLBACK: ChatModel[] = [
  { id: "gemma-4-31b-it", name: "Gemma 4 31B", provider: "Google (Gemini)", tier: "free" },
];

/** Alias lama — jangan dipakai untuk allowlist, hanya fallback loading. */
export const CHAT_MODELS: ChatModel[] = CHAT_MODELS_FALLBACK;

export const DEFAULT_MODEL_ID = "gemma-4-31b-it";

// ---------------------------------------------------------------------------
// MODEL BISNIS (struktur final 2026-09-18)
// ---------------------------------------------------------------------------
// Yang DIJUAL: Gemma 4 (jalur gratis, jangan pelit), DeepSeek Flash, DeepSeek Pro.
// Flash-Lite hanya INTERNAL (fallback murah, tidak ditawarkan sebagai produk).
//
// Id diambil dari katalog gateway yang TERVERIFIKASI
// (`deepseek-ai/deepseek-v4-flash-0731`, `google/gemma-4-31b-it`). Varian
// DeepSeek **Pro belum ada** di katalog (2026-09-18) — entri tetap didefinisikan
// supaya UI/kuota siap begitu id-nya tersedia; `available` menandai kenyataan.
export interface SellableModel extends ChatModel {
  /** Bucket kuota harian (`database.quota_bucket`). */
  bucket: "gemma" | "flash" | "pro";
  /** Tampil di picker? (false = internal, mis. Flash-Lite) */
  sellable: boolean;
  /** Ada di katalog gateway saat ini? */
  available: boolean;
}

export const SELLABLE_MODELS: SellableModel[] = [
  {
    id: "google/gemma-4-31b-it",
    name: "Gemma 4 31B",
    provider: "Google (Gemini)",
    tier: "free",
    bucket: "gemma",
    sellable: true,
    available: true,
  },
  {
    id: "deepseek-ai/deepseek-v4-flash-0731",
    name: "DeepSeek V4 Flash",
    provider: "DeepSeek (NVIDIA NIM)",
    tier: "plus",
    bucket: "flash",
    sellable: true,
    available: true,
  },
  {
    id: "deepseek-ai/deepseek-v4-pro-0731",
    name: "DeepSeek V4 Pro",
    provider: "DeepSeek (NVIDIA NIM)",
    tier: "plus",
    bucket: "pro",
    sellable: true,
    available: false, // TODO: aktifkan saat id Pro muncul di katalog gateway
  },
  {
    id: "gemini-3.1-flash-lite",
    name: "Gemini Flash-Lite (internal)",
    provider: "Google (Gemini)",
    tier: "free",
    bucket: "gemma",
    sellable: false, // internal: dipakai sebagai fallback murah
    available: true,
  },
];

/**
 * Model RPD-20 (kuota harian Google hanya 20) -> CEPAT OVER.
 *
 * Kenapa tidak ditawarkan lagi: begitu RPD habis, model itu dikeluarkan dari
 * roster oleh probe gateway, sehingga user memilih sesuatu yang lalu "hilang"
 * dan request-nya dialihkan tanpa penjelasan. Model seperti ini boleh tetap ada
 * di roster (untuk fallback internal), tetapi tidak layak jadi pilihan produk.
 */
const LOW_RPD_MODEL_RE =
  /^(gemini-2\.5-flash(-lite)?|gemini-3-flash-preview|gemini-3(\.\d+)?-flash)$/i;

export function isLowRpdModel(id: string): boolean {
  return LOW_RPD_MODEL_RE.test((id || "").trim());
}

/**
 * Daftar model untuk PICKER: buang model RPD-20 (produk tidak layak), TETAPI
 * jangan sampai keluarga Flash hilang sama sekali.
 *
 * Kenapa ada syarat "jangan hilang": bila seluruh kandidat Flash kebetulan
 * sedang OVER kuotanya (dan DeepSeek belum ada di roster), memfilter tanpa
 * syarat akan menyisakan daftar yang tidak punya jalur cepat sama sekali --
 * user kehilangan pilihan, dan tampilan jadi menyesatkan ("seolah tidak ada
 * model"). Dalam kondisi itu daftar asli dipertahankan apa adanya.
 */
export function pickerModels(models: ChatModel[]): ChatModel[] {
  const risky = models.filter((m) => isLowRpdModel(m.id));
  if (!risky.length) return models;
  const kept = models.filter((m) => !isLowRpdModel(m.id));
  if (kept.some((m) => /flash/i.test(m.id))) return kept;
  return models;
}

export function getModelById(id: string | null | undefined): ChatModel | undefined {
  if (!id) return undefined;
  return CHAT_MODELS.find((m) => m.id === id);
}

export function providerGroups(models: ChatModel[]): { provider: string; models: ChatModel[] }[] {
  const map = new Map<string, ChatModel[]>();
  for (const m of models) {
    const arr = map.get(m.provider) ?? [];
    arr.push(m);
    map.set(m.provider, arr);
  }
  return Array.from(map.entries()).map(([provider, ms]) => ({ provider, models: ms }));
}