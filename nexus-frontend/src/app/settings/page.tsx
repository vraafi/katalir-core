"use client";

import { useEffect, useState } from "react";
import { Moon, Sun, MonitorSmartphone } from "lucide-react";
import { useTheme } from "next-themes";
import { toast } from "sonner";
import { useAuth } from "@/context/auth";
import { SimplePage } from "@/components/SimplePage";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

/** Konten Pengaturan — dipakai di DALAM SimplePage (SimplePage yang memegang provider).
 *  TIDAK di-export (aturan App Router: hanya default + metadata yang boleh di-export
 *  dari page.tsx; named export lain merusak type-check route). */
function SettingsContent() {
  const { email } = useAuth();
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const initial = (email?.trim()?.[0] ?? "?").toUpperCase();
  const themeVal = mounted ? (theme ?? "system") : "system";
  const themeOpt =
    "flex cursor-pointer items-center gap-2.5 rounded-md border px-3 py-2.5 text-[13px] transition-colors";

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Profil</CardTitle>
          <CardDescription>Identitas akun Anda (hanya-baca).</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3">
            <span
              aria-hidden
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-accent/15 text-[17px] font-bold text-accent"
            >
              {initial}
            </span>
            <div className="min-w-0">
              <p className="truncate text-callout font-medium text-fg">{email ?? "Memuat…"}</p>
              <p className="text-footnote text-fg-muted">Login via Google OAuth</p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Preferensi</CardTitle>
          <CardDescription>Tampilan dan bahasa antarmuka.</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="mb-2 text-footnote font-semibold uppercase tracking-wide text-fg-subtle">Tema</p>
          <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Tema">
            {(
              [
                { id: "light", label: "Terang", Icon: Sun },
                { id: "dark", label: "Gelap", Icon: Moon },
                { id: "system", label: "Ikuti Sistem", Icon: MonitorSmartphone },
              ] as const
            ).map(({ id, label, Icon }) => (
              <button
                key={id}
                type="button"
                role="radio"
                aria-checked={themeVal === id}
                onClick={() => setTheme(id)}
                className={cn(
                  themeOpt,
                  themeVal === id
                    ? "border-accent bg-accent/10 font-medium text-fg"
                    : "border-border text-fg-muted hover:bg-bg-subtle hover:text-fg"
                )}
              >
                <Icon size={15} strokeWidth={1.75} aria-hidden />
                {label}
              </button>
            ))}
          </div>
          <p className="mb-2 mt-5 text-footnote font-semibold uppercase tracking-wide text-fg-subtle">Bahasa</p>
          <div className="flex cursor-not-allowed items-center gap-2.5 rounded-md border border-border px-3 py-2.5 text-[13px] text-fg-subtle" title="Segera hadir">
            Indonesia (segera hadir: English)
          </div>
        </CardContent>
      </Card>

      <Card className="border-danger/40">
        <CardHeader>
          <CardTitle className="text-danger">Zona Berbahaya</CardTitle>
          <CardDescription>Menghapus akun bersifat permanen dan tidak bisa dibatalkan.</CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="danger" onClick={() => toast.info("Fitur hapus akun dalam pengembangan.")}>
            Hapus Akun
          </Button>
        </CardContent>
      </Card>
    </>
  );
}

/** Route /settings: SimplePage (provider) + konten. */
export default function SettingsPage() {
  return (
    <SimplePage title="Pengaturan Akun" subtitle="Kelola preferensi dan profil Anda">
      <SettingsContent />
    </SimplePage>
  );
}
