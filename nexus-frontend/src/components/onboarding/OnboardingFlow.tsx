"use client";

/**
 * OnboardingFlow.tsx — FASE 5 (B5): 3 langkah untuk pengguna baru.
 *
 * KEPUTUSAN PENTING:
 *  1. Tombol "Lewati" ada di SETIAP langkah. Onboarding yang memaksa adalah
 *     dinding, bukan bantuan.
 *  2. Selesai/lewat DISIMPAN DI DUA TEMPAT: localStorage (instan, offline) dan
 *     `PUT /preferences` (ikut user ke perangkat lain). Yang kedua memakai
 *     endpoint preferensi UI FASE 4 — TIDAK perlu migration baru.
 *  3. Tidak pernah muncul sebelum statusnya diketahui (`unknown` merender null),
 *     supaya user lama tidak melihat kilatan dialog. Aman hidrasi: server dan
 *     klien sama-sama merender null pada frame pertama.
 */
import { useCallback, useEffect, useState } from "react";
import { Bot, Check, Cpu, LayoutGrid, Play, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/context/auth";
import { useI18n } from "@/i18n/context";

const LOCAL_KEY = "katalir.onboarding.v1";

type Status = "unknown" | "show" | "hidden";

export function OnboardingFlow({
  models = [],
  onPickModel,
  onTrySample,
  historyKnown = true,
  hasHistory = false,
}: {
  /** Model yang boleh dipilih di langkah 1 (dari roster nyata, bukan hardcode). */
  models?: { id: string; label: string }[];
  onPickModel?: (id: string) => void;
  /** Dipanggil saat user menekan "Coba sekarang" (isi composer + kirim). */
  onTrySample?: (prompt: string) => void;
  /** True bila daftar riwayat chat sudah diketahui (hindari kilatan dialog). */
  historyKnown?: boolean;
  /**
   * True bila user SUDAH punya riwayat chat.
   *
   * KENAPA PENTING (temuan regresi FASE 5): definisi "user baru" tidak boleh
   * hanya "belum menandai onboarding selesai". Pada E2E A2 auth, dialog ini
   * muncul di atas user ber-riwayat dan lapisan `fixed inset-0 z-50`-nya
   * MENUTUP header sehingga klik menu akun tidak pernah sampai (spec gagal
   * timeout 1,5 menit). User yang sudah pernah mengobrol jelas bukan pengguna
   * baru — jadi riwayat diperlakukan sebagai sinyal "sudah kenal aplikasi".
   */
  hasHistory?: boolean;
}) {
  const { t } = useI18n();
  const { email: authEmail, loading } = useAuth();
  const [status, setStatus] = useState<Status>("unknown");
  const [step, setStep] = useState(0);
  const [picked, setPicked] = useState<string | null>(null);
  const email = authEmail ?? "";

  // Tahap 1: keputusan lokal (instan). Tahap 2: preferensi server (lintas device).
  useEffect(() => {
    if (loading) return;
    // Belum tahu ada riwayat atau tidak -> JANGAN menampilkan apa pun dulu.
    // (Kalau langsung tampil, dialog berkedip untuk user lama lalu hilang.)
    if (!historyKnown) return;
    if (!email) {
      setStatus("hidden");
      return;
    }
    if (hasHistory) {
      // Sudah pernah mengobrol = bukan pengguna baru (lihat catatan prop).
      setStatus("hidden");
      return;
    }
    let local = "";
    try {
      local = localStorage.getItem(LOCAL_KEY) ?? "";
    } catch {
      /* storage diblokir: anggap belum selesai, jangan crash */
    }
    if (local === "done" || local === "skipped") {
      setStatus("hidden");
      return;
    }
    let cancelled = false;
    setStatus("show"); // server hanya bisa MEMBATALKAN (lihat di bawah)
    void (async () => {
      try {
        const res = await apiFetch("/preferences");
        if (!res.ok) return;
        const data = (await res.json()) as { prefs?: Record<string, unknown> };
        if (!cancelled && data?.prefs?.onboardingCompleted) {
          try {
            localStorage.setItem(LOCAL_KEY, "done");
          } catch {
            /* tidak fatal */
          }
          setStatus("hidden");
        }
      } catch {
        /* offline: onboarding tetap tampil (bukan alasan mengunci user) */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [email, loading, historyKnown, hasHistory]);

  const finish = useCallback((how: "done" | "skipped") => {
    try {
      localStorage.setItem(LOCAL_KEY, how === "done" ? "done" : "skipped");
    } catch {
      /* tidak fatal */
    }
    setStatus("hidden");
    // Persist ke profil (merge; kunci lain tidak tersentuh — lihat PUT /preferences).
    void apiFetch("/preferences", {
      method: "PUT",
      body: JSON.stringify({
        prefs: {
          onboardingCompleted: true,
          onboardingHow: how,
          onboardingAt: new Date().toISOString(),
        },
      }),
    }).catch(() => {
      /* gagal simpan ke server tidak menghukum user: localStorage sudah mencatat */
    });
  }, []);

  if (status !== "show") return null;

  const steps = [
    { Icon: Cpu, title: t("onboarding.step1Title"), desc: t("onboarding.step1Desc"), testid: "onboarding-step-1" },
    { Icon: Play, title: t("onboarding.step2Title"), desc: t("onboarding.step2Desc"), testid: "onboarding-step-2" },
    { Icon: LayoutGrid, title: t("onboarding.step3Title"), desc: t("onboarding.step3Desc"), testid: "onboarding-step-3" },
  ];
  const current = steps[step];
  const StepIcon = current.Icon;
  const sample = t("onboarding.samplePrompt");

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t("onboarding.title")}
      data-testid="onboarding-flow"
      data-step={step}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <div className="w-full max-w-md rounded-lg border border-border bg-surface p-5 shadow-lg">
        <div className="flex items-center gap-2">
          <Sparkles size={16} strokeWidth={2} aria-hidden className="text-accent" />
          <p className="text-subhead font-semibold text-fg">{t("onboarding.title")}</p>
          <span className="ml-auto font-mono text-[11px] text-fg-muted" data-testid="onboarding-progress">
            {step + 1}/3
          </span>
        </div>

        <div className="mt-4 flex items-start gap-3" data-testid={current.testid}>
          <span className="mt-0.5 rounded-md bg-bg-subtle p-2">
            <StepIcon size={18} strokeWidth={1.75} aria-hidden className="text-accent" />
          </span>
          <div className="min-w-0">
            <p className="text-[14px] font-semibold text-fg">{current.title}</p>
            <p className="mt-1 text-footnote leading-relaxed text-fg-muted">{current.desc}</p>
          </div>
        </div>

        {step === 0 && models.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2" data-testid="onboarding-models">
            {models.map((m) => (
              <button
                key={m.id}
                type="button"
                data-testid="onboarding-model-option"
                data-model={m.id}
                aria-pressed={picked === m.id}
                onClick={() => {
                  setPicked(m.id);
                  onPickModel?.(m.id);
                }}
                className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[12.5px] transition-colors ${
                  picked === m.id
                    ? "border-accent bg-accent/10 text-accent"
                    : "border-border text-fg-muted hover:border-accent/40 hover:text-fg"
                }`}
              >
                {picked === m.id && <Check size={12} strokeWidth={2.5} aria-hidden />}
                {m.label}
              </button>
            ))}
          </div>
        )}

        {step === 1 && (
          <div className="mt-3 rounded-md border border-border/70 bg-bg-subtle px-3 py-2">
            <p className="font-mono text-[12px] text-fg" data-testid="onboarding-sample-prompt">
              {sample}
            </p>
          </div>
        )}

        {step === 2 && (
          <div className="mt-3 flex items-center gap-2 text-footnote text-fg-muted">
            <Bot size={14} strokeWidth={1.75} aria-hidden className="shrink-0 text-accent" />
            <span>{t("onboarding.canvasHint")}</span>
          </div>
        )}

        <div className="mt-5 flex items-center gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={() => finish("skipped")} data-testid="onboarding-skip">
            {t("onboarding.skip")}
          </Button>
          <div className="ml-auto flex gap-2">
            {step > 0 && (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => setStep(step - 1)}
                data-testid="onboarding-back"
              >
                {t("onboarding.back")}
              </Button>
            )}
            {step === 1 && onTrySample && (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => {
                  onTrySample(sample);
                  finish("done");
                }}
                data-testid="onboarding-try-sample"
              >
                {t("onboarding.tryNow")}
              </Button>
            )}
            {/* PENTING: "Lanjut" tetap ada di langkah 2. Versi pertama membuat
                tombol coba-contoh MENGGANTIKAN "Lanjut", sehingga langkah 3
                (tur kanvas) tidak pernah bisa dicapai — tombol alternatif tidak
                boleh menutup jalur utama. */}
            {step < 2 ? (
              <Button type="button" variant="primary" size="sm" onClick={() => setStep(step + 1)} data-testid="onboarding-next">
                {t("onboarding.next")}
              </Button>
            ) : (
              <Button type="button" variant="primary" size="sm" onClick={() => finish("done")} data-testid="onboarding-done">
                {t("onboarding.done")}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
