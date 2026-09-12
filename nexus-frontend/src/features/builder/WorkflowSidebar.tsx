import { Plus, Workflow, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StaggerList, StaggerItem } from "@/components/motion";
import { type WorkflowListItem } from "./hooks/useWorkflow";

export function WorkflowSidebar({
  workflows,
  activeId,
  onSelect,
  onNew,
}: {
  workflows: WorkflowListItem[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  return (
    <aside className="flex w-60 flex-col gap-4 border-r border-gray-700 bg-zinc-900 p-3">
      <div className="text-[11px] font-bold uppercase tracking-wide text-zinc-400">Alur Kerja</div>
      <Button variant="secondary" size="sm" onClick={onNew} className="w-full justify-center">
        <Plus size={14} strokeWidth={1.75} /> Alur Baru
      </Button>
      <div className="mt-1 flex-1 overflow-y-auto">
        {workflows.length === 0 && (
          <p className="text-[11px] leading-snug text-zinc-500">
            Belum ada alur. Klik &quot;+ Alur Baru&quot;.
          </p>
        )}
        <StaggerList>
          {workflows.map((w) => {
            const active = activeId === w.id;
            return (
              <StaggerItem key={w.id}>
                <button
                  onClick={() => onSelect(w.id ?? "")}
                  className={`mb-1 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-subhead ${
                    active ? "bg-zinc-700 text-zinc-100" : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                  }`}
                >
                  <Workflow size={13} strokeWidth={1.75} className={active ? "text-zinc-200" : "text-zinc-500"} />
                  <span className="truncate flex-1">{w.name || "Draft Workflow"}</span>
                  {active && <Zap size={11} className="text-zinc-300" />}
                </button>
              </StaggerItem>
            );
          })}
        </StaggerList>
      </div>
    </aside>
  );
}