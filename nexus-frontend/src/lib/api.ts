import { supabase } from "@/lib/supabase";

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/**
 * Fetch autenticato al backend FastAPI: injeta Authorization: Bearer <jwt>
 * dal session Supabase. TIDAK usar query param email (spoofable).
 */
export async function apiFetch(
  path: string,
  init?: RequestInit & { token?: string }
): Promise<Response> {
  const { token: explicitToken, ...rest } = init ?? {};
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
  return fetch(`${API_URL}${path}`, { ...rest, headers });
}