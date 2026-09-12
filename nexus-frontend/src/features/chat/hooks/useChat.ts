// useChat.ts — server-state voor chat via TanStack Query v5.
// Volgt Makerkit-pattern: staleTime 60s, query keys factory, query
// functies gescheiden. refetchOnWindowFocus=true (chat moet fresh zijn).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { chatKeys } from "@/lib/query-keys";

export interface SessionItem {
  id: string;
  title?: string;
  created_at?: string;
}

export interface ChatMessage {
  id?: string;
  role: "user" | "assistant";
  content: string;
  created_at?: string;
}

async function fetchSessions(email: string): Promise<SessionItem[]> {
  if (!email) return [];
  const res = await apiFetch("/sessions");
  if (!res.ok) return [];
  const data = await res.json();
  return (data?.sessions as SessionItem[]) ?? [];
}

async function fetchMessages(sessionId: string): Promise<ChatMessage[]> {
  if (!sessionId) return [];
  const res = await apiFetch(`/messages/${sessionId}`);
  if (!res.ok) return [];
  const data = await res.json();
  return (data?.messages as ChatMessage[]) ?? [];
}

/** useQuery sessions — staleTime 1 minuut, refetchOnWindowFocus=true. */
export function useSessionsQuery(email: string | null) {
  return useQuery({
    queryKey: chatKeys.sessions(email ?? ""),
    queryFn: () => fetchSessions(email ?? ""),
    enabled: !!email,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  });
}

/** useQuery messages voor een sessie — staleTime 1 minuut. */
export function useMessagesQuery(sessionId: string | null) {
  return useQuery({
    queryKey: chatKeys.messages(sessionId ?? ""),
    queryFn: () => fetchMessages(sessionId ?? ""),
    enabled: !!sessionId,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  });
}

/** useMutation POST /chat — stuurt prompt, geeft session_id + reply. */
export function useSendChatMutation() {
  const qc = useQueryClient();
  return useMutation<
    { reply: string; session_id?: string },
    Error,
    { prompt: string; sessionId?: string | null },
    { previousKeys?: readonly unknown[] }
  >({
    mutationFn: async ({ prompt, sessionId }) => {
      const res = await apiFetch("/chat", {
        method: "POST",
        body: JSON.stringify({ prompt, session_id: sessionId ?? undefined }),
      });
      const data = await res.json();
      if (data.status === "needs_credential") {
        // Frontend meldt credentials-nodig via error payload
        throw new Error("NEEDS_CREDENTIAL");
      }
      if (data.status !== "success") {
        throw new Error(data.reply ?? "Gagal mengirim");
      }
      return { reply: data.reply, session_id: data.session_id };
    },
    onSuccess: (data) => {
      // Invalideer sessions (nieuwe sessie mogelijk) en messages van de sessie.
      void qc.invalidateQueries({ queryKey: chatKeys.all });
      if (data.session_id) {
        void qc.invalidateQueries({ queryKey: chatKeys.messages(data.session_id) });
      }
    },
  });
}