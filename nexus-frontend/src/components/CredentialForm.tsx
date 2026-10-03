"use client";

/**
 * CredentialForm - form credential INLINE di dalam bubble chat.
 *
 * KENAPA BUKAN REDIRECT KE VAULT (2026-10-03)
 * ------------------------------------------
 * Sebelumnya user disuruh membuka halaman Vault/Settings, mengisi credential
 * di sana, lalu kembali ke chat. Itu memutus alur berpikir dan mudah
 * dilupakan ("jadi di mana dulu?"). Pola yang dipakai di sini: server balas
 * `requires_credential` + deskripsi field, lalu form ini dirender DI DALAM
 * percakapan - setara pola MCP (CredentialMissing -> client render form) dan
 * Vercel AI SDK v5 (tool part `requires-action`).
 *
 * Kontrak dengan server:
 *   - `fields` datang dari backend (credential_forms.PROVIDER_FORMS). Form ini
 *     TIDAK meng-hardcode label/tipe per provider, jadi menambah provider di
 *     backend tidak perlu sentuh frontend.
 *   - Submit -> POST /chat/resume. Server mengembalikan `retry_hint` yang
 *     memberi tahu frontend untuk mengirim ulang prompt aslinya; di situ tool
 *     berjalan karena credential sudah ada di vault.
 *
 * UX yang dijaga:
 *   - Credential salah -> error ditampilkan INLINE dan form TIDAK hilang, jadi
 *     user bisa memperbaiki lalu submit ulang.
 *   - Sukses -> form berubah jadi ringkasan "Terhubung" (tidak hilang diam).
 *   - Nilai input TIDAK pernah dicatat ke state global atau log.
 */
import { useState } from "react";
import { Check, KeyRound, Loader2, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";

export interface CredentialField {
  name: string;
  label: string;
  type?: string;
  placeholder?: string;
  required?: boolean;
  min_length?: number;
  transform?: string;
  help_url?: string;
  help_text?: string;
}

export interface CredentialFormProps {
  provider: string;
  displayName?: string;
  fields: CredentialField[];
  resumeToken: string;
  /** Dipanggil setelah credential tersimpan (frontend lalu resend prompt). */
  onSuccess: (info: { provider: string; display_name: string }) => void;
}

export function CredentialForm({
  provider,
  displayName,
  fields,
  resumeToken,
  onSuccess,
}: CredentialFormProps) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{ provider: string; display_name: string } | null>(null);

  // Spasi dihapus sebelum kirim kalau server menandai `strip_spaces` (Google
  // menampilkan App Password bergROUP; IMAP hanya menerima tanpa spasi).
  const outgoing = (f: CredentialField): string => {
    const raw = values[f.name] ?? "";
    return f.transform === "strip_spaces" ? raw.replace(/\s+/g, "") : raw;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (loading || done) return;
    setLoading(true);
    setError(null);
    try {
      const payload: Record<string, string> = {};
      for (const f of fields) payload[f.name] = outgoing(f);
      const res = await apiFetch("/chat/resume", {
        method: "POST",
        body: JSON.stringify({
          resume_token: resumeToken,
          provider,
          credentials: payload,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        // Form TETAP tampil agar user bisa memperbaiki dan submit ulang.
        setError(
          typeof data?.detail === "string"
            ? data.detail
            : "Gagal menyimpan credential. Coba lagi.",
        );
        return;
      }
      const info = {
        provider: data?.provider ?? provider,
        display_name: data?.display_name ?? displayName ?? provider,
      };
      // Bersihkan nilai sensitif dari memory secepatnya.
      setValues({});
      setDone(info);
      onSuccess(info);
    } catch {
      setError("Tidak bisa menghubungi server. Coba lagi.");
    } finally {
      setLoading(false);
    }
  };

  if (done) {
    return (
      <Card className="my-2 border-emerald-500/40 bg-emerald-500/5" data-testid="credential-form-done">
        <CardContent className="flex items-center gap-2 py-3">
          <Check className="h-4 w-4 shrink-0 text-emerald-600" aria-hidden />
          <span className="text-[13px] text-fg">
            {done.display_name} terhubung. Lanjut memproses permintaanmu.
          </span>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="my-2 border-accent/40" data-testid={`credential-form-${provider}`}>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-[13px]">
          <KeyRound className="h-4 w-4 text-accent" aria-hidden />
          Hubungkan {displayName ?? provider}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-3">
          {fields.map((f) => {
            const inputId = `cred-${provider}-${f.name}`;
            return (
              <div key={f.name} className="space-y-1">
                <label
                  htmlFor={inputId}
                  className="block text-caption font-medium text-fg"
                >
                  {f.label}
                </label>
                <Input
                  id={inputId}
                  type={f.type === "password" ? "password" : f.type === "email" ? "email" : "text"}
                  placeholder={f.placeholder}
                  required={f.required}
                  minLength={f.min_length}
                  value={values[f.name] ?? ""}
                  onChange={(e) =>
                    setValues((prev) => ({ ...prev, [f.name]: e.target.value }))
                  }
                  autoComplete={f.type === "password" ? "new-password" : "off"}
                  data-testid={`${inputId}-input`}
                />
                {f.help_url ? (
                  <a
                    href={f.help_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-block text-caption text-accent underline"
                  >
                    {f.help_text ?? "Pelajari lebih lanjut"}
                  </a>
                ) : null}
              </div>
            );
          })}

          {error ? (
            <p
              role="alert"
              className="text-caption text-red-600"
              data-testid="credential-form-error"
            >
              {error}
            </p>
          ) : null}

          <Button type="submit" size="sm" disabled={loading} data-testid="credential-form-submit">
            {loading ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : null}
            {loading ? "Menyimpan..." : "Simpan & Lanjutkan"}
          </Button>

          <p className="flex items-center gap-1 text-caption text-fg-subtle">
            <ShieldCheck className="h-3 w-3" aria-hidden />
            Data disimpan terenkripsi di vault Anda.
          </p>
        </form>
      </CardContent>
    </Card>
  );
}