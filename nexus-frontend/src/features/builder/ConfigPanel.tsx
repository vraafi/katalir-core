"use client";

import { useState } from "react";
import { motion } from "motion/react";
import { Check, Copy, Loader2 } from "lucide-react";
import dynamic from "next/dynamic";
import { META, type FlowNode } from "./types";
import { cssKind, describeCron } from "./nodes/CanvasNode";
import { useMcpTools } from "./useMcpTools";
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

  // Katalog tool MCP hanya diambil untuk node mcp (node trigger/agent tidak
  // butuh), dan di-cache di modul supaya berpindah node tidak memicu fetch
  // 13 detik lagi.
  const { tools: gatewayTools, state: toolsState, reload: reloadTools } = useMcpTools(kind === "mcp");
  const knownToolNames = new Set<string>([
    "web_search",
    "http_request",
    ...gatewayTools.map((t) => t.name),
  ]);
  const isGatewayTool = Boolean(cfg.tool) && gatewayTools.some((t) => t.name === cfg.tool);

  /**
   * Pilih tool: set `tool`, lalu tentukan JALUR EKSEKUSINYA lewat `provider`.
   *
   * Ini bagian yang membuat pilihan user benar-benar berjalan: node mcp dengan
   * provider `gateway` dirutekan ke jembatan katalog MCP
   * (`provider_registry`), sedangkan tool bawaan tetap di jalur lama.
   * `provider: ""` aman — pembaca config memperlakukan string kosong sebagai
   * "tidak disebut", sama seperti key yang tidak ada.
   */
  function onPickTool(name: string) {
    setNodeCfg("tool", name);
    setNodeCfg("provider", gatewayTools.some((t) => t.name === name) ? "gateway" : "");
  }

  /**
   * Parameter ditulis ke DUA key — dan itu disengaja:
   *  - `arguments` dibaca jembatan gateway (dict ATAU JSON string; teks biasa
   *    diperlakukan sebagai {"message": teks}),
   *  - `tool_param` dibaca jalur tool bawaan (`execution_engine._exec_mcp`).
   *
   * Sebelumnya field ini hanya menulis `param`, yang **tidak dibaca siapa pun**
   * (bug pra-eksisting: user mengetik parameter, eksekusi mengabaikannya).
   */
  function setParam(v: string) {
    setNodeCfg("arguments", v);
    setNodeCfg("tool_param", v);
  }

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
          style={{ background: `var(--node-${cssKind(kind)}-color)` }}
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

      {kind === "cron_trigger" && (
        <>
          <label className="block">
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              Ekspresi Cron
            </span>
            <input
              className={FIELD_CLS}
              style={FIELD_STYLE}
              placeholder="Misal: 0 22 * * *"
              value={cfg.cron ?? ""}
              onChange={(e) => setNodeCfg("cron", e.target.value)}
            />
            <span className={HINT_CLS} style={HINT_STYLE}>
              Format 5-field: menit jam tanggal bulan hari. Contoh
              <code> 0 22 * * * </code> = setiap hari pukul 22:00.
            </span>
          </label>
          <label className="block">
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              Timezone
            </span>
            <input
              className={FIELD_CLS}
              style={FIELD_STYLE}
              placeholder="Asia/Jakarta"
              value={cfg.timezone ?? ""}
              onChange={(e) => setNodeCfg("timezone", e.target.value)}
            />
            <span className={HINT_CLS} style={HINT_STYLE}>
              Nama IANA (mis. Asia/Jakarta, UTC, America/New_York). Bukan &quot;WIB&quot;.
            </span>
          </label>
          <div className={BOX_CLS} style={BOX_STYLE}>
            <div className="mb-2 text-[11px] font-bold uppercase tracking-wide" style={LABEL_STYLE}>
              Pratinjau
            </div>
            <div className="text-[12px]" style={{ color: "var(--canvas-text-primary)" }}>
              {describeCron(cfg.cron ?? "")}
              {cfg.timezone ? ` · ${cfg.timezone}` : " · Asia/Jakarta"}
            </div>
            <span className={HINT_CLS} style={HINT_STYLE}>
              Jadwal disimpan di server; aktif setelah workflow disimpan.
            </span>
          </div>
        </>
      )}

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

      {kind === "code" && (
        <>
          <label className="block">
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              Bahasa
            </span>
            <select
              className={FIELD_CLS}
              style={FIELD_STYLE}
              value={cfg.language ?? "python"}
              onChange={(e) => setNodeCfg("language", e.target.value)}
              data-testid="code-language"
            >
              <option value="python">Python 3</option>
              <option value="javascript">JavaScript (Node)</option>
            </select>
            <span className={HINT_CLS} style={HINT_STYLE}>
              Keduanya berjalan di sandbox terpisah, bukan di server aplikasi.
            </span>
          </label>

          <label className="block">
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              Kode
            </span>
            <div className="mt-1">
              <ExpressionEditor
                value={cfg.code ?? ""}
                placeholder={
                  (cfg.language ?? "python") === "javascript"
                    ? "// Tetapkan `result` untuk mengembalikan nilai\nresult = input_data.input.nilai * 2;"
                    : "# Tetapkan `result` untuk mengembalikan nilai\nresult = input_data[\"input\"][\"nilai\"] * 2"
                }
                minHeight="168px"
                lineNumbers
                // `{{...}}` TIDAK disubstitusi di dalam kode — lihat komentar
                // di ExpressionEditor. Menawarkan variabel workflow di sini
                // akan menghasilkan kode yang tidak pernah terisi.
                suggestions={null}
                onChange={(v) => setNodeCfg("code", v)}
              />
            </div>
            <span className={HINT_CLS} style={HINT_STYLE}>
              Data dari node sebelumnya tersedia sebagai variabel{" "}
              <code>input_data</code>. Tetapkan <code>result</code> untuk
              mengembalikan nilai; <code>print()</code>/<code>console.log()</code>{" "}
              masuk ke stdout.
            </span>
          </label>

          <label className="block">
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              Batas waktu (detik)
            </span>
            <input
              type="number"
              min={1}
              max={30}
              className={FIELD_CLS}
              style={FIELD_STYLE}
              value={cfg.timeout_s ?? "30"}
              onChange={(e) => setNodeCfg("timeout_s", e.target.value)}
              data-testid="code-timeout"
            />
            <span className={HINT_CLS} style={HINT_STYLE}>
              Maksimum 30 detik. Kode yang melewatinya dihentikan paksa.
            </span>
          </label>

          <div className={BOX_CLS} style={BOX_STYLE}>
            <div className="mb-2 text-[11px] font-bold uppercase tracking-wide" style={LABEL_STYLE}>
              Batas sandbox
            </div>
            <ul
              className="flex flex-col gap-1 text-[11px] leading-snug"
              style={{ color: "var(--canvas-text-primary)" }}
            >
              <li>• Tanpa <code>import</code> — <code>import os</code> ditolak sebelum kode berjalan.</li>
              <li>• Tanpa jaringan, tanpa akses filesystem.</li>
              <li>• Memori 128 MB, keluaran dipotong 64 KB.</li>
            </ul>
            <span className={HINT_CLS} style={HINT_STYLE}>
              Kode yang gagal TIDAK diulang otomatis: perbaiki kodenya lalu
              jalankan ulang.
            </span>
          </div>
        </>
      )}

      {kind === "mcp" && (
        <div className="flex flex-col gap-3">
          <label className="block">
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              Nama Tool (MCP)
            </span>
            {toolsState === "loading" ? (
              <p
                className="mt-1 flex items-center gap-2 text-[11px]"
                style={LABEL_STYLE}
                data-testid="mcp-tools-loading"
                role="status"
                aria-live="polite"
              >
                <Loader2 size={12} className="animate-spin" aria-hidden />
                Memuat katalog tool MCP…
              </p>
            ) : toolsState === "error" ? (
              <div
                className="mt-1 rounded-md border p-2 text-[11px] leading-snug"
                style={{
                  borderColor: "var(--node-warning-color, #f59e0b)",
                  color: "var(--node-warning-color, #f59e0b)",
                }}
                data-testid="mcp-tools-error"
                role="alert"
              >
                Gagal memuat tools. Coba refresh.
                <button
                  type="button"
                  onClick={() => { void reloadTools(); }}
                  className="ml-2 rounded border px-2 py-0.5 text-[11px] font-semibold"
                  style={{ borderColor: "var(--node-warning-color, #f59e0b)" }}
                  data-testid="mcp-tools-retry"
                >
                  Muat ulang
                </button>
              </div>
            ) : (
              <select
                className={FIELD_CLS}
                style={FIELD_STYLE}
                value={cfg.tool ?? ""}
                onChange={(e) => onPickTool(e.target.value)}
                data-testid="mcp-tool-select"
                data-gateway-tools={gatewayTools.length}
              >
                <option value="">-- Pilih tool --</option>
                {/* Tool bawaan mesin (tanpa provider): tetap ada supaya workflow
                    lama yang memakainya tidak kehilangan pilihannya. */}
                <optgroup label="Bawaan (tanpa gateway)">
                  <option value="web_search">web_search</option>
                  <option value="http_request">http_request</option>
                </optgroup>
                {gatewayTools.length > 0 && (
                  <optgroup label={`Katalog MCP gateway (${gatewayTools.length})`}>
                    {gatewayTools.map((t) => (
                      <option key={t.name} value={t.name} data-tool-source="gateway">
                        {t.name}
                      </option>
                    ))}
                  </optgroup>
                )}
                {/* Pilihan tersimpan yang tidak ada di katalog (mis. gateway
                    sedang tidak dapat dijangkau) tetap ditampilkan, jangan
                    sampai config user diam-diam hilang. */}
                {cfg.tool && !knownToolNames.has(cfg.tool) && (
                  <option value={cfg.tool}>{cfg.tool} (tidak di katalog)</option>
                )}
              </select>
            )}
            <span className={HINT_CLS} style={HINT_STYLE}>
              {isGatewayTool
                ? `Dijalankan lewat gateway MCP (provider=gateway, ${gatewayTools.length} tool tersedia).`
                : "Tool bawaan dijalankan langsung oleh mesin Katalir."}
            </span>
          </label>
          <label className="block">
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              Parameter
            </span>
            <div className="mt-1">
              <ExpressionEditor
                value={cfg.arguments ?? cfg.param ?? ""}
                placeholder="JSON argumen (mis. {&quot;message&quot;: &quot;halo&quot;}) atau teks biasa... ketik {{ untuk variabel"
                minHeight="80px"
                onChange={(v) => setParam(v)}
              />
            </div>
          </label>
        </div>
      )}

      {kind === "guardrails" && (
        <>
          <label className="block">
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              Operasi
            </span>
            <select
              className={FIELD_CLS}
              style={FIELD_STYLE}
              value={cfg.operation ?? "check"}
              onChange={(e) => setNodeCfg("operation", e.target.value)}
              data-testid="guardrails-operation"
            >
              <option value="check">Check Text for Violations (blokir bila melanggar)</option>
              <option value="sanitize">Sanitize Text (ganti pelanggaran dengan placeholder)</option>
            </select>
          </label>

          <label className="block">
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              Aksi default
            </span>
            <select
              className={FIELD_CLS}
              style={FIELD_STYLE}
              value={cfg.guardrail_action ?? "block"}
              onChange={(e) => setNodeCfg("guardrail_action", e.target.value)}
              data-testid="guardrails-action"
            >
              <option value="block">Block (gagalkan node)</option>
              <option value="warn">Warn (lanjut dengan peringatan)</option>
              <option value="log">Log (catat saja)</option>
            </select>
          </label>

          <label className="block">
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              Ambang (0.0 – 1.0)
            </span>
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              className={FIELD_CLS}
              style={FIELD_STYLE}
              value={cfg.guardrail_threshold ?? "0.5"}
              onChange={(e) => setNodeCfg("guardrail_threshold", e.target.value)}
              data-testid="guardrails-threshold"
            />
            <span className={HINT_CLS} style={HINT_STYLE}>
              Berlaku untuk guardrail berbasis model (jailbreak, NSFW, topical, custom).
            </span>
          </label>

          <div className={BOX_CLS} style={BOX_STYLE}>
            <div className="mb-2 text-[11px] font-bold uppercase tracking-wide" style={LABEL_STYLE}>
              9 Tipe Guardrail (paritas n8n)
            </div>
            <div className="grid grid-cols-2 gap-1.5">
              {[
                "keywords", "jailbreak", "nsfw", "pii", "secret_keys",
                "topical_alignment", "urls", "custom", "custom_regex",
              ].map((t) => {
                let items: Array<{ type?: string }> = [];
                try {
                  const parsed = JSON.parse(cfg.guardrails_json || "[]");
                  items = Array.isArray(parsed) ? parsed : [];
                } catch {
                  items = [];
                }
                const on = items.some((i) => i.type === t);
                return (
                  <label
                    key={t}
                    className="flex cursor-pointer items-center gap-1.5 text-[11px]"
                    style={{ color: "var(--canvas-text-primary)" }}
                  >
                    <input
                      type="checkbox"
                      checked={on}
                      data-testid={`guardrail-type-${t}`}
                      onChange={() => {
                        const next = on
                          ? items.filter((i) => i.type !== t)
                          : [...items, {
                              type: t,
                              action: cfg.guardrail_action || "block",
                              threshold: Number(cfg.guardrail_threshold ?? 0.5),
                            }];
                        setNodeCfg("guardrails_json", JSON.stringify(next));
                      }}
                    />
                    {t}
                  </label>
                );
              })}
            </div>
          </div>

          <label className="block">
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              Teks yang diperiksa (opsional)
            </span>
            <div className="mt-1">
              <ExpressionEditor
                value={cfg.text ?? ""}
                placeholder="Kosongkan untuk memakai teks dari node sebelumnya... ketik {{ untuk variabel"
                minHeight="72px"
                onChange={(v) => setNodeCfg("text", v)}
              />
            </div>
          </label>

          <label className="block">
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              Konfigurasi lanjutan (JSON)
            </span>
            <div className="mt-1">
              <ExpressionEditor
                value={cfg.guardrails_json ?? "[]"}
                placeholder='[{"type":"pii","action":"block"},{"type":"keywords","keywords":"rahasia"}]'
                minHeight="96px"
                suggestions={null}
                onChange={(v) => setNodeCfg("guardrails_json", v)}
              />
            </div>
            <span className={HINT_CLS} style={HINT_STYLE}>
              Field per-tipe: <code>keywords</code>, <code>entities</code>,{" "}
              <code>permissiveness</code>, <code>patterns</code>,{" "}
              <code>block_all_urls_except</code>, <code>prompt</code>,{" "}
              <code>threshold</code>, <code>action</code>.
            </span>
          </label>
        </>
      )}

      {kind === "vector_store" && (
        <>
          <label className="block">
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              Operasi
            </span>
            <select
              className={FIELD_CLS}
              style={FIELD_STYLE}
              value={cfg.operation ?? "insert"}
              onChange={(e) => setNodeCfg("operation", e.target.value)}
              data-testid="vector-operation"
            >
              <option value="insert">Insert (chunk → embed → simpan)</option>
              <option value="query">Query (cari dokumen relevan)</option>
              <option value="delete">Delete (hapus dokumen)</option>
            </select>
          </label>

          <label className="block">
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              Koleksi
            </span>
            <input
              className={FIELD_CLS}
              style={FIELD_STYLE}
              value={cfg.collection ?? "default"}
              onChange={(e) => setNodeCfg("collection", e.target.value)}
              data-testid="vector-collection"
            />
          </label>

          {(cfg.operation ?? "insert") === "insert" && (
            <>
              <label className="block">
                <span style={LABEL_STYLE} className={LABEL_CLS}>
                  Dokumen
                </span>
                <div className="mt-1">
                  <ExpressionEditor
                    value={cfg.document ?? ""}
                    placeholder="Teks dokumen... ketik {{ untuk variabel dari node sebelumnya"
                    minHeight="120px"
                    onChange={(v) => setNodeCfg("document", v)}
                  />
                </div>
              </label>
              <div className="grid grid-cols-2 gap-2">
                <label className="block">
                  <span style={LABEL_STYLE} className={LABEL_CLS}>
                    Ukuran chunk
                  </span>
                  <input
                    type="number" min={1}
                    className={FIELD_CLS} style={FIELD_STYLE}
                    value={cfg.chunk_size ?? "800"}
                    onChange={(e) => setNodeCfg("chunk_size", e.target.value)}
                    data-testid="vector-chunk-size"
                  />
                </label>
                <label className="block">
                  <span style={LABEL_STYLE} className={LABEL_CLS}>
                    Tumpang-tindih
                  </span>
                  <input
                    type="number" min={0}
                    className={FIELD_CLS} style={FIELD_STYLE}
                    value={cfg.chunk_overlap ?? "100"}
                    onChange={(e) => setNodeCfg("chunk_overlap", e.target.value)}
                  />
                </label>
              </div>
            </>
          )}

          {(cfg.operation === "query" || cfg.operation === "delete") && (
            <label className="block">
              <span style={LABEL_STYLE} className={LABEL_CLS}>
                {cfg.operation === "delete" ? "ID dokumen" : "Kueri"}
              </span>
              <div className="mt-1">
                <ExpressionEditor
                  value={cfg.query ?? ""}
                  placeholder="Tulis pertanyaan... ketik {{ untuk variabel"
                  minHeight="80px"
                  onChange={(v) => setNodeCfg("query", v)}
                />
              </div>
            </label>
          )}

          {cfg.operation === "query" && (
            <>
              <div className="grid grid-cols-2 gap-2">
                <label className="block">
                  <span style={LABEL_STYLE} className={LABEL_CLS}>
                    Top-K
                  </span>
                  <input
                    type="number" min={1} max={50}
                    className={FIELD_CLS} style={FIELD_STYLE}
                    value={cfg.top_k ?? "5"}
                    onChange={(e) => setNodeCfg("top_k", e.target.value)}
                    data-testid="vector-topk"
                  />
                </label>
                <label className="block">
                  <span style={LABEL_STYLE} className={LABEL_CLS}>
                    Mode pencarian
                  </span>
                  <select
                    className={FIELD_CLS} style={FIELD_STYLE}
                    value={cfg.search_mode ?? "hybrid"}
                    onChange={(e) => setNodeCfg("search_mode", e.target.value)}
                    data-testid="vector-search-mode"
                  >
                    <option value="hybrid">Hybrid (vektor + kata kunci)</option>
                    <option value="vector">Vektor (semantik)</option>
                    <option value="keyword">Kata kunci (BM25)</option>
                  </select>
                </label>
              </div>
              <label className="block">
                <span style={LABEL_STYLE} className={LABEL_CLS}>
                  Bobot hybrid α (0=keyword, 1=vektor)
                </span>
                <input
                  type="number" min={0} max={1} step={0.1}
                  className={FIELD_CLS} style={FIELD_STYLE}
                  value={cfg.alpha ?? "0.5"}
                  onChange={(e) => setNodeCfg("alpha", e.target.value)}
                />
              </label>
            </>
          )}
          <span className={HINT_CLS} style={HINT_STYLE}>
            Penyimpanan: Supabase pgvector, embedding Gemini 1536-dim. Tenant
            dipisah otomatis per user.
          </span>
        </>
      )}

      {kind === "wait_for_human" && (
        <>
          <label className="block">
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              Kanal notifikasi
            </span>
            <select
              className={FIELD_CLS} style={FIELD_STYLE}
              value={cfg.channel ?? "chat"}
              onChange={(e) => setNodeCfg("channel", e.target.value)}
              data-testid="hitl-channel"
            >
              <option value="chat">Chat (kartu di percakapan)</option>
              <option value="slack">Slack</option>
              <option value="email">Email</option>
              <option value="telegram">Telegram</option>
              <option value="webhook">Webhook (resume via HTTP)</option>
            </select>
          </label>

          <label className="block">
            <span style={LABEL_STYLE} className={LABEL_CLS}>
              Pesan persetujuan
            </span>
            <div className="mt-1">
              <ExpressionEditor
                value={cfg.message ?? ""}
                placeholder="Setujui pengiriman 1.000 email pemasaran?"
                minHeight="72px"
                onChange={(v) => setNodeCfg("message", v)}
              />
            </div>
          </label>

          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span style={LABEL_STYLE} className={LABEL_CLS}>
                Batas waktu (detik)
              </span>
              <input
                type="number" min={0}
                className={FIELD_CLS} style={FIELD_STYLE}
                value={cfg.timeout_s ?? "3600"}
                onChange={(e) => setNodeCfg("timeout_s", e.target.value)}
                data-testid="hitl-timeout"
              />
            </label>
            <label className="block">
              <span style={LABEL_STYLE} className={LABEL_CLS}>
                Saat timeout
              </span>
              <select
                className={FIELD_CLS} style={FIELD_STYLE}
                value={cfg.on_timeout ?? "resume"}
                onChange={(e) => setNodeCfg("on_timeout", e.target.value)}
                data-testid="hitl-on-timeout"
              >
                <option value="resume">Lanjut (default action)</option>
                <option value="reject">Hentikan workflow</option>
              </select>
            </label>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span style={LABEL_STYLE} className={LABEL_CLS}>
                Mode approver
              </span>
              <select
                className={FIELD_CLS} style={FIELD_STYLE}
                value={cfg.approval_mode ?? "any"}
                onChange={(e) => setNodeCfg("approval_mode", e.target.value)}
              >
                <option value="any">Cukup satu</option>
                <option value="all">Semua harus setuju</option>
              </select>
            </label>
            <label className="block">
              <span style={LABEL_STYLE} className={LABEL_CLS}>
                Approver (koma)
              </span>
              <input
                className={FIELD_CLS} style={FIELD_STYLE}
                value={cfg.approvers ?? ""}
                placeholder="a@x.com, b@x.com"
                onChange={(e) => setNodeCfg("approvers", e.target.value)}
              />
            </label>
          </div>
          <span className={HINT_CLS} style={HINT_STYLE}>
            Workflow dijeda; user menyetujui lewat kartu di chat atau tautan
            resume, lalu alur lanjut. Timeout memakai aksi default.
          </span>
        </>
      )}
    </motion.div>
  );
}

