"use client";

import { useState } from "react";
import { KeyRound, Save, Check } from "lucide-react";
import { Sheet } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

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
    <Sheet open={open} onOpenChange={(o) => !o && onClose()} title="Brankas Kredensial" description="Kunci dienkripsi end-to-end (AES/Fernet) sebelum disimpan. Tidak pernah tercatat di log atau riwayat LLM.">
      <div className="flex items-start gap-2">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-sm bg-accent/15 text-accent">
          <KeyRound size={18} strokeWidth={1.5} />
        </span>
        <p className="text-footnote leading-snug text-fg-muted">
          Provider dan API Key akan disimpan aman di Brankas (vault).
        </p>
      </div>

      <div className="mt-5 grid gap-4">
        <Select
          label="Provider"
          value={provider}
          onChange={(e) => setProvider(e.target.value)}
          options={PROVIDERS.map((p) => ({ value: p.value, label: p.label }))}
          data-testid="vault-provider"
        />
        <Input
          label="API Key"
          type="password"
          placeholder="sk-... / gsk-... / AIza..."
          value={key}
          onChange={(e) => setKey(e.target.value)}
        />
      </div>

      <Button className="mt-5 w-full" onClick={() => void onSave()} disabled={!key.trim() || status === "saving"} loading={status === "saving"}>
        {status !== "saving" && <Save className="h-4 w-4" strokeWidth={1.75} />} Simpan Kredensial
      </Button>

      {status === "ok" && (
        <div className="mt-2 flex items-center gap-1.5 text-footnote text-success">
          <Check size={14} strokeWidth={2} /> Kunci dienkripsi & disimpan sukses.
        </div>
      )}
      {status === "err" && (
        <div className="mt-2 text-footnote text-danger">Gagal menyimpan. Coba lagi.</div>
      )}

      <div className="mt-5 border-t border-border pt-3">
        <div className="text-caption font-semibold uppercase tracking-wide text-fg-subtle">Kredensial disimpan</div>
        {saved.length === 0 ? (
          <p className="mt-1 text-footnote text-fg-muted">Belum ada kredensial disimpan.</p>
        ) : (
          <ul className="mt-1 space-y-1">
            {saved.map((s) => (
              <li key={s.provider} className="flex items-center gap-2 text-footnote text-fg-muted">
              <KeyRound size={12} strokeWidth={1.5} className="text-accent" />
                <span>{s.provider}</span>
                <span className="rounded-full bg-success/15 px-1.5 text-[10px] text-success">enabled</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Sheet>
  );
}
