"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { Send, Sparkles, Bot, User, Loader2, KeyRound } from "lucide-react";
import { useQueryState, parseAsString } from "nuqs";
import Shell from "@/components/shell";
import { AuthProvider, useAuth } from "@/context/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { QueryProvider } from "@/features/builder/provider";
import { apiFetch } from "@/lib/api";
import { useSessionsQuery, useMessagesQuery, useSendChatMutation } from "@/features/chat/hooks/useChat";

const SUGGESTIONS = ["Kirim pesan WA", "Rangkum dokumen", "Analisis data"];

const PROVIDER_LABELS: Record<string, string> = {
  whatsapp: "WhatsApp Cloud API",
  google_sheets: "Google Sheets",
  gmail: "Gmail",
  google_calendar: "Google Calendar",
};

type Msg =
  | { role: "user"; content: string }
  | { role: "assistant"; content: string }
  | {
      role: "system";
      type: "credential_form";
      provider: string;
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
  const [loadingMsg, setLoadingMsg] = useState(false);
  const [credValue, setCredValue] = useState("");
  // Overlay: berichten alleen lokaal (o.a. credential_form + user-pijl).
  const [localMsgs, setLocalMsgs] = useState<Msg[]>([]);
  const endRef = useRef<HTMLDivElement>(null);

  const emailRef = useRef(activeEmail);
  useEffect(() => {
    emailRef.current = activeEmail;
  }, [activeEmail]);

  // Server-state via TanStack Query v5 (staleTime 60s, refetchOnWindowFocus=true).
  const { data: sessions = [] } = useSessionsQuery(activeEmail);
  const { data: messagesData = [] } = useMessagesQuery(sessionId);
  const sendMutation = useSendChatMutation();

  // Combineer server-berichten (uit query) + lokale overlay.
  const messages: Msg[] = [
    ...messagesData.map((m): Msg =>
      m.role === "user"
        ? { role: "user", content: m.content }
        : { role: "assistant", content: m.content }
    ),
    ...localMsgs,
  ];

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loadingMsg]);

  // Bij wisselen van sessie: reset lokale overlay.
  useEffect(() => {
    setLocalMsgs([]);
  }, [sessionId]);

  const currentSessionId = sessionId || null;

  function openSession(id: string) {
    void setSessionId(id);
  }

  function newChat() {
    void setSessionId(null);
    setLocalMsgs([]);
    setInput("");
  }

  async function sendPrompt(text: string) {
    const em = emailRef.current;
    if (!em) {
      alert("Silakan login dulu untuk mengirim pesan.");
      return;
    }
    setLoadingMsg(true);
    setInput("");
    setLocalMsgs((m) => [...m, { role: "user", content: text }]);
    try {
      const data = await sendMutation.mutateAsync({ prompt: text, sessionId });
      if (data.session_id && !sessionId) void setSessionId(data.session_id);
      // Reply komt via query-invalidatie (messagesData refresh).
    } catch {
      setLocalMsgs((m) => [
        ...m,
        { role: "assistant", content: "Gagal terhubung ke server AI." },
      ]);
    } finally {
      setLoadingMsg(false);
    }
  }

  async function submitCredential(provider: string, original: string) {
    if (!credValue.trim() || !activeEmail) return;
    try {
      await apiFetch("/integrations", {
        method: "POST",
        body: JSON.stringify({ provider, token: credValue.trim() }),
      });
      setCredValue("");
      setLocalMsgs((m) =>
        m.filter(
          (x) => !(x.role === "system" && x.type === "credential_form" && x.provider === provider)
        )
      );
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
      {/* Chat area */}
      <div className="flex-1 space-y-4 overflow-y-auto px-5 pb-28 pt-4">
        {!loading && !activeEmail ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <Bot size={48} strokeWidth={1.25} className="text-fg-subtle" />
            <h2 className="mt-4 text-title3 font-semibold text-fg">Silakan masuk dulu</h2>
            <p className="mt-1 max-w-sm text-callout text-fg-muted">
              Gunakan tombol "Login dengan Google" di pojok kanan atas
              untuk memulai percakapan.
            </p>
          </div>
        ) : messages.length === 0 && !loadingMsg ? (
          <div className="flex h-full flex-col items-center justify-center text-center animate-fade-up">
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
          </div>
        ) : (
          <>
            {messages.map((msg, i) => (
              <div
                key={i}
                className={`flex items-end gap-2 animate-fade-up ${
                  msg.role === "user" ? "justify-end" : ""
                }`}
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
                  ) : msg.role === "system" ? (
                    msg.original
                  ) : (
                    msg.content
                  )}
                </div>
                {msg.role === "user" && (
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent">
                    <User size={14} strokeWidth={1.5} className="text-accent-fg" />
                  </div>
                )}
              </div>
            ))}

            {loadingMsg && (
              <div className="flex items-center gap-2 text-subhead text-fg-muted animate-fade-in">
                <Loader2 size={16} strokeWidth={1.5} className="animate-spin" /> Agen sedang berpikir...
              </div>
            )}
          </>
        )}
        <div ref={endRef} />
      </div>
{/* Floating input */}
      <div className="pointer-events-none fixed bottom-0 left-64 right-0">
        <div className="pointer-events-auto mx-auto max-w-3xl px-4 pb-5">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (input.trim()) sendPrompt(input.trim());
            }}
            className="flex items-center gap-2 rounded-sm border border-border bg-surface/95 p-1.5 shadow-md backdrop-blur"
          >
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={activeEmail ? "Ketik pesan ke Nexus Agent..." : "Login untuk mulai mengobrol"}
              aria-label="Pesan"
              className="h-9 border-0 shadow-none focus-visible:shadow-none bg-transparent"
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