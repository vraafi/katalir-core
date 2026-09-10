"use client";

import { Plus, Bot, LogIn, LogOut, MessageSquare, Workflow, KeyRound } from "lucide-react";
import Link from "next/link";
import { useAuth } from "@/context/auth";
import VaultModal from "@/components/VaultModal";
import ThemeToggle from "@/components/ThemeToggle";
import { useState } from "react";
import { Button } from "@/components/ui/button";

interface SessionItem { id: string; title?: string; }

interface ShellProps {
  children: React.ReactNode;
  sessions: SessionItem[];
  currentSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
}

export default function Shell({ children, sessions, currentSessionId, onSelectSession, onNewChat }: ShellProps) {
  const { email, loading, signInWithGoogle, signOut } = useAuth();
  const [vaultOpen, setVaultOpen] = useState(false);

  return (
    <div className="flex h-screen overflow-hidden bg-bg">
      <aside className="flex w-64 shrink-0 flex-col border-r border-border bg-bg-subtle">
        <Button variant="secondary" size="md" onClick={onNewChat} className="mx-3 mt-3">
          <Plus className="h-4 w-4" strokeWidth={1.75} /> Chat Baru
        </Button>
        <div className="mt-4 flex-1 overflow-y-auto px-2">
          <p className="px-2 pb-2 text-caption font-semibold uppercase tracking-wide text-fg-subtle">Riwayat Chat</p>
          {sessions.length === 0 && <p className="px-2 py-1 text-footnote text-fg-subtle">Belum ada riwayat.</p>}
          {sessions.map((s) => {
            const active = s.id === currentSessionId;
            return (
              <button key={s.id} onClick={() => onSelectSession(s.id)}
                className={`mb-1 flex w-full items-center gap-2 rounded-sm px-3 py-2 text-left text-subhead transition ${active ? "bg-surface font-medium text-fg shadow-xs" : "text-fg-muted hover:bg-surface/50 hover:text-fg"}`}>
                <MessageSquare size={12} strokeWidth={1.75} className={`shrink-0 ${active ? "text-fg-muted" : "text-fg-subtle"}`} />
                <span className="truncate">{s.title || "Chat"}</span>
              </button>
            );
          })}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border bg-surface/80 px-5 py-3 backdrop-blur">
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
      </div>
    </div>
  );
}
