"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { SimplePage } from "@/components/SimplePage";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";

type Server = { id: string; name: string; category: string; description: string; tools?: { name: string; description?: string }[]; install_config?: { transport?: string; package?: string } };

/** Static export needs explicit dynamic routes; runtime registry data is still loaded client-side. */
export function generateStaticParams() { return []; }

export default function IntegrationDetailPage() {
  const params = useParams<{ slug: string }>(); const router = useRouter();
  const [item, setItem] = useState<Server | null>(null); const [error, setError] = useState(false);
  useEffect(() => { apiFetch(`/mcp/registry/${encodeURIComponent(params.slug)}`, { timeoutMs: 8000 }).then(r => r.ok ? r.json() : Promise.reject()).then(setItem).catch(() => setError(true)); }, [params.slug]);
  if (error) return <SimplePage title="Integrasi tidak ditemukan"><p>Server ini tidak tersedia di registry.</p></SimplePage>;
  if (!item) return <SimplePage title="Memuat integrasi…"><p className="text-sm text-fg-muted">Mengambil detail server…</p></SimplePage>;
  return <SimplePage title={item.name} subtitle={item.category}>
    <Card><CardHeader><CardTitle>{item.name}</CardTitle><CardDescription>{item.description}</CardDescription></CardHeader><CardContent className="flex flex-col gap-4"><p className="text-sm text-fg-muted">Transport metadata: {item.install_config?.transport ?? "unknown"}</p><ul className="list-disc pl-5 text-sm">{item.tools?.map(t => <li key={t.name}>{t.name}</li>)}</ul><div className="flex gap-2"><Button onClick={() => window.alert("Pemasangan membutuhkan konfirmasi pengguna.")}>Pasang integrasi</Button><Button variant="ghost" onClick={() => router.push("/integrations")}>Kembali</Button></div></CardContent></Card>
  </SimplePage>;
}

