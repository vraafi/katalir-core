"use client";

import { useState } from "react";
import { motion } from "motion/react";
import { Check, Copy } from "lucide-react";
import dynamic from "next/dynamic";
import { META, type FlowNode } from "./types";
import { springPanel } from "@/components/motion";

/**
 * Panel konfigurasi node (FASE 4 — token tema).
 *
 * SEBELUMNYA panel ini memakai kelas warna Tailwind KERAS (`text-gray-100`,
 * `bg-gray-800`, …) dari era sebelum token tema. Akibatnya, di tema terang
 * (Daylight/Minimal) teks panel nyaris tak terbaca, dan FASE 3 terpaksa
 * menambal dengan pembungkus `.k-config-host` di globals.css.
 *
 * FASE 4 menghapus tambalan itu: semua warna di sini memakai token kanvas
 * (`--canvas-text-primary`, `--node-border`, …) sehingga satu sumber warna
 * untuk kanvas, kartu node, toolbar, dan panel — dan tema terang benar-benar
 * terbaca. Bukti kontras diukur di `tests/fase4-a11y.spec.ts` (WCAG AA).
 */
const ExpressionEditor = dynamic(
  () => import("@/components/ExpressionEditor"),
  {
    ssr: false,
    loading: () => (
      <p className="mt-1 text-xs" style={{ color: "var(--canvas-text-secondary)" }}>
        Memuat editor...
      </p>
    ),
  }
);

/** Kelas field: warna dari token tema, bukan palet zinc/gray. */
const FIELD_CLS =
  "mt-1 w-full rounded-md border px-2.5 py-1.5 text-[13px] outline-none focus:border-[color:var(--canvas-accent)]";
const FIELD_STYLE = {
  borderColor: "var(--node-border)",
  background: "var(--canvas-bg)",
  color: "var(--canvas-text-primary)",
} as const;

const LABEL_CLS = "text-[11px]";
const LABEL_STYLE = { color: "var(--canvas-text-secondary)" } as const;
const HINT_CLS = "mt-1 block text-[10px]";
const HINT_STYLE = { color: "var(--canvas-text-secondary)", opacity: 0.85 } as const;
const BOX_CLS = "rounded-xl border p-3";
const BOX_STYLE = { borderColor: "var(--node-border)" } as const;

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

  return (
    <motion.div
      key={node?.id ?? "config"}
      className="flex flex-col gap-4"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springPanel}
      style={{ willChange: "opacity, transform" }}
    >
      <div className="flex items-center gap-2">
        <span
          className="flex h-8 w-8 items-center justify-center rounded-lg text-white"
          style={{ background: `var(--node-${kind === "agent" ? "action" : kind}-color)` }}
        >
          <Icon size={16} strokeWidth={1.75} />
        </span>
        <div>
          <div className="text-sm font-semibold" style={{ color: "var(--canvas-text-primary)" }}>
            {data?.label || meta.label}
          </div>
          <div className="text-[10px] uppercase tracking-wide" style={LABEL_STYLE}>
            {kind}
          </div>
        </div>
      </div>

      {kind === "trigger" && (
        <>
          <label className="block">
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              Event Name
            </span>
            <input
              className={FIELD_CLS}
              style={FIELD_STYLE}
              placeholder="Misal: Saat email masuk"
              value={cfg.event ?? ""}
              onChange={(e) => setNodeCfg("event", e.target.value)}
            />
            <span className={HINT_CLS} style={HINT_STYLE}>
              Titik yang memicu alur ini, misal event dari email atau manual.
            </span>
          </label>
          <div className={BOX_CLS} style={BOX_STYLE}>
            <div className="mb-2 text-[11px] font-bold uppercase tracking-wide" style={LABEL_STYLE}>
              Webhook URL
            </div>
            {workflowId ? (
              <>
                <code
                  className="block break-all rounded p-2 font-mono text-[11px] leading-relaxed"
                  style={{
                    background: "var(--canvas-bg)",
                    color: "var(--node-success-glow)",
                  }}
                >
                  {`${apiUrl}/webhook/${workflowId}`}
                </code>
                <button
                  onClick={() => { void copyWebhook(); }}
                  className="mt-2 flex w-full items-center justify-center gap-2 rounded-md border px-3 py-1.5 text-[12px] font-semibold"
                  style={{ borderColor: "var(--node-border)", color: "var(--canvas-text-primary)" }}
                >
                  {copied ? <Check size={14} strokeWidth={2} /> : <Copy size={14} strokeWidth={1.5} />}
                  {copied ? "Tersalin ✓" : "Salin URL"}
                </button>
              </>
            ) : (
              <div
                className="rounded-md border p-2 text-[11px] leading-snug"
                style={{ borderColor: "var(--node-warning-color, #f59e0b)", color: "var(--node-warning-color, #f59e0b)" }}
              >
                ⚠️ Klik &apos;Simpan Alur&apos; terlebih dahulu di menu atas untuk men-generate URL Webhook Anda.
              </div>
            )}
          </div>
        </>
      )}

      {kind === "agent" && (
        <>
          <label className="block">
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              Custom API Key (Opsional)
            </span>
            <input
              type="password"
              className={FIELD_CLS}
              style={FIELD_STYLE}
              placeholder="sk-... (sistem acak bila kosong)"
              value={cfg.custom_api_key ?? ""}
              onChange={(e) => setNodeCfg("custom_api_key", e.target.value)}
            />
            <span className={HINT_CLS} style={HINT_STYLE}>
              Bila terisi, kunci ini dipaksa untuk semua model (BYOK). Tidak disimpan di database.
            </span>
          </label>
          <label className="block">
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              AI Model (Tier)
            </span>
            <select
              className={FIELD_CLS}
              style={FIELD_STYLE}
              value={cfg.model ?? "universal"}
              onChange={(e) => setNodeCfg("model", e.target.value)}
            >
              <option value="universal">🟢 [FREE] Universal AI (Sistem Acak)</option>
              <option value="deepseek-flash">🔵 [PLUS] DeepSeek V4 Flash</option>
              <option value="premium" disabled>🔒 [PRO/ULTRA] Model Premium (Disabled - Segera Hadir)</option>
            </select>
          </label>
          <label className="block">
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              System Prompt
            </span>
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
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              Nama Tool (MCP)
            </span>
            <select
              className={FIELD_CLS}
              style={FIELD_STYLE}
              value={cfg.tool ?? ""}
              onChange={(e) => setNodeCfg("tool", e.target.value)}
            >
              <option value="">-- Pilih tool --</option>
              <option value="web_search">web_search</option>
              <option value="http_request">http_request</option>
            </select>
          </label>
          <label className="block">
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              Parameter
            </span>
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
    </motion.div>
  );
}

