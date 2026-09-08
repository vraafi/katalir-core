"use client";

import { Plus, Bot, LogIn, LogOut, MessageSquare, Workflow } from "lucide-react";
import Link from "next/link";
import { useAuth } from "@/context/auth";

interface SessionItem {
  id: string;
  title?: string;
}

interface ShellProps {
  children: React.ReactNode;
  sessions: SessionItem[];
  currentSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
}

export default function Shell({
  children,
  sessions,
  currentSessionId,
  onSelectSession,
  onNewChat,
}: ShellProps) {
  const { email, loading, signInWithGoogle, signOut } = useAuth();

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      {/* Sidebar kiri — riwayat obrolan */}
      <aside className="flex w-64 shrink-0 flex-col border-r border-gray-200 bg-gray-100">
        <button
          onClick={onNewChat}
          className="mx-3 mt-3 flex items-center justify-center gap-2 rounded-xl border border-gray-300 bg-white py-2 text-sm font-semibold text-gray-800 shadow-sm transition hover:bg-gray-50"
        >
          <Plus size={16} /> Chat Baru
        </button>

        <div className="mt-4 flex-1 overflow-y-auto px-2">
          <p className="px-2 pb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
            Riwayat Chat
          </p>
          {sessions.length === 0 && (
            <p className="px-2 py-1 text-xs text-gray-400">
              Belum ada riwayat.
            </p>
          )}
          {sessions.map((s) => {
            const active = s.id === currentSessionId;
            return (
              <button
                key={s.id}
                onClick={() => onSelectSession(s.id)}
                className={`mb-1 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition ${
                  active
                    ? "bg-gray-200 font-medium text-gray-900"
                    : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
                }`}
              >
                <MessageSquare
                  size={12}
                  className={`shrink-0 ${active ? "text-gray-600" : "text-gray-400"}`}
                />
                <span className="truncate">{s.title || "Chat"}</span>
              </button>
            );
          })}
        </div>
      </aside>

      {/* Area utama: header + konten chat */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-gray-200 bg-white/80 px-5 py-3 backdrop-blur">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-brand to-blue-500 text-white">
              <Bot size={16} />
            </div>
            <span className="text-base font-bold text-gray-900">Nexus Agent</span>
          </div>

          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
            >
              <MessageSquare size={14} /> Chat
            </Link>
            <Link
              href="/builder"
              className="flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
            >
              <Workflow size={14} /> Builder
            </Link>
            {email && (
              <span className="max-w-[180px] truncate text-sm text-gray-600">
                {email}
              </span>
            )}
            {loading ? (
              <span className="text-sm text-gray-400">Memuat...</span>
            ) : email ? (
              <button
                onClick={signOut}
                className="flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
              >
                <LogOut size={14} /> Logout
              </button>
            ) : (
              <button
                onClick={signInWithGoogle}
                className="flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
              >
                <LogIn size={14} /> Login dengan Google
              </button>
            )}
          </div>
        </header>
        {children}
      </div>
    </div>
  );
}