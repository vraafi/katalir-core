"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, KeyRound, Loader2, MonitorSmartphone, Moon, Sun, Trash2 } from "lucide-react";
import { useTheme } from "next-themes";
import { toast } from "sonner";
import { useAuth } from "@/context/auth";
import { useI18n } from "@/i18n/context";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { SimplePage } from "@/components/SimplePage";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { cn } from "@/lib/cn";
import { apiFetch } from "@/lib/api";
import { useCanvasTheme } from "@/features/builder/themes/CanvasThemeProvider";
import { THEMES, type CanvasThemeId } from "@/features/builder/themes/canvas-themes";

/**
 * Halaman Pengaturan (FASE 4.1 — rebuild).
 *
 * KENAPA DIREBUILD (temuan FASE 3): tema aplikasi dan bahasa dulu berada di SATU
 * kartu "Preferensi", dipisah hanya oleh judul kecil. Pengguna bisa mengklik
 * radio bahasa dan mengira itu tema. FASE 4 memisahkan menjadi kartu tersendiri
 * (`Bahasa`, `Tema Aplikasi`, `Tema Kanvas Builder`) dengan deskripsi eksplisit
 * per grup, sehingga tema kanvas (4 pilihan) tidak lagi tertukar dengan mode
 * gelap/terang aplikasi.
 *
 * Aksesibilitas (FASE 4.5): setiap kontrol punya label terhubung (`htmlFor`/`id`
 * atau `role=radiogroup` + `aria-checked`), hint lewat `aria-describedby`,
 * status simpan diumumkan lewat `aria-live="polite"`, tombol ikon-saja punya
 * `aria-label` — semua diukur di `tests/fase4-a11y.spec.ts`.
 */

const PROVIDER_OPTIONS = [
  { value: "groq", label: "Groq" },
  { value: "openai", label: "OpenAI" },
  { value: "gemini", label: "Gemini (Google AI Studio)" },
  { value: "whatsapp", label: "WhatsApp Cloud API" },
  { value: "custom_llm", label: "Custom LLM / OpenRouter" },
];

interface VaultItem {
  provider: string;
  saved: boolean;
}

/** Seksi Kredensial: simpan (Fernet via /api/vault/save) + cabut per provider. */
function CredentialsSection() {
  const { t } = useI18n();
  const { email } = useAuth();
  const [provider, setProvider] = useState("groq");
  const [key, setKey] = useState("");
  const [status, setStatus] = useState<"idle" | "saving" | "ok" | "err">("idle");
  const [items, setItems] = useState<VaultItem[]>([]);

  const refresh = useCallback(async () => {
    try {
      const r = await apiFetch("/api/vault/list", { method: "GET" });
      if (r.ok) {
        const d = await r.json();
        setItems((d.items ?? []) as VaultItem[]);
      }
    } catch {
      /* daftar kredensial opsional: jangan ganggu halaman */
    }
  }, []);

  useEffect(() => {
    if (email) void refresh();
  }, [email, refresh]);

  async function onSave(e: React.FormEvent) {
    e.preventDefault();
    if (!key.trim()) return;
    setStatus("saving");
    try {
      const r = await apiFetch("/api/vault/save", {
        method: "POST",
        body: JSON.stringify({ provider, api_key: key.trim() }),
      });
      if (r.ok) {
        setStatus("ok");
        setKey("");
        await refresh();
      } else {
        setStatus("err");
      }
    } catch {
      setStatus("err");
    }
  }

  async function onRevoke(p: string) {
    try {
      const r = await apiFetch(`/api/vault/${encodeURIComponent(p)}`, { method: "DELETE" });
      if (r.ok) {
        toast.success(t("settings.revoked"));
        await refresh();
      } else {
        toast.error(t("settings.revokeFailed"));
      }
    } catch {
      toast.error(t("settings.revokeFailed"));
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings.credentials")}</CardTitle>
        <CardDescription>{t("settings.credentialsDesc")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSave} className="flex flex-col gap-3">
          <div>
            <Select
              id="vault-provider"
              data-testid="vault-provider"
              label={t("settings.provider")}
              options={PROVIDER_OPTIONS}
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="vault-key" className="text-footnote font-medium text-fg">
              {t("settings.apiKey")}
            </label>
            <Input
              id="vault-key"
              data-testid="vault-key"
              type="password"
              className="mt-1"
              autoComplete="off"
              aria-describedby="vault-key-hint"
              value={key}
              onChange={(e) => setKey(e.target.value)}
            />
            <p id="vault-key-hint" className="mt-1 text-caption text-fg-subtle">
              {t("settings.apiKeyHint")}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Button type="submit" variant="primary" loading={status === "saving"} data-testid="vault-save">
              {status === "saving" ? t("settings.savingCredential") : t("settings.saveCredential")}
            </Button>
            {/* Status simpan diumumkan ke asisten (bukan hanya warna). */}
            <span aria-live="polite" className="text-footnote" data-testid="vault-status">
              {status === "ok" && (
                <span className="inline-flex items-center gap-1 text-success">
                  <Check size={14} strokeWidth={2} aria-hidden /> {t("settings.credentialSaved")}
                </span>
              )}
              {status === "err" && <span className="text-danger">{t("settings.credentialSaveFailed")}</span>}
            </span>
          </div>
        </form>

        <div className="mt-5 border-t border-border pt-4">
          <p className="text-footnote font-semibold uppercase tracking-wide text-fg-subtle">
            {t("settings.storedCredentials")}
          </p>
          {items.length === 0 ? (
            <p className="mt-1 text-footnote text-fg-muted" data-testid="vault-empty">
              {t("settings.noCredentials")}
            </p>
          ) : (
            <ul className="mt-2 flex flex-col gap-1.5" data-testid="vault-list">
              {items.map((it) => (
                <li
                  key={it.provider}
                  className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-footnote"
                >
                  <span className="flex items-center gap-2">
                    <KeyRound size={13} strokeWidth={1.75} aria-hidden className="text-fg-subtle" />
                    <span className="font-medium text-fg">{it.provider}</span>
                  </span>
                  <button
                    type="button"
                    onClick={() => void onRevoke(it.provider)}
                    aria-label={t("settings.revokeLabel", { provider: it.provider })}
                    data-testid={`vault-revoke-${it.provider}`}
                    className="flex items-center gap-1.5 rounded-sm px-2 py-1 text-caption font-medium text-danger transition-colors hover:bg-danger/10"
                  >
                    <Trash2 size={12} strokeWidth={2} aria-hidden />
                    {t("settings.revoke")}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}


/**
 * Task 1B — kartu koneksi OAuth (Google Sheets + Slack).
 *
 * KENAPA KARTU TERPISAH dari form Brankas: koneksi ini BUKAN token yang bisa
 * ditempel user. Kalau digabung, user akan mencari "token Slack" yang tidak
 * pernah ada dan mengisi sesuatu yang mustahil benar.
 *
 * Redirect memakai HALAMAN PENUH (bukan popup) setelah URL authorize diambil
 * lewat `apiFetch`: endpoint authorize butuh header Authorization, dan redirect
 * mentah tidak bisa membawa header — karena itu backend punya `mode=json`.
 * JWT tidak pernah masuk ke URL.
 */
interface OAuthCardSpec {
  id: "google" | "slack";
  provider: string;
  authorize: string;
  disconnect: string;
  testid: string;
}

const OAUTH_CARDS: OAuthCardSpec[] = [
  { id: "google", provider: "Google Sheets", authorize: "/oauth/google/authorize", disconnect: "/oauth/google", testid: "card-oauth-google" },
  { id: "slack", provider: "Slack", authorize: "/oauth/slack/authorize", disconnect: "/oauth/slack", testid: "card-oauth-slack" },
];

interface OAuthState {
  loaded: boolean;
  connected: boolean;
  target: string;
  configured: boolean;
  error?: boolean;
}

function ConnectionsSection() {
  const { t } = useI18n();
  const { email } = useAuth();
  const [state, setState] = useState<Record<string, OAuthState>>({});
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const next: Record<string, OAuthState> = {};
    for (const card of OAUTH_CARDS) {
      try {
        const r = await apiFetch(`/oauth/${card.id}/status`, { method: "GET" });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = (await r.json()) as Record<string, unknown>;
        if (card.id === "google") {
          const g = (d.google_sheets ?? {}) as { connected?: boolean };
          next[card.id] = {
            loaded: true,
            connected: Boolean(g.connected),
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
        next[card.id] = { loaded: true, connected: false, target: "", configured: false, error: true };
      }
    }
    setState(next);
  }, [email]);

  useEffect(() => {
    if (email) void refresh();
  }, [email, refresh]);

  /** Setelah consent, callback backend mengarahkan ke `/settings?<provider>=...`.
   *  Dibaca dari `window.location` (bukan useSearchParams) supaya halaman ini
   *  tidak butuh boundary Suspense tambahan. Query dibersihkan agar toast tidak
   *  muncul lagi saat refresh. */
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
      const r = await apiFetch(`${card.authorize}?mode=json`, { method: "GET" });
      const d = (await r.json().catch(() => ({}))) as { url?: string; detail?: string };
      if (!r.ok || !d.url) throw new Error(d.detail || `HTTP ${r.status}`);
      window.location.href = d.url; // halaman penuh (bukan popup)
    } catch (error) {
      setBusy(null);
      // Preserve the backend's actionable reason (missing session, missing
      // provider configuration, redirect mismatch) instead of hiding it behind
      // the old generic toast.
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
        <CardTitle>{t("settings.connections")}</CardTitle>
        <CardDescription>{t("settings.connectionsDesc")}</CardDescription>
      </CardHeader>
      <CardContent>
        <div data-testid="oauth-cards" className="grid gap-3 sm:grid-cols-2">
          {OAUTH_CARDS.map((card) => {
            const st = state[card.id];
            const loading = !st?.loaded;
            const target = card.id === "slack" ? st?.target || "" : email || "";
            return (
              <div
                key={card.id}
                data-testid={card.testid}
                className="flex flex-col gap-2 rounded-md border border-border p-3"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-footnote font-medium text-fg">{card.provider}</span>
                  {loading ? (
                    <span className="inline-flex items-center gap-1 text-caption text-fg-muted">
                      <Loader2 size={12} className="animate-spin" aria-hidden /> {t("common.loading")}
                    </span>
                  ) : st?.connected ? (
                    <span
                      data-testid={`oauth-badge-${card.id}`}
                      className="inline-flex items-center gap-1 rounded-full bg-success/15 px-2 py-0.5 text-caption font-medium text-success"
                    >
                      <Check size={12} strokeWidth={2.5} aria-hidden /> {t("settings.connected")}
                    </span>
                  ) : (
                    <span
                      data-testid={`oauth-badge-${card.id}`}
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
                  <p className="text-caption text-danger" data-testid={`oauth-error-${card.id}`}>
                    {t("settings.oauthLoadFailed")}
                  </p>
                )}
                <div className="mt-auto pt-1">
                  {st?.connected ? (
                    <Button
                      variant="danger"
                      size="sm"
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
                      data-testid={`oauth-connect-${card.id}`}
                      loading={busy === card.id}
                      disabled={loading}
                      onClick={() => void connect(card)}
                    >
                      {t("settings.connect", { provider: card.provider })}
                    </Button>
                  )}
                </div>
                {card.id === "slack" && st?.connected && (
                  <p className="text-caption text-fg-subtle">{t("settings.slackRevokeNote")}</p>
                )}
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}


/** Konten Pengaturan — di DALAM SimplePage (SimplePage yang memegang provider). */
function SettingsContent() {
  const { email } = useAuth();
  const { t } = useI18n();
  const { theme, setTheme } = useTheme();
  const { themeId, setTheme: setCanvasTheme } = useCanvasTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const initial = (email?.trim()?.[0] ?? "?").toUpperCase();
  const themeVal = mounted ? (theme ?? "system") : "system";
  const optCls =
    "flex cursor-pointer items-center gap-2.5 rounded-md border px-3 py-2.5 text-[13px] transition-colors focus-visible:shadow-focus";

  return (
    <>
      {/* 1. PROFIL (hanya-baca) */}
      <Card>
        <CardHeader>
          <CardTitle>{t("settings.profile")}</CardTitle>
          <CardDescription>{t("settings.profileDesc")}</CardDescription>
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
              <p className="truncate text-callout font-medium text-fg" data-testid="settings-email">
                {email ?? t("common.loading")}
              </p>
              <p className="text-footnote text-fg-muted">{t("settings.loginVia")}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 2. BAHASA — kartu SENDIRI (backlog FASE 3 #4: dulu satu kartu dengan tema) */}
      <Card data-testid="card-language">
        <CardHeader>
          <CardTitle>{t("settings.language")}</CardTitle>
          <CardDescription>{t("settings.languageDesc")}</CardDescription>
        </CardHeader>
        <CardContent>
          <LanguageSwitcher />
          <p id="language-note" className="mt-2 text-caption text-fg-subtle">
            {t("settings.languageNote")}
          </p>
        </CardContent>
      </Card>

      {/* 3. TEMA APLIKASI (terang/gelap/sistem) */}
      <Card data-testid="card-app-theme">
        <CardHeader>
          <CardTitle>{t("settings.appearance")}</CardTitle>
          <CardDescription id="app-theme-desc">{t("settings.appearanceDesc")}</CardDescription>
        </CardHeader>
        <CardContent>
          <div
            className="grid gap-2 sm:grid-cols-3"
            role="radiogroup"
            aria-label={t("settings.appearance")}
            aria-describedby="app-theme-desc"
            data-testid="app-theme-group"
          >
            {(
              [
                { id: "light", label: t("settings.themeLight"), Icon: Sun },
                { id: "dark", label: t("settings.themeDark"), Icon: Moon },
                { id: "system", label: t("settings.themeSystem"), Icon: MonitorSmartphone },
              ] as const
            ).map(({ id, label, Icon }) => (
              <button
                key={id}
                type="button"
                role="radio"
                aria-checked={themeVal === id}
                data-testid={`app-theme-${id}`}
                onClick={() => setTheme(id)}
                className={cn(
                  optCls,
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
        </CardContent>
      </Card>


      {/* 4. TEMA KANVAS BUILDER (4 tema, TERPISAH dari tema aplikasi) */}
      <Card data-testid="card-canvas-theme">
        <CardHeader>
          <CardTitle>{t("settings.canvasTheme")}</CardTitle>
          <CardDescription id="canvas-theme-desc">{t("settings.canvasThemeDesc")}</CardDescription>
        </CardHeader>
        <CardContent>
          <div
            className="grid gap-2 sm:grid-cols-2"
            role="radiogroup"
            aria-label={t("settings.canvasTheme")}
            aria-describedby="canvas-theme-desc"
            data-testid="canvas-theme-group"
          >
            {Object.values(THEMES).map((th) => {
              const active = themeId === th.id;
              return (
                <button
                  key={th.id}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  data-testid={`canvas-theme-radio-${th.id}`}
                  onClick={() => setCanvasTheme(th.id as CanvasThemeId)}
                  className={cn(
                    optCls,
                    active
                      ? "border-accent bg-accent/10 font-medium text-fg"
                      : "border-border text-fg-muted hover:bg-bg-subtle hover:text-fg"
                  )}
                >
                  <span
                    aria-hidden
                    className="h-5 w-5 shrink-0 rounded-sm border"
                    style={{ background: th.canvasBg, borderColor: th.nodeBorder }}
                  />
                  <span className="min-w-0">
                    <span className="block">{th.name}</span>
                    <span className="block text-caption text-fg-muted">{th.description}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* 5. KREDENSIAL (Vault Fernet) */}
      <CredentialsSection />

      {/* 5b. KONEKSI OAUTH (Task 1B: tombol Connect/Disconnect + badge) */}
      <ConnectionsSection />

      {/* 6. ZONA BERBAHAYA */}
      <Card className="border-danger/40" data-testid="card-danger">
        <CardHeader>
          <CardTitle className="text-danger">{t("settings.dangerZone")}</CardTitle>
          <CardDescription>{t("settings.dangerDesc")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="danger" onClick={() => toast.info(t("settings.deleteToast"))}>
            {t("settings.deleteAccount")}
          </Button>
        </CardContent>
      </Card>
    </>
  );
}

/** Route /settings: SimplePage (provider) + konten. Judul memakai KEY i18n
 *  supaya ikut bahasa aktif (SimplePageInner menerjemahkannya di dalam
 *  I18nProvider). */
export default function SettingsPage() {
  return (
    <SimplePage title="settings.title" subtitle="settings.subtitle" maxW="max-w-3xl">
      <SettingsContent />
    </SimplePage>
  );
}

