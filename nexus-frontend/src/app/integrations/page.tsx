"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Search, Plus, ExternalLink } from "lucide-react";
import { SimplePage } from "@/components/SimplePage";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

type Server = { id: string; name: string; category: string; description: string; tools?: { name: string }[]; install_config?: { transport?: string } };

export default function IntegrationsPage() {
  const [search, setSearch] = useState("");
  const [items, setItems] = useState<Server[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState<string>("Memuat registry…");
  const [error, setError] = useState<string | null>(null);

  async function load(q = "") {
    setStatus("Memuat registry…"); setError(null);
    try {
      const r = await apiFetch(`/mcp/registry?limit=50&search=${encodeURIComponent(q)}`, { timeoutMs: 8000 });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setItems(d.items ?? []); setTotal(d.total ?? 0); setStatus(`${d.items?.length ?? 0} dari ${d.total ?? 0} integrasi`);
    } catch { setError("Registry tidak dapat dimuat. Coba lagi."); setStatus("Gagal memuat registry"); }
  }
  useEffect(() => { void load(); }, []);

  return <SimplePage title="Integrasi MCP" subtitle="Temukan koneksi untuk otomasi Anda.">
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2 sm:flex-row">
        <label className="relative flex-1"><span className="sr-only">Cari integrasi</span><Search className="absolute left-3 top-3 text-fg-muted" size={16}/><Input value={search} onChange={e => setSearch(e.target.value)} onKeyDown={e => e.key === "Enter" && load(search)} placeholder="Cari Telegram, Sheets, Slack…" className="pl-9" data-testid="integrations-search" /></label>
        <Button onClick={() => load(search)} data-testid="integrations-refresh">Cari</Button>
      </div>
      <p role="status" aria-live="polite" className="text-sm text-fg-muted">{status}</p>
      {error && <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm text-danger">{error}</div>}
      <div className="grid gap-3 sm:grid-cols-2">
        {items.map(item => <Card key={item.id} data-testid="integration-card">
          <CardHeader><CardTitle className="truncate">{item.name}</CardTitle><CardDescription>{item.category} · {item.tools?.length ?? 0} tools</CardDescription></CardHeader>
          <CardContent className="flex flex-col gap-3"><p className="line-clamp-2 text-sm text-fg-muted">{item.description}</p><div className="flex gap-2"><Button size="sm" onClick={() => alert(`Pemasangan ${item.name} membutuhkan konfirmasi dan konfigurasi.`)} data-testid="integration-install"><Plus size={14}/> Pasang</Button><Button size="sm" variant="ghost" onClick={() => window.location.href = `/integrations/${encodeURIComponent(item.id)}`}><ExternalLink size={14}/> Detail</Button></div></CardContent>
        </Card>)}
      </div>
      {!items.length && !error && <div className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-fg-muted">Belum ada hasil. Coba kata kunci lain.</div>}
      <Link href="/my-integrations" className="text-sm text-primary hover:underline">Kelola integrasi saya →</Link>
      <p className="text-xs text-fg-subtle">Total katalog: {total}. Metadata belum tentu berarti server runtime tervalidasi.</p>
    </div>
  </SimplePage>;
}
