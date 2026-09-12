import { motion, useReducedMotion } from "motion/react";

export function renderPayload(p: any): string {
  if (p == null) return "";
  if (typeof p === "string") return p;
  try {
    const r = p.reply ?? p.instruction ?? p.result ?? p.message ?? p;
    return typeof r === "string" ? r : JSON.stringify(p).slice(0, 400);
  } catch {
    return String(p).slice(0, 400);
  }
}

export function Terminal({
  open,
  status,
  logs,
  onClose,
}: {
  open: boolean;
  status: string | null;
  logs: any[];
  onClose: () => void;
}) {
  if (!open) return null;
  const reduce = useReducedMotion();
  return (
    <motion.div
      className="fixed inset-x-0 bottom-0 z-50 border-t border-gray-700 bg-[rgb(var(--bg-subtle))] font-mono"
      initial={{ opacity: 0, y: reduce ? 0 : 32 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 300, damping: 25 }}
      style={{ willChange: "opacity, transform" }}
    >
      <div className="flex items-center justify-between border-b border-gray-800 px-4 py-2">
        <span className="text-[12px] font-bold tracking-wide text-success">
          Execution Console {status ? `— ${status}` : ""}
        </span>
        <button
          onClick={onClose}
          className="rounded-md px-2 py-1 text-[12px] text-gray-300 hover:bg-gray-700"
        >
          Close ✕
        </button>
      </div>
      <div className="max-h-64 space-y-0.5 overflow-y-auto p-4 text-[12px] leading-relaxed text-gray-200">
        {logs.length === 0 && <div className="text-gray-500">$ menunggu logs...</div>}
        {logs.map((l, i) => (
          <div key={i} className="whitespace-pre-wrap">
            <span className="text-gray-500">[{i + 1}]</span>{" "}
            <span className="text-accent">{l?.step_kind ?? "step"}</span>{" "}
            <span className="text-gray-400">{l?.node_id ?? ""}</span>{" "}
            <span className={String(l?.status) === "error" ? "text-danger" : "text-success"}>{String(l?.status ?? "")}</span>
            <span className="text-gray-200"> — {renderPayload(l?.payload)}</span>
          </div>
        ))}
      </div>
    </motion.div>
  );
}