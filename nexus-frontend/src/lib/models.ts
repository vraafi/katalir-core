// models.ts — registry model untuk ModelSelector composer (chat).
// Tier: 'free' = bisa dipilih semua user. 'plus' = terkunci di tier free
// (ditampilkan redup + tautan Upgrade). Hanya model 'free' yang diizinkan
// dipilih saat ini agar selalu ter-serve oleh backend (Gemini/Google keys).

export interface ChatModel {
  id: string;
  name: string;
  provider: string;
  tier: "free" | "plus";
  hint?: string;
}

export const CHAT_MODELS: ChatModel[] = [
  { id: "gemma-4-31b-it", name: "Gemma 4 31B", provider: "Google (Gemini)", tier: "free" },
  { id: "gemini-2.5-flash", name: "Gemini 2.5 Flash", provider: "Google (Gemini)", tier: "free", hint: "Cepat, hemat token" },
  { id: "gemma-4-9b-it", name: "Gemma 4 9B", provider: "Google (Gemini)", tier: "free", hint: "Ringan & hemat" },
  { id: "gemini-1.5-pro", name: "Gemini Advanced", provider: "Google (Gemini)", tier: "plus" },
];

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