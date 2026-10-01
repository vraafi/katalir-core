import { supabase } from "@/lib/supabase";

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** Timeout default untuk semua request (ms). Chat Gemini lambat -> 90s. */
export const FETCH_TIMEOUT_MS = 90_000;

/** Timeout KHUSUS endpoint `/chat` (ms).
 *
 *  Kenapa lebih besar dari default: `apiFetch` memulai ulang timer AbortController
 *  untuk SETIAP fetch, jadi 90s di sini bukan batas total — batasnya per percobaan.
 *  Yang terjadi tanpa nilai ini: satu percobaan yang macet (gateway lambat, atau
 *  panggilan Supabase yang tidak dijawab) sudah melewati 90s, sehingga abort
 *  menyala dan user melihat "Server lambat, coba lagi." padahal backend masih
 *  bekerja dan jawabannya hampir jadi.
 *
 *  BUDGET TIMER INI: satu fetch. Retry loop di `useChat` (3 percobaan +
 *  backoff 2s/5s) punya plafon sendiri, jadi total teratas adalah
 *  3 x budget_backend + 7s dan harus tetap DI BAWAH nilai ini agar tidak ada
 *  fetch yang terbunuh di tengah jalan oleh abort.
 */
export const CHAT_TIMEOUT_MS = 150_000;

export function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

/**
 * Klasifikasi error untuk UI (Fase 1 resilience).
 * Pesan ramah + flag retryable untuk decision retry.
 */
export function classifyChatError(err: unknown): { message: string; retryable: boolean } {
  const e = err as Error & { name?: string; status?: number };
  if (e && (e.name === "AbortError" || e.name === "TimeoutError")) {
    return { message: "Server lambat, coba lagi.", retryable: true };
  }
  if (e && e.name === "TypeError") {
    // fetch network failure (offline / DNS / reset)
    return { message: "Koneksi lambat. Cek internetmu.", retryable: true };
  }
  if (e && typeof e.message === "string" && e.message) {
    return { message: e.message, retryable: false };
  }
  return { message: "Terjadi kesalahan. Coba lagi.", retryable: false };
}

export function classifyHttpError(status: number): { message: string; retryable: boolean } {
  switch (status) {
    case 401:
      return { message: "Sesi habis. Silakan login ulang.", retryable: false };
    case 503:
      return { message: "Server sedang sibuk. Coba lagi sebentar.", retryable: true };
    case 429:
      return { message: "Model sedang sibuk. Coba lagi dalam 1 menit.", retryable: false };
    case 500:
      return { message: "Server error. Tim kami sudah diberi tahu.", retryable: false };
    default:
      return { message: `Server error (${status}).`, retryable: false };
  }
}

/**
 * Fetch autenticato al backend FastAPI: injeta Authorization Bearer JWT,
 * Content-Type json, dan AbortController timeout (drop infine hang).
 */
export async function apiFetch(
  path: string,
  init?: RequestInit & { token?: string; timeoutMs?: number }
): Promise<Response> {
  const { token: explicitToken, timeoutMs = FETCH_TIMEOUT_MS, signal: externalSignal, ...rest } = init ?? {};
  let token: string | null | undefined = explicitToken;
  if (!token) {
    try {
      const { data } = await supabase.auth.getSession();
      token = data.session?.access_token ?? null;
    } catch {
      token = null;
    }
  }
  const headers = new Headers(rest.headers ?? {});
  headers.set("Content-Type", headers.get("Content-Type") ?? "application/json");
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  // Dukungan cancel eksternal (Stop button): kombinasi signal caller dengan
  // timeout internal tanpa menimpa satu sama lain.
  const controller = new AbortController();
  const onExternalAbort = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort();
    else externalSignal.addEventListener("abort", onExternalAbort, { once: true });
  }
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(`${API_URL}${path}`, { ...rest, headers, signal: controller.signal });
  } finally {
    clearTimeout(timer);
    if (externalSignal) externalSignal.removeEventListener("abort", onExternalAbort);
  }
}