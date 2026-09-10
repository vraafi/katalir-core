"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Send, Sparkles, Bot, User, Loader2, KeyRound } from "lucide-react";
import Shell from "@/components/shell";
import { AuthProvider, useAuth } from "@/context/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
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
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loadingMsg, setLoadingMsg] = useState(false);
  const [credValue, setCredValue] = useState("");
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const activeEmail = email || null;
  // emailRef: selalu memegang email terbaru agar callback tak baca nilai lama (stale)
  const emailRef = useRef(activeEmail);
  useEffect(() => {
    emailRef.current = activeEmail;
  }, [activeEmail]);

  // Muat riwayat session saat email berubah
  const reloadSessions = useCallback(async () => {
    if (!activeEmail) {
      setSessions([]);
      setCurrentSessionId(null);
      setMessages([]);
      return;
    }
    try {
      const res = await fetch(`${API_URL}/sessions?email=${encodeURIComponent(activeEmail)}`);
      const data = await res.json();
      setSessions(data.sessions ?? []);
    } catch {
      setSessions([]);
    }
  }, [activeEmail]);

  useEffect(() => {
    reloadSessions();
  }, [reloadSessions]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loadingMsg]);

  // Buka satu sesi dari riwayat: muat pesannya
  async function openSession(sessionId: string) {
    setCurrentSessionId(sessionId);
    if (!activeEmail) return;
    try {
      const res = await fetch(
        `${API_URL}/messages/${sessionId}?email=${encodeURIComponent(activeEmail)}`
      );
      const data = await res.json();
      const msgs: Msg[] = (data.messages ?? []).map((m: any) => {
        if (m.role === "user") return { role: "user", content: m.content };
        return { role: "assistant", content: m.content };
      });
      setMessages(msgs);
    } catch {
      setMessages([]);
    }
  }

  // Chat Baru: reset state layar jadi kosong
  function newChat() {
    setCurrentSessionId(null);
    setMessages([]);
    setInput("");
  }

  // useCallback + baca email via ref agar status login SELALU ter-update (anti stale closure)
  const sendPrompt = useCallback(
    async (text: string, withCredential?: string) => {
      const em = emailRef.current;
      if (!em) {
        alert("Silakan login dulu untuk mengirim pesan.");
        return;
      }
      setLoadingMsg(true);
      setInput("");
      setMessages((m) => [...m, { role: "user", content: text }]);
    try {
      const body: any = {
        prompt: text,
        email: em,
        session_id: currentSessionId ?? undefined,
      };
      if (withCredential) body.credential = withCredential;
      const res = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (data.status === "needs_credential") {
        setMessages((m) => [
          ...m,
          { role: "system", type: "credential_form", provider: data.provider, original: text },
        ]);
      } else if (data.status === "success") {
        if (data.session_id && !currentSessionId) setCurrentSessionId(data.session_id);
        setMessages((m) => [...m, { role: "assistant", content: data.reply }]);
        // refresh riwayat sidebar agar nama/sesi baru muncul
        reloadSessions();
      } else {
        setMessages((m) => [...m, { role: "assistant", content: "Ada masalah, coba lagi." }]);
      }
    } catch {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: "Gagal terhubung ke server AI." },
      ]);
    } finally {
        setLoadingMsg(false);
      }
    },
    [currentSessionId, reloadSessions]
  );

  async function submitCredential(provider: string, original: string) {
    if (!credValue.trim() || !activeEmail) return;
    try {
      await fetch(`${API_URL}/integrations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: activeEmail, provider, token: credValue.trim() }),
      });
      setCredValue("");
      setMessages((m) =>
        m.filter(
          (x) => !(x.role === "system" && x.type === "credential_form" && x.provider === provider)
        )
      );
      await sendPrompt(original, provider);
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
      <ChatApp />
    </AuthProvider>
  );
}