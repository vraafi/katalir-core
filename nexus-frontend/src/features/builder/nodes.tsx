import { Handle, NodeToolbar, Position, useReactFlow } from "@xyflow/react";
import { Trash2 } from "lucide-react";
import { META, type FlowNode, type FlowNodeData, type Kind } from "./types";

export function PaletteNode(props: { id: string; data: FlowNodeData; selected?: boolean }) {
  const { deleteElements } = useReactFlow<FlowNode>();
  const id = props.id;
  const data = props.data;
  const selected = !!props.selected;
  const kind: Kind = data?.kind ?? "agent";
  const meta = META[kind];
  const Icon = meta.Icon;

  function removeNode() {
    deleteElements({ nodes: [{ id }] });
  }

  return (
    <div
      className={
        "node-card-enter w-56 rounded-xl border bg-zinc-900 text-[13px] text-zinc-100 " +
        (selected ? " border-accent ring-2 ring-accent/40 shadow-lg" : " border-zinc-700 shadow-md")
      }
    >
      <NodeToolbar>
        <button
          onClick={removeNode}
          className="flex h-7 w-7 items-center justify-center rounded-md border border-danger/60 bg-danger/20 text-danger hover:bg-danger/40"
        >
          <Trash2 size={14} strokeWidth={1.5} />
        </button>
      </NodeToolbar>

      <div className="flex h-12 items-center gap-2.5 px-3">
        {kind !== "trigger" && (
          <Handle
            type="target"
            position={Position.Left}
            className="!w-3 !h-10 !-left-1.5 !rounded-md !border-2 !border-zinc-900 cursor-crosshair transition-colors bg-success hover:bg-success"
            style={{ width: "12px", height: "40px", borderRadius: "6px" }}
          />
        )}
        <span
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg"
          style={{ background: meta.color, color: "rgb(255, 255, 255)", flexShrink: 0 }}
        >
          <Icon size={15} strokeWidth={1.75} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate font-semibold text-zinc-100">{data?.label || meta.label}</span>
          <span className="block truncate text-[10px] text-zinc-500">{meta.desc}</span>
        </span>
        <Handle
          type="source"
          position={Position.Right}
          className={
            "!w-3 !h-10 !-right-1.5 !rounded-md !border-2 !border-zinc-900 cursor-crosshair transition-colors " +
            (kind === "trigger" ? "bg-accent hover:bg-accent" : kind === "agent" ? "bg-success hover:bg-success" : "bg-warning hover:bg-warning")
          }
          style={{ width: "12px", height: "40px", borderRadius: "6px" }}
        />
      </div>
    </div>
  );
}

export const NODE_TYPES = { trigger: PaletteNode, agent: PaletteNode, mcp: PaletteNode };