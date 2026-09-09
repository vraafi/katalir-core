"use client";

import { useState } from "react";
import { KeyRound, Save, X, Check } from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const PROVIDERS = [
  { value: "groq", label: "Groq" },
  { value: "openai", label: "OpenAI" },
  { value: "gemini", label: "Gemini (Google AI Studio)" },
  { value: "whatsapp", label: "WhatsApp Cloud API" },
  { value: "custom_llm", label: "Custom LLM / OpenRouter" },
];

interface VaultModalProps {
  open: boolean;
  email: string;
  onClose: () => void;
}

export default function VaultModal({ open, email, onClose }: VaultModalProps) {
  const [provider, setProvider] = useState("groq");
  const [key, setKey] = useState("");
  const [status, setStatus] = useState<"idle" | "saving" | "ok" | "err">("idle");
  const [saved, setSaved] = useState<{ provider: string; saved: boolean }[]>([]);

  if (!open) return null;

  async function refresh() {
    try {
      const r = await fetch(`${API_URL}/api/vault/list?email=${encodeURIComponent(email)}`);
      if (r.ok) {
        const d = await r.json();
        setSaved(d.items ?? []);
      }
    } catch {
      /* ignore */
    }
  }

  async function onSave() {
    if (!key.trim() || !provider) return;
    setStatus("saving");
    try {
      const r = await fetch(`${API_URL}/api/vault/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, provider, api_key: key.trim() }),
      });
      if (r.ok) {
        setStatus("ok");
        setKey("");
        void refresh();
      } else {
        setStatus("err");
      }
    } catch {
      setStatus("err");
    }
  }

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-[440px] max-h-[88vh] overflow-y-auto rounded-2xl border border-gray-700 bg-gray-900 p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-500/20 text-indigo-300">
              <KeyRound size={18} />
            </span>
            <h2 className="text-base font-bold text-gray-100">Brankas Kredensial</h2>
          </div>
          <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-md text-gray-400 hover:bg-gray-800">
            <X size={16} />
          </button>
        </div>

        <p className="mt-2 text-xs leading-snug text-gray-400">
          Kunci enkriptoi end-to-end (AES/Fernet) ennen Supabase tallennusta. Ei koskaan jää logiin tai riwayat LLM:iin.
        </p>

        <label className="mt-4 block">
          <span className="text-xs text-gray-400">Provider</span>
          <select
            className="mt-1 w-full rounded-lg border border-gray-600 bg-gray-800 px-2.5 py-2 text-sm text-gray-100 outline-none focus:border-indigo-400"
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
          >
            {PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </label>

        <label className="mt-3 block">
          <span className="text-xs text-gray-400">API Key</span>
          <input
            type="password"
            className="mt-1 w-full rounded-lg border border-gray-600 bg-gray-800 px-2.5 py-2 text-sm text-gray-100 outline-none focus:border-indigo-400"
            placeholder="sk-... / gsk-... / AIza..."
            value={key}
            onChange={(e) => setKey(e.target.value)}
          />
        </label>

        <button
          onClick={() => void onSave()}
          disabled={!key.trim() || status === "saving"}
          className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 py-2 text-sm font-semibold text-white transition hover:bg-indigo-500 disabled:opacity-50"
        >
          {status === "saving" ? <span className="animate-pulse">Simpan...</span> : <><Save size={15} /> Simpan Kredensial</>}
        </button>

        {status === "ok" && (
          <div className="mt-2 flex items-center gap-1.5 text-xs text-green-400">
            <Check size={14} /> Kunci enkriptoi & disimpan sukses.
          </div>
        )}
        {status === "err" && (
          <div className="mt-2 text-xs text-red-400">Gagal menyimpan. Coba lagi.</div>
        )}

        <div className="mt-5 border-t border-gray-700 pt-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">Kredensial disimpan</div>
          {saved.length === 0 ? (
            <p className="mt-1 text-xs text-gray-500">Belum ada kredensial disimpan.</p>
          ) : (
            <ul className="mt-1 space-y-1">
              {saved.map((s) => (
                <li key={s.provider} className="flex items-center gap-2 text-xs text-gray-300">
                  <KeyRound size={12} className="text-indigo-400" />
                  <span>{s.provider}</span>
                  <span className="rounded-full bg-green-500/15 px-1.5 text-[10px] text-green-400">enabled</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}