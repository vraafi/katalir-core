"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Search, Plus, ExternalLink } from "lucide-react";
import { SimplePage } from "@/components/SimplePage";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

type Server = { id: string; name: string; category: string; description: string; tools?: { name: string }[]; tools_count?: number; install_config?: { transport?: string; package?: string }; source?: string; source_url?: string; attribution_required?: boolean; no_auth?: boolean; auth_type?: string; kind?: string; runtime_verified?: boolean; verification?: { discovered?: boolean; tools_listed?: boolean; call_verified?: boolean } };

type Sources = Record<string, number> & { glama?: number; "glama-connector"?: number; composio?: number; openconnector?: number };

/**
 * Runtime status badge, four tiers, strictly ordered.
 *
 * The order is the whole point: "listed" is not "usable", and a source that
 * needs a credential is a different state from one that was never run at all.
 * Collapsing any two of these is how a marketplace ends up claiming it has
 * thousands of working integrations.
 *
 *   call_verified -> a real tools/call returned a result
 *   auth_required -> we can reach it, but it needs the user's credential
 *   tools_listed  -> initialize + tools/list answered
 *   discovered    -> metadata only, never contacted
 */
function badgeFor(item: Server): { label: string; cls: string; testid: string } {
  const v = item.verification ?? {};
  if (v.call_verified || item.runtime_verified)
    return { label: "call_verified", cls: "bg-emerald-500/15 text-emerald-600", testid: "badge-ready" };
  // no_auth === false is an explicit statement that a credential is required.
  // Absent means unknown, so it must NOT be treated as auth_required.
  if (item.no_auth === false)
    return { label: "auth_required", cls: "bg-amber-500/15 text-amber-600", testid: "badge-auth" };
  if (v.tools_listed)
    return { label: "tools_listed", cls: "bg-sky-500/15 text-sky-600", testid: "badge-listed" };
  return { label: "discovered", cls: "bg-fg-muted/15 text-fg-muted", testid: "badge-catalog" };
}

const SOURCE_LABEL: Record<string, string> = { native: "Native MCP", glama: "Glama", "glama-connector": "Glama Connector", composio: "Composio", openconnector: "OpenConnector", toolsdk: "ToolSDK", "openapi-generated": "OpenAPI" };

/**
 * Integrations proven by a real `tools/call`, not just tools/list.
 *
 * 351 no-auth Glama connectors were called with one read-only tool each; 203
 * returned a real result. Those 203 are 201 distinct integrations: one connector
 * is a directory rather than an integration, and two share a name and collapse in
 * dedup. Source: `glama-connector-call-batch1.json`, re-derived by
 * `scripts/audit_call_safety.py`.
 */
const GLAMA_CALL_VERIFIED = 201;

/**
 * Tabs are driven by real sources. "Native" is NOT the ToolSDK catalogue: it is
 * the set of providers that actually execute in-process, counted by the backend
 * from provider_registry, so the number can never drift from reality.
 *
 * One tab per real `source` value in the registry. `glama` (server directory)
 * and `glama-connector` (live remote endpoints) used to be merged into one
 * "Glama" tab, which hid the only source we can actually verify at runtime, so
 * they are separate now.
 */
const TABS = [
  { key: "", label: "All", note: "Gabungan semua sumber di katalog." },
  { key: "native", label: "Native MCP", note: "Provider yang benar-benar berjalan di produksi — dihitung dari kode, bukan klaim marketing." },
  { key: "glama", label: "Glama", note: "Server direktori Glama. Metadata listing, bukan endpoint yang kita jalankan sendiri." },
  { key: "glama-connector", label: "Glama Connector", note: "Endpoint MCP remote milik pihak ketiga. 351 konektor no-auth diuji; 201 integrasi call-verified lewat satu tools/call baca-saja." },
  { key: "openconnector", label: "OpenConnector", note: "18.010 actions dijangkau lewat 5 meta-tool MCP (list_apps, list_connections, search_actions, get_action_guide, execute_action)." },
  { key: "composio", label: "Composio", note: "Toolkit Composio. OAuth dikunci per user, jadi sebagian besar butuh koneksi akun lebih dulu." },
  { key: "toolsdk", label: "ToolSDK", note: "Katalog metadata saja — tidak ada verifikasi runtime untuk entri ini." },
  { key: "openapi-generated", label: "OpenAPI", note: "API yang di-import dari spesifikasi OpenAPI lalu di-generate jadi tool. Dihasilkan dari manifest, bukan dari listing pihak ketiga." },
  { key: "nango", label: "Nango (OAuth)", note: "1.024 provider OAuth dari Nango — ini lapisan koneksi, BUKAN katalog tool, jadi tidak menambah angka tools. 434-nya duplikat dari Composio/Glama/OpenConnector dan sengaja digabung, bukan dihitung dua kali." },
  { key: "metorial", label: "Metorial", note: "Platform MCP terkelola. Akun ini punya 1 integration provider aktif (GitHub) di instance Production." },
] as const;

export default function IntegrationsPage() {
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<string>("");
  const [items, setItems] = useState<Server[]>([]);
  const [total, setTotal] = useState(0);
  const [sources, setSources] = useState<Sources>({});
  const [uniqueSources, setUniqueSources] = useState<Sources>({});
  const [view, setView] = useState<"all" | "unique">("all");
  const [status, setStatus] = useState<string>("Memuat registry…");
  const [error, setError] = useState<string | null>(null);
  const [installing, setInstalling] = useState<string | null>(null);

  async function install(item: Server) {
    // Glama = endpoint milik pihak ketiga. Satu-satunya jalan yang jujur adalah
    // arahkan user ke listing resminya, bukan mengklaim kita bisa memasangnya.
    if (item.source === "glama" || item.source === "glama-connector") {
      if (item.source_url) window.open(item.source_url, "_blank", "noopener");
      setStatus(`${item.name} dibuka di Glama. Pasang langsung dari sana.`);
      return;
    }
    // Native providers are already wired into the runtime; "Pasang" would be a lie.
    if (item.source === "native") { setStatus(`${item.name} sudah aktif di runtime Katalir.`); return; }
    // Konfigurasi runtime ditentukan BACKEND (mcp_autoconfig), bukan tebakan UI:
    // preview menolak entri katalog metadata-only sebelum confirm dialog muncul.
    setInstalling(item.id); setError(null);
    let plan: { runtime: string; transport: string; package: string; missing_config: string[] } | null = null;
    try {
      const pv = await apiFetch("/mcp/auto-config/preview", { method: "POST", body: JSON.stringify({ mcp_id: item.id, config: {} }), timeoutMs: 8000 });
      if (!pv.ok) {
        const e = await pv.json().catch(() => null);
        throw new Error(typeof e?.detail === "string" ? e.detail : `${item.name} belum punya runtime tervalidasi.`);
      }
      plan = (await pv.json()).plan;
    } catch (err) {
      setError(err instanceof Error ? err.message : `Pemasangan ${item.name} gagal. Coba lagi.`);
      setInstalling(null);
      return;
    }
    const ok = plan!;
    if (!window.confirm(
      `Pasang ${item.name}?\n\nRuntime: ${ok.runtime} · ${ok.transport} · ${ok.package}` +
      (ok.missing_config.length ? `\n\nKonfigurasi belum lengkap: ${ok.missing_config.join(", ")}` : "")
    )) { setInstalling(null); return; }
    try {
      const r = await apiFetch("/mcp/install", { method: "POST", body: JSON.stringify({ mcp_id: item.id, config: {}, confirmed: true }), timeoutMs: 8000 });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const inst = (await r.json()).instance;
      setStatus(inst?.status === "needs_config"
        ? `${item.name} terpasang tetapi butuh konfigurasi. Buka Integrasi saya.`
        : `${item.name} dipasang. Buka Integrasi saya untuk kelola.`);
    } catch { setError(`Pemasangan ${item.name} gagal. Coba lagi.`); }
    finally { setInstalling(null); }
  }

  async function load(q = "", source = tab) {
    setStatus("Memuat registry…"); setError(null);
    try {
      if (source === "native") {
        const r = await apiFetch("/mcp/native", { timeoutMs: 15000 });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        const mapped: Server[] = (d.items ?? []).map((n: { id: string; name: string; summary: string; needs_credential: boolean; verification?: Server["verification"]; source: string }) => ({
          id: n.id, name: n.name, category: "native", description: n.summary,
          source: n.source, tools: [], tools_count: 1, no_auth: !n.needs_credential,
          verification: n.verification, runtime_verified: !n.needs_credential,
          install_config: { transport: "native" },
        }));
        setItems(mapped); setTotal(d.total ?? mapped.length);
        setStatus(`${d.total ?? mapped.length} provider native berjalan`);
      } else {
        const qs = new URLSearchParams({ limit: "50", search: q });
        if (source) qs.set("source", source);
        qs.set("view", view);
        const r = await apiFetch(`/mcp/registry?${qs.toString()}`, { timeoutMs: 15000 });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        setItems(d.items ?? []); setTotal(d.total ?? 0);
        setStatus(`${d.items?.length ?? 0} dari ${d.total ?? 0} integrasi`);
      }
      const sr = await apiFetch("/mcp/registry/sources", { timeoutMs: 15000 });
      if (sr.ok) {
        const j = await sr.json();
        setSources((j.sources ?? {}) as Sources);
        setUniqueSources((j.sources_unique ?? {}) as Sources);
      }
    } catch { setError("Registry tidak dapat dimuat. Coba lagi."); setStatus("Gagal memuat registry"); }
  }
  useEffect(() => { void load("", ""); }, []);
  function pickTab(key: string) { setTab(key); void load(search, key); }
  function pickView(v: "all" | "unique") { setView(v); void load(search, tab); }

  return <SimplePage title="Integrasi MCP" subtitle="Temukan koneksi untuk otomasi Anda.">
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2 sm:flex-row">
        <label className="relative flex-1"><span className="sr-only">Cari integrasi</span><Search className="absolute left-3 top-3 text-fg-muted" size={16}/><Input value={search} onChange={e => setSearch(e.target.value)} onKeyDown={e => e.key === "Enter" && load(search)} placeholder="Cari Telegram, Sheets, Slack…" className="pl-9" data-testid="integrations-search" /></label>
        <Button onClick={() => load(search)} data-testid="integrations-refresh">Cari</Button>
      </div>
      {/*
        Dedup toggle. "All" is the raw merged catalogue, "Unique" is one row per
        integration after collapsing cross-source duplicates. They differ by ~21%
        (29.558 vs 23.474), and showing only one of them either hides how much of
        the catalogue is duplicated or inflates the headline - so both are here,
        each labelled with its own total.
      */}
      <div className="flex items-center gap-2" role="group" aria-label="Tampilan katalog">
        {(["all", "unique"] as const).map(v => {
          const active = view === v;
          return <button key={v} onClick={() => pickView(v)} aria-pressed={active} data-testid={`view-toggle-${v}`}
            className={`rounded-full border px-3 py-1 text-xs transition ${active ? "border-primary bg-primary/10 text-primary" : "border-border text-fg-muted hover:text-fg"}`}>
            {v === "all" ? "All (mentah)" : "Unique (dedup)"}
          </button>;
        })}
        <span className="text-xs text-fg-muted" data-testid="view-hint">
          {view === "all"
            ? "Satu baris per entri katalog, duplikat antar sumber masih dihitung."
            : "Satu baris per integrasi; duplikat antar sumber sudah digabung."}
        </span>
      </div>
      <div role="tablist" aria-label="Sumber integrasi" className="flex flex-wrap gap-2">
        {TABS.map(t => {
          const pool = view === "all" ? sources : uniqueSources;
          const count = t.key === "" ? total : (pool as Record<string, number>)[t.key] ?? 0;
          const active = tab === t.key;
          return <button key={t.key || "all"} role="tab" aria-selected={active} data-testid={`source-tab-${t.key || "all"}`}
            onClick={() => pickTab(t.key)}
            className={`rounded-full border px-3 py-1.5 text-sm transition ${active ? "border-primary bg-primary/10 text-primary" : "border-border text-fg-muted hover:text-fg"}`}>
            {t.label} <span className="tabular-nums opacity-70">({count.toLocaleString("id-ID")})</span>
          </button>;
        })}
      </div>
      {TABS.filter(t => t.key === tab).map(t => (
        <p key={t.key || "all"} className="rounded-lg border border-border bg-fg-muted/5 p-3 text-xs text-fg-muted" data-testid="tab-note">{t.note}</p>
      ))}
      <p role="status" aria-live="polite" className="text-sm text-fg-muted">{status}</p>
      {error && <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm text-danger">{error}</div>}
      <div className="grid gap-3 sm:grid-cols-2">
        {items.map(item => { const b = badgeFor(item); return <Card key={item.id} data-testid="integration-card">
          <CardHeader><CardTitle className="truncate">{item.name} <span className={`ml-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${b.cls}`} data-testid={b.testid}>{b.label}</span></CardTitle><CardDescription>{item.category} · {item.tools?.length ?? item.tools_count ?? 0} tools · {SOURCE_LABEL[item.source ?? "toolsdk"] ?? item.source}</CardDescription></CardHeader>
          <CardContent className="flex flex-col gap-3">
            <p className="line-clamp-2 text-sm text-fg-muted">{item.description}</p>
            {/* WAJIB lisensi: tiap listing Glama tertaut ke halamannya di Glama.
                Tanpa rel nofollow/sponsored/ugc — itu syarat API Data License. */}
            {item.source_url && <a href={item.source_url} target="_blank" rel="noopener noreferrer" data-testid="attribution-link" className="text-xs text-primary hover:underline">View on Glama →</a>}
            <div className="flex gap-2"><Button size="sm" onClick={() => install(item)} loading={installing === item.id} data-testid="integration-install"><Plus size={14}/> Pasang</Button><Button size="sm" variant="ghost" onClick={() => window.location.href = `/integrations/${encodeURIComponent(item.id)}`}><ExternalLink size={14}/> Detail</Button></div>
          </CardContent>
        </Card>; })}
      </div>
      {!items.length && !error && <div className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-fg-muted">Belum ada hasil. Coba kata kunci lain.</div>}
      <Link href="/my-integrations" className="text-sm text-primary hover:underline">Kelola integrasi saya →</Link>
      <div className="rounded-lg border border-border bg-fg-muted/5 p-3 text-xs text-fg-muted" data-testid="meta-layer-note">
        <p><strong>5 meta-tool OpenConnector</strong> menjangkau 18.010 actions — bukan 18.010 tool terpisah.</p>
        <p className="mt-1">{total.toLocaleString("id-ID")} entri katalog · 11 action OpenConnector call-verified · {GLAMA_CALL_VERIFIED} integrasi Glama call-verified (dari 351 konektor no-auth diuji). Badge hanya menandai apa yang benar-benar diuji.</p>
      </div>
      {/* Kredit Glama: WAJIB di setiap halaman yang menampilkan data Glama
          (API Data License). Jangan dihapus, jangan ditambah rel nofollow. */}
      <p className="text-xs text-fg-subtle" data-testid="glama-attribution">
        Katalog server termasuk data dari{" "}
        <a href="https://glama.ai/mcp/servers" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">Glama</a>
      </p>
    </div>
  </SimplePage>;
}
