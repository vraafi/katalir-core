import { QueryClient } from "@tanstack/react-query";

/**
 * Gedeelde QueryClient singleton (SSR-veilig via module-scope in client).
 * Standaard refetchOnWindowFocus=false (behalve chat, dat override per-query).
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { gcTime: 60_000, refetchOnWindowFocus: false, retry: 1 },
  },
});

/** Invalideer alle chat-queries bij auth-wissel (SIGNED_IN / SIGNED_OUT). */
export function invalidateChatQueries() {
  return queryClient.invalidateQueries({ queryKey: ["chat"] });
}