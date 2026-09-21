"use client";

/**
 * FASE 2 — Chat primitives (pola assistant-ui: Thread / Message / Composer /
 * ActionBar / ChainOfThought). Komponen presentasional murni: ChatApp tetap
 * pemilik state & logika; file ini hanya render. Diekstrak dari page.tsx
 * (bukan ditulis ulang) supaya perilaku identik.
 */
import { Bot, KeyRound, AlertTriangle, RotateCcw, AlertCircle, Sparkles } from "lucide-react";
import { motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ChatMessage } from "@/features/chat/hooks/useChat";

export type Msg =
  | { key: string; role: "user"; content: string }
  | { key: string; role: "assistant"; content: string; meta?: ChatMessage["meta"] }
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

/** Indikator mengetik: 3 dot animasi (transform+opacity only, CSS .typing-dot).
 * CallSphere 200ms rule — bukan spinner statis. Reduced-motion di-global CSS. */
export function TypingDots({ ariaHidden }: { ariaHidden?: boolean }) {
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

/** Terjemahan kode `fallback_reason` backend -> bahasa manusia. */
export function formatFallbackReason(reason: string | null | undefined): string {
  switch (reason) {
    case "quota_exhausted":
      return "Kuota harian model ini habis";
    case "rate_limit":
      return "Terlalu banyak permintaan ke model ini";
    case "overloaded":
      return "Server model ini sedang sibuk";
    case "model_unavailable":
      return "Model tidak tersedia untuk tier Anda";
    case "gateway_down":
      return "Layanan gateway sedang tidak tersedia";
    default:
      return "Model yang dipilih tidak tersedia";
  }
}

/** Keterangan fallback: model DIMINTA vs DIPAKAI + alasan. */
export function FallbackNotice({ meta }: { meta: NonNullable<ChatMessage["meta"]> }) {
  const used = meta.model;
  const wanted = meta.requested_model;
  if (!used || !wanted || wanted === used) return null;
  return (
    <span className="mt-2 flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 px-2.5 py-1.5 text-[11px] leading-snug text-warning">
      <AlertCircle size={12} strokeWidth={2} className="mt-0.5 shrink-0" aria-hidden />
      <span className="flex-1">
        <span className="block font-medium">Model yang Anda pilih tidak tersedia</span>
        <span className="block text-warning/90">
          {formatFallbackReason(meta.fallback_reason)} · Beralih ke{" "}
          <strong className="font-mono font-medium">{used}</strong>
        </span>
        <span className="mt-0.5 block font-mono text-[10px] text-warning/70">
          diminta: {wanted}
        </span>
      </span>
    </span>
  );
}

/** Baris metadata model di bubble AI (transparansi model/token/latensi). */
export function MetaRow({ meta }: { meta: NonNullable<ChatMessage["meta"]> }) {
  const model = meta.model || "model";
  const secs =
    typeof meta.latency_ms === "number" ? (meta.latency_ms / 1000).toFixed(1) : null;
  const hasUsage = meta.total_tokens != null;
  const inT = fmtToken(meta.prompt_tokens);
  const outT = fmtToken(meta.completion_tokens);
  const parts = [model];
  if (secs) parts.push(`${secs}s`);
  if (hasUsage) parts.push(`${inT}→${outT} tok`);
  return (
    <span className="mt-1.5 flex flex-col">
      <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] leading-none text-fg-subtle">
        <span className="font-mono tracking-tight">{parts.join(" · ")}</span>
      </span>
      {meta.fallback && <FallbackNotice meta={meta} />}
    </span>
  );
}

/** Format token count: 10502 -> "10.5K", 1500000 -> "1.5M". */
export function fmtToken(n: number | undefined | null): string {
  const v = Number(n ?? 0);
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 10_000) return `${(v / 1000).toFixed(1)}K`;
  return String(Math.round(v || 0));
}

/** Satu bubble pesan (avatar + konten). Dipakai Thread untuk tiap row. */
export function Message({
  msg,
  credValue,
  onCredChange,
  onCredSubmit,
  onRetry,
}: {
  msg: Msg;
  credValue: string;
  onCredChange: (v: string) => void;
  onCredSubmit: (provider: string, original: string) => void;
  onRetry: (m: { content: string; original: string }) => void;
}) {
  return (
    <>
      {msg.role !== "user" && (
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-bg-subtle">
          <Bot size={14} strokeWidth={1.5} className="text-fg-muted" />
        </div>
      )}
      <div
        className={
          msg.role === "user"
            ? "max-w-[75%] rounded-2xl rounded-br-lg bg-accent px-4 py-2.5 text-[14px] leading-[1.55] text-accent-fg shadow-sm tracking-[-0.006em]"
            : "max-w-[85%] rounded-2xl rounded-bl-lg bg-surface px-4 py-2.5 text-[15px] leading-[1.68] text-fg shadow-xs tracking-[-0.006em]"
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
              onChange={(e) => onCredChange(e.target.value)}
              type="password"
              placeholder="Token / API key..."
              aria-label="Token / API key"
            />
            <Button
              disabled={!credValue.trim()}
              onClick={() => onCredSubmit(msg.provider, msg.original)}
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
              onClick={() => onRetry({ content: msg.content, original: msg.original })}
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
          <>
            <div className="whitespace-pre-wrap break-words">{msg.content}</div>
            {msg.role === "assistant" && msg.meta && (
              <MetaRow meta={msg.meta} />
            )}
          </>
        )}
      </div>
    </>
  );
}

/** Daftar pesan + status mengetik (pola assistant-ui Thread). */
export function Thread({
  messages,
  loadingMsg,
  longHint,
  slowHint,
  handlers,
  runReports = [],
  animTail = 8,
}: {
  messages: Msg[];
  loadingMsg: boolean;
  longHint: boolean;
  slowHint: boolean;
  handlers: {
    credValue: string;
    onCredChange: (v: string) => void;
    onCredSubmit: (p: string, o: string) => void;
    onRetry: (m: { content: string; original: string }) => void;
  };
  /** FASE 2.5: laporan eksekusi otomatis dirender dari STATE LOKAL. */
  runReports?: { id: string; text: string }[];
  animTail?: number;
}) {
  return (
    <>
      {messages.map((msg, i) => {
        // Perf: animasi hanya di row terakhir. Row lama = plain <div>.
        const animate = i + animTail >= messages.length;
        const rowCls = `flex items-end gap-2 ${msg.role === "user" ? "justify-end" : ""}`;
        const body = (
          <Message
            msg={msg}
            credValue={handlers.credValue}
            onCredChange={handlers.onCredChange}
            onCredSubmit={handlers.onCredSubmit}
            onRetry={handlers.onRetry}
          />
        );
        if (!animate) {
          return (
            <div key={msg.key} className={rowCls}>
              {body}
            </div>
          );
        }
        return (
          <motion.div
            key={msg.key}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            style={{ willChange: "opacity" }}
            className={rowCls}
          >
            {body}
          </motion.div>
        );
      })}
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
      {/* FASE 2.5: laporan eksekusi otomatis dirender dari STATE LOKAL,
          bukan dari cache pesan server. Refetch daftar pesan menimpa cache
          sehingga pesan sistem laporan hilang sebelum terbaca user. */}
      {runReports.map((r) => (
        <div
          key={r.id}
          data-testid="run-report"
          className="flex items-end gap-2"
        >
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-bg-subtle">
            <Sparkles size={14} strokeWidth={1.75} className="text-accent" />
          </div>
          <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-bl-lg border border-border/60 bg-bg-subtle px-4 py-2.5 text-[14px] leading-[1.6] text-fg tracking-[-0.006em]">
            {r.text}
          </div>
        </div>
      ))}
    </>
  );
}

const PROVIDER_LABELS: Record<string, string> = {
  whatsapp: "WhatsApp Cloud API",
  google_sheets: "Google Sheets",
  gmail: "Gmail",
  google_calendar: "Google Calendar",
};
