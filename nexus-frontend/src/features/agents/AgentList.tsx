"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Archive,
  Bot,
  CheckCircle2,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { agentKeys } from "@/lib/query-keys";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  AgentApiError,
  createAgent,
  deleteAgent,
  listAgents,
  setAgentStatus,
} from "./api";
import type { Agent, AgentStatus } from "./types";

type Notice = { kind: "ok" | "err"; text: string };

const STATUS_META: Record<
  AgentStatus,
  { label: string; className: string; icon: typeof Bot }
> = {
  draft: {
    label: "Draf",
    className: "bg-bg-subtle text-fg-muted",
    icon: Bot,
  },
  active: {
    label: "Aktif",
    className: "bg-success/15 text-success",
    icon: Play,
  },
  paused: {
    label: "Dijeda",
    className: "bg-warning/15 text-warning",
    icon: Pause,
  },
  archived: {
    label: "Diarsip",
    className: "bg-bg-subtle text-fg-muted",
    icon: Archive,
  },
};

const FILTERS: Array<{ value: "" | AgentStatus; label: string }> = [
  { value: "", label: "Semua" },
  { value: "draft", label: "Draf" },
  { value: "active", label: "Aktif" },
  { value: "paused", label: "Dijeda" },
  { value: "archived", label: "Diarsip" },
];

/**
 * Daftar Agents — entitas kelas satu (TASK 5 / Fitur #1).
 *
 * Menampilkan siklus hidup lengkap: buat (draft) → aktifkan → jeda → arsip →
 * hapus. Setiap aksi memakai endpoint yang memvalidasi transisi di server,
 * jadi UI tidak pernah "menebak" transisi yang sah — tombol difilter oleh
 * `can_transition` yang dikirim server.
 */
export function AgentList() {
  const qc = useQueryClient();
  const [status, setStatus] = useState<"" | AgentStatus>("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [notice, setNotice] = useState<Notice | null>(null);

  const listQuery = useQuery({
    queryKey: agentKeys.list(status),
    queryFn: () => listAgents(status || undefined),
    staleTime: 15_000,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: agentKeys.all });

  const createMut = useMutation({
    mutationFn: (n: string) => createAgent({ name: n }),
    onSuccess: (a) => {
      setNotice({ kind: "ok", text: `Agent "${a.name}" dibuat sebagai draf.` });
      setName("");
      setCreating(false);
      invalidate();
    },
    onError: (err: unknown) => {
      setNotice({
        kind: "err",
        text: err instanceof AgentApiError ? err.message : "Gagal membuat agent.",
      });
    },
  });

  const statusMut = useMutation({
    mutationFn: ({ id, to }: { id: string; to: AgentStatus }) =>
      setAgentStatus(id, to),
    onSuccess: (a) => {
      setNotice({ kind: "ok", text: `Status "${a.name}" → ${STATUS_META[a.status].label}.` });
      invalidate();
    },
    onError: (err: unknown) => {
      setNotice({
        kind: "err",
        text: err instanceof AgentApiError ? err.message : "Transisi tidak diizinkan.",
      });
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteAgent(id),
    onSuccess: () => {
      setNotice({ kind: "ok", text: "Agent dihapus." });
      invalidate();
    },
    onError: (err: unknown) => {
      setNotice({
        kind: "err",
        text: err instanceof AgentApiError ? err.message : "Gagal menghapus agent.",
      });
    },
  });

  const agents = listQuery.data ?? [];

  return (
    <div className="space-y-5">
      {/* Bilah aksi */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1.5">
          {FILTERS.map((f) => (
            <button
              key={f.value || "all"}
              onClick={() => setStatus(f.value)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                status === f.value
                  ? "border-accent bg-accent text-accent-fg"
                  : "border-border text-fg-muted hover:text-fg",
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => listQuery.refetch()}
            disabled={listQuery.isFetching}
          >
            <RefreshCw className={cn("size-4", listQuery.isFetching && "animate-spin")} />
          </Button>
          <Button size="sm" onClick={() => setCreating((v) => !v)}>
            <Plus className="size-4" />
            Agent baru
          </Button>
        </div>
      </div>

      {notice && (
        <div
          className={cn(
            "flex items-center gap-2 rounded-md border px-3 py-2 text-sm",
            notice.kind === "ok"
              ? "border-success/30 bg-success/10 text-success"
              : "border-danger/40 bg-danger/10 text-danger",
          )}
        >
          {notice.kind === "ok" ? (
            <CheckCircle2 className="size-4 shrink-0" />
          ) : (
            <AlertCircle className="size-4 shrink-0" />
          )}
          <span>{notice.text}</span>
        </div>
      )}

      {creating && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) createMut.mutate(name.trim());
          }}
          className="flex items-center gap-2 rounded-lg border p-3"
        >
          <Input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Nama agent, mis. Support Bot"
            maxLength={120}
          />
          <Button type="submit" size="sm" disabled={!name.trim() || createMut.isPending}>
            {createMut.isPending ? "Menyimpan…" : "Simpan"}
          </Button>
        </form>
      )}

      {/* Isi */}
      {listQuery.isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-36 rounded-lg" />
          ))}
        </div>
      ) : listQuery.isError ? (
        <div className="rounded-lg border border-danger/40 bg-danger/10 p-4 text-sm text-danger">
          Gagal memuat agent. Coba lagi.
        </div>
      ) : agents.length === 0 ? (
        <div className="rounded-lg border border-dashed p-10 text-center">
          <Bot className="mx-auto size-8 text-fg-muted" />
          <p className="mt-3 text-sm text-fg-muted">
            Belum ada agent. Buat satu untuk mulai.
          </p>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {agents.map((a) => (
            <AgentCard
              key={a.id}
              agent={a}
              onStatus={(to) => statusMut.mutate({ id: a.id, to })}
              onDelete={() => deleteMut.mutate(a.id)}
              busy={statusMut.isPending || deleteMut.isPending}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function AgentCard({
  agent,
  onStatus,
  onDelete,
  busy,
}: {
  agent: Agent;
  onStatus: (to: AgentStatus) => void;
  onDelete: () => void;
  busy: boolean;
}) {
  const meta = STATUS_META[agent.status];
  const Icon = meta.icon;
  const can = new Set(agent.can_transition ?? []);
  const channels = agent.channels ?? [];

  return (
    <div className="flex flex-col rounded-lg border p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold">{agent.name}</h3>
          <p className="mt-0.5 truncate text-xs text-fg-muted">
            {agent.model || "model bawaan"}
            {agent.memory_enabled ? " · memori aktif" : ""}
          </p>
        </div>
        <span
          className={cn(
            "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
            meta.className,
          )}
        >
          <Icon className="size-3" />
          {meta.label}
        </span>
      </div>

      <div className="mt-3 flex flex-wrap gap-1">
        {channels.length === 0 ? (
          <span className="text-[11px] text-fg-muted">tanpa kanal</span>
        ) : (
          channels.map((c, i) => (
            <span
              key={`${c.type}-${i}`}
              className="rounded border px-1.5 py-0.5 text-[11px] text-fg-muted"
            >
              {c.type}
            </span>
          ))
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t pt-3">
        {can.has("active") && (
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => onStatus("active")}>
            <Play className="size-3.5" />
            Aktifkan
          </Button>
        )}
        {can.has("paused") && (
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => onStatus("paused")}>
            <Pause className="size-3.5" />
            Jeda
          </Button>
        )}
        {can.has("archived") && (
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => onStatus("archived")}>
            <Archive className="size-3.5" />
            Arsipkan
          </Button>
        )}
        {agent.status !== "active" && (
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            className="ml-auto text-danger hover:text-danger"
            onClick={onDelete}
          >
            <Trash2 className="size-3.5" />
          </Button>
        )}
      </div>
    </div>
  );
}
