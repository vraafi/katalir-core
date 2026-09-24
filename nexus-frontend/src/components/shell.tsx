"use client";

import dynamic from "next/dynamic";
import { Plus, LogIn, MessageSquare, Menu, X, Workflow, KeyRound, MoreHorizontal, Trash2 } from "lucide-react";
import Link from "next/link";
import { useAuth } from "@/context/auth";
import ThemeToggle from "@/components/ThemeToggle";
import { UserMenu } from "@/components/UserMenu";
import { BrandMark } from "@/components/BrandMark";
import { useI18n } from "@/i18n/context";
import { StaggerList, StaggerItem } from "@/components/motion";
import { SkipToContent } from "@/components/SkipToContent";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import * as Dialog from "@radix-ui/react-dialog";

/**
 * FASE 6 lanjutan — CODE SPLITTING (Pendekatan 1).
 *
 * TEMUAN TERUKUR: Lighthouse mobile `/` = perf **57-65** dengan
 * `mainthread=8035ms` / `bootup=5908ms` dan 1,38 MB script. Tiga chunk terberat
 * adalah Radix (281 KB) dan motion (2 × ~180 KB). Shell ini membungkus SEMUA
 * rute, dan dua komponen di bawah adalah penyumbang Radix-Dialog terbesar padahal
 * TIDAK diperlukan untuk first paint:
 *   * `VaultModal` hanya tampil saat user membuka Brankas,
 *   * `CommandPalette` hanya saat Cmd+K ditekan.
 * Keduanya kini dimuat sebagai chunk terpisah SETELAH hidrasi (ssr:false), jadi
 * unduhan + parsing-nya tidak lagi menghalangi LCP.
 *
 * Catatan: `ssr:false` aman di sini karena keduanya memang hanya hidup di klien
 * (dialog yang dibuka oleh interaksi user) dan build ini `output: "export"`.
 */
const VaultModal = dynamic(() => import("@/components/VaultModal"), { ssr: false });
const CommandPalette = dynamic(() => import("@/components/CommandPalette").then((m) => m.CommandPalette), {
  ssr: false,
});

interface SessionItem { id: string; title?: string; }

interface ShellProps {
  children: React.ReactNode;
  sessions: SessionItem[];
  currentSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onNewWorkflow?: () => void;
  onDeleteSession?: (id: string) => void | Promise<void>;
  /** tier efektif user ("free" | "plus") — diteruskan ke UserMenu footer. */
  userTier?: "free" | "plus";
}

export default function Shell({ children, sessions, currentSessionId, onSelectSession, onNewChat, onNewWorkflow, onDeleteSession, userTier = "free" }: ShellProps) {
  const { email, signInWithGoogle } = useAuth();
  const { t } = useI18n();
  const [vaultOpen, setVaultOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  // FASE 1: drawer mobile (<768px) — sidebar off-canvas.
  const [mobileOpen, setMobileOpen] = useState(false);

  // Safety net (Radix #3141 / shadcn #7575): bila dialog modal sempat
  // meninggalkan body.pointerEvents="none" (stuck — seluruh halaman tak bisa
  // diklik, termasuk tombol Chat Baru), bersihkan pada unmount. Dialog sudah
  // dipaksa modal={false} (root cause dihilangkan); ini hanya jaring pengaman.
  useEffect(() => {
    return () => {
      document.body.style.pointerEvents = "";
    };
  }, []);

  // FASE 1: tutup drawer saat Escape + kunci scroll body saat terbuka.
  useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false);
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [mobileOpen]);

  const closeMobile = () => setMobileOpen(false);

  return (
    <div className="flex h-screen overflow-hidden bg-bg">
      {/* FASE 5: tautan lewati-ke-konten — elemen fokusable PERTAMA di halaman
          (targetnya `<main id="main-content">` di bawah). */}
      <SkipToContent />
      {/* FASE 1: sidebar desktop — tersembunyi di <md, diganti drawer. */}
      <aside aria-label={t("nav.sessionsLabel")} className="hidden w-64 shrink-0 flex-col border-r border-border bg-bg-subtle md:flex">
        <Button variant="secondary" size="md" onClick={() => { onNewChat(); closeMobile(); }} className="mx-3 mt-3">
          <Plus className="h-4 w-4" strokeWidth={1.75} /> {t("nav.newChat")}
        </Button>
        <div className="mt-4 flex-1 overflow-y-auto px-2">
          <p className="px-2 pb-2 text-caption font-semibold uppercase tracking-wide text-fg-subtle">{t("nav.history")}</p>
          {sessions.length === 0 && <p className="px-2 py-1 text-footnote text-fg-subtle">{t("nav.noHistory")}</p>}
          <StaggerList>
            {sessions.map((s) => {
              const active = s.id === currentSessionId;
              return (
                <StaggerItem key={s.id}>
                  <div className="group relative mb-1 flex items-center">
                    <button onClick={() => { onSelectSession(s.id); closeMobile(); }}
                      className={`flex min-w-0 flex-1 items-center gap-2 rounded-lg border px-3 py-2 text-left text-[13px] leading-[18px] transition-colors duration-150 ${active
                        ? "border-accent/20 bg-accent/10 font-medium text-fg shadow-xs dark:border-accent/25 dark:bg-accent/15"
                        : "border-transparent font-normal text-fg-muted hover:bg-bg-subtle/70 hover:text-fg"}`}>
                      <MessageSquare size={12} strokeWidth={1.75} className={`shrink-0 ${active ? "text-accent" : "text-fg-subtle"}`} />
                      <span className="truncate">{s.title || "Chat"}</span>
                    </button>
                    <DropdownMenu.Root>
                      <DropdownMenu.Trigger asChild>
                        <button
                          aria-label={`Opsi ${s.title || "chat"}`}
                          type="button"
                          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-r-sm text-fg-subtle opacity-0 transition focus:opacity-100 group-hover:opacity-100 hover:text-fg"
                        >
                          <MoreHorizontal size={14} strokeWidth={1.75} />
                        </button>
                      </DropdownMenu.Trigger>
                      <DropdownMenu.Portal>
                        <DropdownMenu.Content
                          align="end"
                          sideOffset={4}
                          className="z-50 min-w-40 rounded-md border border-border bg-surface p-1 shadow-md"
                        >
                          <DropdownMenu.Item
                            onSelect={() => setTimeout(() => setDeleteTarget(s.id), 0)}
                            className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-footnote text-red-500 outline-none hover:bg-bg-subtle focus:bg-bg-subtle"
                          >
                            <Trash2 size={13} strokeWidth={1.75} /> Hapus
                          </DropdownMenu.Item>
                        </DropdownMenu.Content>
                      </DropdownMenu.Portal>
                    </DropdownMenu.Root>
                  </div>
                </StaggerItem>
              );
            })}
          </StaggerList>
        </div>
        {/* Footer sidebar: menu akun (avatar + dropdown). Selalu terlihat
            saat login — Upgrade ke Plus ada di sini (path upgrade yang jelas),
            bukan hanya di dalam dropdown model. */}
        {email && (
          <div className="border-t border-border p-2">
            <UserMenu userTier={userTier} />
          </div>
        )}
      </aside>
      {/* FASE 1: drawer mobile — overlay + panel off-canvas (target 44px). */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Menu navigasi">
          <div className="absolute inset-0 bg-black/50" onClick={closeMobile} aria-hidden="true" />
          <aside className="absolute left-0 top-0 flex h-full w-72 max-w-[85vw] flex-col border-r border-border bg-bg-subtle shadow-lg">
            <div className="flex items-center justify-between px-3 pt-3">
            <span className="text-xl font-bold tracking-tight text-fg">Katalir</span>
              <button
                type="button"
                onClick={closeMobile}
                aria-label="Tutup menu"
                className="flex h-11 w-11 items-center justify-center rounded-md text-fg-muted transition hover:bg-bg-subtle hover:text-fg"
              >
                <X className="h-5 w-5" strokeWidth={1.75} />
              </button>
            </div>
            <Button variant="secondary" size="md" onClick={() => { onNewChat(); closeMobile(); }} className="mx-3 mt-3">
              <Plus className="h-4 w-4" strokeWidth={1.75} /> {t("nav.newChat")}
            </Button>
            <div className="mt-4 flex-1 overflow-y-auto px-2">
              <p className="px-2 pb-2 text-caption font-semibold uppercase tracking-wide text-fg-subtle">{t("nav.history")}</p>
              {sessions.length === 0 && <p className="px-2 py-1 text-footnote text-fg-subtle">{t("nav.noHistory")}</p>}
              {sessions.map((s) => (
                <button key={s.id} onClick={() => { onSelectSession(s.id); closeMobile(); }}
                  className="mb-1 flex min-w-0 w-full items-center gap-2 rounded-lg border border-transparent px-3 py-2 text-left text-[13px] font-normal text-fg-muted transition-colors duration-150 hover:bg-bg-subtle/70 hover:text-fg">
                  <MessageSquare size={12} strokeWidth={1.75} className="shrink-0 text-fg-subtle" />
                  <span className="truncate">{s.title || "Chat"}</span>
                </button>
              ))}
            </div>
            {email && (
              <div className="border-t border-border p-2">
                <UserMenu userTier={userTier} />
              </div>
            )}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex items-center justify-between bg-bg/70 px-5 py-3 backdrop-blur-xl">
          <div className="flex items-center gap-2">
            <BrandMark data-testid="header-logo" />
            <button
              type="button"
              onClick={() => setMobileOpen(true)}
              aria-label="Buka menu"
              aria-expanded={mobileOpen}
              className="flex h-11 w-11 items-center justify-center rounded-md text-fg-muted transition hover:bg-bg-subtle hover:text-fg md:hidden"
            >
              <Menu className="h-5 w-5" strokeWidth={1.75} />
            </button>
            {/* FASE 5: judul aplikasi = <h1> halaman. Sebelumnya <span>, sehingga
                axe `page-has-heading-one` (best-practice) merah di /, /chat, dan
                /builder: pembaca layar tidak punya penanda awal struktur. */}
            <h1 className="sr-only">Katalir</h1>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <Link href="/" className="flex h-9 items-center gap-2 rounded-md border border-border bg-surface px-3 text-subhead font-medium text-fg transition duration-200 hover:bg-bg-subtle">
              <MessageSquare className="h-4 w-4" strokeWidth={1.75} /> {t("nav.chat")}
            </Link>
            <Link href="/builder" className="flex h-9 items-center gap-2 rounded-md border border-border bg-surface px-3 text-subhead font-medium text-fg transition duration-200 hover:bg-bg-subtle">
              <Workflow className="h-4 w-4" strokeWidth={1.75} /> {t("nav.builder")}
            </Link>
            {email && (
              <Button variant="secondary" size="md" onClick={() => setVaultOpen(true)}>
                <KeyRound className="h-4 w-4" strokeWidth={1.75} /> {t("nav.vault")}
              </Button>
            )}
            {email ? <UserMenu userTier={userTier} compact /> : (
              <Button variant="secondary" size="md" onClick={signInWithGoogle}>
                <LogIn className="h-4 w-4" strokeWidth={1.75} /> {t("nav.loginGoogle")}
              </Button>
            )}
          </div>
        </header>
        {/* FASE 5: `children` dibungkus landmark <main> supaya tautan
            lewati-ke-konten punya target nyata dan pembaca layar bisa melompat
            ke konten (sebelumnya halaman ini TIDAK punya landmark main sama
            sekali). `tabIndex={-1}` membuat target bisa menerima fokus saat
            tautan diklik — tanpa itu Safari/screen reader tidak berpindah.
            Kelas flex dipertahankan agar tinggi kanvas/chat tidak berubah. */}
        <main id="main-content" tabIndex={-1} className="flex min-h-0 flex-1 flex-col outline-none">
          {children}
        </main>
        {/* FASE 1: command palette global (Cmd/Ctrl+K). onNewWorkflow opsional:
            di /builder meneruskan aksi workflow baru, di halaman lain fallback
            navigasi ke /builder. */}
        <CommandPalette
          onNewChat={onNewChat}
          onNewWorkflow={onNewWorkflow ?? (() => { window.location.href = "/builder"; })}
        />
        {email && <VaultModal open={vaultOpen} email={email} onClose={() => setVaultOpen(false)} />}
        {/* Confirm delete — sibling Dialog (bukan child DropdownMenu) agar tidak
            kena bug "page stuck setelah dialog dari menu" (@btcv/auth-provider). */}
        <Dialog.Root open={deleteTarget !== null} onOpenChange={(o) => { if (!o) setDeleteTarget(null); }} modal={false}>
          <Dialog.Portal>
            <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
            <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[92vw] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-md border border-border bg-surface p-5 shadow-xl">
              <Dialog.Title className="text-callout font-bold text-fg">Hapus percakapan?</Dialog.Title>
              <Dialog.Description className="mt-1.5 text-footnote text-fg-muted">
                Percakapan ini beserta isinya akan dihapus permanen. Tindakan ini tidak bisa dibatalkan.
              </Dialog.Description>
              <div className="mt-4 flex justify-end gap-2">
                <Dialog.Close asChild>
                  <button type="button" className="rounded-md px-3 py-1.5 text-subhead font-medium text-fg-muted transition hover:bg-bg-subtle hover:text-fg">
                    Batal
                  </button>
                </Dialog.Close>
                <button
                  type="button"
                  onClick={() => {
                    const id = deleteTarget;
                    setDeleteTarget(null);
                    if (id && onDeleteSession) onDeleteSession(id);
                  }}
                  className="rounded-md bg-red-600 px-3 py-1.5 text-subhead font-medium text-white transition hover:bg-red-700"
                >
                  Hapus
                </button>
              </div>
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      </div>
    </div>
  );
}
