"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Search, Plus, ExternalLink } from "lucide-react";
import { SimplePage } from "@/components/SimplePage";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

type Server = { id: string; name: string; category: string; description: string; tools?: { name: string }[]; tools_count?: number; install_config?: { transport?: string; package?: string }; source?: string; source_url?: string; attribution_required?: boolean; no_auth?: boolean; runtime_verified?: boolean; verification?: { discovered?: boolean; tools_listed?: boolean; call_verified?: boolean } };

type Sources = Record<string, number> & { glama?: number; "glama-connector"?: number; composio?: number; openconnector?: number };

/**
 * Badge status. Sengaja tiga tingkat, karena "ada di katalog" != "bisa dipakai":
 *   call_verified  -> hijau  (tools/call nyata berhasil)
 *   tools_listed   -> kuning (terdaftar & butuh kredensial)
 *   discovered     -> abu   (metadata saja)
 */
function badgeFor(item: Server): { label: string; cls: string; testid: string } {
  const v = item.verification ?? {};
  if (v.call_verified || item.runtime_verified) return { label: "Ready", cls: "bg-emerald-500/15 text-emerald-600", testid: "badge-ready" };
  if (v.tools_listed) return { label: "Auth required", cls: "bg-amber-500/15 text-amber-600", testid: "badge-auth" };
  return { label: "Catalog", cls: "bg-fg-muted/15 text-fg-muted", testid: "badge-catalog" };
}

const SOURCE_LABEL: Record<string, string> = { glama: "Glama", "glama-connector": "Glama", composio: "Composio", openconnector: "OpenConnector", toolsdk: "Native" };
const TABS = [
  { key: "", label: "All" },
  { key: "toolsdk", label: "Native" },
  { key: "openconnector", label: "OpenConnector" },
  { key: "composio", label: "Composio" },
  { key: "glama", label: "Glama" },
] as const;

export default function IntegrationsPage() {
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<string>("");
  const [items, setItems] = useState<Server[]>([]);
  const [total, setTotal] = useState(0);
  const [sources, setSources] = useState<Sources>({});
  const [status, setStatus] = useState<string>("Memuat registry…");
  const [error, setError] = useState<string | null>(null);
  const [installing, setInstalling] = useState<string | null>(null);

  async function install(item: Server) {
    const runtimeReady = item.install_config?.transport === "stdio" || item.install_config?.transport === "http" || item.install_config?.transport === "sse" || ["everything", "fetch", "memory", "filesystem", "time"].includes(item.id);
    // Glama = endpoint milik pihak ketiga. Satu-satunya jalan yang jujur adalah
    // arahkan user ke listing resminya, bukan mengklaim kita bisa memasangnya.
    if (item.source === "glama" || item.source === "glama-connector") {
      if (item.source_url) window.open(item.source_url, "_blank", "noopener");
      setStatus(`${item.name} dibuka di Glama. Pasang langsung dari sana.`);
      return;
    }
    if (!runtimeReady) { setError(`${item.name} masih metadata-only dan belum bisa dipasang otomatis.`); return; }
    if (!window.confirm(`Pasang ${item.name}? Anda dapat mengaturnya setelah dipasang.`)) return;
    setInstalling(item.id); setError(null);
    try {
      const r = await apiFetch("/mcp/install", { method: "POST", body: JSON.stringify({ mcp_id: item.id, config: {}, confirmed: true }), timeoutMs: 8000 });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setStatus(`${item.name} dipasang. Buka Integrasi saya untuk kelola.`);
    } catch { setError(`Pemasangan ${item.name} gagal. Coba lagi.`); }
    finally { setInstalling(null); }
  }

  async function load(q = "", source = tab) {
    setStatus("Memuat registry…"); setError(null);
    try {
      const qs = new URLSearchParams({ limit: "50", search: q });
      if (source) qs.set("source", source);
      const r = await apiFetch(`/mcp/registry?${qs.toString()}`, { timeoutMs: 15000 });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setItems(d.items ?? []); setTotal(d.total ?? 0); setStatus(`${d.items?.length ?? 0} dari ${d.total ?? 0} integrasi`);
      if (d.sources) setSources(d.sources as Sources);
    } catch { setError("Registry tidak dapat dimuat. Coba lagi."); setStatus("Gagal memuat registry"); }
  }
  useEffect(() => { void load("", ""); }, []);
  function pickTab(key: string) { setTab(key); void load(search, key); }

  return <SimplePage title="Integrasi MCP" subtitle="Temukan koneksi untuk otomasi Anda.">
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2 sm:flex-row">
        <label className="relative flex-1"><span className="sr-only">Cari integrasi</span><Search className="absolute left-3 top-3 text-fg-muted" size={16}/><Input value={search} onChange={e => setSearch(e.target.value)} onKeyDown={e => e.key === "Enter" && load(search)} placeholder="Cari Telegram, Sheets, Slack…" className="pl-9" data-testid="integrations-search" /></label>
        <Button onClick={() => load(search)} data-testid="integrations-refresh">Cari</Button>
      </div>
      <div role="tablist" aria-label="Sumber integrasi" className="flex flex-wrap gap-2">
        {TABS.map(t => {
          const count = t.key === "" ? total : (t.key === "glama" ? (sources.glama ?? 0) + (sources["glama-connector"] ?? 0) : (sources as Record<string, number>)[t.key] ?? 0);
          const active = tab === t.key;
          return <button key={t.key || "all"} role="tab" aria-selected={active} data-testid={`source-tab-${t.key || "all"}`}
            onClick={() => pickTab(t.key)}
            className={`rounded-full border px-3 py-1.5 text-sm transition ${active ? "border-primary bg-primary/10 text-primary" : "border-border text-fg-muted hover:text-fg"}`}>
            {t.label} <span className="tabular-nums opacity-70">({count.toLocaleString("id-ID")})</span>
          </button>;
        })}
      </div>
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
        <p><strong>18.010 actions OpenConnector</strong> dijangkau lewat 5 meta-tool MCP (list_apps, list_connections, search_actions, get_action_guide, execute_action) — bukan 18.010 tool terpisah.</p>
        <p className="mt-1">{total.toLocaleString("id-ID")} entri katalog · 11 action OpenConnector call-verified · 28 konektor Glama terverifikasi runtime. Badge hanya menandai apa yang benar-benar diuji.</p>
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
