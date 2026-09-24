"use client";

import { useEffect, useState } from "react";
import { AlertCircle, Check, ChevronDown, Lock } from "lucide-react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { providerGroups, type ChatModel } from "@/lib/models";
import { useI18n } from "@/i18n/context";
import { cn } from "@/lib/cn";

interface ModelSelectorProps {
  models: ChatModel[];
  value: string | null;
  onChange: (id: string) => void;
  disabled?: boolean;
  /** tier user saat ini: 'free' | 'plus' — mengontrol gating model plus. */
  userTier?: "free" | "plus";
  /** True bila daftar model dari sumber CADANGAN (roster gateway gagal).
   *  Ditampilkan sebagai peringatan halus — sebelumnya kondisi ini senyap,
   *  sehingga user hanya melihat daftar tanpa penjelasan (temuan 2026-09-19). */
  degraded?: boolean;
}

/**
 * Link checkout Dodo Payments (Plus: $299 / TAHUN — produk "Katalir",
 * pdt_0NnsVLn7IzpG8Sokr3pZh).
 *
 * Diambil dari `NEXT_PUBLIC_DODO_CHECKOUT_URL`. Next meng-INLINE nilai
 * `NEXT_PUBLIC_*` saat build, jadi mengubah URL = build ulang (bukan runtime).
 */
const CHECKOUT_URL = (process.env.NEXT_PUBLIC_DODO_CHECKOUT_URL || "").trim();

/**
 * Tombol upgrade ke Plus. Dua keadaan, keduanya jujur:
 *  - URL tersedia  -> tautan keluar ke checkout Dodo (tab baru, noopener).
 *  - URL belum ada -> tombol NONAKTIF + keterangan, BUKAN link palsu yang
 *    diam-diam tidak melakukan apa pun (perilaku lama `href="#upgrade"` +
 *    preventDefault: user bingung karena tombolnya tidak bereaksi).
 */
function BuyPlusButton({ checkoutUrl }: { checkoutUrl: string }) {
  const base =
    "mt-1 flex items-center justify-center rounded-sm border-t border-border " +
    "px-2.5 py-2 text-[12px] font-semibold transition-colors";
  if (!checkoutUrl) {
    return (
      <span
        className={cn(base, "cursor-not-allowed text-fg-subtle")}
        title="Link checkout belum dikonfigurasi (NEXT_PUBLIC_DODO_CHECKOUT_URL)"
      >
        Upgrade ke Plus — $299 / tahun (segera)
      </span>
    );
  }
  return (
    <a
      href={checkoutUrl}
      target="_blank"
      rel="noopener noreferrer"
      className={cn(base, "text-accent hover:bg-bg-subtle")}
    >
      Upgrade ke Plus — $299 / tahun
    </a>
  );
}

/** Dropdown pemilih model di composer (radix, non-modal → tanpa pointer-events lock).
 *  Baseline: thiagovarela/clankie #49, assistant-ui ModelSelector, hermes-agent #5880. */
export function ModelSelector({
  models,
  value,
  onChange,
  disabled,
  userTier = "free",
  degraded = false,
}: ModelSelectorProps) {
  const [open, setOpen] = useState(false);
  // HYDRATION (Lapis A): render pertama — HTML server dan render hydration
  // client — WAJIB identik. Nilai `value`/`models` baru final SETELAH mount
  // (restore localStorage di parent + daftar dari GET /models), dan update
  // parent yang mendarat sebelum React selesai men-hydrate subtree composer
  // membuat label di sini beda dari HTML server:
  //   server "Gemma 4 31B"  vs  client "Pilih model"
  // -> "Hydration failed because the server rendered text didn't match the
  //    client" (tereproduksi, lihat tests/hydration.spec.ts).
  // Gate `mounted` (pola sama seperti ThemeToggle) membuat render pertama
  // selalu netral, sehingga divaisi hanya terjadi sebagai update setelah
  // hydration — bukan bagian dari hydration.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const { t } = useI18n();
  const active = models.find((m) => m.id === value);
  const label = mounted ? (active?.name ?? t("modelPicker.stub")) : t("modelPicker.loading");
  const plusDisabled = userTier !== "plus";
  const groups = providerGroups(models);

  return (
    <DropdownMenu.Root open={open} onOpenChange={setOpen}>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          disabled={disabled}
          /* FASE 5: `data-testid` STABIL. Sebelumnya tes memilih tombol ini lewat
             `button[aria-label='Pilih model AI']` (teks berbahasa Indonesia),
             padahal label aksesibel kini memuat nama model yang berubah-ubah dan
             ikut bahasa pengguna -> selector lama rapuh dan pecah begitu label
             diperbaiki. Pola yang sama sudah dipakai untuk `composer-input` /
             `composer-send`. */
          data-testid="model-selector"
          /* FASE 5 (Lighthouse `label-content-name-mismatch`, ditemukan di `/`):
             nama aksesibel WAJIB memuat teks yang terlihat ("Gemma 4…"), bukan
             hanya tujuannya. Label lama "Pilih model AI" tidak memuat nama model
             -> pelanggaran WCAG 2.5.3 (Label in Name). */
          aria-label={`${label} — ${t("modelPicker.label")}`}
          className={cn(
            "flex h-8 items-center gap-1.5 rounded-full border border-border bg-surface px-3 text-[12px] font-medium text-fg transition-colors",
            "hover:bg-bg-subtle hover:text-fg focus-visible:shadow-focus disabled:opacity-40 disabled:pointer-events-none"
          )}
        >
          <span className="truncate max-w-[120px]">{label}</span>
          <ChevronDown size={13} strokeWidth={2} className="shrink-0 text-fg-subtle" />
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        {/* SCROLLABLE (fix 2026-09-19): tanpa max-height, daftar model terpotong
            di tepi viewport -> model provider lain (Groq/NVIDIA) tidak bisa
            dipilih sama sekali. max-h[min(60vh,26rem)] memberi ruang cukup untuk
            12-30 model tanpa menutupi seluruh layar; overscroll-contain mencegah
            scroll "bocor" ke halaman di belakang saat panel di ujung. */}
        <DropdownMenu.Content
          align="end"
          sideOffset={6}
          collisionPadding={8}
          className="scroll-thin z-[90] max-h-[min(60vh,26rem)] min-w-[240px] overflow-y-auto overscroll-contain rounded-md border border-border bg-surface p-1 text-subhead text-fg shadow-lg"
        >
          {/* Peringatan degradasi (B): daftar model dari sumber cadangan.
              Sebelumnya kondisi ini SENYAP — user hanya melihat daftar tanpa
              model provider lain dan tidak tahu sebabnya. */}
          {degraded && (
            <div className="mb-1 flex items-start gap-1.5 rounded-sm border border-warning/30 bg-warning/10 px-2.5 py-1.5 text-[11px] leading-snug text-warning">
              <AlertCircle size={12} strokeWidth={2} className="mt-0.5 shrink-0" aria-hidden />
              <span>
                <span className="block font-medium">{t("modelPicker.degraded")}</span>
                <span className="block text-warning/90">{t("modelPicker.degradedHint")}</span>
              </span>
            </div>
          )}
          {groups.map((g) => (
            <div key={g.provider} className="mb-1">
              {/* Sticky: saat scroll, label provider tetap terlihat sebagai
                  penanda seksi (pola section header iOS). z-20 + bg opaque
                  supaya item yang lewat di belakangnya tidak tembus. */}
              <p className="sticky top-0 z-20 bg-surface/95 px-2.5 pb-1 pt-2 text-caption font-semibold uppercase tracking-wide text-fg-subtle backdrop-blur-sm">
                {g.provider}
              </p>
              {g.models.map((m) => {
                // `locked` dari server (plus untuk user non-plus) ATAU tebakan
                // lokal dari tier. Keduanya dipertahankan: server bisa
                // mengunci model yang tier-nya bukan "plus" (mis. kuota habis).
                const locked = Boolean(m.locked) || (m.tier === "plus" && plusDisabled);
                const isActive = m.id === value;
                return (
                  <DropdownMenu.Item
                    key={m.id}
                    disabled={locked}
                    onSelect={() => {
                      if (!locked) onChange(m.id);
                    }}
                    className={cn(
                      "flex cursor-pointer items-center gap-2 rounded-sm px-2.5 py-2 text-[13px] leading-tight outline-none transition-colors",
                      "focus:bg-bg-subtle data-[highlighted]:bg-bg-subtle",
                      locked
                        ? "cursor-not-allowed text-fg-subtle"
                        : isActive
                          ? "font-medium text-fg"
                          : "text-fg-muted hover:text-fg",
                      disabled && "opacity-40"
                    )}
                  >
                    <span className="flex-1">
                      <span className="block">{m.name}</span>
                      {locked && (
                        <span className="block text-[11px] font-normal text-fg-subtle">
                          {t("modelPicker.locked")}
                        </span>
                      )}
                      {!locked && m.hint && (
                        <span className="block text-[11px] font-normal text-fg-subtle">{m.hint}</span>
                      )}
                    </span>
                    {locked ? (
                      <Lock size={13} strokeWidth={1.75} className="shrink-0 text-fg-subtle" />
                    ) : isActive ? (
                      <Check size={14} strokeWidth={2} className="shrink-0 text-accent" />
                    ) : null}
                  </DropdownMenu.Item>
                );
              })}
            </div>
          ))}
          {/* Fade bawah: sticky, tetap menempel di tepi bawah panel saat scroll
              — penanda halus bahwa masih ada item di bawah. `-mb-1` menutup
              padding p-1 container agar fade rata ke tepi. */}
          <div
            aria-hidden
            className="pointer-events-none sticky bottom-0 z-10 -mb-1 h-3 bg-gradient-to-t from-surface to-transparent"
          />
          {plusDisabled && (
            // Link checkout Dodo Payments (Plus: $299 / TAHUN — produk "Katalir").
            // Nilai diambil dari `NEXT_PUBLIC_DODO_CHECKOUT_URL` (di-INLINE saat build — Next
            // menyalin env NEXT_PUBLIC_* ke bundle, jadi mengubahnya perlu
            // build ulang). Sebelumnya `href="#upgrade"` + preventDefault =
            // tombol mati: user tidak punya jalan membayar.
            //
            // Bila env belum di-set (mis. belum ada produk di dashboard Dodo),
            // penampilan tetap jujur: link TIDAK dibuat seolah berfungsi.
            //
            // STICKY (fix 2026-09-19): panel kini bisa di-scroll, jadi CTA
            // pembelian ditempel di tepi bawah supaya tetap terjangkau tanpa
            // harus scroll ke item terakhir. bg-surface wajib — item lain lewat
            // di belakangnya.
            <div className="sticky bottom-0 z-20 bg-surface">
              <BuyPlusButton checkoutUrl={CHECKOUT_URL} />
            </div>
          )}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}