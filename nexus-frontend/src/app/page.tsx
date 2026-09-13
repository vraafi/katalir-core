"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { Send, Square, Sparkles, Bot, User, KeyRound, RotateCcw, AlertTriangle, Pencil, X, Clock, ChevronDown, ChevronRight } from "lucide-react";
import { motion } from "motion/react";
import { useQueryState, parseAsString } from "nuqs";
import Shell from "@/components/shell";
import { AuthProvider, useAuth } from "@/context/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { QueryProvider } from "@/features/builder/provider";
import { apiFetch } from "@/lib/api";
import { FadeIn } from "@/components/motion";
import { useSessionsQuery, useMessagesQuery, useSendChatMutation, useDeleteSessionMutation } from "@/features/chat/hooks/useChat";
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

/** Indikator mengetik: 3 dot animasi (transform+opacity only, CSS .typing-dot).
 * CallSphere 200ms rule — bukan spinner statis. Reduced-motion di-global CSS. */
function TypingDots({ ariaHidden }: { ariaHidden?: boolean }) {
  return (
    <span
      aria-hidden={ariaHidden}
      className="inline-flex items-center text-current"
    >
      <span className="typing-dot" />
      <span className="typing-dot" />
      <span className="typing-dot" />
    </span>
  );
}

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

/** Pesan yang menunggu diproses saat AI sedang sibuk (queue FIFO). */
interface QueuedMsg {
  id: string;
  text: string;
}

/** id unik lokal untuk item antrean. */
function qid(): string {
  return Math.random().toString(36).slice(2, 9) + Date.now().toString(36);
}

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
  // Antrean pesan di atas composer (Opsi A — openclaw #104445, Geta.Team
  // v2.0.20, gini-agent ADR): bukan konten chat primer, tapi slim status
  // area; compact + collapsible + persist localStorage + animasi opacity.
  const [messageQueue, setMessageQueue] = useState<QueuedMsg[]>(() => {
    try {
      if (typeof window === "undefined") return [];
      const raw = window.localStorage.getItem("nexus.queue.v1");
      if (!raw) return [];
      const arr = JSON.parse(raw) as QueuedMsg[];
      return Array.isArray(arr) ? arr.filter((m) => m && typeof m.text === "string") : [];
    } catch {
      return [];
    }
  });
  const [queueExpanded, setQueueExpanded] = useState(false);
  // Edit pesan di antrean (Fix 4) + konfirmasi Chat Baru saat AI aktif (Fix 6).
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [confirmNewChat, setConfirmNewChat] = useState(false);
  // Cancel (Stop): pada permintaan /chat yang sedang berjalan.
  const cancelRef = useRef<AbortController | null>(null);
  // Flag sinkron "ada mutasi berjalan": isPending (React state) update async,
  // sehingga 3 submit dalam 1 tick bisa lolos semua -> 3 mutateAsync paralel
  // yang menabrak pasangan optimistic user+asst. busyRef menutup celah ini.
  const busyRef = useRef(false);
  const endRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);

  const emailRef = useRef(activeEmail);
  useEffect(() => {
    emailRef.current = activeEmail;
  }, [activeEmail]);

  // Persist antrean (gini-agent ADR, fallback localStorage): refresh page
  // -> queue tetap ada. Tulis debounced-natural via effect per perubahan.
  useEffect(() => {
    try {
      if (typeof window === "undefined") return;
      window.localStorage.setItem("nexus.queue.v1", JSON.stringify(messageQueue));
    } catch {
      /* storage penuh/diblokir — queue tetap jalan in-memory */
    }
  }, [messageQueue]);

  // Default collapsed (Geta.Team v2.0.20): tiap ada item baru, kembali
  // collapsed agar area tetap slim; user klik untuk expand.
  const prevQueueLen = useRef(messageQueue.length);
  useEffect(() => {
    if (messageQueue.length > prevQueueLen.current) setQueueExpanded(false);
    prevQueueLen.current = messageQueue.length;
  }, [messageQueue.length]);

  // Server-state via TanStack Query v5 (staleTime 60s, refetchOnWindowFocus=true).
  const { data: sessions = [] } = useSessionsQuery(activeEmail);
  const {
    data: messagesData = [],
    isFetching: messagesFetching,
    isFetched: messagesFetched,
  } = useMessagesQuery(sessionId);
  const sendMutation = useSendChatMutation();
  const deleteMutation = useDeleteSessionMutation();
  const qc = useQueryClient();
  const loadingMsg = sendMutation.isPending;

  // Fase 1 / CallSphere 200ms rule: indikator berstage.
  //   <5s  -> dot + "Agen sedang berpikir..."
  //   >=5s -> dot + "Sedang memproses..."
  //   >=10s-> dot + fallback "Server sibuk, coba lagi sebentar."
  const [slowHint, setSlowHint] = useState(false);
  const [longHint, setLongHint] = useState(false);
  useEffect(() => {
    if (!loadingMsg) {
      setSlowHint(false);
      setLongHint(false);
      return;
    }
    const t1 = setTimeout(() => setSlowHint(true), 5000);
    const t2 = setTimeout(() => setLongHint(true), 10000);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [loadingMsg]);

// Setelah sesi benar-benar aktif (sessionId ter-set pasca-echo), bersihkan
  // sisa optimistic di "__pending__" (anti stray saat pindah ke sesi lain).
  // Tidak ber-race dengan setSessionId (nuqs async) karena hanya jalan setalah
  // sessionId commit.
  const prevPendingSid = useRef<string | null>(null);
  useEffect(() => {
    if (sessionId && prevPendingSid.current !== sessionId) {
      qc.setQueryData<ChatMessage[]>(chatKeys.messages("__pending__"), []);
    }
    prevPendingSid.current = sessionId;
  }, [sessionId, qc]);
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
  const overlay: ChatMessage[] = (() => {
    // Hanya optimistic (punya _localId); dedup per _localId ACROSS pendingCache
    // dan cached => saat frame switch (sessionId baru), optimistic yang sudah
    // disalin ke messages(sid) tetapi masih ada di "__pending__" TIDAK ganda.
    const seen = new Set<string>();
    return [...pendingCache, ...cached].filter((m) => {
      if (!m._localId) return false;
      if (seen.has(m._localId)) return false;
      seen.add(m._localId);
      return true;
    });
  })();
  const serverConfirmedCount = new Map<string, number>();
  for (const m of messagesData) {
    if (m.role === "user" || m.role === "assistant") {
      const k = `${m.role}|${m.content}`;
      serverConfirmedCount.set(k, (serverConfirmedCount.get(k) ?? 0) + 1);
    }
  }
  // FIX Tugas1: dedup BERDASAR HITUNGAN occurrence, bukan Set.
  // Pakai Set(role|content) -> dua pesan user yang IDENTIK ("halo","halo")
  // dianggap sudah terkonfirmasi dan yang kedua DIBUANG (pesan hilang).
  // Dengan counter, tiap optimistic yang tampil di server mengkonsumsi 1
  // slot; optimistic LEBIH dari jumlah di server tetap dirender (unconfirmed).
  const unconfirmed = overlay.filter((m) => {
    if (m.type === "credential_form") return true;
    if (m.role !== "user" && m.role !== "assistant") return true;
    const k = `${m.role}|${m.content}`;
    const n = serverConfirmedCount.get(k) ?? 0;
    if (n > 0) {
      serverConfirmedCount.set(k, n - 1);
      return false; // sudah dikonfirmasi di server → jangan render duplikat
    }
    return true; // masih lebih banyak di optimistic → pertahankan
  });

  const messagesRaw: Msg[] = [
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
// Guard anti-blank-flash (lapisan render): tahan konten non-kosong terakhir
  // selama sesi aktif bila data sempat kosong 1-2 frame (efek placeholderData).
  // Saat newChat (sessionId null) guard nonaktif -> empty-state normal.
  const lastNonEmpty: { current: Msg[] } = useRef<Msg[]>([]);
  const messages: Msg[] =
    messagesRaw.length > 0
      ? messagesRaw
      : sessionId && lastNonEmpty.current.length > 0
        ? lastNonEmpty.current
        : messagesRaw;
  if (messagesRaw.length > 0) lastNonEmpty.current = messagesRaw;

  // Sentinel: hanya auto-scroll saat user sudah di bawah (anti scroll-fighting).
  // Scroll area diberi ref scrollRef; endRef sebagai sentinel target.
  const programmaticRef = useRef(false);

  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (programmaticRef.current) {
      setAtBottom(true);
      return;
    }
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
    // Hysteresis: masuk-bawah <100px, keluar-(scroll atas) >150px (anti flicker tombol).
    setAtBottom((prev) => (prev ? dist < 150 : dist < 100));
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => el.removeEventListener("scroll", onScroll);
  }, [onScroll]);

  // Auto-scroll via requestAnimationFrame (chroxy #2636): hindari race antara
  // React commit & browser paint; guard programmaticRef mencegah onScroll
  // salah deteksi "user scroll naik" saat auto-scroll berlangsung.
  useEffect(() => {
    if (!atBottom) return;
    programmaticRef.current = true;
    const raf = requestAnimationFrame(() => {
      endRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
      programmaticRef.current = false;
    });
    return () => {
      cancelAnimationFrame(raf);
      programmaticRef.current = false;
    };
  }, [messages.length, loadingMsg, atBottom]);

  // SISA echo-pattern lama DIHAPUS (fix #1 revisi): tidak ada lagi
  // sessionEchoRef / prevSessionIdRef / setLocalMsgs. Overlay hidup di
  // cache TanStack (onMutate) dan TIDAK PERNAH di-clear oleh pergantian
  // sessionId — refetch server hanya me-merge, bukan overwrite.

  const currentSessionId = sessionId || null;

  function openSession(id: string) {
    void setSessionId(id);
  }

  function newChat() {
    setMessageQueue([]);
    setEditingId(null);
    setConfirmNewChat(false);
    qc.setQueryData<ChatMessage[]>(chatKeys.messages("__pending__"), []);
    void setSessionId(null);
    setInput("");
  }

  // Fix 6: Chat Baru saat AI bekerja -> konfirmasi; default pindah langsung.
  function handleNewChat() {
    if (loadingMsg || messageQueue.length > 0) {
      setConfirmNewChat(true);
      return;
    }
    newChat();
  }

  // Fix 2 Stop morph (openhuman #4103): AI generating + composer kosong
  // -> tombol Stop; sekali user mengetik, kembali jadi Send agar follow-up
  // bisa diantre. cancelRef = penanda ada request berjalan milik sesi ini.
  const showStop = loadingMsg && cancelRef.current !== null && !input.trim();

  // Fix 3 FIFO: saat tidak ada mutasi in-flight & ada antrean -> kirim berikutnya.
  // Guard `busyRef.current` (sinkron): loadingMsg (state) + sendMutation.isPending
  // bisa basi dalam 1 tick; tanpa ini, 3 submit cepat -> 3 mutateAsync paralel
  // yang triple-append pasangan optimistic ke key yang sama (Fix A/B race).
  useEffect(() => {
    if (sendMutation.isPending || busyRef.current || messageQueue.length === 0) return;
    const next = messageQueue[0];
    setMessageQueue((prev) => prev.slice(1));
    void sendPrompt(next.text);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadingMsg, messageQueue, sendMutation.isPending]);

  // Fix 2 Stop: batalkan permintaan /chat berjalan + kosongkan sisa antrean.
  function onStop() {
    cancelRef.current?.abort();
    cancelRef.current = null;
    busyRef.current = false;
    setMessageQueue([]);
    setEditingId(null);
  }

  async function sendPrompt(text: string) {
    // Fix 1/3: bila AI sedang sibuk, jangan blokir — antre, bukan lock UI.
    // busyRef sinkron menutup race window 1-tick (3 submit cepat sekaligus):
    // yang pertama jalan, sisanya masuk antrean FIFO — TIDAK pernah 2
    // mutateAsync paralel ke key yang sama.
    if (busyRef.current || loadingMsg || sendMutation.isPending) {
      setMessageQueue((prev) => [...prev, { id: qid(), text }]);
      setInput("");
      return;
    }
    busyRef.current = true;
    const em = emailRef.current;
    if (!em) {
      alert("Silakan login dulu untuk mengirim pesan.");
      return;
    }
    setInput("");
    const controller = new AbortController();
    cancelRef.current = controller;
    // Idempotensi (openclaw #69266): UUID unik per kiriman logis. Backend memakai
    // ini untuk TIDAK meng-insert user-message dua kali bila request retry
    // setelah server-commit (mis. timeout saat respons hilang) — mencegah pesan
    // user duplikat dalam 1 sesi. Di-kirim via POST /chat body client_request_id.
    const clientRequestId =
      (typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`);
    // Optimistic bubble ditulis oleh onMutate (setQueryData) — TANPA useState.
    try {
      const data = await sendMutation.mutateAsync({
        prompt: text,
        sessionId,
        email: em,
        abortSignal: controller.signal,
        clientRequestId,
      });
      if (data.session_id && !sessionId) {
        // Echo sesi baru: onSuccess sudah memindahkan optimistic ke messages(sid).
        // JANGAN reset "__pending__" di sini — setSessionId (nuqs) async, reset
        // sinkron bisa commit lebih dulu => activeKey("__pending__") kosong =>
        // blank 1-2 frame. "__pending__" dibersihkan oleh effect[sessionId] &
        // newChat; overlay men-dedup agar tidak duplikat saat frame switch.
        void setSessionId(data.session_id);
      }
      // Reply + kartu kredensial datang via cache update (onSuccess) dan
      // query-invalidatie (messagesData refresh).
    } catch {
      // Error spesifik sudah dirender sebagai kartu (type=error) oleh onError
      // bersama tombol retry — TIDAK perlu alert generic di sini.
    } finally {
      if (cancelRef.current === controller) cancelRef.current = null;
      busyRef.current = false;
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

  /** Tugas3: hapus satu sesi. Bila itu sesi aktif → reset ke chat baru. */
  async function handleDeleteSession(id: string) {
    try {
      await deleteMutation.mutateAsync({ sessionId: id, email: activeEmail ?? "" });
      if (currentSessionId === id) {
        qc.setQueryData<ChatMessage[]>(chatKeys.messages("__pending__"), []);
        void setSessionId(null);
      }
    } catch {
      /* toast/silent — daftar riwayat tetap utuh; user bisa coba lagi. */
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
      onNewChat={handleNewChat}
      onDeleteSession={handleDeleteSession}
    >
      {/* Fix 6: Chat Baru saat AI bekerja -> dialog konfirmasi agar reply tetap
          diproses di sesi lama; user bisa memilih pindah atau bertahan. */}
      {confirmNewChat && (
        <div
          role="alertdialog"
          aria-modal="true"
          aria-label="Konfirmasi chat baru"
          data-testid="newchat-confirm"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={() => setConfirmNewChat(false)}
        >
          <div
            className="w-full max-w-sm rounded-md border border-border bg-surface p-5 shadow-md"
            onClick={(e) => e.stopPropagation()}
          >
            <p className="text-subhead font-semibold text-fg">AI sedang bekerja di chat ini.</p>
            <p className="mt-1.5 text-footnote text-fg-muted">
              Yakin pindah ke chat baru? Reply tetap diproses dan muncul di riwayat.
              {messageQueue.length > 0 ? ` (${messageQueue.length} pesan antrean ikut dibatalkan)` : ""}
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setConfirmNewChat(false)}>
                Tetap di sini
              </Button>
              <Button
                onClick={() => {
                  onStop();
                  newChat();
                }}
              >
                Pindah
              </Button>
            </div>
          </div>
        </div>
      )}
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
            <div className="flex flex-col gap-4 contain-layout" aria-live="polite" data-testid="msg-list">
            {messages.map((msg) => (
              <motion.div
                key={msg.key}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.18, ease: "easeOut" }}
                style={{ willChange: "opacity" }}
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
                  ) : msg.role === "assistant" && msg.content === "…" ? (
                    <span className="inline-flex py-0.5" aria-hidden="true">
                      <TypingDots ariaHidden />
                    </span>
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
                <div
                  role="status"
                  aria-live="polite"
                  className="flex min-h-[20px] items-center gap-2 text-subhead text-fg-muted animate-fade-in"
                >
                  <TypingDots />
                  <span>
                    {longHint
                      ? "Server sibuk, coba lagi sebentar."
                      : slowHint
                        ? "Sedang memproses..."
                        : "Agen sedang berpikir..."}
                  </span>
                </div>
              )}
            </div>
            <div ref={endRef} />
            {messages.length > 0 && (
              <button
                type="button"
                aria-label="Lompat ke bawah"
                aria-hidden={atBottom}
                tabIndex={atBottom ? -1 : 0}
                onClick={() =>
                  endRef.current?.scrollIntoView({ behavior: "auto", block: "end" })
                }
                className={`sticky bottom-2 mx-auto flex items-center gap-1.5 rounded-full border border-border bg-surface px-3 py-1.5 text-footnote text-fg-muted shadow-sm transition-opacity duration-200 hover:text-fg ${atBottom ? "pointer-events-none opacity-0" : "opacity-100"}`}
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
        {/* QUEUE-AREA-START — DI ATAS composer, slim status line (Opsi A,
            openclaw #104445): composer-width, compact, collapsible (Geta.Team),
            transisi opacity-only. */}
        {messageQueue.length > 0 && (
          <div className="flex-none border-t border-border/40 px-5 py-2" data-testid="queue-area">
            <div className="mx-auto max-w-[48rem]">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setQueueExpanded((v) => !v)}
                  aria-expanded={queueExpanded}
                  aria-label={queueExpanded ? "Tutup antrean" : "Buka antrean"}
                  data-testid="queue-toggle"
                  className="flex items-center gap-1.5 text-footnote text-fg-muted transition-opacity hover:text-fg"
                >
                  <Clock size={12} strokeWidth={1.75} />
                  <span>Antrean ({messageQueue.length})</span>
                  {queueExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                </button>
                {!queueExpanded && messageQueue[0] && (
                  <p className="truncate text-footnote text-fg-subtle" data-testid="queue-preview">
                    {messageQueue[0].text.slice(0, 60)}
                    {messageQueue[0].text.length > 60 ? "…" : ""}
                  </p>
                )}
                {messageQueue.length > 3 && (
                  <button
                    type="button"
                    onClick={() => {
                      setEditingId(null);
                      setMessageQueue([]);
                    }}
                    aria-label="Hapus semua antrean"
                    className="ml-auto text-footnote text-fg-muted underline underline-offset-2 transition-opacity hover:text-fg"
                  >
                    Clear all
                  </button>
                )}
              </div>
              <div id="queue-rows-anchor" />
              {queueExpanded && (
                <div className="mt-1.5 flex flex-col gap-1.5 animate-fade-in">
                  {messageQueue.map((q) => (
                    <div
                      key={q.id}
                      data-testid="queued-msg"
                      className="flex items-center gap-2 rounded-sm border border-border/60 bg-bg/60 px-2.5 py-1.5 text-footnote opacity-80"
                    >
                      <Clock size={12} strokeWidth={1.75} className="shrink-0 text-fg-muted" />
                      {editingId === q.id ? (
                        <span className="flex min-w-0 flex-1 items-center gap-1.5">
                          <input
                            value={editText}
                            onChange={(e) => setEditText(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") {
                                e.preventDefault();
                                const t = editText.trim();
                                if (t) setMessageQueue((prev) => prev.map((m) => (m.id === q.id ? { ...m, text: t } : m)));
                                setEditingId(null);
                              } else if (e.key === "Escape") {
                                setEditingId(null);
                              }
                            }}
                            aria-label="Ubah teks antrean"
                            autoFocus
                            className="h-7 min-w-0 flex-1 rounded-sm bg-bg px-2 text-footnote text-fg outline-none"
                          />
                          <button
                            type="button"
                            aria-label="Simpan edit antrean"
                            onClick={() => {
                              const t = editText.trim();
                              if (t) setMessageQueue((prev) => prev.map((m) => (m.id === q.id ? { ...m, text: t } : m)));
                              setEditingId(null);
                            }}
                            className="shrink-0 rounded-sm px-1.5 py-1 text-footnote font-medium underline underline-offset-2"
                          >
                            Simpan
                          </button>
                          <button
                            type="button"
                            aria-label="Batal edit antrean"
                            onClick={() => setEditingId(null)}
                            className="shrink-0 rounded-sm p-1 opacity-80 hover:opacity-100"
                          >
                            <X size={13} strokeWidth={2} />
                          </button>
                        </span>
                      ) : (
                        <>
                          <span className="min-w-0 flex-1 truncate text-fg">{q.text}</span>
                          <span className="shrink-0 rounded-full border border-current/30 px-1.5 py-px text-[10px] font-medium uppercase tracking-wide text-fg-muted">
                            Queued
                          </span>
                          <button
                            type="button"
                            aria-label="Edit antrean"
                            onClick={() => {
                              setEditingId(q.id);
                              setEditText(q.text);
                            }}
                            className="shrink-0 rounded-sm p-1 opacity-80 hover:opacity-100"
                          >
                            <Pencil size={13} strokeWidth={1.75} />
                          </button>
                          <button
                            type="button"
                            aria-label="Hapus antrean"
                            onClick={() => {
                              if (editingId === q.id) setEditingId(null);
                              setMessageQueue((prev) => prev.filter((m) => m.id !== q.id));
                            }}
                            className="shrink-0 rounded-sm p-1 opacity-80 hover:opacity-100"
                          >
                            <X size={13} strokeWidth={2} />
                          </button>
                        </>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
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
                onKeyDown={(e) => {
                  if (e.key === "Escape" && showStop) {
                    e.preventDefault();
                    onStop();
                  }
                }}
                placeholder={activeEmail ? "Ketik pesan ke Nexus Agent..." : "Login untuk mulai mengobrol"}
                aria-label="Pesan"
                className="h-9 border-0 shadow-none bg-transparent focus-visible:shadow-none"
              />
              <Button
                type={showStop ? "button" : "submit"}
                size="icon"
                aria-label={showStop ? "Stop" : "Kirim"}
                onClick={showStop ? onStop : undefined}
                disabled={showStop ? false : !input.trim()}
                className="shrink-0"
              >
                {showStop ? <Square size={16} strokeWidth={1.75} /> : <Send size={16} strokeWidth={1.75} />}
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