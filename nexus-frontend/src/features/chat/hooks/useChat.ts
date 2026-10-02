// useChat.ts — server-state voor chat via TanStack Query v5.
// Volgt Makerkit-pattern: staleTime 60s, query keys factory, query
// functies gescheiden. refetchOnWindowFocus=true (chat moet fresh zijn).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CHAT_TIMEOUT_MS, apiFetch, classifyChatError, classifyHttpError, sleep } from "@/lib/api";
import { chatKeys } from "@/lib/query-keys";

/** Error khusus untuk pembatalan user (Stop button). onError membedakannya
 *  agar optimistic DIBUANG (bukan di-hold jadi kartu error). */
export function canceledError(message = "Dibatalkan"): Error {
  const e = new Error(message) as Error & { name: string };
  e.name = "CanceledError";
  return e;
}

export interface SessionItem {
  id: string;
  title?: string;
  created_at?: string;
}

/** Metadata model (transparansi). Satu definisi untuk semua jalur —
 *  sebelumnya bentuk ini diduplikasi inline 3x sehingga field baru
 *  (requested_model/fallback_reason) mudah lolos dari salah satu jalur. */
export interface ChatMeta {
  /** Model yang BENAR-BENAR menjawab. */
  model?: string;
  /** Model yang DIMINTA user — untuk "diminta vs dipakai" (claude-jacked). */
  requested_model?: string;
  latency_ms?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  fallback?: boolean;
  /** Kode penyebab fallback: quota_exhausted | rate_limit | overloaded |
   *  model_unavailable | gateway_down. Kosong saat request normal. */
  fallback_reason?: string | null;
  /** True bila dijawab lewat free-llm-gateway (self-hosted). */
  gateway?: boolean;
  /** FASE 2.1/2.2: draf workflow dari Discovery Agent (bentuk mentah — divalidasi
   *  ulang di `parseAgentWorkflow` sebelum menyentuh kanvas). */
  workflow?: unknown;
  provider?: string;
}

export interface ChatMessage {
  id?: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at?: string;
  /** Tag optimistic lokal (pattern openclaw #14859) — tidak dikirim ke server. */
  _localId?: string;
  /** Kartu form kredensial / kartu OAuth / kartu error kontekstual (system message khusus). */
  type?: "credential_form" | "oauth_prompt" | "error";
  provider?: string;
  original?: string;
  /** Task 1C: endpoint authorize dari backend (hanya untuk `oauth_prompt`). */
  connectUrl?: string;
  /** Metadata model (transparansi): model, latency, tokens, fallback. */
  meta?: ChatMeta;
  /** BUG FIX 2026-10-01: kunci idempotensi kiriman logis. Disimpan pada kartu
   *  error agar `retry` mengirim UUID yang SAMA — kalau di-regenerate, backend
   *  tidak bisa melakukan dedup dan pesan user ter-insert GANDUL tiap retry. */
  clientRequestId?: string;
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

/** useQuery messages voor een sessie.
 * FIX Tugas1 (TanStack #10712): staleTime=Infinity + refetchOnWindowFocus=false.
 * Reply/optimistic ditulis via setQueryData (single source), jadi SEBUAH refetch
 * (focus/reconnect/stale) die terdaat-belakangan tidak boleh menimpanya dengan
 * data server yang belum ter-commit. Hanya fetch pertama per sesi yang berhak
 * mengisi; sisanya dikontrol onMutate/onSuccess.
 *
 * FIX Baru (chat-aktif blank): staleTime=Infinity WAJIB dipasangkan gcTime=Infinity
 * (TanStack caching guide). Default global gcTime=60s → entri cache bisa di-GC
 * saat idle/background/remount di browser nyata; karena refocus sudah false,
 * tidak ada refetch yang akan memulihkan → chat 'kosong' permanen (area utama
 * blanks walau sidebar & DB masih utuh). gcTime=Infinity mempertahankan entri
 * selama aplikasi hidup. placeholderData=(prev)=>prev menahan data terakhir
 * saat query sempat tanpa data (guard H4) → tidak pernah blank flash. */
export function useMessagesQuery(sessionId: string | null) {
  // FIX B (intermittent blank): kalau cache messages(sessionId) SUDAH berisi
  // optimistic (punya _localId — hasil echo send-pesan), JANGAN auto-fetch.
  // Fetch pertama yang menyusul bisa mengembalikan server yang masih lag
  // (kosong) dan MENIMPA optimistic+reply yang barusan ditulis via setQueryData
  // => chat 'hilang lalu muncul'. Optimistic+reply adalah sumbernya; Genuine
  // sidebar-open (cache tanpa _localId) tetap fetch server normal.
  const qc = useQueryClient();
  const hasLocal = !!sessionId && (qc.getQueryData<ChatMessage[]>(chatKeys.messages(sessionId)) ?? []).some((m) => !!m._localId);
  return useQuery({
    queryKey: chatKeys.messages(sessionId ?? ""),
    queryFn: () => fetchMessages(sessionId ?? ""),
    enabled: !!sessionId, // FIX REGRESI 2026-09-13: guard lama mematikan fetch utk sesi tanpa optimistic -> UI kosong permanen. Perlindungan optimistic ditangani merge server+overlay di page.tsx.
    staleTime: Infinity,
    gcTime: Infinity,
    // TANPA placeholderData: placeholder (prev) => prev menahan data sesi
    // lama 1-2 frame saat pindah sesi -> Chat Baru tampil chat lama (bug).
    refetchOnWindowFocus: false,
  });
}

export interface ChatModelItem {
  id: string;
  name: string;
  provider: string;
  tier: "free" | "plus";
  locked: boolean;
  hint?: string;
}

/** useQuery GET /me — profil {email, tier} untuk tier-gate ModelSelector. */
export function useMeQuery(enabled: boolean) {
  return useQuery({
    queryKey: ["me"],
    queryFn: async (): Promise<{ email: string; tier: string }> => {
      const res = await apiFetch("/me");
      if (!res.ok) return { email: "", tier: "free" };
      const data = await res.json();
      return { email: data?.email ?? "", tier: String(data?.tier ?? "free").toLowerCase() };
    },
    enabled,
    staleTime: 300_000,
    refetchOnWindowFocus: false,
  });
}

/** useQuery GET /models — daftar model + flag locked per tier user. */
export function useModelsQuery(enabled: boolean) {
  return useQuery({
    queryKey: ["models"],
    queryFn: async (): Promise<{
      tier: string;
      def: string;
      models: ChatModelItem[];
      /** True bila daftar berasal dari sumber cadangan (roster gateway gagal). */
      degraded: boolean;
    }> => {
      const res = await apiFetch("/models");
      if (!res.ok) return { tier: "free", def: "", models: [], degraded: false };
      const data = await res.json();
      return {
        tier: String(data?.tier ?? "free").toLowerCase(),
        def: String(data?.default ?? ""),
        models: (data?.models as ChatModelItem[]) ?? [],
        // Backend mengirim `degraded` + `roster_source` (2026-09-19). Bila
        // server belum memuat versi itu, anggap sehat (jangan memunculkan
        // peringatan palsu).
        degraded: data?.degraded === true,
      };
    },
    enabled,
    staleTime: 300_000,
    refetchOnWindowFocus: false,
  });
}

/** useMutation DELETE /sessions/{id} — hapus riwayat + isinya (cascade). */
export function useDeleteSessionMutation() {
  const qc = useQueryClient();
  return useMutation<void, Error, { sessionId: string; email: string }>({
    mutationFn: async ({ sessionId }) => {
      const res = await apiFetch(`/sessions/${encodeURIComponent(sessionId)}`, {
        method: "DELETE",
        timeoutMs: 30_000,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error((body as { detail?: string })?.detail || "Gagal menghapus percakapan.");
      }
    },
    onSuccess: (_d, { sessionId, email }) => {
      // Buang cache pesan sesi itu + refetch daftar riwayat.
      qc.removeQueries({ queryKey: chatKeys.messages(sessionId) });
      if (email) void qc.invalidateQueries({ queryKey: chatKeys.sessions(email) });
    },
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
    { reply: string; session_id?: string; needsCredential?: boolean; needsOauth?: boolean; provider?: string; connectUrl?: string; message?: string; meta?: ChatMeta },
    Error & { provider?: string; promptEcho?: string },
    { prompt: string; sessionId?: string | null; email?: string | null; abortSignal?: AbortSignal; clientRequestId?: string; model?: string; retryOfLocalId?: string },
    {
      optimisticUserId: string;
      optimisticAsstId: string;
      targetKey: readonly unknown[];
      previous?: ChatMessage[];
      sessionId: string | null;
      prompt: string;
      /** BUG FIX 2026-10-01: retry TIDAK menambah bubble user baru (sudah ada
       *  dan sudah ter-persist di server); ia hanya mengganti kartu error. */
      isRetry: boolean;
    }
  >({
    mutationFn: async ({ prompt, sessionId, abortSignal, clientRequestId, model }) => {
      // Fase 1 resilience: timeout 90s (di apiFetch) + retry 2x dengan
      // exponential backoff (2s,5s) UNTUK error transien (503/network/abort).
      // Retry di-loop di sini (bukan 'retry' TanStack) supaya onMutate cuma
      // sekali -> optimistic bubble JOHN saat retry, drop cuma di onError final.
      // Cancel (Stop): abortSignal.aborted -> lempar CanceledError, BERHENTI retry.
      // client_request_id: UUID per kiriman logis -> backend idempoten, mencegah
      // pesan user DUPLIKAT kalau request ini retry-setelah-server-commit.
      const body = JSON.stringify({
        prompt,
        session_id: sessionId ?? undefined,
        client_request_id: clientRequestId ?? undefined,
        model: model ?? undefined, // Vercel AI SDK 5 body:{model} — dikirim apa adanya, difallback di backend.
      });
      const maxAttempts = 3; // 1 + 2 retry
      const delays = [2000, 5000];
      // BUG FIX 2026-10-02: plafon PER-COBAN, bukan plafon total.
      //
      // Sebelumnya setiap percobaan memakai CHAT_TIMEOUT_MS penuh (150s).
      // Dengan maxAttempts=3 itu memberi plafon efektif 3x150s + 7s = 457s,
      // BUKAN 187s seperti yang diklaim komentar di bawah. Satu percobaan
      // yang macet menghabiskan seluruh anggaran sebelum retry sempat jalan.
      //
      // Backend punya anggaran LLM sendiri (default 45s via LLM_GATEWAY_BUDGET),
      // jadi attempt yang masih hidup jauh di bawah 150s sudah pasti macet.
      const perAttemptMs = Math.max(
        30_000,
        Math.floor(CHAT_TIMEOUT_MS / maxAttempts) - 5_000,
      );
      for (let attempt = 0; ; attempt++) {
        if (abortSignal?.aborted) throw canceledError();
        let res: Response;
        try {
          // BUG FIX 2026-10-01: fetch ini memakai CHAT_TIMEOUT_MS, bukan
          // 90_000 global. Alasannya `apiFetch` install timer per fetch; 90s
          // cukup untuk endpoint biasa, tapi satu percobaan /chat yang macet
          // akan memicu abort dan user melihat "Server lambat" walaupun
          // backend masih bekerja. Plafon retry loop sendiri =
          // 3 x budget backend + 7s backoff, harus < CHAT_TIMEOUT_MS.
          res = await apiFetch("/chat", { method: "POST", body, timeoutMs: perAttemptMs, signal: abortSignal });
        } catch (e) {
          if (abortSignal?.aborted) throw canceledError();
          const { message, retryable } = classifyChatError(e);
          if (retryable && attempt < maxAttempts - 1) {
            await sleep(delays[attempt] ?? 2000);
            continue;
          }
          throw new Error(message);
        }
        let data: Record<string, unknown> = {};
        try {
          data = await res.json();
        } catch {
          /* body non-json */
        }
        if (data.status === "needs_credential") {
          return {
            reply: "",
            session_id: data.session_id as string | undefined,
            needsCredential: true,
            provider: data.provider as string | undefined,
            message: data.message as string | undefined,
          };
        }
        if (data.status === "needs_oauth") {
          // Task 1C: provider OAuth (Google/Slack). UI menampilkan TOMBOL
          // Connect, bukan form token — form akan meminta user menempel
          // sesuatu yang tidak mungkin benar untuk provider ber-OAuth.
          return {
            reply: "",
            session_id: data.session_id as string | undefined,
            needsOauth: true,
            provider: data.provider as string | undefined,
            connectUrl: data.connect_url as string | undefined,
            message: data.message as string | undefined,
          };
        }
        if (res.ok && data.status === "success") {
          return { reply: data.reply as string, session_id: data.session_id as string | undefined, meta: data.meta as ChatMeta | undefined };
        }
        const { message, retryable } = classifyHttpError(res.status);
        if (retryable && attempt < maxAttempts - 1) {
          await sleep(delays[attempt] ?? 2000);
          continue;
        }
        throw new Error(message);
      }
    },
    onMutate: async ({ prompt, sessionId, retryOfLocalId }) => {
      const key = chatKeys.messages(sessionId ?? "__pending__");
      await qc.cancelQueries({ queryKey: key });
      const previous = qc.getQueryData<ChatMessage[]>(key);
      const isRetry = Boolean(retryOfLocalId);
      const optimisticUserId = `local-user-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      // Pada retry, placeholder assistant MEWAKILI kartu error (ganti di tempat,
      // _localId sama) supaya key React stabil dan kartu error tidak mengambang
      // sebagai kartu lama sementara placeholder baru muncul.
      const optimisticAsstId = isRetry
        ? (retryOfLocalId as string)
        : `local-asst-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
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
      qc.setQueryData<ChatMessage[]>(key, (old) => {
        const base = old ?? [];
        if (isRetry) {
          // JANGAN tambah bubble user: pesan itu sudah tampil DAN sudah
          // ter-insert di server pada percakapan pertama. Menambahnya lagi
          // bikin user melihat pesan dobel, dan mengosongkan cache bila
          // retried-nya juga gagal (bug "riwayat hilang").
          return [...base.filter((m) => m._localId !== optimisticAsstId),
            optimisticAsst];
        }
        return [...base, optimisticUser, optimisticAsst];
      });
      return {
        optimisticUserId,
        optimisticAsstId,
        targetKey: key,
        previous,
        sessionId: sessionId ?? null,
        prompt,
        isRetry,
      };
    },
    onError: (err, vars, context) => {
      if (!context) return;
      // User klik Stop: buang bubble optimistic user+asst yang sedang diproses
      // (jangan holt jadi kartu error).
      if ((err as Error)?.name === "CanceledError") {
        qc.setQueryData<ChatMessage[]>(context.targetKey, (old) =>
          (old ?? []).filter(
            (m) =>
              // Pada retry TIDAK ada bubble user baru milik kiriman ini, jadi
              // bubble user milik giliran lain WAJIB tetap ada. Versi lama
              // membungkus segalanya dalam satu filter dan ikut menghapus
              // `optimisticUserId` milik giliran LAIN karena nilainya selalu
              // di-generate ulang -> history terkirim ikut hilang saat Stop.
              m._localId !== context.optimisticAsstId &&
              (!context.isRetry || m._localId !== context.optimisticUserId)
          )
        );
        return;
      }
      // Fase 1: HOLD optimistic — jangan hapus bubble user sampai reply/error
      // jelas (instruksi user). Kita ganti placeholder assistant "…" dengan
      // kartu error (role system type error) + tombol retry. Retry di dalam
      // mutationFn sudah habis sebelum onError ini dipanggil.
      const msg = (err as Error)?.message || "Terjadi kesalahan. Coba lagi.";
      qc.setQueryData<ChatMessage[]>(context.targetKey, (old) =>
        (old ?? []).map((m) =>
          m._localId === context.optimisticAsstId
            ? {
                id: `local-err-${Date.now()}`,
                _localId: context.optimisticAsstId,
                role: "system",
                type: "error",
                content: msg,
                original: context.prompt,
                // Kunci idempotensi ikut dibawa ke kartu error. Tanpa ini
                // `retry` membuat UUID BARU -> backend tidak bisa dedup ->
                // pesan user ter-insert ulang di DB tiap kali retry.
                clientRequestId: vars.clientRequestId,
              }
            : m
        )
      );
    },
    onSuccess: (data, vars, context) => {
      // Sesi baru (session_id dari echo): pindahkan optimistic ke key final.
      // FIX A: JANGAN reset targetKey ("__pending__") di sini/sendPrompt — 
      // setSessionId (nuqs) async; reset sinkron bisa commit lebih dulu =>
      // activeKey("__pending__") kosong => blank 1-2 frame. "__pending__"
      // dikosongkan oleh effect[sessionId] (setelah commit) dan newChat;
      // overlay men-dedup per _localId agar tidak duplikat saat frame switch.
      const finalKey = chatKeys.messages(data.session_id ?? vars.sessionId ?? "__pending__");
      if (context && (finalKey.join("/") !== context.targetKey.join("/"))) {
        // Pada retry TIDAK ada bubble user baru milik kiriman ini, jadi
        // menyaring hanya dua `_localId` akan meninggalkan bubble user YANG
        // SUDAH ADA di `__pending__` -> ikut terhapus saat effect[sessionId]
        // mengosongkan `__pending__` = "percakapan hilang" setelah reply sukses.
        // Karena itu untuk retry kita pindahkan SELURUH isi targetKey.
        const moving = context.isRetry
          ? (qc.getQueryData<ChatMessage[]>(context.targetKey) ?? [])
          : (qc.getQueryData<ChatMessage[]>(context.targetKey) ?? []).filter(
              (m) => m._localId === context.optimisticUserId
                || m._localId === context.optimisticAsstId
            );
        if (moving.length) {
          qc.setQueryData<ChatMessage[]>(finalKey, (old) => [...(old ?? []), ...moving]);
        }
        // CATATAN: sengaja TIDAK reset context.targetKey ("__pending__") di sini —
        // lihat FIX A di atas; "__pending__" dikosongkan oleh effect[sessionId].
      }
      if ((data.needsCredential || data.needsOauth) && context) {
        // Ganti placeholder assistant dengan kartu form kredensial / kartu
        // Connect OAuth (Task 1C: `oauth_prompt`). PENTING: `_localId` HARUS
        // dipertahankan. Layer render (`page.tsx` `overlay`) hanya meneruskan
        // entri yang punya `_localId`; tanpa itu kartu kredensial dibuang
        // sebelum sempat tampil dan user tidak pernah bisa mengisi token
        // (bug nyata pada S2: /chat menjawab needs_credential, UI tidak
        // menampilkan apa pun).
        qc.setQueryData<ChatMessage[]>(finalKey, (old) =>
          (old ?? []).map((m) =>
            m._localId === context.optimisticAsstId
              ? {
                  id: `local-cred-${Date.now()}`,
                  _localId: context.optimisticAsstId,
                  role: "system",
                  content: "",
                  type: data.needsOauth ? "oauth_prompt" : "credential_form",
                  provider: data.provider,
                  connectUrl: data.connectUrl,
                  original: context.prompt,
                }
              : m
          )
        );
      } else if (context && data.reply) {
        // FIX Bug2 (TanStack #10712): TULIS reply ke cache via setQueryData,
        // JANGAN invalidateQueries(messages) -> refetch lama bisa datang
        // belakangan & overwrite optimistic -> chat 'hilang' (coder #23995).
        qc.setQueryData<ChatMessage[]>(finalKey, (old) =>
          (old ?? []).map((m) =>
            m._localId === context.optimisticAsstId
              ? { ...m, content: data.reply, meta: data.meta }
              : m
          )
        );
      }
      // Hanya invalidate SESSIONS (sidebar munculkan entri/judul baru).
      // Messages TIDAK di-invalidate (lihat komentar Bug2 di atas).
      if (vars.email) {
        void qc.invalidateQueries({ queryKey: chatKeys.sessions(vars.email) });
      }
    },
  });
}