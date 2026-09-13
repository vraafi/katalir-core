"use client";

import { Plus, Bot, LogIn, LogOut, MessageSquare, Workflow, KeyRound, MoreHorizontal, Trash2 } from "lucide-react";
import Link from "next/link";
import { useAuth } from "@/context/auth";
import VaultModal from "@/components/VaultModal";
import ThemeToggle from "@/components/ThemeToggle";
import { StaggerList, StaggerItem } from "@/components/motion";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import * as Dialog from "@radix-ui/react-dialog";

interface SessionItem { id: string; title?: string; }

interface ShellProps {
  children: React.ReactNode;
  sessions: SessionItem[];
  currentSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onDeleteSession?: (id: string) => void | Promise<void>;
}

export default function Shell({ children, sessions, currentSessionId, onSelectSession, onNewChat, onDeleteSession }: ShellProps) {
  const { email, loading, signInWithGoogle, signOut } = useAuth();
  const [vaultOpen, setVaultOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  // Safety net (Radix #3141 / shadcn #7575): bila dialog modal sempat
  // meninggalkan body.pointerEvents="none" (stuck — seluruh halaman tak bisa
  // diklik, termasuk tombol Chat Baru), bersihkan pada unmount. Dialog sudah
  // dipaksa modal={false} (root cause dihilangkan); ini hanya jaring pengaman.
  useEffect(() => {
    return () => {
      document.body.style.pointerEvents = "";
    };
  }, []);

  return (
    <div className="flex h-screen overflow-hidden bg-bg">
      <aside className="flex w-64 shrink-0 flex-col border-r border-border bg-bg-subtle">
        <Button variant="secondary" size="md" onClick={onNewChat} className="mx-3 mt-3">
          <Plus className="h-4 w-4" strokeWidth={1.75} /> Chat Baru
        </Button>
        <div className="mt-4 flex-1 overflow-y-auto px-2">
          <p className="px-2 pb-2 text-caption font-semibold uppercase tracking-wide text-fg-subtle">Riwayat Chat</p>
          {sessions.length === 0 && <p className="px-2 py-1 text-footnote text-fg-subtle">Belum ada riwayat.</p>}
          <StaggerList>
            {sessions.map((s) => {
              const active = s.id === currentSessionId;
              return (
                <StaggerItem key={s.id}>
                  <div className="group relative mb-1 flex items-center">
                    <button onClick={() => onSelectSession(s.id)}
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
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex items-center justify-between bg-bg/70 px-5 py-3 backdrop-blur-xl">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-sm bg-gradient-to-br from-accent to-brand text-accent-fg">
              <Bot className="h-4 w-4" strokeWidth={1.75} />
            </div>
            <span className="text-callout font-bold text-fg">Nexus Agent</span>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <Link href="/" className="flex h-9 items-center gap-2 rounded-md border border-border bg-surface px-3 text-subhead font-medium text-fg transition duration-200 hover:bg-bg-subtle">
              <MessageSquare className="h-4 w-4" strokeWidth={1.75} /> Chat
            </Link>
            <Link href="/builder" className="flex h-9 items-center gap-2 rounded-md border border-border bg-surface px-3 text-subhead font-medium text-fg transition duration-200 hover:bg-bg-subtle">
              <Workflow className="h-4 w-4" strokeWidth={1.75} /> Builder
            </Link>
            {email && (
              <Button variant="secondary" size="md" onClick={() => setVaultOpen(true)}>
                <KeyRound className="h-4 w-4" strokeWidth={1.75} /> Brankas
              </Button>
            )}
            {email && <span className="max-w-[180px] truncate text-subhead text-fg-muted">{email}</span>}
            {loading ? (
              <span className="text-subhead text-fg-subtle">Memuat...</span>
            ) : email ? (
              <Button variant="ghost" size="md" onClick={signOut}>
                <LogOut className="h-4 w-4" strokeWidth={1.75} /> Logout
              </Button>
            ) : (
              <Button variant="secondary" size="md" onClick={signInWithGoogle}>
                <LogIn className="h-4 w-4" strokeWidth={1.75} /> Login dengan Google
              </Button>
            )}
          </div>
        </header>
        {children}
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
