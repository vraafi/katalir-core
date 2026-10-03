"use client";

/**
 * ai-surfaces.tsx — FASE 5: permukaan AI-native di dalam chat.
 *
 * PRINSIP: setiap permukaan adalah BAGIAN DARI PESAN (inline bubble), bukan
 * modal/widget mengambang — pengguna tidak perlu mencari, dan tidak ada state
 * tersembunyi di luar percakapan.
 *
 * Yang sengaja TIDAK dilakukan: mengarang isi. `ChainOfThought` hanya muncul
 * bila model benar-benar mengirim blok penalaran (lihat `splitReasoning`); kalau
 * tidak ada, tidak ada yang ditampilkan. Menampilkan "berpikir..." palsu akan
 * membuat user mempercayai proses yang tidak terjadi.
 */
import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  KeyRound,
  Link2,
  Loader2,
  Play,
  Workflow as WorkflowIcon,
  XCircle,
} from "lucide-react";
import { motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/i18n/context";
import type { AgentWorkflow } from "@/features/agent/workflow-spec";
import type { ExecutionReport } from "@/features/agent/execution-report";

// Form credential inline di bubble chat (2026-10-03). Dipisah ke
// components/CredentialForm.tsx karena dipakai juga di /settings, tapi
// diekspor dari sini agar thread.tsx cukup satu import dari barrel.
export { CredentialForm } from "@/components/CredentialForm";
export type { CredentialField, CredentialFormProps } from "@/components/CredentialForm";

/**
 * Pisahkan blok penalaran dari jawaban final.
 *
 * Backend tidak memaksa format apa pun, jadi ketiga bentuk yang umum dipakai
 * model didukung: `<thinking>…</thinking>`, `<reasoning>…</reasoning>`, dan
 * pagar kode ```think. Bila tidak ada, `reason` = "" dan jawaban dibiarkan utuh
 * (tidak ada teks yang hilang hanya karena parser agresif).
 */
export function splitReasoning(content: string): { reason: string; answer: string } {
  const patterns = [
    /<think(?:ing)?>([\s\S]*?)<\/think(?:ing)?>/i,
    /<reasoning>([\s\S]*?)<\/reasoning>/i,
    /```think\s*([\s\S]*?)```/i,
  ];
  for (const re of patterns) {
    const m = re.exec(content);
    if (m) {
      return {
        reason: m[1].trim(),
        answer: content.replace(m[0], "").trim(),
      };
    }
  }
  return { reason: "", answer: content };
}

/** Layar kecil => penalaran dibuka (di mobile ruang sempit, sekali buka lebih murah). */
function useDefaultOpenOnMobile(): boolean {
  const [mobile, setMobile] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const apply = () => setMobile(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);
  return mobile;
}

/** Penalaran AI yang bisa dibuka/tutup. Default: tertutup di desktop (fokus
 *  jawaban), terbuka di mobile. Tombol selalu ada supaya bisa dibalik. */
export function ChainOfThought({ reason }: { reason: string }) {
  const { t } = useI18n();
  const defaultOpen = useDefaultOpenOnMobile();
  const [open, setOpen] = useState(false);
  const [touched, setTouched] = useState(false);
  // User yang sudah memilih TIDAK boleh dilawan oleh perubahan ukuran layar.
  const shown = touched ? open : defaultOpen;

  if (!reason) return null;
  return (
    <div data-testid="chain-of-thought" className="mb-2 overflow-hidden rounded-lg border border-border/60 bg-bg-subtle/60">
      <button
        type="button"
        onClick={() => {
          setTouched(true);
          setOpen(!shown);
        }}
        aria-expanded={shown}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] font-medium text-fg-muted transition-colors hover:text-fg focus-visible:shadow-focus"
      >
        <ChevronDown
          size={13}
          strokeWidth={2}
          aria-hidden
          className={`shrink-0 transition-transform duration-200 ${shown ? "" : "-rotate-90"}`}
        />
        <span>{shown ? t("chat.reasoningHide") : t("chat.reasoningShow")}</span>
      </button>
      {shown && (
        <motion.div
          data-testid="chain-of-thought-body"
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          transition={{ duration: 0.2, ease: "easeOut" }}
          className="border-t border-border/50 px-3 py-2"
        >
          <p className="whitespace-pre-wrap break-words text-[12.5px] leading-[1.6] text-fg-muted">
            {reason}
          </p>
        </motion.div>
      )}
    </div>
  );
}

/** B1 — draf workflow dari AI, dengan aksi langsung di dalam pesan.
 *
 * KENAPA DUA TOMBOL DAN BUKAN OTOMATIS SAJA: user awam tidak boleh "dibawa" ke
 * halaman lain tanpa pilihan, tetapi juga tidak boleh dipaksa mencari tombol di
 * halaman lain. Jadi aksinya di sini, sedangkan "Buka di Kanvas" hanya berpindah
 * halaman (draf sudah disimpan di localStorage oleh pemanggil).
 */
export function WorkflowDraftCard({
  wf,
  running,
  onOpenCanvas,
  onRun,
}: {
  wf: AgentWorkflow;
  running: boolean;
  onOpenCanvas: () => void;
  onRun: () => void;
}) {
  const { t } = useI18n();
  const counts = {
    trigger: wf.nodes.filter((n) => n.data.kind === "trigger").length,
    agent: wf.nodes.filter((n) => n.data.kind === "agent").length,
    mcp: wf.nodes.filter((n) => n.data.kind === "mcp").length,
  };
  return (
    <div
      data-testid="workflow-draft-card"
      data-nodes={wf.nodes.length}
      data-edges={wf.edges.length}
      className="mt-2 rounded-xl border border-accent/30 bg-accent/5 p-3"
    >
      <div className="flex items-start gap-2">
        <WorkflowIcon size={15} strokeWidth={1.9} className="mt-0.5 shrink-0 text-accent" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-[12.5px] font-semibold text-fg">{t("chat.draftTitle")}</p>
          <p className="truncate text-[12px] text-fg-muted" data-testid="draft-name">
            {wf.name}
          </p>
          <p className="mt-1 font-mono text-[11px] text-fg-muted/90" data-testid="draft-counts">
            {t("chat.draftCounts", {
              nodes: wf.nodes.length,
              edges: wf.edges.length,
              trigger: counts.trigger,
              agent: counts.agent,
              mcp: counts.mcp,
            })}
          </p>
        </div>
      </div>
      <div className="mt-2.5 flex flex-wrap gap-2">
        <Button type="button" variant="secondary" size="sm" onClick={onOpenCanvas} data-testid="draft-open-canvas">
          {t("chat.draftOpen")}
        </Button>
        <Button
          type="button"
          variant="primary"
          size="sm"
          onClick={onRun}
          disabled={running}
          data-testid="draft-run-now"
        >
          {running ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <Play size={14} aria-hidden />}
          {running ? t("chat.draftRunning") : t("chat.draftRun")}
        </Button>
      </div>
    </div>
  );
}

const STATUS_STYLE = {
  success: { icon: CheckCircle2, cls: "text-success", key: "chat.reportSuccess" },
  partial: { icon: AlertTriangle, cls: "text-warning", key: "chat.reportPartial" },
  error: { icon: XCircle, cls: "text-danger", key: "chat.reportError" },
} as const;

const STEP_STYLE = {
  success: "text-success",
  error: "text-danger",
  running: "text-accent",
  pending: "text-fg-muted",
  // Percobaan ulang: bukan gagal dan belum tentu sukses. Warna
  // peringatan supaya terbaca sebagai "dalam proses", bukan verdict.
  retrying: "text-warning",
} as const;

/** B2 — laporan eksekusi terstruktur (bukan teks polos): header status +
 *  durasi, daftar langkah per node yang bisa dibuka, dan aksi lanjutan. */
export function ExecutionReportCard({
  report,
  running,
  onOpenCanvas,
  onRunAgain,
}: {
  report: ExecutionReport;
  running: boolean;
  onOpenCanvas: () => void;
  onRunAgain: () => void;
}) {
  const { t } = useI18n();
  const [openStep, setOpenStep] = useState<string | null>(null);
  const style = STATUS_STYLE[report.status];
  const StatusIcon = style.icon;
  const secs = report.durationMs > 0 ? (report.durationMs / 1000).toFixed(1) : null;

  return (
    <div
      data-testid="execution-report-card"
      data-status={report.status}
      className="w-full max-w-[85%] rounded-2xl rounded-bl-lg border border-border/60 bg-bg-subtle px-3.5 py-3"
    >
      <div className="flex items-center gap-2">
        <StatusIcon size={15} strokeWidth={2} aria-hidden className={`shrink-0 ${style.cls}`} />
        <span className={`text-[13px] font-semibold ${style.cls}`} data-testid="report-status">
          {t(style.key)}
        </span>
        {secs && (
          <span className="ml-auto font-mono text-[11px] text-fg-muted" data-testid="report-duration">
            {t("chat.reportDuration", { secs })}
          </span>
        )}
      </div>

      <p className="mt-1 text-[12.5px] text-fg-muted" data-testid="report-summary">
        {report.steps.length
          ? t("chat.reportSummary", { ok: report.okCount, fail: report.failCount })
          : report.text}
      </p>

      {report.steps.length > 0 && (
        <ul className="mt-2 space-y-0.5" data-testid="report-steps">
          {report.steps.map((s, i) => {
            const open = openStep === s.id;
            const clickable = Boolean(s.detail);
            return (
              <li key={`${s.id}-${i}`}>
                <button
                  type="button"
                  data-testid="report-step"
                  data-step-status={s.status}
                  onClick={clickable ? () => setOpenStep(open ? null : s.id) : undefined}
                  aria-expanded={clickable ? open : undefined}
                  className={`flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-[12.5px] ${
                    clickable ? "hover:bg-bg-surface" : "cursor-default"
                  }`}
                >
                  <span className={`font-mono text-[11px] ${STEP_STYLE[s.status]}`} aria-hidden>
                    {s.status === "success" ? "OK" : s.status === "error" ? "GAGAL" : s.status === "retrying" ? `RETRY ${s.healing?.attempt ?? ""}/${s.healing?.max_attempts ?? ""}` : s.status}
                  </span>
                  <span className="truncate text-fg">{s.label}</span>
                  {clickable && (
                    <ChevronDown
                      size={12}
                      aria-hidden
                      className={`ml-auto shrink-0 text-fg-muted transition-transform ${open ? "" : "-rotate-90"}`}
                    />
                  )}
                </button>
                {open && s.detail && (
                  <p
                    className="px-1.5 pb-1 font-mono text-[11px] leading-snug text-fg-muted"
                    data-testid="report-step-detail"
                  >
                    {s.detail}
                  </p>
                )}
                {/* Rincian self-healing: kategori, provider, sumber error,
                    jeda backoff, dan saran developer. Tanpa ini data
                    healing datang ke browser lalu dibuang. */}
                {open && s.healing && (
                  <div
                    className="mx-1.5 mb-1.5 rounded-md border border-line px-2 py-1.5 text-[11px] leading-snug"
                    data-testid="healing-detail"
                    data-healing-action={s.healing.action}
                  >
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-fg-muted">
                      <span className="font-mono uppercase">{s.healing.category}</span>
                      <span aria-hidden>·</span>
                      <span>{s.healing.provider || "provider tidak dikenal"}</span>
                      {s.healing.delay_ms > 0 && (
                        <>
                          <span aria-hidden>·</span>
                          <span className="font-mono" data-testid="healing-delay">
                            jeda {s.healing.delay_ms} ms
                          </span>
                        </>
                      )}
                    </div>
                    {s.healing.search_hits > 0 && (
                      <p className="mt-1 text-fg-muted">
                        {s.healing.search_hits} hasil referensi forum dicocokkan
                      </p>
                    )}
                    {s.healing.suggestions.length > 0 && (
                      <ol className="mt-1 list-decimal space-y-0.5 pl-4" data-testid="healing-suggestions">
                        {s.healing.suggestions.map((sg, j) => (
                          <li key={j}>
                            {sg.link ? (
                              <a
                                href={sg.link}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="underline decoration-dotted underline-offset-2"
                              >
                                {sg.text}
                              </a>
                            ) : (
                              sg.text
                            )}
                          </li>
                        ))}
                      </ol>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {/* Laporan bahasa-manusia dari backend DIPERTAHANKAN di DOM (bukan
          dibuang): (a) itu sumber teks yang sudah diuji `test_execution_report.py`
          + E2E L3 S1 (`run-report` harus memuat "Workflow berhasil/berhenti"),
          (b) user bisa menyalinnya apa adanya bila butuh detail penuh. */}
      {report.text && (
        <details className="mt-2" data-testid="report-raw">
          <summary className="cursor-pointer text-[11.5px] text-fg-muted hover:text-fg">
            {t("chat.reportRaw")}
          </summary>
          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-snug text-fg-muted">
            {report.text}
          </pre>
        </details>
      )}

      <div className="mt-2.5 flex flex-wrap gap-2">
        <Button type="button" variant="secondary" size="sm" onClick={onOpenCanvas} data-testid="report-open-canvas">
          {t("chat.reportOpen")}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onRunAgain}
          disabled={running}
          data-testid="report-run-again"
        >
          {running ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <Play size={14} aria-hidden />}
          {t("chat.reportRunAgain")}
        </Button>
      </div>
    </div>
  );
}

/** B3 — form kredensial INLINE di dalam bubble pesan (bukan modal terpisah).
 *  Markup-nya sama dengan yang sudah dipakai FASE 2 (hanya dipindah ke sini
 *  supaya punya data-testid + ikut i18n), jadi perilakunya tidak berubah. */
export function CredentialPromptCard({
  provider,
  value,
  onChange,
  onSubmit,
}: {
  provider: string;
  value: string;
  onChange: (v: string) => void;
  onSubmit: (provider: string) => void;
}) {
  const { t } = useI18n();
  const label = PROVIDER_LABELS[provider] ?? provider;
  return (
    <div data-testid="credential-prompt" data-provider={provider} className="w-72">
      <div className="flex items-center gap-2">
        <KeyRound size={14} strokeWidth={1.9} aria-hidden className="shrink-0 text-accent" />
        <p className="text-[12.5px] font-medium text-fg">{t("chat.credTitle", { provider: label })}</p>
      </div>
      <form
        className="mt-2 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit(provider);
        }}
      >
        <Input
          type="password"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={t("chat.credPlaceholder")}
          aria-label={t("chat.credLabel", { provider: label })}
          data-testid="credential-input"
          autoComplete="off"
        />
        <Button type="submit" size="sm" variant="primary" disabled={!value.trim()} data-testid="credential-submit">
          {t("chat.credSave")}
        </Button>
      </form>
      <p className="mt-1.5 text-[11px] leading-snug text-fg-muted">{t("chat.credHint")}</p>
    </div>
  );
}

/** Task 1C — kartu koneksi OAuth INLINE di dalam bubble chat.
 *
 * KENAPA TANPA INPUT TOKEN: Google Sheets/Gmail/Calendar dan Slack hanya bisa
 * diakses lewat OAuth. Menampilkan form token di sini akan membuat user
 * menempel sesuatu yang MUSTAHIL benar, jadi satu-satunya jalan yang ditawarkan
 * adalah tombol Connect.
 *
 * Redirect memakai HALAMAN PENUH (bukan popup): popup diblokir browser pada
 * beberapa konfigurasi dan tidak bisa diuji ulang dengan andal. Handler-nya
 * (`onConnect`) disediakan ChatApp — ia meminta URL authorize lewat apiFetch
 * (JWT di header) lalu mengarahkan browser, sehingga JWT tidak pernah masuk URL.
 */
export function OAuthConnectCard({
  provider,
  busy = false,
  onConnect,
}: {
  provider: string;
  busy?: boolean;
  onConnect: (provider: string) => void;
}) {
  const { t } = useI18n();
  const label = PROVIDER_LABELS[provider] ?? provider;
  return (
    <div data-testid="oauth-connect" data-provider={provider} className="w-80 max-w-full">
      <div className="flex items-center gap-2">
        <Link2 size={14} strokeWidth={1.9} aria-hidden className="shrink-0 text-accent" />
        <p className="text-[12.5px] font-medium text-fg">{t("chat.oauthTitle", { provider: label })}</p>
      </div>
      <p className="mt-1 text-[11.5px] leading-snug text-fg-muted">
        {t("chat.oauthDesc")}
      </p>
      <Button
        type="button"
        size="sm"
        variant="primary"
        className="mt-2"
        disabled={busy}
        onClick={() => onConnect(provider)}
        data-testid="oauth-connect-button"
      >
        {busy ? (
          <span className="inline-flex items-center gap-1.5">
            <Loader2 size={13} className="animate-spin" aria-hidden /> {t("settings.connecting")}
          </span>
        ) : (
          t("chat.oauthConnect", { provider: label })
        )}
      </Button>
      <p className="mt-1.5 text-[11px] leading-snug text-fg-muted">{t("chat.oauthHint", { provider: label })}</p>
    </div>
  );
}

const PROVIDER_LABELS: Record<string, string> = {
  whatsapp: "WhatsApp Cloud API",
  telegram: "Telegram",
  google_sheets: "Google Sheets",
  gmail: "Gmail",
  slack: "Slack",
  google_calendar: "Google Calendar",
};


