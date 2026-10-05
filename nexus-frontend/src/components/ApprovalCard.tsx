"use client";

/**
 * ApprovalCard - persetujuan user untuk tool yang mengirim data ke luar.
 *
 * KAPAN MUNCUL (2026-10-05)
 * -------------------------
 * Backend mengembalikan `requires_approval` pada dua kondisi:
 *   1. policy gate: TELEGRAM/SLACK mengirim isi ke pihak luar;
 *   2. intent-alignment: pola tool di balasannya tidak terlihat diminta
 *      di pesan user (defense-in-depth injeksi prompt).
 *
 * KENAPA KARTU INI, BUKAN TOMBOL LANGSUNG
 * --------------------------------------
 * Persetujuan hanya bermakna kalau user MELIHAT apa yang sebenarnya akan
 * dikirim sebelum mengiyakan. Kalau tombolnya langsung mengirim pesan,
 * approval berubah jadi formalitas. Karena itu args ditampilkan apa
 * adanya di dalam <pre>.
 *
 * CATATAN KONTRAK: `args` di sini dibaca dari token approval di server,
 * BUKAN dari nilai yang dikirim ulang client. Server mengabaikan argumen
 * dari client dan memakai ulang yang tertanam di token - jadi tampilan di
 * sini tidak bisa berbeda dari yang benar-benar dieksekusi.
 */
import { useState } from "react";
import { AlertTriangle, Check, Loader2, ShieldQuestion, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

export interface ApprovalCardProps {
  /** Nama alat, mis. "TELEGRAM". */
  tool: string;
  /** Argumen yang AKAN dieksekusi (dari token, bukan dari client). */
  args?: Record<string, unknown>;
  /** Alasan dari backend, mis. "tool tidak selaras dengan pesan user". */
  reason?: string;
  /** "not_aligned" bila pemicunya intent-check. */
  alignment?: string;
  approvalToken: string;
  /** FIX 2026-10-05: membawa HASIL eksekusi ke atas (ChatApp) supaya user
   *  melihat output tool, bukan cuma "disetujui dan dijalankan". `result`
   *  adalah field apa adanya dari response /chat/approve. */
  onDecision?: (info: { approved: boolean; result?: unknown }) => void;
}
export function ApprovalCard({
  tool,
  args,
  reason,
  alignment,
  approvalToken,
  onDecision,
}: ApprovalCardProps) {
  const [busy, setBusy] = useState<"approve" | "deny" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<"approved" | "denied" | null>(null);

  const decide = async (approved: boolean) => {
    if (busy || result) return;
    setBusy(approved ? "approve" : "deny");
    setError(null);
    try {
      const res = await apiFetch("/chat/approve", {
        method: "POST",
        // Sengaja HANYA token + keputusan. Server mengabaikan tool/args
        // dari client dan memakai ulang yang tertanam di token.
        body: JSON.stringify({
          approval_token: approvalToken,
          decision: approved ? "approve" : "deny",
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(
          typeof data?.detail === "string"
            ? data.detail
            : "Persetujuan gagal diproses. Coba lagi.",
        );
        setBusy(null);
        return;
      }
      setResult(approved ? "approved" : "denied");
      onDecision?.({ approved, result: (data as { result?: unknown }).result });
    } catch {
      setError("Tidak bisa menghubungi server. Coba lagi.");
      setBusy(null);
    }
  };

  if (result) {
    return (
      <Card className="w-80" data-testid="approval-done">
        <CardContent className="pt-4 pb-4">
          <div className="flex items-center gap-2 text-sm font-medium text-fg">
            {result === "approved" ? (
              <>
                <Check size={15} strokeWidth={2} aria-hidden className="text-success" />
                <span>{tool} disetujui dan dijalankan.</span>
              </>
            ) : (
              <>
                <X size={15} strokeWidth={2} aria-hidden className="text-fg-muted" />
                <span>{tool} dibatalkan.</span>
              </>
            )}
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="w-80" data-testid="approval-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <ShieldQuestion size={15} strokeWidth={1.75} aria-hidden />
          <span>Perlu persetujuan Anda</span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {reason ? (
          <p className="mb-2.5 text-footnote text-fg-muted">{reason}</p>
        ) : null}

        {alignment ? (
          // FIX 2026-10-05: prop ini sebelumnya diteruskan tapi tidak pernah
          // dirender, jadi user tidak bisa membedakan "policy gate minta izin"
          // dari "pola ini tidak kamu minta" (intent-alignment).
          <details data-testid="approval-alignment" className="mb-2.5">
            <summary className="cursor-pointer text-footnote text-fg-muted">
              Kenapa tool ini butuh persetujuan?
            </summary>
            <p className="mt-1.5 text-footnote text-fg-muted">
              {alignment === "not_aligned"
                ? "Pola tool pada balasan model tidak terlihat diminta di pesan Anda (pemeriksaan intent-alignment)."
                : alignment}
            </p>
          </details>
        ) : null}

        <dl className="mb-2.5 flex items-center gap-2 text-sm">
          <dt className="text-fg-muted">Alat</dt>
          <dd className="font-medium text-fg">{tool}</dd>
        </dl>

        {args && Object.keys(args).length > 0 ? (
          <pre
            data-testid="approval-args"
            className="mb-3 max-h-40 overflow-auto rounded border border-border bg-surface-muted p-2 font-mono text-[11px] leading-relaxed text-fg-muted"
          >
            {JSON.stringify(args, null, 2)}
          </pre>
        ) : null}

        {error ? (
          <p
            role="alert"
            className="mb-2.5 flex items-start gap-1.5 text-footnote text-danger"
          >
            <AlertTriangle
              size={13}
              strokeWidth={2}
              aria-hidden
              className="mt-0.5 shrink-0"
            />
            <span>{error}</span>
          </p>
        ) : null}

        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            className="flex-1 justify-center gap-1.5"
            disabled={busy !== null}
            onClick={() => decide(false)}
            data-testid="approval-deny"
          >
            {busy === "deny" ? (
              <Loader2 size={13} className="animate-spin" aria-hidden />
            ) : null}
            Tolak
          </Button>
          <Button
            size="sm"
            className="flex-1 justify-center gap-1.5"
            disabled={busy !== null}
            onClick={() => decide(true)}
            data-testid="approval-approve"
          >
            {busy === "approve" ? (
              <Loader2 size={13} className="animate-spin" aria-hidden />
            ) : null}
            Setujui
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
