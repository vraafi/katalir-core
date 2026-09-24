"use client";

/**
 * FASE 2 — Chat primitives (pola assistant-ui: Thread / Message / Composer /
 * ActionBar / ChainOfThought). Komponen presentasional murni: ChatApp tetap
 * pemilik state & logika; file ini hanya render. Diekstrak dari page.tsx
 * (bukan ditulis ulang) supaya perilaku identik.
 */
import { AlertCircle, AlertTriangle, Bot, RotateCcw, Sparkles } from "lucide-react";
import { motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/i18n/context";
import type { ChatMessage } from "@/features/chat/hooks/useChat";
import type { AgentWorkflow } from "@/features/agent/workflow-spec";
import type { ExecutionReport } from "@/features/agent/execution-report";
import {
  ChainOfThought,
  CredentialPromptCard,
  ExecutionReportCard,
  OAuthConnectCard,
  WorkflowDraftCard,
  splitReasoning,
} from "./ai-surfaces";

export type Msg =
  | { key: string; role: "user"; content: string }
  | {
      key: string;
      role: "assistant";
      content: string;
      meta?: ChatMessage["meta"];
      /** FASE 5 (B1): draf workflow yang sudah lolos `parseAgentWorkflow`. */
      workflow?: AgentWorkflow;
    }
  | {
      key: string;
      role: "system";
      type: "credential_form";
      provider: string;
      original: string;
    }
  | {
      /* Task 1C: provider ber-OAuth — bukan form token, tapi tombol Connect. */
      key: string;
      role: "system";
      type: "oauth_prompt";
      provider: string;
      /** Dari backend (`connect_url`); dipakai agar FE tidak menebak endpoint. */
      connectUrl?: string;
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
  onOauthConnect,
  oauthBusy = false,
  onRetry,
  draftRunning = false,
  onOpenCanvas,
  onRunDraft,
}: {
  msg: Msg;
  credValue: string;
  onCredChange: (v: string) => void;
  onCredSubmit: (provider: string, original: string) => void;
  /** Task 1C: tombol Connect pada provider ber-OAuth (handler dari ChatApp). */
  onOauthConnect: (provider: string, connectUrl?: string) => void;
  oauthBusy?: boolean;
  onRetry: (m: { content: string; original: string }) => void;
  /** FASE 5: draf sedang dijalankan (tombol "Jalankan Langsung" disabled). */
  draftRunning?: boolean;
  onOpenCanvas: (wf: AgentWorkflow) => void;
  onRunDraft: (wf: AgentWorkflow) => void;
}) {
  const { t } = useI18n();
  // B4: hitung sekali per pesan. Pesan non-assistant diabaikan isinya.
  const { reason, answer } = msg.role === "assistant" ? splitReasoning(msg.content) : { reason: "", answer: "" };
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
          <CredentialPromptCard
            provider={msg.provider}
            value={credValue}
            onChange={onCredChange}
            onSubmit={(p) => onCredSubmit(p, msg.original)}
          />
        ) : msg.role === "system" && msg.type === "oauth_prompt" ? (
          <OAuthConnectCard
            provider={msg.provider}
            busy={oauthBusy}
            onConnect={(p) => onOauthConnect(p, msg.connectUrl)}
          />
        ) : msg.role === "system" && msg.type === "error" ? (
          <div className="w-72" data-testid="error-card">
            <div className="flex items-center gap-2 text-danger">
              <AlertTriangle size={15} strokeWidth={1.75} aria-hidden />
              <span className="font-semibold text-fg">{t("chat.errorTitle")}</span>
            </div>
            <p className="mt-1.5 text-footnote text-fg-muted">{msg.content}</p>
            <Button
              variant="secondary"
              onClick={() => onRetry({ content: msg.content, original: msg.original })}
              className="mt-2.5 w-full justify-center gap-1.5"
            >
              <RotateCcw size={14} strokeWidth={1.75} aria-hidden />
              {t("chat.retry")}
            </Button>
          </div>
        ) : msg.role === "assistant" && msg.content === "…" ? (
          <span className="inline-flex py-0.5" aria-hidden="true">
            <TypingDots ariaHidden />
          </span>
        ) : (
          <>
            {/* FASE 5 (B4): blok penalaran dipisah dari jawaban. Bila model tidak
                mengirim penalaran, `reason` kosong dan ChainOfThought tidak
                merender apa pun — tidak ada "berpikir..." palsu. */}
            {msg.role === "assistant" && reason && <ChainOfThought reason={reason} />}
            <div className="whitespace-pre-wrap break-words">{msg.role === "assistant" ? answer : msg.content}</div>
            {/* FASE 5 (B1): draf workflow + aksinya, DI DALAM pesan. */}
            {msg.role === "assistant" && msg.workflow && (
              <WorkflowDraftCard
                wf={msg.workflow}
                running={draftRunning}
                onOpenCanvas={() => onOpenCanvas(msg.workflow as AgentWorkflow)}
                onRun={() => onRunDraft(msg.workflow as AgentWorkflow)}
              />
            )}
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
  draftRunning = false,
  onOpenCanvas,
  onRunDraft,
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
    /** Task 1C: handler tombol Connect (diisi ChatApp; default = no-op). */
    onOauthConnect?: (p: string, connectUrl?: string) => void;
    oauthBusy?: boolean;
    onRetry: (m: { content: string; original: string }) => void;
  };
  /** FASE 5 (B2): laporan eksekusi TERSTRUKTUR dari state lokal. */
  runReports?: { id: string; report: ExecutionReport }[];
  draftRunning?: boolean;
  onOpenCanvas?: (wf: AgentWorkflow | null) => void;
  onRunDraft?: (wf: AgentWorkflow | null) => void;
  animTail?: number;
}) {
  const { t } = useI18n();
  const openCanvas = onOpenCanvas ?? (() => {});
  const runDraft = onRunDraft ?? (() => {});
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
            onOauthConnect={handlers.onOauthConnect ?? (() => {})}
            oauthBusy={handlers.oauthBusy ?? false}
            onRetry={handlers.onRetry}
            draftRunning={draftRunning}
            onOpenCanvas={openCanvas}
            onRunDraft={runDraft}
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
      {/* FASE 2.5/5: laporan eksekusi dirender dari STATE LOKAL (bukan cache
          pesan server — refetch menimpa cache sehingga laporan hilang sebelum
          terbaca). Sejak FASE 5 bentuknya kartu TERSTRUKTUR, tetapi testid
          `run-report` dipertahankan karena E2E L3 S1 memakainya. */}
      {runReports.map((r) => (
        <div key={r.id} data-testid="run-report" className="flex items-end gap-2">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-bg-subtle">
            <Sparkles size={14} strokeWidth={1.75} className="text-accent" aria-hidden />
          </div>
          <ExecutionReportCard
            report={r.report}
            running={Boolean(draftRunning)}
            onOpenCanvas={() => openCanvas(r.report.workflowRef ?? null)}
            onRunAgain={() => runDraft(r.report.workflowRef ?? null)}
          />
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
