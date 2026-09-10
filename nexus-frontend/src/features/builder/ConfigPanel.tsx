import { useState } from "react";
import { Copy, Check } from "lucide-react";
import dynamic from "next/dynamic";
import { META, type FlowNode } from "./types";

const ExpressionEditor = dynamic(
  () => import("@/components/ExpressionEditor"),
  { ssr: false, loading: () => <p className="mt-1 text-xs text-gray-500">Memuat editor...</p> }
);

export function ConfigPanel({
  node,
  setNodeCfg,
  apiUrl,
  workflowId,
}: {
  node: FlowNode;
  setNodeCfg: (key: string, value: string) => void;
  apiUrl: string;
  workflowId: string | null;
}) {
  const data = node.data;
  const kind = data?.kind ?? "agent";
  const meta = META[kind];
  const Icon = meta.Icon;
  const cfg = data?.config ?? {};
  const [copied, setCopied] = useState(false);

  async function copyWebhook() {
    if (!workflowId) return;
    const url = `${apiUrl}/webhook/${workflowId}`;
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = url;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const fieldCls =
    "nodrag mt-1 w-full rounded-md border border-gray-600 bg-gray-800 px-2.5 py-1.5 text-[13px] text-gray-100 outline-none focus:border-accent nodrag";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg" style={{ background: meta.color, color: "rgb(var(--accent-fg))" }}>
          <Icon size={16} strokeWidth={1.75} />
        </span>
        <div>
          <div className="text-sm font-semibold text-gray-100">{data?.label || meta.label}</div>
          <div className="text-[10px] uppercase tracking-wide text-zinc-500">{kind}</div>
        </div>
      </div>
      {kind === "trigger" && (
        <>
        <label className="block">
          <span className="text-[11px] text-zinc-400">Event Name</span>
          <input
            className={fieldCls}
            placeholder="Misal: Saat email masuk"
            value={cfg.event ?? ""}
            onChange={(e) => setNodeCfg("event", e.target.value)}
          />
          <span className="mt-1 block text-[10px] text-zinc-500">
            Titik yang memicu alur ini, misal event dari email atau manual.
          </span>
        </label>
        <div className="rounded-xl border border-gray-700 bg-gray-800/60 p-3">
          <div className="mb-2 text-[11px] font-bold uppercase tracking-wide text-zinc-400">
            Webhook URL
          </div>
          {workflowId ? (
            <>
              <code className="block break-all rounded bg-black/50 p-2 font-mono text-[11px] leading-relaxed text-success">
                {`${apiUrl}/webhook/${workflowId}`}
              </code>
              <button
                onClick={() => { void copyWebhook(); }}
                className="mt-2 flex w-full items-center justify-center gap-2 rounded-md border border-gray-600 bg-gray-800 px-3 py-1.5 text-[12px] font-semibold text-gray-100 hover:bg-gray-700"
              >
                {copied ? <Check size={14} strokeWidth={2} /> : <Copy size={14} strokeWidth={1.5} />}
                {copied ? "Tersalin ✓" : "Salin URL"}
              </button>
            </>
          ) : (
            <div className="rounded-md border border-warning/50 bg-warning/10 p-2 text-[11px] leading-snug text-warning">
              ⚠️ Klik 'Simpan Alur' terlebih dahulu di menu atas untuk men-generate URL Webhook Anda.
            </div>
          )}
        </div>
        </>
      )}

      {kind === "agent" && (
        <>
        <label className="block">
          <span className="text-[11px] text-zinc-400">Custom API Key (Opsional)</span>
          <input
            type="password"
            className={fieldCls}
            placeholder="sk-... (sistem acak bila kosong)"
            value={cfg.custom_api_key ?? ""}
            onChange={(e) => setNodeCfg("custom_api_key", e.target.value)}
          />
          <span className="mt-1 block text-[10px] text-zinc-500">
            Bila terisi, kunci ini dipaksa untuk semua model (BYOK). Tidak disimpan di database.
          </span>
        </label>
        <label className="block">
          <span className="text-[11px] text-zinc-400">AI Model (Tier)</span>
          <select
            className={fieldCls}
            value={cfg.model ?? "universal"}
            onChange={(e) => setNodeCfg("model", e.target.value)}
          >
            <option value="universal">🟢 [FREE] Universal AI (Sistem Acak)</option>
            <option value="deepseek-flash">🔵 [PLUS] DeepSeek V4 Flash</option>
            <option value="premium" disabled>🔒 [PRO/ULTRA] Model Premium (Disabled - Segera Hadir)</option>
          </select>
        </label>
        <label className="block">
          <span className="text-[11px] text-zinc-400">System Prompt</span>
          <div className="mt-1">
            <ExpressionEditor
              value={cfg.prompt ?? ""}
              placeholder="Instruksi agent (system prompt)... ketik {{ untuk variabel"
              minHeight="112px"
              onChange={(v) => setNodeCfg("prompt", v)}
            />
          </div>
        </label>
        </>
      )}

      {kind === "mcp" && (
        <div className="flex flex-col gap-3">
          <label className="block">
            <span className="text-[11px] text-zinc-400">Nama Tool (MCP)</span>
            <select
              className={fieldCls}
              value={cfg.tool ?? ""}
              onChange={(e) => setNodeCfg("tool", e.target.value)}
            >
              <option value="">-- Pilih tool --</option>
              <option value="web_search">web_search</option>
              <option value="http_request">http_request</option>
            </select>
          </label>
          <label className="block">
            <span className="text-[11px] text-zinc-400">Parameter</span>
            <div className="mt-1">
              <ExpressionEditor
                value={cfg.param ?? ""}
                placeholder="Query / JSON parameter... ketik {{ untuk variabel"
                minHeight="80px"
                onChange={(v) => setNodeCfg("param", v)}
              />
            </div>
          </label>
        </div>
      )}
    </div>
  );
}
