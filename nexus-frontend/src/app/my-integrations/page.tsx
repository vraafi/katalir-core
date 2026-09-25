"use client";

import { useEffect, useState } from "react";
import { SimplePage } from "@/components/SimplePage";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";

type Instance = { mcp_id: string; status: string; config: Record<string, unknown> };
export default function MyIntegrationsPage() {
  const [items, setItems] = useState<Instance[]>([]); const [state, setState] = useState("Memuat…");
  async function load() { setState("Memuat…"); try { const r = await apiFetch("/mcp/my-instances", { timeoutMs: 8000 }); if (!r.ok) throw new Error(); setItems((await r.json()).instances ?? []); setState("Siap"); } catch { setState("Gagal memuat"); } }
  useEffect(() => { void load(); }, []);
  return <SimplePage title="Integrasi saya" subtitle="Kelola instance MCP milik akun Anda."><div role="status" aria-live="polite" className="text-sm text-fg-muted">{state}</div><div className="flex flex-col gap-3">{items.map(i => <Card key={i.mcp_id}><CardHeader><CardTitle>{i.mcp_id}</CardTitle></CardHeader><CardContent className="flex items-center justify-between"><span className="text-sm text-fg-muted">{i.status}</span><Button variant="ghost" onClick={async () => { await apiFetch(`/mcp/uninstall/${encodeURIComponent(i.mcp_id)}`, { method: "DELETE", timeoutMs: 8000 }); await load(); }}>Putuskan</Button></CardContent></Card>)}{!items.length && <p className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-fg-muted">Belum ada integrasi aktif.</p>}</div></SimplePage>;
}
