import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { META, type Kind } from "./types";

export function Palette({
  onAddNode,
  onClear,
}: {
  onAddNode: (kind: Kind) => void;
  onClear: () => void;
}) {
  return (
    <aside className="flex w-64 flex-col gap-4 border-r border-gray-700 bg-gray-900 p-4">
      <div className="text-[11px] font-bold uppercase tracking-wide text-zinc-400">Node Palette</div>
      <p className="text-[11px] leading-snug text-zinc-500">Drag a node onto the canvas, or click to place it.</p>
      {Object.keys(META).map((k) => {
        const kind: Kind = k as Kind;
        const meta = META[kind];
        const Icon = meta.Icon;
        return (
          <div
            key={kind}
            draggable
            onDragStart={(e) => {
              e.dataTransfer?.setData("application/reactflow", kind);
              if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
            }}
            onClick={() => onAddNode(kind)}
            className="flex w-full cursor-grab items-center gap-3 rounded-xl border border-gray-700 bg-gray-800 px-3 py-3 text-left transition hover:border-accent/60 hover:bg-gray-700"
          >
            <span className="flex h-8 w-8 items-center justify-center rounded-lg" style={{ background: meta.color, color: "rgb(var(--accent-fg))" }}>
              <Icon size={15} strokeWidth={1.75} />
            </span>
            <span className="flex-1 text-left">
              <span className="block text-sm font-semibold text-gray-100">{meta.label}</span>
              <span className="block text-[11px] text-zinc-500">Drag to canvas</span>
            </span>
            <Plus size={14} className="text-zinc-500" />
          </div>
        );
      })}
      <Button variant="danger" onClick={onClear} className="w-full justify-center">
        <Trash2 size={14} strokeWidth={1.5} /> Cavira alur
      </Button>
    </aside>
  );
}