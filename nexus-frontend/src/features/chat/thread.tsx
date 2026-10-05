"use client";

/**
 * FASE 2 — Chat primitives (pola assistant-ui: Thread / Message / Composer /
 * ActionBar / ChainOfThought). Komponen presentasional murni: ChatApp tetap
 * pemilik state & logika; file ini hanya render. Diekstrak dari page.tsx
 * (bukan ditulis ulang) supaya perilaku identik.
 */
import { AlertCircle, AlertTriangle, Bot, Check, RotateCcw, Sparkles } from "lucide-react";
import { motion } from "motion/react";
import { ApprovalCard } from "@/components/ApprovalCard";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/i18n/context";
import type { ChatMessage } from "@/features/chat/hooks/useChat";
import type { AgentWorkflow } from "@/features/agent/workflow-spec";
import type { ExecutionReport } from "@/features/agent/execution-report";
import {
  ChainOfThought,
  CredentialForm,
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
      /* Form inline (2026-10-03): deskripsi field + token dari backend.
       * Bila `fields`/`resumeToken` ada, renderer memakai <CredentialForm />;
       * kalau tidak, jatuh ke kartu token lama (backward compatible). */
      displayName?: string;
      icon?: string;
      fields?: Array<{
        secret?: boolean;
        name: string;
        label: string;
        type?: string;
        placeholder?: string;
        required?: boolean;
        min_length?: number;
        transform?: string;
        help_url?: string;
        help_text?: string;
      }>;
      resumeToken?: string;
    }
  | {
      /* Persetujuan tool (2026-10-05): TELEGRAM/SLACK, atau tool
       * yang intent-nya tidak terlihat di pesan user. */
      key: string;
      role: "system";
      type: "approval_prompt";
      tool?: string;
      toolArgs?: Record<string, unknown>;
      reason?: string;
      alignment?: string;
      approvalToken?: string;
      original: string;
    }
  | {
      /* HASIL tool setelah keputusan (2026-10-05). Output /chat/approve
       * sebelumnya DIBUANG di ApprovalCard: user menyetujui, tool berjalan,
       * dan output-nya tidak pernah tampil. Kartu ini menampilkannya. */
      key: string;
      role: "system";
      type: "tool_result";
      tool?: string;
      content: string;
      status: "executed" | "denied";
    }
  | {
      /* Task 1C: provider ber-OAuth — bukan form token, tapi tombol Connect. */
      key: string;
      role: "system";
      type: "oauth_prompt";
      provider: string;
      /** Dari backend (`connect_url`); dipakai agar FE tidak menebak endpoint. */
      connectUrl?: string;
      /**
       * Token resume dari backend. Dibawa ke URL OAuth supaya setelah
       * consent user mendarat kembali ke percakapan ini (Bagian 3.2c).
       */
      resumeToken?: string;
    }
  | {
      key: string;
      role: "system";
      type: "error";
      content: string;
      original: string;
      /** BUG FIX 2026-10-01: `_localId` + kunci idempotensi ikut dibawa agar
       *  `onRetry` bisa men-target kartu error ini secara presisi dan memakai
       *  ulang `clientRequestId` (retry = kiriman logis yang sama). */
      localId?: string;
      clientRequestId?: string;
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

/** Terjemahan kode `fallback_reason` backend -> bahasa manusia.
 *
 *  BUG FIX 2026-10-03 (tuduhan tier salah).
 *
 *  Versi lama memetakan `model_unavailable` -> "Model tidak tersedia untuk tier
 *  Anda". Itu tuduhan yang TIDAK BENAR: `model_unavailable` di backend adalah
 *  kode generik "model ini tidak bisa dipakai sekarang", dan pemanggilnya
 *  mencakup upstream 404/410, alias mati, dan gateway yang tidak terjangkau.
 *  Bukti bahwa kode ini sendiri tahu masalahnya — lihat komentar di
 *  `api_server._fallback_reason`: "frontend menuduh 'tidak tersedia untuk tier
 *  Anda' padahal 500".
 *
 *  Akibatnya user free yang memilih model gratis (mis. Gemma 4) tetap diberi
 *  tahu "tidak tersedia untuk tier Anda" saat modelnya sedang hiccup — padahal
 *  model itu gratis dan tier-nya sudah benar. Membership memang disampaikan
 *  di tempat yang tepat: `ModelSelector` mengunci model plus dengan badge
 *  "locked" + tombol Upgrade. Pesan fallback tidak boleh mengulangi tuduhan itu.
 */
export function formatFallbackReason(reason: string | null | undefined): string {
  switch (reason) {
    case "quota_exhausted":
      return "Kuota harian model ini habis";
    case "rate_limit":
      return "Terlalu banyak permintaan ke model ini";
    case "overloaded":
      return "Server model ini sedang sibuk";
    case "model_unavailable":
      // Netral: jangan menyebut tier. Model free yang bermasalah akan memberi
      // pesan yang sama persis, dan itu jujur — bukan tanda langganan kurang.
      return "Model ini sedang tidak bisa dipakai. Silakan coba lagi sebentar atau pilih model lain.";
    case "gateway_down":
      return "Layanan gateway sedang tidak tersedia";
    default:
      return "Model yang dipilih sedang tidak tersedia";
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
  onResume,
  onCredChange,
  onCredSubmit,
  onOauthConnect,
  oauthBusy = false,
  onRetry,
  onApprovalDecision,
  draftRunning = false,
  onOpenCanvas,
  onRunDraft,
}: {
  msg: Msg;
  credValue: string;
  /** Dipanggil setelah form inline credential tersimpan: frontend mengirim
   *  ulang prompt asli agar tool langsung jalan (tanpa navigasi ke halaman lain). */
  onResume: (originalPrompt: string) => void;
  onCredChange: (v: string) => void;
  onCredSubmit: (provider: string, original: string) => void;
  /** Task 1C: tombol Connect pada provider ber-OAuth (handler dari ChatApp). */
  onOauthConnect: (provider: string, connectUrl?: string, resume?: string) => void;
  oauthBusy?: boolean;
  onRetry: (m: { content: string; original: string; localId?: string; clientRequestId?: string }) => void;
  /** FIX 2026-10-05: keputusan persetujuan + hasil /chat/approve. Diteruskan
   *  ke ChatApp yang menaruh kartu tool_result di cache percakapan. */
  onApprovalDecision: (
    m: Extract<Msg, { type: "approval_prompt" }>,
    info: { approved: boolean; result?: unknown },
  ) => void;
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
          msg.fields && msg.fields.length > 0 && msg.resumeToken ? (
            // Form INLINE (2026-10-03): deskripsi field datang dari backend,
            // jadi frontend tidak perlu tahu detail per provider. Submit ->
            // POST /chat/resume -> lalu onResume.send ulang prompt asli,
            // sehingga tool langsung jalan tanpa user membuka halaman lain.
            <CredentialForm
              provider={msg.provider}
              displayName={msg.displayName}
              icon={msg.icon}
              fields={msg.fields}
              resumeToken={msg.resumeToken}
              onSuccess={() => onResume(msg.original)}
            />
          ) : (
            // Fallback: server tidak mengirim definisi field -> kartu token lama.
            <CredentialPromptCard
              provider={msg.provider}
              value={credValue}
              onChange={onCredChange}
              onSubmit={(p) => onCredSubmit(p, msg.original)}
            />
          )
        ) : msg.role === "system" && msg.type === "approval_prompt" ? (
          // Tanpa approvalToken server tidak bisa memverifikasi, jadi
          // tampilkan catatan jelas - bukan diam saja.
          msg.approvalToken ? (
            <ApprovalCard
              tool={msg.tool ?? "tool"}
              args={msg.toolArgs}
              reason={msg.reason}
              alignment={msg.alignment}
              approvalToken={msg.approvalToken}
              onDecision={(info) => onApprovalDecision(msg, info)}
            />
          ) : (
            <div className="w-80" data-testid="approval-expired">
              <p className="text-footnote text-fg-muted">
                Persetujuan tidak tersedia. Silakan kirim ulang permintaan.
              </p>
            </div>
          )
        ) : msg.role === "system" && msg.type === "tool_result" ? (
          // FIX 2026-10-05: output /chat/approve sebelumnya dibuang di
          // ApprovalCard. Kartu ini menampilkan HASILNYA apa adanya - keputusan
          // tanpa output tidak bermakna karena user tidak tahu apa yang
          // benar-benar terjadi.
          <div className="w-80" data-testid="tool-result-card" data-tool-status={msg.status}>
            <div className="flex items-center gap-2 text-sm font-medium text-fg">
              <Check size={15} strokeWidth={2} aria-hidden className="text-success" />
              <span>{msg.tool ?? "Tool"} selesai dijalankan.</span>
            </div>
            {msg.content ? (
              <pre
                data-testid="tool-result-output"
                className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded border border-border bg-surface-muted p-2 font-mono text-[11px] leading-relaxed text-fg-muted"
              >
                {msg.content}
              </pre>
            ) : null}
          </div>
        ) : msg.role === "system" && msg.type === "oauth_prompt" ? (
          <OAuthConnectCard
            provider={msg.provider}
            busy={oauthBusy}
            onConnect={(p) => onOauthConnect(p, msg.connectUrl, msg.resumeToken)}
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
              onClick={() => onRetry({
          content: msg.content,
          original: msg.original,
          // BUG FIX 2026-10-01: teruskan `localId` + `clientRequestId` supaya
          // retry men-target kartu error ini saja dan memakai UUID yang sama.
          localId: msg.localId,
          clientRequestId: msg.clientRequestId,
        })}
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
    /** Dikirim ulang prompt asli setelah form inline credential tersimpan. */
    onResume: (originalPrompt: string) => void;
    onCredChange: (v: string) => void;
    onCredSubmit: (p: string, o: string) => void;
    /** Task 1C: handler tombol Connect (diisi ChatApp; default = no-op). */
    onOauthConnect?: (p: string, connectUrl?: string, resume?: string) => void;
    oauthBusy?: boolean;
    onRetry: (m: { content: string; original: string; localId?: string; clientRequestId?: string }) => void;
    /** FIX 2026-10-05: keputusan persetujuan + hasil eksekusi (lihat Message). */
    onApprovalDecision: (
      m: Extract<Msg, { type: "approval_prompt" }>,
      info: { approved: boolean; result?: unknown },
    ) => void;
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
            onResume={handlers.onResume}
            onCredChange={handlers.onCredChange}
            onCredSubmit={handlers.onCredSubmit}
            onOauthConnect={handlers.onOauthConnect ?? (() => {})}
            oauthBusy={handlers.oauthBusy ?? false}
            onRetry={handlers.onRetry}
            onApprovalDecision={handlers.onApprovalDecision}
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
