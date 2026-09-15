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