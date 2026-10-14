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
  // Isinya HARUS model yang benar-benar bisa dilayani. Label tombol picker
  // dibaca dari daftar ini pada frame pertama setelah mount
  // (`ModelSelector`: `active?.name ?? t("modelPicker.stub")`); bila id di sini
  // tidak ada di roster, label jatuh ke "Pilih model" lalu berkedip berganti
  // begitu `GET /models` mendarat. Id di sini = default server, jadi labelnya
  // sudah benar sejak frame pertama.
  //
  // 14 Okt 2026: isi sebelumnya `google/gemma-4-31b-it`. DIHAPUS karena model
  // itu tidak bisa dilayani (kuota habis -> spanduk fallback di setiap pesan)
  // dan latensinya 52985ms di roster. Gerbang server: `NOT_OFFERED_MODEL_IDS`
  // di `api_server.py`.
  { id: "gemini-3.5-flash-lite", name: "Gemini 3.5 Flash Lite", provider: "Google (Gemini)", tier: "free" },
];

/** Alias lama — jangan dipakai untuk allowlist, hanya fallback loading. */
export const CHAT_MODELS: ChatModel[] = CHAT_MODELS_FALLBACK;

// BUG-05 FIX (2026-10-13): id HARUS sama persis dengan katalog server.
// Sebelumnya `"gemma-4-31b-it"` (tanpa awalan penyedia) — katalog gateway
// memakai `"google/gemma-4-31b-it"` (terverifikasi via model_discovery:
// 13 model, salah satunya `google/gemma-4-31b-it`). Id lama tak pernah
// teresolusi sehingga backend menandai fallback=True di SETIAP pesan dan
// user melihat spanduk "Model yang Anda pilih tidak tersedia".
// Acuan: docs/real-user-hard-test-2026-10-13.md §BUG-05.
//
// Sejak 2026-10-14 default dapat diatur lewat env tanpa mengubah kode.
// Bila NEXT_PUBLIC_DEFAULT_MODEL_ID kosong/tidak ada, jatuh ke id katalog yang
// benar di atas. Catatan: NEXT_PUBLIC_* di-inline SAAT BUILD, jadi mengubahnya
// perlu build ulang (lihat docs/fix-all-bugs-2026-10-13.md §7.3).
const ENV_DEFAULT_MODEL_ID = (process.env.NEXT_PUBLIC_DEFAULT_MODEL_ID || "").trim();

// Fallback keras (env kosong) = model yang TERBUKTI dilayani tanpa fallback.
// 14 Okt 2026: nilai lama `"google/gemma-4-31b-it"` DIGANTI. Id itu masih ada
// di roster gateway tetapi seluruh kuncinya cooldown kuota, jadi memakainya
// sebagai default akan memunculkan spanduk fallback di setiap pesan — persis
// bug yang baru saja diperbaiki. Disamakan dengan `NEXT_PUBLIC_DEFAULT_MODEL_ID`
// di `.env.production` supaya "env hilang" tidak diam-diam mengembalikan bug.
export const DEFAULT_MODEL_ID = ENV_DEFAULT_MODEL_ID || "gemini-3.5-flash-lite";

/**
 * BUG-05 (2026-10-13): id lama tanpa awalan penyedia pernah tersimpan di
 * localStorage pengguna. Tanpa normalisasi, nilai basi itu di-restore apa
 * adanya dan mengembalikan bug yang sama (fallback tiap pesan). Petakan
 * alias lama -> id katalog yang benar saat membaca storage.
 *
 * 14 Okt 2026: `google/gemma-4-31b-it` ditambahkan ke sini. Model itu tidak
 * lagi ditawarkan (lihat `NOT_OFFERED_MODEL_IDS` di `api_server.py`), jadi
 * pilihan tersimpan milik pengguna lama akan menunjuk id yang TIDAK ADA di
 * daftar picker -> `ModelSelector` kehilangan `active` dan labelnya jatuh ke
 * stub "Pilih model". Memetakan ke `DEFAULT_MODEL_ID` membuat pilihan basi itu
 * menyembuhkan diri ke model yang benar-benar dilayani.
 */
const LEGACY_MODEL_ALIASES: Record<string, string> = {
  "gemma-4-31b-it": DEFAULT_MODEL_ID,
  "google/gemma-4-31b-it": DEFAULT_MODEL_ID,
};

export function normalizeModelId(id: string | null | undefined): string {
  if (!id) return DEFAULT_MODEL_ID;
  const trimmed = id.trim();
  return LEGACY_MODEL_ALIASES[trimmed] ?? trimmed;
}

// ---------------------------------------------------------------------------
// MODEL BISNIS (launch 2026-09-18)
// ---------------------------------------------------------------------------
// Hanya Free + Plus yang DITAWARKAN saat launch ("Pro"/"Ultra" disembunyikan
// sementara, JANGAN dihapus — id, harga, dan batas kuotanya tetap ada dan siap
// dinyalakan lagi tanpa migrasi).
// Yang DIJUAL: jalur gratis (bucket `gemma`) dan DeepSeek Flash (Plus).
// DeepSeek Pro + tier pro/ultra tetap terdefinisi tapi hidden.
//
// CATATAN PENTING (14 Okt 2026): blok ini TIDAK dikonsumsi kode mana pun —
// grep `SELLABLE_MODELS` hanya menemukan definisi ini. Ia dokumentasi lineup,
// BUKAN gerbang. Sumber kebenaran picker = `GET /models` (backend), dan
// gerbang "jangan tawarkan" = `NOT_OFFERED_MODEL_IDS` di `api_server.py`.
// Jangan jadikan blok ini allowlist tanpa memindahkan gerbangnya juga.
export interface SellableModel extends ChatModel {
  /** Bucket kuota harian (`database.quota_bucket`). */
  bucket: "gemma" | "flash" | "pro";
  /** Tampil di picker? (false = hidden: internal ATAU Pro/Ultra saat launch). */
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
    // 14 Okt 2026 — DIJADIKAN false (sebelumnya true). Model ini masih ADA di
    // roster gateway (`available: true`) tetapi SELURUH kuncinya cooldown
    // kuota, jadi memilihnya memunculkan spanduk "Model yang Anda pilih tidak
    // tersedia" di setiap pesan. Karena tidak bisa dilayani, ia tidak lagi
    // ditawarkan. Gerbang nyatanya di backend (`NOT_OFFERED_MODEL_IDS`).
    // Jalur gratis kini dilayani `gemini-3.5-flash-lite` (dipilih backend lewat
    // `DEFAULT_MODEL_PREFERENCE`, bukan lewat blok ini).
    sellable: false,
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
    // HIDDEN saat launch 2026-09-18: hanya Free + Plus yang ditawarkan.
    // JANGAN hapus — id/harga/kuota Pro tetap ada dan siap dinyalakan lagi.
    sellable: false,
    available: false, // TODO: aktifkan saat id Pro muncul di katalog gateway
  },
  // ENTRI DIHAPUS (14 Okt 2026): `gemini-3.1-flash-lite`.
  //   Alasan: BASI. Id-nya sudah tidak ada di roster gateway (dikonfirmasi
  //   `GET /models` -> 13 model, id ini tidak termasuk) dan probe model
  //   membuktikan permintaan ke id ini dialihkan ke model lain
  //   (`fallback=true / model_unavailable`).
  //   Bukti: docs/evidence/default-model-id-2026-10-14/probe_default_model_id.json
  //   dan docs/evidence/models-picker-2026-10-14/models_before.json.
  //   Catatan: id ini MASIH ada di allowlist `FREE_TIER_MODEL_IDS`
  //   (`gateway_roster.py`) — allowlist hanya MENGIZINKAN, tidak menyuntikkan,
  //   jadi tidak ada model hantu yang muncul di picker karena entri itu.
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