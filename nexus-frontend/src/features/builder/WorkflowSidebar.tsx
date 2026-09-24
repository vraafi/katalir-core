import { useEffect, useRef, useState } from "react";
import { Check, Pencil, Plus, Trash2, Workflow, X, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StaggerList, StaggerItem } from "@/components/motion";
import { useI18n } from "@/i18n/context";
import { type WorkflowListItem } from "./hooks/useWorkflow";

/**
 * Sidebar daftar workflow.
 *
 * Menambah dua aksi yang sebelumnya TIDAK ADA sama sekali (user tidak bisa
 * membersihkan atau menamai ulang workflow-nya sendiri):
 *  - rename inline (klik ikon pensil -> input -> Enter/cek),
 *  - hapus dengan konfirmasi (`window.confirm`) supaya tidak ada penghapusan
 *    tak sengaja; backend tetap owner-scoped.
 */
export function WorkflowSidebar({
  workflows,
  activeId,
  onSelect,
  onNew,
  onRename,
  onDelete,
}: {
  workflows: WorkflowListItem[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, name: string) => void;
  onDelete: (id: string) => void;
}) {
  // FASE 5: aside ini SEBELUMNYA tanpa nama, sehingga di /builder ada dua
  // landmark "complementary" tanpa nama (bareng sidebar Shell) -> axe
  // `landmark-unique`. Nama aksesibel membuat keduanya bisa dibedakan.
  const { t } = useI18n();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (editingId) inputRef.current?.focus();
  }, [editingId]);

  function startEdit(id: string, name: string) {
    setEditingId(id);
    setDraft(name);
  }

  function commitEdit(id: string) {
    const name = draft.trim();
    setEditingId(null);
    if (name) onRename(id, name);
  }

  return (
    <aside aria-label={t("builder.workflowListLabel")} className="flex w-60 flex-col gap-4 border-r border-gray-700 bg-zinc-900 p-3">
      <div className="text-[11px] font-bold uppercase tracking-wide text-zinc-400">Alur Kerja</div>
      <Button variant="secondary" size="sm" onClick={onNew} className="w-full justify-center">
        <Plus size={14} strokeWidth={1.75} /> Alur Baru
      </Button>
      <div className="mt-1 flex-1 overflow-y-auto" data-testid="workflow-list">
        {workflows.length === 0 && (
          <p className="text-[11px] leading-snug text-zinc-400">
            Belum ada alur. Klik &quot;+ Alur Baru&quot;.
          </p>
        )}
        <StaggerList>
          {workflows.map((w) => {
            const id = w.id ?? "";
            const active = activeId === id;
            const editing = editingId === id;
            return (
              <StaggerItem key={id}>
                <div
                  className={`mb-1 flex w-full items-center gap-1 rounded-md px-1.5 py-1 text-subhead ${
                    active ? "bg-zinc-700 text-zinc-100" : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                  }`}
                  data-testid="workflow-item"
                  data-workflow-id={id}
                >
                  <button
                    onClick={() => onSelect(id)}
                    className="flex min-w-0 flex-1 items-center gap-2 text-left"
                    aria-label={`Buka alur ${w.name || "Draft Workflow"}`}
                  >
                    <Workflow size={13} strokeWidth={1.75} className={active ? "text-zinc-200" : "text-zinc-500"} />
                    {editing ? (
                      <input
                        ref={inputRef}
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") commitEdit(id);
                          if (e.key === "Escape") setEditingId(null);
                        }}
                        onClick={(e) => e.stopPropagation()}
                        data-testid="workflow-rename-input"
                        className="min-w-0 flex-1 rounded border border-zinc-600 bg-zinc-800 px-1 py-0.5 text-[12px] text-zinc-100"
                      />
                    ) : (
                      <span className="truncate flex-1" data-testid="workflow-name">
                        {w.name || "Draft Workflow"}
                      </span>
                    )}
                  </button>
                  {active && !editing && <Zap size={11} className="text-zinc-300" />}
                  {editing ? (
                    <>
                      <button
                        onClick={() => commitEdit(id)}
                        aria-label="Simpan nama"
                        data-testid="workflow-rename-save"
                        className="rounded p-1 text-success hover:bg-zinc-700"
                      >
                        <Check size={12} strokeWidth={2} />
                      </button>
                      <button
                        onClick={() => setEditingId(null)}
                        aria-label="Batal ganti nama"
                        className="rounded p-1 text-zinc-400 hover:bg-zinc-700"
                      >
                        <X size={12} strokeWidth={2} />
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        onClick={() => startEdit(id, w.name || "Draft Workflow")}
                        aria-label="Ganti nama alur"
                        data-testid="workflow-rename"
                        className="rounded p-1 text-zinc-500 hover:bg-zinc-700 hover:text-zinc-200"
                      >
                        <Pencil size={12} strokeWidth={1.75} />
                      </button>
                      <button
                        onClick={() => {
                          const nm = w.name || "Draft Workflow";
                          if (window.confirm(`Hapus alur "${nm}"? Tindakan ini tidak bisa dibatalkan.`)) {
                            onDelete(id);
                          }
                        }}
                        aria-label="Hapus alur"
                        data-testid="workflow-delete"
                        className="rounded p-1 text-zinc-500 hover:bg-danger/30 hover:text-danger"
                      >
                        <Trash2 size={12} strokeWidth={1.75} />
                      </button>
                    </>
                  )}
                </div>
              </StaggerItem>
            );
          })}
        </StaggerList>
      </div>
    </aside>
  );
}