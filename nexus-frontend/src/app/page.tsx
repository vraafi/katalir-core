"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { Send, Sparkles, Bot, User, Loader2, KeyRound, RotateCcw, AlertTriangle } from "lucide-react";
import { motion } from "motion/react";
import { useQueryState, parseAsString } from "nuqs";
import Shell from "@/components/shell";
import { AuthProvider, useAuth } from "@/context/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { QueryProvider } from "@/features/builder/provider";
import { apiFetch } from "@/lib/api";
import { FadeIn } from "@/components/motion";
import { useSessionsQuery, useMessagesQuery, useSendChatMutation } from "@/features/chat/hooks/useChat";
import type { ChatMessage } from "@/features/chat/hooks/useChat";
import { useQueryClient } from "@tanstack/react-query";
import { useQuery } from "@tanstack/react-query";
import { chatKeys } from "@/lib/query-keys";

const SUGGESTIONS = ["Kirim pesan WA", "Rangkum dokumen", "Analisis data"];

const PROVIDER_LABELS: Record<string, string> = {
  whatsapp: "WhatsApp Cloud API",
  google_sheets: "Google Sheets",
  gmail: "Gmail",
  google_calendar: "Google Calendar",
};

type Msg =
  | { key: string; role: "user"; content: string }
  | { key: string; role: "assistant"; content: string }
  | {
      key: string;
      role: "system";
      type: "credential_form";
      provider: string;
      original: string;
    }
  | {
      key: string;
      role: "system";
      type: "error";
      content: string;
      original: string;
    };

interface SessionItem {
  id: string;
  title?: string;
}

function ChatApp() {
  const { email, loading } = useAuth();
  // URL state: ?s=<sessionId> (nuqs, shallow) — source of truth.
  const [sessionId, setSessionId] = useQueryState(
    "s",
    parseAsString.withOptions({ shallow: true, clearOnDefault: true })
  );
  const activeEmail = email || null;
  const [input, setInput] = useState("");
  const [credValue, setCredValue] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);

  const emailRef = useRef(activeEmail);
  useEffect(() => {
    emailRef.current = activeEmail;
  }, [activeEmail]);

  // Server-state via TanStack Query v5 (staleTime 60s, refetchOnWindowFocus=true).
  const { data: sessions = [] } = useSessionsQuery(activeEmail);
  const {
    data: messagesData = [],
    isFetching: messagesFetching,
    isFetched: messagesFetched,
  } = useMessagesQuery(sessionId);
  const sendMutation = useSendChatMutation();
  const qc = useQueryClient();
  const loadingMsg = sendMutation.isPending;

  // Fase 1: bila >5s pending, ubah indikator jadi "Memuat... (server sedang memproses)".
  const [slowHint, setSlowHint] = useState(false);
  useEffect(() => {
    if (!loadingMsg) {
      setSlowHint(false);
      return;
    }
    const t = setTimeout(() => setSlowHint(true), 5000);
    return () => clearTimeout(t);
  }, [loadingMsg]);

  // FIX #2a (key stabil — issue #685): pakai backend message.id bila ada.
  // useQuery hanya SUBSCRIBE (tanpa fetch duplikat — queryFn disabled,
  // data datang dari useMessagesQuery di atas); ini membuat komponen
  // re-render saat cache optimistic berubah (setQueryData).
  const activeKey = chatKeys.messages(sessionId ?? "__pending__");
  const { data: liveCache = [] } = useQuery<ChatMessage[]>({
    queryKey: activeKey,
    queryFn: () => Promise.resolve([] as ChatMessage[]),
    enabled: false,
    initialData: [],
  });
  void liveCache;
  // SINGLE SOURCE OF TRUTH (data-machine #210): TIDAK ada useState paralel.
  // Cache TanStack (optimistic via setQueryData) adalah satu-satunya sumber
  // overlay; server-data (messagesData) adalah sumber kebenaran pasca-refetch.
  // Merge (openclaw #14859): server duluan, lalu optimistic yang BELUM
  // terkonfirmasi (dedup by content) di-append.
  const cached: ChatMessage[] =
    qc.getQueryData<ChatMessage[]>(activeKey) ?? liveCache ?? [];
  const pendingCache: ChatMessage[] = !sessionId
    ? []
    : (qc.getQueryData<ChatMessage[]>(chatKeys.messages("__pending__")) ?? []);
  const overlay: ChatMessage[] = [...pendingCache, ...cached].filter((m) => !!m._localId);
  const serverConfirmed = new Set(
    messagesData.map((m) => `${m.role}|${m.content}`)
  );
  const unconfirmed = overlay.filter(
    (m) => m.type === "credential_form" || !serverConfirmed.has(`${m.role}|${m.content}`)
  );

  const messages: Msg[] = [
    ...messagesData
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m, i): Msg =>
        // FIX #2a: key stabil dari backend id bila ada (issue #685).
        // content-slice TIDAK dipakai — duplikat konten ("halo","halo")
        // dulu berbagi prefix key dan memicu remount/jitter.
        m.role === "user"
          ? { key: `srv-${m.id ?? `u-${i}`}`, role: "user", content: m.content }
          : { key: `srv-${m.id ?? `a-${i}`}`, role: "assistant", content: m.content }
      ),
    ...unconfirmed.map((m): Msg | null => {
      if (m.type === "credential_form" && m.provider && m.original !== undefined) {
        return { key: `cred-${m.id ?? m._localId ?? m.provider}`, role: "system", type: "credential_form", provider: m.provider, original: m.original };
      }
      if (m.type === "error" && m.original !== undefined) {
        return { key: `err-${m.id ?? m._localId ?? m.original}`, role: "system", type: "error", content: m.content, original: m.original };
      }
      if (m.role === "user") return { key: `opt-${m._localId ?? m.id ?? m.content}`, role: "user", content: m.content };
      if (m.role === "assistant") return { key: `opt-${m._localId ?? m.id ?? "pending"}`, role: "assistant", content: m.content };
      return null;
    }).filter((m): m is Msg => m !== null),
  ];

  // Sentinel: hanya auto-scroll saat user sudah di bawah (anti scroll-fighting).
  // Scroll area diberi ref scrollRef; endRef sebagai sentinel target.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
      setAtBottom(dist < 100);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!atBottom) return;
    endRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
  }, [messages, loadingMsg, atBottom]);

  // SISA echo-pattern lama DIHAPUS (fix #1 revisi): tidak ada lagi
  // sessionEchoRef / prevSessionIdRef / setLocalMsgs. Overlay hidup di
  // cache TanStack (onMutate) dan TIDAK PERNAH di-clear oleh pergantian
  // sessionId — refetch server hanya me-merge, bukan overwrite.

  const currentSessionId = sessionId || null;

  function openSession(id: string) {
    void setSessionId(id);
  }

  function newChat() {
    // Ganti sesi: cache optimistic sesi lama dibiarkan (terisolasi per key);
    // "__pending__" dibersihkan agar chat baru mulai bersih.
    qc.setQueryData<ChatMessage[]>(chatKeys.messages("__pending__"), []);
    void setSessionId(null);
    setInput("");
  }

  async function sendPrompt(text: string) {
    const em = emailRef.current;
    if (!em) {
      alert("Silakan login dulu untuk mengirim pesan.");
      return;
    }
    setInput("");
    // Optimistic bubble ditulis oleh onMutate (setQueryData) — TANPA useState.
    try {
      const data = await sendMutation.mutateAsync({ prompt: text, sessionId, email: em });
      if (data.session_id && !sessionId) {
        // Echo sesi baru: optimistic sudah dipindahkan ke key final oleh
        // onSuccess; cukup pindah URL. Overlay TIDAK di-clear di sini.
        void setSessionId(data.session_id);
      }
      // Reply + kartu kredensial datang via cache update (onSuccess) dan
      // query-invalidatie (messagesData refresh).
    } catch {
      // Error spesifik sudah dirender sebagai kartu (type=error) oleh onError
      // bersama tombol retry — TIDAK perlu alert generic di sini.
    }
  }

  /** Fase 1: tombol "Coba Lagi" pada kartu error. Hapus bubble error + user
   *  pasangannya dari cache, lalu kirim ulang prompt asli secara fresh. */
  async function retryMessage(errMsg: { content: string; original: string }) {
    const key = chatKeys.messages(sessionId ?? "__pending__");
    qc.setQueryData<ChatMessage[]>(key, (old) =>
      (old ?? []).filter(
        (m) =>
          !(m.type === "error" && m.original === errMsg.original && m.content === errMsg.content) &&
          !(m.role === "user" && m.content === errMsg.original)
      )
    );
    await sendPrompt(errMsg.original);
  }

  async function submitCredential(provider: string, original: string) {
    if (!credValue.trim() || !activeEmail) return;
    try {
      await apiFetch("/integrations", {
        method: "POST",
        body: JSON.stringify({ provider, token: credValue.trim() }),
      });
      setCredValue("");
      // Hapus kartu form dari cache (bukan dari useState).
      const keys = [chatKeys.messages(sessionId ?? "__pending__")];
      for (const k of keys) {
        qc.setQueryData<ChatMessage[]>(k, (old) =>
          (old ?? []).filter(
            (x) => !(x.type === "credential_form" && x.provider === provider)
          )
        );
      }
      await sendPrompt(original);
    } catch {
      alert("Gagal menyimpan kredensial.");
    }
  }

return (
    <Shell
      sessions={sessions}
      currentSessionId={currentSessionId}
      onSelectSession={openSession}
      onNewChat={newChat}
    >
      <div className="flex min-h-0 w-full flex-1 flex-col">
        {/* Chat area — scroll independen (flex-1), input di flow terpisah */}
        <div ref={scrollRef} className="chat-scroll min-h-0 w-full flex-1 overflow-y-auto">
          <div className="mx-auto flex min-h-full w-full max-w-[48rem] flex-col justify-end px-5 pt-4">
            {!loading && !activeEmail ? (
              <FadeIn className="m-auto flex w-full flex-col items-center text-center">
                <Bot size={48} strokeWidth={1.25} className="text-fg-subtle" />
                <h2 className="mt-4 text-title3 font-semibold text-fg">Silakan masuk dulu</h2>
                <p className="mt-1 max-w-sm text-callout text-fg-muted">
                  Gunakan tombol "Login dengan Google" di pojok kanan atas
                  untuk memulai percakapan.
                </p>
              </FadeIn>
            ) : messages.length === 0 && !loadingMsg ? (
              <FadeIn className="m-auto flex w-full flex-col items-center text-center">
                <div className="rounded-sm bg-surface/70 p-5 shadow-sm">
                  <Sparkles size={52} strokeWidth={1.25} className="text-accent drop-shadow-md" />
                </div>
                <h2 className="mt-5 text-title2 font-bold tracking-tight">
                  Halo, ada yang bisa saya bantu hari ini?
                </h2>
                <div className="mt-6 grid w-full max-w-md grid-cols-3 gap-3">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => sendPrompt(s)}
                      className="rounded-sm border border-border bg-surface px-3 py-2.5 text-subhead font-medium text-fg shadow-xs transition-all duration-200 hover:-translate-y-0.5 hover:border-accent/40 hover:text-accent"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </FadeIn>
            ) : (
          <>
            <div className="flex flex-col gap-4" data-testid="msg-list">
            {messages.map((msg) => (
              <motion.div
                key={msg.key}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5 }}
                style={{ willChange: "opacity, transform" }}
                className={`flex items-end gap-2 ${msg.role === "user" ? "justify-end" : ""}`}
              >
                {msg.role !== "user" && (
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-bg-subtle">
                    <Bot size={14} strokeWidth={1.5} className="text-fg-muted" />
                  </div>
                )}
                <div
                  className={
                    msg.role === "user"
                      ? "max-w-[75%] rounded-sm rounded-br-sm bg-accent px-4 py-2.5 text-subhead text-accent-fg shadow-sm"
                      : "max-w-[85%] rounded-sm rounded-bl-sm bg-surface px-4 py-2.5 text-subhead text-fg shadow-xs"
                  }
                >
                  {msg.role === "system" && msg.type === "credential_form" ? (
                    <div className="w-72">
                      <div className="flex items-center gap-2">
                        <KeyRound size={15} strokeWidth={1.5} className="text-accent" />
                        <span className="font-semibold text-fg">
                          Akses dibutuhkan: {PROVIDER_LABELS[msg.provider] ?? msg.provider}
                        </span>
                      </div>
                      <p className="mt-1.5 text-footnote text-fg-muted">
                        Masukkan token provider untuk melanjutkan tugas Anda.
                      </p>
                      <Input
                        value={credValue}
                        onChange={(e) => setCredValue(e.target.value)}
                        type="password"
                        placeholder="Token / API key..."
                        aria-label="Token / API key"
                      />
                      <Button
                        disabled={!credValue.trim()}
                        onClick={() => submitCredential(msg.provider, msg.original)}
                        className="mt-2.5 w-full justify-center"
                        variant="secondary"
                      >
                        Simpan & Lanjutkan
                      </Button>
                    </div>
                  ) : msg.role === "system" && msg.type === "error" ? (
                    <div className="w-72">
                      <div className="flex items-center gap-2 text-red-500">
                        <AlertTriangle size={15} strokeWidth={1.75} />
                        <span className="font-semibold text-fg">Gagal mengirim</span>
                      </div>
                      <p className="mt-1.5 text-footnote text-fg-muted">{msg.content}</p>
                      <Button
                        variant="secondary"
                        onClick={() => retryMessage({ content: msg.content, original: msg.original })}
                        className="mt-2.5 w-full justify-center gap-1.5"
                      >
                        <RotateCcw size={14} strokeWidth={1.75} />
                        Coba Lagi
                      </Button>
                    </div>
                  ) : (
                    msg.content
                  )}
                </div>
                {msg.role === "user" && (
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent">
                    <User size={14} strokeWidth={1.5} className="text-accent-fg" />
                  </div>
                )}
              </motion.div>
            ))}
              {loadingMsg && (
                <div className="flex items-center gap-2 text-subhead text-fg-muted animate-fade-in">
                  <Loader2 size={16} strokeWidth={1.5} className="animate-spin" />
                  {slowHint ? "Memuat... (server sedang memproses)" : "Agen sedang berpikir..."}
                </div>
              )}
            </div>
            <div ref={endRef} />
            {!atBottom && messages.length > 0 && (
              <button
                type="button"
                aria-label="Lompat ke bawah"
                onClick={() =>
                  endRef.current?.scrollIntoView({ behavior: "auto", block: "end" })
                }
                className="sticky bottom-2 mx-auto flex items-center gap-1.5 rounded-full border border-border bg-surface px-3 py-1.5 text-footnote text-fg-muted shadow-sm hover:text-fg"
              >
                ↓ Terbaru
              </button>
            )}
            {/* Fix #1: skeleton saat refetch sesi baru — nooit meer lege chat. */}
            {messages.length === 0 && sessionId && (messagesFetching || !messagesFetched || loadingMsg) && (
              <div className="flex flex-col gap-2.5" aria-live="polite" aria-busy="true">
                {[0, 1].map((i) => (
                  <div
                    key={i}
                    className="h-10 max-w-[70%] animate-pulse rounded-md bg-bg-subtle"
                  />
                ))}
              </div>
            )}
          </>
        )}
          </div>
        </div>
        {/* Input bar — flex-none, sticky di bawah, TIDAK ikut scroll */}
        <div className="flex-none border-t border-border bg-surface/95 px-5 py-3">
          <div className="mx-auto max-w-[48rem]">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (input.trim()) sendPrompt(input.trim());
              }}
              className="flex items-center gap-2 rounded-lg border border-border bg-bg/60 px-3 py-2 shadow-xs focus-within:border-accent/50"
            >
              <Input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={activeEmail ? "Ketik pesan ke Nexus Agent..." : "Login untuk mulai mengobrol"}
                aria-label="Pesan"
                className="h-9 border-0 shadow-none bg-transparent focus-visible:shadow-none"
              />
              <Button
                type="submit"
                size="icon"
                aria-label="Kirim"
                disabled={!input.trim() || loadingMsg}
                className="shrink-0"
              >
                <Send size={16} strokeWidth={1.75} />
              </Button>
            </form>
          </div>
        </div>
      </div>
    </Shell>
  );
}

export default function Home() {
  return (
    <AuthProvider>
      <QueryProvider>
        {/* Suspense DI IN page: vereist door Next 15 static-export voor useSearchParams (nuqs). */}
        <Suspense fallback={null}>
          <ChatApp />
        </Suspense>
      </QueryProvider>
    </AuthProvider>
  );
}