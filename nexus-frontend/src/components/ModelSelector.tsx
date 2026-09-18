"use client";

import { useEffect, useState } from "react";
import { Check, ChevronDown, Lock } from "lucide-react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { providerGroups, type ChatModel } from "@/lib/models";
import { cn } from "@/lib/cn";

interface ModelSelectorProps {
  models: ChatModel[];
  value: string | null;
  onChange: (id: string) => void;
  disabled?: boolean;
  /** tier user saat ini: 'free' | 'plus' — mengontrol gating model plus. */
  userTier?: "free" | "plus";
}

/**
 * Link checkout Dodo Payments (Plus: Rp 5.000.000 / TAHUN).
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
        Upgrade ke Plus — Rp 5.000.000 / tahun (segera)
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
      Upgrade ke Plus — Rp 5.000.000 / tahun
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

  const active = models.find((m) => m.id === value);
  const label = mounted ? (active?.name ?? "Pilih model") : "Memuat…";
  const plusDisabled = userTier !== "plus";
  const groups = providerGroups(models);

  return (
    <DropdownMenu.Root open={open} onOpenChange={setOpen}>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          disabled={disabled}
          aria-label="Pilih model AI"
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
        <DropdownMenu.Content
          align="end"
          sideOffset={6}
          className="z-[90] min-w-[240px] rounded-md border border-border bg-surface p-1 text-subhead text-fg shadow-lg"
        >
          {groups.map((g) => (
            <div key={g.provider} className="mb-1">
              <p className="px-2.5 pb-1 pt-2 text-caption font-semibold uppercase tracking-wide text-fg-subtle">
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
                          Tidak tersedia di tier Anda
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
          {plusDisabled && (
            // Link checkout Dodo Payments. Nilai diambil dari
            // `NEXT_PUBLIC_DODO_CHECKOUT_URL` (di-INLINE saat build — Next
            // menyalin env NEXT_PUBLIC_* ke bundle, jadi mengubahnya perlu
            // build ulang). Sebelumnya `href="#upgrade"` + preventDefault =
            // tombol mati: user tidak punya jalan membayar.
            //
            // Bila env belum di-set (mis. belum ada produk di dashboard Dodo),
            // penampilan tetap jujur: link TIDAK dibuat seolah berfungsi.
            <BuyPlusButton checkoutUrl={CHECKOUT_URL} />
          )}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}