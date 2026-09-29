"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Plus, ExternalLink } from "lucide-react";
import { SimplePage } from "@/components/SimplePage";
import { OAuthConnections } from "@/components/OAuthConnections";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { SearchBar } from "@/components/search-bar";

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
 *
 * F4.3 changed where this decision is made. The tier now arrives from the
 * backend as `runtime_tier`, computed by the same function the tier *filter*
 * uses. It used to be re-derived here, which is exactly the shape of bug where
 * a filter returns rows that are not the rows their badge claims: two copies of
 * one rule will eventually disagree. The local fallback stays for the native
 * tab, which is built client-side and never passes through the registry.
 */
/** The four tiers, in the same order the backend ranks them. */
const RUNTIME_TIERS = ["call_verified", "auth_required", "tools_listed", "discovered"] as const;

const TIER_STYLE: Record<string, { cls: string; testid: string }> = {
  call_verified: { cls: "bg-emerald-500/15 text-emerald-600", testid: "badge-ready" },
  auth_required: { cls: "bg-amber-500/15 text-amber-600", testid: "badge-auth" },
  tools_listed: { cls: "bg-sky-500/15 text-sky-600", testid: "badge-listed" },
  discovered: { cls: "bg-fg-muted/15 text-fg-muted", testid: "badge-catalog" },
};

function badgeFor(item: Server): { label: string; cls: string; testid: string } {
  const shipped = (item as { runtime_tier?: string }).runtime_tier;
  if (shipped && TIER_STYLE[shipped]) {
    return { label: shipped, ...TIER_STYLE[shipped] };
  }
  const v = item.verification ?? {};
  if (v.call_verified || item.runtime_verified)
    return { label: "call_verified", ...TIER_STYLE.call_verified };
  // no_auth === false is an explicit statement that a credential is required.
  // Absent means unknown, so it must NOT be treated as auth_required.
  if (item.no_auth === false)
    return { label: "auth_required", ...TIER_STYLE.auth_required };
  if (v.tools_listed)
    return { label: "tools_listed", ...TIER_STYLE.tools_listed };
  return { label: "discovered", ...TIER_STYLE.discovered };
}

/**
 * Source label per `source` key, with a deliberate fallback.
 *
 * Nango and Metorial were missing here, so their cards rendered the raw key
 * ("nango") next to every other source showing a proper name. A missing label
 * is a small thing, but it is the same failure as a hardcoded tab count: the UI
 * implying a source is not really wired up when it is.
 */
const SOURCE_LABEL: Record<string, string> = { native: "Native MCP", glama: "Glama", "glama-connector": "Glama Connector", composio: "Composio", openconnector: "OpenConnector", toolsdk: "ToolSDK", "openapi-generated": "OpenAPI", nango: "Nango (OAuth)", metorial: "Metorial" };

/**
 * Where an item's external link actually goes.
 *
 * The attribution link used to say "View on Glama" for every item with a
 * `source_url`, which put "View on Glama" on all 1.024 Nango cards pointing at
 * Nango. Only the Glama sources may claim that link: the nofollow/sponsored
 * rel is a Glama Data License requirement, and naming a different vendor while
 * pointing somewhere else is simply a wrong link.
 */
const ATTRIBUTION_LABEL: Record<string, string> = { glama: "View on Glama →", "glama-connector": "View on Glama →" };

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
  const [tier, setTier] = useState("");
  const [category, setCategory] = useState("");
  const [categories, setCategories] = useState<Array<{ category: string; count: number }>>([]);
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

  async function load(q = "", source = tab, opts?: { view?: "all" | "unique"; tier?: string; category?: string }) {
    // The overrides exist because of a real bug this phase caught: the pickers
    // used to call setTier(t) and then load(), and load() read `tier` from the
    // closure - which is still the OLD value, because React has not re-rendered
    // yet. The filter silently did nothing. Passing the value through makes the
    // load self-consistent instead of depending on a render it has not had.
    const v = opts?.view ?? view;
    const t = opts?.tier ?? tier;
    const cat = opts?.category ?? category;
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
        if (cat) qs.set("category", cat);
        if (t) qs.set("tier", t);
        qs.set("view", v);
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
      // Facets follow the active source, so switching tab cannot leave a
      // category selected that belongs to a different source and returns 0.
      const cr = await apiFetch(`/mcp/registry/categories?limit=40${source ? `&source=${encodeURIComponent(source)}` : ""}`, { timeoutMs: 15000 });
      if (cr.ok) setCategories((await cr.json()).categories ?? []);
    } catch { setError("Registry tidak dapat dimuat. Coba lagi."); setStatus("Gagal memuat registry"); }
  }
  useEffect(() => { void load("", ""); }, []);
  // Every picker passes its own new value through. Calling setX() and then
  // load() without the override is the stale-closure bug described on load().
  function pickTab(key: string) { setTab(key); setCategory(""); void load(search, key, { category: "" }); }
  function pickView(v: "all" | "unique") { setView(v); void load(search, tab, { view: v }); }
  function pickTier(t: string) { setTier(t); void load(search, tab, { tier: t }); }
  function pickCategory(c: string) { setCategory(c); void load(search, tab, { category: c }); }
  function clearFilters() { setTier(""); setCategory(""); void load(search, tab, { tier: "", category: "" }); }

  return <SimplePage title="Integrasi MCP" subtitle="Temukan koneksi untuk otomasi Anda.">
    <div className="flex flex-col gap-4">
      {/*
        KONEKSI AKUN SAYA — kartu OAuth pindah ke sini dari /settings.

        User bertanya "di mana connect Slack, di mana GitHub?" karena
        /settings mencampur akun dengan koneksi. Kartu ini menjawab
        pertanyaan itu di tempat yang mereka cari, dan /settings cukup
        menaut ke halaman ini.

        Dicetak sebelum baris pencarian dengan sengaja: koneksi yang SUDAH
        aktif adalah hal yang paling ingin dilihat user, bukan katalog.
      */}
      <OAuthConnections
        title="Koneksi Anda"
        description="Hubungkan akun yang boleh Katalir gunakan atas nama Anda. Token disimpan terenkripsi di Brankas."
      />
      {/* Baris pencarian dipindah ke BAWAH tab sumber (lihat blok tablist
          di bawah). Di atas ia terpisah dari filter yang mengaktifkannya;
          di bawah urutannya mengikuti yang dilakukan user: pilih sumber,
          lalu ketik kebutuhannya. Catatan lama "Gabungan semua sumber di
          katalog." dihapus karena hint baris pencarian sekarang
          menjelaskan hal itu lebih baik, dan tidak perlu dua kali. */}
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
      {/*
        F4.3 filters. The tier filter is evaluated by the same backend function
        that assigns the badge, so "call_verified" cannot return a row badged
        something else. Category options come from a real facet endpoint rather
        than a hardcoded list, so every option shown has a non-zero result.
      */}
      <div className="flex flex-col gap-2" data-testid="integrations-filters">
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter status runtime">
          <span className="text-xs text-fg-muted">Status runtime:</span>
          {(["", ...RUNTIME_TIERS] as const).map(t => {
            const active = tier === t;
            return <button key={t || "any"} onClick={() => pickTier(t)} aria-pressed={active}
              data-testid={`tier-filter-${t || "any"}`}
              className={`rounded-full border px-3 py-1 text-xs transition ${active ? "border-primary bg-primary/10 text-primary" : "border-border text-fg-muted hover:text-fg"}`}>
              {t || "Semua"}
            </button>;
          })}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-xs text-fg-muted">
            <span>Kategori:</span>
            <select value={category} onChange={e => pickCategory(e.target.value)} data-testid="category-filter"
              className="rounded-md border border-border bg-surface px-2 py-1 text-xs text-fg">
              <option value="">Semua kategori</option>
              {categories.map(c => <option key={c.category} value={c.category}>{c.category} ({c.count.toLocaleString("id-ID")})</option>)}
            </select>
          </label>
          {(tier || category) && <button onClick={clearFilters}
            data-testid="filters-clear" className="rounded-full border border-border px-3 py-1 text-xs text-fg-muted hover:text-fg">
            Bersihkan filter
          </button>}
        </div>
      </div>
      <div role="tablist" aria-label="Sumber integrasi" className="flex flex-wrap gap-2">
        {TABS.map(t => {
          const pool = view === "all" ? sources : uniqueSources;
          const count = t.key === "" ? total : (pool as Record<string, number>)[t.key] ?? 0;
          const active = tab === t.key;
          return <button key={t.key || "all"} role="tab" aria-selected={active} data-testid={`source-tab-${t.key || "all"}`}
            onClick={() => pickTab(t.key)}
            className={`rounded-full border px-3 py-1.5 text-sm transition ${active ? "border-primary bg-primary/10 text-primary" : "border-border text-fg-muted hover:text-fg"}`}>
            {/* Angka jumlah di dalam tab.
              `opacity-70` dulu menurunkan kontras jadi 3.55:1 di atas
              bg #fafafa -- di bawah WCAG AA 4.5:1 untuk teks 14px. Angka ini
              justru informasi (berapa banyak integrasi per sumber), jadi
              diredupkan berarti informasi penting dibuat tak terbaca. `text-fg-muted` tanpa opacity sudah 4.6:1. */}
          {t.label} <span className="tabular-nums text-fg-muted">({count.toLocaleString("id-ID")})</span>
          </button>;
        })}
      </div>
      {/* Task C: baris pencarian duduk DI BAWAH tab sumber, menggantikan
          catatan lama "Gabungan semua sumber di katalog.".
          Task D: pencarian berjalan seketika dengan debounce 250 ms, jadi
          user tidak perlu menekan Enter atau tombol Cari. */}
      <SearchBar onSearch={(q) => { setSearch(q); void load(q); }} />
      <p role="status" aria-live="polite" className="text-sm text-fg-muted">{status}</p>
      {error && <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm text-danger">{error}</div>}
      {/* `min-w-0` on the grid: a grid item defaults to min-width:auto, so the
          `truncate` title below (white-space:nowrap) would otherwise set the
          track's minimum width and push the whole grid past the viewport —
          measured 12px of horizontal scroll at 390px wide. min-w-0 lets the
          item shrink so truncate actually does its job. */}
      <div className="grid min-w-0 gap-3 sm:grid-cols-2">
        {items.map(item => { const b = badgeFor(item); return <Card key={item.id} data-testid="integration-card" className="min-w-0">
          <CardHeader><CardTitle className="truncate">{item.name} <span className={`ml-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${b.cls}`} data-testid={b.testid}>{b.label}</span></CardTitle><CardDescription>{item.category} · {item.tools?.length ?? item.tools_count ?? 0} tools · {SOURCE_LABEL[item.source ?? "toolsdk"] ?? item.source}</CardDescription></CardHeader>
          <CardContent className="flex flex-col gap-3">
            <p className="line-clamp-2 text-sm text-fg-muted">{item.description}</p>
            {/* WAJIB lisensi: tiap listing Glama tertaut ke halamannya di Glama.
                Tanpa rel nofollow/sponsored/ugc — itu syarat API Data License. */}
            {item.source_url && (ATTRIBUTION_LABEL[item.source ?? ""]
              ? <a href={item.source_url} target="_blank" rel="noopener noreferrer nofollow sponsored" data-testid="attribution-link" className="text-xs text-primary hover:underline">{ATTRIBUTION_LABEL[item.source ?? ""]}</a>
              : <a href={item.source_url} target="_blank" rel="noopener noreferrer" data-testid="attribution-link" className="text-xs text-fg-muted hover:underline">Lihat detail →</a>)}
            <div className="flex gap-2"><Button size="sm" onClick={() => install(item)} loading={installing === item.id} data-testid="integration-install"><Plus size={14}/> Pasang</Button><Button size="sm" variant="ghost" onClick={() => window.location.href = `/integrations/catalog?slug=${encodeURIComponent(item.id)}`} data-testid="integration-detail-link"><ExternalLink size={14}/> Detail</Button></div>
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
