"use client";

/**
 * GmailImapCard - hubungkan Gmail untuk trigger email masuk lewat IMAP.
 *
 * KENAPA BUKAN "CONNECT" OAUTH (2026-10-03)
 * -----------------------------------------
 * Semua scope Gmail untuk trigger (`gmail.readonly`, `gmail.modify`) adalah
 * RESTRICTED scope Google: butuh security assessment CASA tahunan sebelum boleh
 * dipakai user umum. Karena itu dipakai jalur IMAP + App Password - TANPA OAuth
 * sama sekali, jadi tanpa CASA, tanpa verifikasi aplikasi, jalan di akun Gmail
 * biasa.
 *
 * Kartu Gmail lama berstatus "comingSoon" karena tidak ada jalur yang bisa
 * dipakai. Sekarang jalurnya ada, jadi form ini nyata.
 *
 * Keamanan: App Password adalah kredensial nyata. Nilai yang tersimpan TIDAK
 * pernah ditampilkan ulang (server juga tidak mengembalikannya), dan input
 * dibersihkan dari spasi karena Google menampilkannya bergROUP.
 */
import { useCallback, useEffect, useState } from "react";
import { Check, ExternalLink, Loader2, Plug, Unplug } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";
import { toast } from "sonner";

const APP_PASSWORD_URL = "https://myaccount.google.com/apppasswords";

type Status = {
  connected: boolean;
  email_address: string | null;
  app_password_url: string;
};

export function GmailImapCard() {
  const [status, setStatus] = useState<Status | null>(null);
  const [address, setAddress] = useState("");
  const [appPassword, setAppPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await apiFetch("/api/vault/gmail-imap");
      if (res.ok) setStatus((await res.json()) as Status);
    } catch {
      setStatus(null);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await apiFetch("/api/vault/gmail-imap", {
        method: "POST",
        body: JSON.stringify({
          email_address: address.trim(),
          // Spasi dihapus di klien juga: ini bentuk yang ditampilkan Google.
          app_password: appPassword.replace(/\s+/g, ""),
          test_connection: true,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data?.detail || "Gagal menyimpan App Password.");
        return;
      }
      setAppPassword("");
      if (data.connection_test === "ok") {
        toast.success("Gmail terhubung lewat IMAP.");
      } else {
        setError(data.connection_error || "Login IMAP gagal.");
        toast.error("Tersimpan, tapi koneksi IMAP gagal.");
      }
      await load();
    } catch {
      setError("Jaringan bermasalah. Coba lagi.");
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async () => {
    setBusy(true);
    try {
      await apiFetch("/api/vault/gmail-imap", { method: "DELETE" });
      setAddress("");
      toast.success("Koneksi Gmail dilepas.");
      await load();
    } finally {
      setBusy(false);
    }
  };

  const connected = !!status?.connected;

  return (
    <Card data-testid="card-gmail-imap">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Gmail (App Password / IMAP)
          {connected ? (
            <span className="inline-flex items-center gap-1 text-xs font-normal text-emerald-600">
              <Check className="h-3.5 w-3.5" /> Terhubung
            </span>
          ) : null}
        </CardTitle>
        <CardDescription>
          Trigger email masuk tanpa OAuth. Butuh 2FA aktif lalu buat App
          Password 16 karakter. Tidak memakai restricted scope Google, jadi
          tanpa review CASA.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {connected ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-fg-muted" data-testid="gmail-imap-address">
              {status?.email_address}
            </span>
            <Button variant="secondary" onClick={disconnect} disabled={busy}
              data-testid="gmail-imap-disconnect">
              <Unplug className="mr-1.5 h-3.5 w-3.5" /> Putuskan
            </Button>
          </div>
        ) : (
          <>
            <div className="space-y-1.5">
              <label htmlFor="gmail-imap-address" className="text-caption font-medium text-fg">Alamat Gmail</label>
              <Input id="gmail-imap-address" type="email" autoComplete="username"
                placeholder="nama@gmail.com" value={address}
                onChange={(e) => setAddress(e.target.value)}
                data-testid="gmail-imap-address-input" />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="gmail-imap-password" className="text-caption font-medium text-fg">App Password (16 karakter)</label>
              <Input id="gmail-imap-password" type="password"
                autoComplete="current-password" placeholder="xxxxxxxx xxxx xxxx xxxx"
                value={appPassword}
                onChange={(e) => setAppPassword(e.target.value)}
                data-testid="gmail-imap-password-input" />
              <a href={APP_PASSWORD_URL} target="_blank" rel="noreferrer noopener"
                className="inline-flex items-center gap-1 text-xs text-accent underline">
                Buat App Password di Google
                <ExternalLink className="h-3 w-3" />
              </a>
            </div>
            {error ? (
              <p className="text-xs text-red-600" data-testid="gmail-imap-error">{error}</p>
            ) : null}
            <Button onClick={save}
              disabled={busy || !address.trim() || appPassword.replace(/\s+/g, "").length < 16}
              data-testid="gmail-imap-save">
              {busy ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Plug className="mr-1.5 h-4 w-4" />}
              Simpan &amp; Test
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  );
}