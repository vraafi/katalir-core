// =========================================================================
// ExpressionEditor — Smart Expression Editor (CodeMirror, Enterprise 2026)
// Pengganti <textarea> di ConfigPanel. Ketik `{{` untuk dropdown variabel.
// Saran (iterasi ini): trigger.body, trigger.headers, agent.output, agent.reply.
// =========================================================================
"use client";

import CodeMirror from "@uiw/react-codemirror";
import { autocompletion, CompletionContext } from "@codemirror/autocomplete";

// Z-index tinggi agar dropdown autocomplete tidak tertutup Sidebar React Flow.
const AUTOCOMPLETE_HIGH_Z = {
  "& .cm-tooltip-autocomplete": { zIndex: "9999 !important" },
  "& .cm-tooltip": { zIndex: "9999 !important" },
} as const;

const SUGGESTIONS = [
  { label: "trigger.body", detail: "Payload body webhook" },
  { label: "trigger.headers", detail: "Headers webhook" },
  { label: "agent.output", detail: "Output node Agent" },
  { label: "agent.reply", detail: "Balasan teks Agent" },
];

function braceCompleter(context: CompletionContext) {
  const before = context.state.sliceDoc(
    Math.max(0, context.pos - 2), context.pos);
  if (before !== "{{") return null;
  return {
    from: context.pos,
    options: SUGGESTIONS.map((s) => ({
      label: s.label,
      detail: s.detail,
      apply: `${s.label}}}`,
    })),
  };
}

export default function ExpressionEditor(props: {
  value: string;
  placeholder?: string;
  onChange: (value: string) => void;
  minHeight?: string;
  /** Nomor baris. Berguna untuk KODE (banyak baris), tidak untuk ekspresi. */
  lineNumbers?: boolean;
  /**
   * Saran autocomplete `{{`-triggered.
   *
   *   undefined -> perilaku lama (variabel workflow: trigger.body, …)
   *   null      -> autocomplete DIMATIKAN
   *
   * `null` dipakai oleh node Code, dan itu keputusan sadar: `{{...}}` TIDAK
   * disubstitusi di dalam `config.code` (substitusi teks pada kode = data
   * tak tepercaya menjadi program). Menawarkan `trigger.body` di sana akan
   * menghasilkan kode yang terlihat benar tapi tidak pernah terisi — lebih
   * buruk daripada tidak ada saran sama sekali. Data workflow masuk sebagai
   * variabel `input_data`.
   */
  suggestions?: { label: string; detail?: string }[] | null;
}) {
  const { value, placeholder, onChange, minHeight, lineNumbers, suggestions } = props;
  const daftar = suggestions === undefined ? SUGGESTIONS : suggestions;
  return (
    <div className="nodrag overflow-hidden rounded-md border border-gray-600 bg-gray-900 font-mono text-[12px]">
      <style>{`.nodrag .cm-tooltip-autocomplete, .nodrag .cm-tooltip { z-index: 9999 !important; }`}</style>
      <CodeMirror
        value={value ?? ""}
        placeholder={placeholder ?? "Ketik... (gunakan {{ untuk variabel)"}
        theme="dark"
        height={minHeight ?? "112px"}
        basicSetup={{
          lineNumbers: lineNumbers ?? false,
          foldGutter: false,
          highlightActiveLine: lineNumbers ?? false,
        }}
        extensions={daftar ? [autocompletion({ override: [braceCompleter] })] : []}
        onChange={(v) => onChange(v)}
      />
    </div>
  );
}
