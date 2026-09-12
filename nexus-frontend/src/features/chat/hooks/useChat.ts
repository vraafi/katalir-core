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
  role: "user" | "assistant" | "system";
  content: string;
  created_at?: string;
  /** Tag optimistic lokal (pattern openclaw #14859) — tidak dikirim ke server. */
  _localId?: string;
  /** Kartu form kredensial kontekstual (system message khusus). */
  type?: "credential_form";
  provider?: string;
  original?: string;
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

/** useMutation POST /chat — optimistic update single source of truth.
 * Pattern: data-machine #210 (hapus useState paralel) + openclaw #14859
 * (tag _localId, preserve saat refresh, dedup by content) + openclaw #49261
 * (drop pending saat send gagal — tanpa ghost message).
 * CATATAN: TIDAK pakai React useOptimistic — TanStack Query v5 + React 18
 * tidak menyediakannya (React 19 canary only); setQueryData adalah
 * pendekatan resmi v5 yang setara untuk kasus ini. */
export function useSendChatMutation() {
  const qc = useQueryClient();
  return useMutation<
    { reply: string; session_id?: string; needsCredential?: boolean; provider?: string; message?: string },
    Error & { provider?: string; promptEcho?: string },
    { prompt: string; sessionId?: string | null },
    {
      optimisticUserId: string;
      optimisticAsstId: string;
      targetKey: readonly unknown[];
      previous?: ChatMessage[];
      sessionId: string | null;
      prompt: string;
    }
  >({
    mutationFn: async ({ prompt, sessionId }) => {
      const res = await apiFetch("/chat", {
        method: "POST",
        body: JSON.stringify({ prompt, session_id: sessionId ?? undefined }),
      });
      const data = await res.json();
      if (data.status === "needs_credential") {
        // Kembalikan sebagai hasil terkendali (bukan throw) supaya kartu
        // form kredensial bisa dirender dari onSuccess via cache update.
        return {
          reply: "",
          session_id: data.session_id,
          needsCredential: true,
          provider: data.provider,
          message: data.message,
        };
      }
      if (data.status !== "success") {
        throw new Error(data.reply ?? data.message ?? "Gagal mengirim");
      }
      return { reply: data.reply, session_id: data.session_id };
    },
    onMutate: async ({ prompt, sessionId }) => {
      const key = chatKeys.messages(sessionId ?? "__pending__");
      await qc.cancelQueries({ queryKey: key });
      const previous = qc.getQueryData<ChatMessage[]>(key);
      const optimisticUserId = `local-user-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const optimisticAsstId = `local-asst-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const optimisticUser: ChatMessage = {
        id: optimisticUserId,
        _localId: optimisticUserId,
        role: "user",
        content: prompt,
      };
      const optimisticAsst: ChatMessage = {
        id: optimisticAsstId,
        _localId: optimisticAsstId,
        role: "assistant",
        content: "…",
      };
      qc.setQueryData<ChatMessage[]>(key, (old) => [...(old ?? []), optimisticUser, optimisticAsst]);
      return {
        optimisticUserId,
        optimisticAsstId,
        targetKey: key,
        previous,
        sessionId: sessionId ?? null,
        prompt,
      };
    },
    onError: (err, _vars, context) => {
      // openclaw #49261: drop pending optimistic — jangan biarkan ghost message.
      if (context) {
        qc.setQueryData<ChatMessage[]>(context.targetKey, (old) =>
          (old ?? []).filter(
            (m) => m._localId !== context.optimisticUserId && m._localId !== context.optimisticAsstId
          )
        );
      }
      void err;
    },
    onSuccess: (data, vars, context) => {
      // Sesi baru (session_id dari echo): pindahkan optimistic ke key final,
      // lalu invalidasi agar server-data sinkron (dedup by content di page).
      const finalKey = chatKeys.messages(data.session_id ?? vars.sessionId ?? "__pending__");
      if (context && (finalKey.join("/") !== context.targetKey.join("/"))) {
        const moving = (qc.getQueryData<ChatMessage[]>(context.targetKey) ?? []).filter(
          (m) => m._localId === context.optimisticUserId || m._localId === context.optimisticAsstId
        );
        if (moving.length) {
          qc.setQueryData<ChatMessage[]>(finalKey, (old) => [...(old ?? []), ...moving]);
        }
        qc.setQueryData<ChatMessage[]>(context.targetKey, context.previous ?? []);
      }
      if (data.needsCredential && context) {
        // Ganti placeholder assistant dengan kartu form kredensial.
        qc.setQueryData<ChatMessage[]>(finalKey, (old) =>
          (old ?? []).map((m) =>
            m._localId === context.optimisticAsstId
              ? {
                  id: `local-cred-${Date.now()}`,
                  role: "system",
                  content: "",
                  type: "credential_form",
                  provider: data.provider,
                  original: context.prompt,
                }
              : m
          )
        );
      }
      // Invalideer sessions (judul baru) dan messages sesi final.
      void qc.invalidateQueries({ queryKey: chatKeys.all });
      if (data.session_id) {
        void qc.invalidateQueries({ queryKey: chatKeys.messages(data.session_id) });
      }
    },
  });
}