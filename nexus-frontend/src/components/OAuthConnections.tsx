"use client";

/**
 * OAuthConnections — status + connect/disconnect untuk akun pihak ketiga.
 *
 * KENAPA KOMPONEN TERPISAH (bukan tetap di /settings): user sendiri
 * bertanya "di mana connect Slack, di mana GitHub?" karena /settings
 * mencampur akun dengan koneksi. Standar 2026 (Linear, Vercel, Supabase)
 * memisahkannya: /settings = akun & preferensi, /integrations = koneksi.
 * Komponen ini hidup di /integrations, dan /settings hanya menautkannya.
 *
 * Kontrak penting: komponen ini TIDAK mengarang status. `connected` datang
 * dari endpoint status, dan `configured` menentukan apakah tombolnya
 * diaktifkan. Lihat docs/oauth/provider-status.md.
 */
import { useCallback, useEffect, useState } from "react";
import { Check, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { toast } from "sonner";
import { useI18n } from "@/i18n/context";
import { useAuth } from "@/context/auth";

export interface OAuthCardSpec {
  id: "google" | "slack";
  provider: string;
  authorize: string;
  disconnect: string;
  testid: string;
  /** Tujuan pencabutan penuh, dipakai disclaimer.
   *  Dulu disclaimer hanya ada di Slack (`card.id === "slack"`), jadi kartu
   *  Google lebih pendek dan tombolnya tidak sejajar. Sekarang setiap kartu
   *  punya teks sendiri dengan struktur yang sama. */
  revokeTarget: string;
}

export const OAUTH_CARDS: OAuthCardSpec[] = [
  {
    id: "google",
    provider: "Google Sheets",
    authorize: "/oauth/google/authorize",
    disconnect: "/oauth/google",
    testid: "card-oauth-google",
    revokeTarget: "Google account permissions",
  },
  {
    id: "slack",
    provider: "Slack",
    authorize: "/oauth/slack/authorize",
    disconnect: "/oauth/slack",
    testid: "card-oauth-slack",
    revokeTarget: "Slack workspace",
  },
];

interface OAuthState {
  loaded: boolean;
  connected: boolean;
  target: string;
  configured: boolean;
  error?: boolean;
}

export function OAuthConnections({ title, description }: { title?: string; description?: string }) {
  const { t } = useI18n();
  const { email } = useAuth();
  const [state, setState] = useState<Record<string, OAuthState>>({});
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const next: Record<string, OAuthState> = {};
    for (const card of OAUTH_CARDS) {
      try {
        // 5 detik terlalu agresif untuk endpoint yang membaca vault:
        // latensi Railway terukur 284-1551 ms dan sesekali lebih lama
        // saat decrypt. Timeout yang keputus lalu dibaca sebagai
        // "tidak terhubung" (lihat catatan di bawah).
        let r = await apiFetch(`/oauth/${card.id}/status`, { method: "GET", timeoutMs: 15_000 });
        // 401 = token Supabase yang dipakai kedaluwarsa, BUKAN berarti
        // koneksi OAuth diputus. getSession() sudah memicu refresh,
        // jadi satu percobaan ulang biasanya membetulkan. Tanpa ini,
        // token yang megang di detik membuat kartu menampilkan "Not
        // connected" padahal vault utuh.
        if (r.status === 401) {
          await supabase.auth.getSession();
          r = await apiFetch(`/oauth/${card.id}/status`, { method: "GET", timeoutMs: 15_000 });
        }
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = (await r.json().catch(() => ({}))) as {
          connected?: boolean;
          google_sheets?: { connected?: boolean };
          team_name?: string;
          keys_present?: number;
          keys_total?: number;
          configured?: boolean;
        };
        if (card.id === "google") {
          next[card.id] = {
            loaded: true,
            connected: Boolean(d.google_sheets?.connected),
            target: email ?? "",
            configured: Boolean(d.configured),
          };
        } else {
          next[card.id] = {
            loaded: true,
            connected: Boolean(d.connected),
            target: String(d.team_name ?? ""),
            configured: d.keys_present === d.keys_total,
          };
        }
      } catch {
        // PENTING: `connected: false` DI SINI tidak berarti "terputus".
        // Ini hanya bisa berarti "tidak bisa dipastikan".
        // Error network, timeout, atau 5xx akan mendarat di branch ini,
        // dan sebelumnya branch ini ditampilkan sebagai "Not connected"
        // -- itu akar laporan "connect lalu beberapa menit kemudian
        // Not connected lagi". Kolom `error` sudah ada tapi tidak
        // pernah dipakai untuk membedakan keduanya.
        next[card.id] = { loaded: true, connected: false, target: "", configured: false, error: true };
      }
    }
    setState(next);
  }, [email]);

  useEffect(() => {
    if (email) void refresh();
  }, [email, refresh]);


  /** Setelah consent, callback backend mengarahkan ke `/settings?<provider>=...`.
   *  Callback yang sama juga muncul di /integrations, jadi keduanya membaca
   *  query dari `window.location` dan menampilkan toast yang sama. */
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    let changed = false;
    for (const card of OAUTH_CARDS) {
      const v = params.get(card.id);
      if (!v) continue;
      changed = true;
      if (v === "connected") toast.success(t("settings.oauthConnected", { provider: card.provider }));
      else toast.error(t("settings.oauthDenied", { provider: card.provider, reason: v }));
      params.delete(card.id);
    }
    if (changed) {
      const q = params.toString();
      window.history.replaceState({}, "", `${window.location.pathname}${q ? `?${q}` : ""}`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function connect(card: OAuthCardSpec) {
    setBusy(card.id);
    try {
      // JWT tidak boleh masuk URL, jadi backend menyediakan `mode=json` yang
      // mengembalikan URL consent sementara header auth tetap terpakai.
      const r = await apiFetch(`${card.authorize}?mode=json`, { method: "GET" });
      const d = (await r.json().catch(() => ({}))) as { url?: string; detail?: string };
      if (!r.ok || !d.url) throw new Error(d.detail || `HTTP ${r.status}`);
      window.location.href = d.url; // halaman penuh (bukan popup)
    } catch (error) {
      setBusy(null);
      const message = error instanceof Error ? error.message : "";
      toast.error(message || t("settings.connectFailed"));
    }
  }

  async function disconnect(card: OAuthCardSpec) {
    setBusy(card.id);
    try {
      const r = await apiFetch(card.disconnect, { method: "DELETE" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      toast.success(t("settings.disconnectDone", { provider: card.provider }));
      await refresh();
    } catch {
      toast.error(t("settings.disconnectFailed", { provider: card.provider }));
    } finally {
      setBusy(null);
    }
  }


  return (
    <Card data-testid="card-connections">
      <CardHeader>
        <CardTitle>{title ?? t("settings.connections")}</CardTitle>
        <CardDescription>{description ?? t("settings.connectionsDesc")}</CardDescription>
      </CardHeader>
      <CardContent>
        <div data-testid="oauth-cards" className="grid items-stretch gap-3 sm:grid-cols-2">
          {OAUTH_CARDS.map((card) => {
            const st = state[card.id];
            const loading = !st?.loaded;
            const target = card.id === "slack" ? st?.target || "" : email || "";
            return (
              <div
                key={card.id}
                data-testid={card.testid}
                className="flex h-full flex-col gap-2 rounded-md border border-border p-3"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-footnote font-medium text-fg">{card.provider}</span>
                  {loading ? (
                    <span className="inline-flex items-center gap-1 text-caption text-fg-muted">
                      <Loader2 size={12} strokeWidth={2} className="animate-spin" aria-hidden /> {t("common.loading")}
                    </span>
                  ) : st?.error ? (
                    // Status TIDAK bisa dipastikan. Menampilkan "Not connected"
                    // di sini adalah kebohongan: kartu ini bisa jadi tetap
                    // terhubung, hanya saja request-nya yang gagal. Laporan
                    // "connect lalu beberapa menit kemudian Not connected
                    // lagi" berasal dari branch tepat ini.
                    <span
                      data-testid={`oauth-badge-${card.id}`}
                      data-state="unknown"
                      className="inline-flex items-center gap-1 rounded-full border border-warning/40 bg-warning/10 px-2 py-0.5 text-caption font-medium text-fg-muted"
                    >
                      {t("settings.oauthStatusUnknown")}
                    </span>
                  ) : st?.connected ? (
                    <span
                      data-testid={`oauth-badge-${card.id}`}
                      data-state="connected"
                      className="inline-flex items-center gap-1 rounded-full bg-success/15 px-2 py-0.5 text-caption font-medium text-success"
                    >
                      <Check size={12} strokeWidth={2.5} aria-hidden /> {t("settings.connected")}
                    </span>
                  ) : (
                    <span
                      data-testid={`oauth-badge-${card.id}`}
                      data-state="disconnected"
                      className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-caption text-fg-muted"
                    >
                      {t("settings.notConnected")}
                    </span>
                  )}
                </div>
                {st?.connected && target && (
                  <p className="text-caption text-fg-muted" data-testid={`oauth-target-${card.id}`}>
                    {t("settings.connectedAs", { target })}
                  </p>
                )}
                {st?.error && (
                  <div className="flex flex-wrap items-center gap-2" role="status" aria-live="polite">
                    <p className="text-caption text-danger" data-testid={`oauth-error-${card.id}`}>
                      {t("settings.oauthLoadFailed")}
                    </p>
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      data-testid={`oauth-retry-${card.id}`}
                      onClick={() => void refresh()}
                    >
                      {t("common.retry")}
                    </Button>
                  </div>
                )}
                {/*
                  Footer. `mt-auto` MENYEJAKANKAN tombol ke dasar kartu, dan
                  disclaimer sekarang DI DALAM footer ini -- sebelumnya berada
                  di luar, sehingga pada kartu Slack (yang punya disclaimer)
                  `mt-auto` tidak lagi mendorong apa pun ke bawah dan kedua
                  kartu jadi berbeda tinggi. Disclaimer juga dirender untuk
                  SETIAP provider, jadi strukturnya identik.
                */}
                <div className="mt-auto flex flex-col gap-2 pt-1" data-testid={`oauth-footer-${card.id}`}>
                  {st?.connected ? (
                    <Button
                      variant="danger"
                      size="sm"
                      className="self-start"
                      data-testid={`oauth-disconnect-${card.id}`}
                      loading={busy === card.id}
                      onClick={() => void disconnect(card)}
                    >
                      {t("settings.disconnect")}
                    </Button>
                  ) : (
                    <Button
                      variant="primary"
                      size="sm"
                      className="self-start"
                      data-testid={`oauth-connect-${card.id}`}
                      loading={busy === card.id}
                      disabled={loading || st?.configured === false}
                      onClick={() => void connect(card)}
                    >
                      {t("settings.connect", { provider: card.provider })}
                    </Button>
                  )}
                  <p className="text-caption text-fg-subtle" data-testid={`oauth-revoke-${card.id}`}>
                    {t("settings.revokeNote", { target: card.revokeTarget })}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
