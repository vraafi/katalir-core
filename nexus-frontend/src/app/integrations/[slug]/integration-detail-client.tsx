"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { SimplePage } from "@/components/SimplePage";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";

type Tool = { name: string; description?: string };
type Server = {
  id: string; name: string; category: string; description: string;
  tools?: Tool[];
  /**
   * Jumlah tool yang TAHU ADA, terpisah dari `tools`.
   *
   * Keduanya tidak selalu sinkron: `cloudflare` mengembalikan `tools=[]`
   * tapi `tools_count=20`, `openai` `tools=[]` tapi `tools_count=126`.
   * Backend mencatat jumlahnya tapi tidak mengirim nama toolnya, jadi
   * menampilkan "0 tools" untuk record seperti itu salah dan wasting —
   */
  tools_count?: number;
  source?: string;
  source_url?: string;
  install_config?: { transport?: string; package?: string };
};

/** Label sumber yang enak dibaca, bukan slug mentah. */
const SOURCE_LABEL: Record<string, string> = {
  composio: "Composio",
  nango: "Nango",
  glama: "Glama",
  github: "GitHub",
  local: "Katalog internal",
};

/**
 * Tiga kondisi, dan tidak boleh ada kondisi keempat "daftar kosong diam".
 * - array terisi  -> tampilkan namanya
 * - hanya count   -> jujur sebut jumlahnya, jangan pretend 0
 * - tidak ada data-> arahkan ke sumber, bukan menampilkan 0
 */
function ToolsSection({ item }: { item: Server }) {
  const listed = item.tools ?? [];
  const src = item.source ? (SOURCE_LABEL[item.source] ?? item.source) : null;
  const count = listed.length || (item.tools_count ?? 0);

  if (listed.length > 0) {
    return (
      <section aria-labelledby="tools-heading">
        <h2 id="tools-heading" className="mb-2 text-subhead font-semibold text-fg">
          Tools ({listed.length})
        </h2>
        <ul className="list-disc pl-5 text-sm text-fg-muted">
          {listed.slice(0, 60).map((t) => (
            <li key={t.name}>{t.name}</li>
          ))}
        </ul>
        {listed.length > 60 && (
          <p className="mt-2 text-xs text-fg-muted">
            Menampilkan 60 pertama dari {listed.length}. Daftar lengkap tersedia di sumber.
          </p>
        )}
      </section>
    );
  }

  if (count > 0) {
    // Backend tahu ada `count` tool tapi tidak mengirim nama-namanya.
    // Menyebut angka ini lebih jujur dan lebih berguna daripada "0".
    return (
      <section aria-labelledby="tools-heading" data-testid="tools-count-only">
        <h2 id="tools-heading" className="mb-2 text-subhead font-semibold text-fg">
          Tools ({count})
        </h2>
        <p className="text-sm text-fg-muted">
          {count} tool terdaftar. Katalog kami menyimpan jumlahnya, nama toolnya
          diambil dari{src ? ` ${src}` : " sumber integrasi"} saat kamu memasang.
        </p>
        {item.source_url && (
          <a
            href={item.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2 inline-block text-sm text-fg underline underline-offset-4"
          >
            Lihat daftar tool di {src ?? "sumber"} &rarr;
          </a>
        )}
      </section>
    );
  }

  // Tidak ada data tool sama sekali. Tetap jangan tampilkan angka 0.
  return (
    <section aria-labelledby="tools-heading" data-testid="tools-no-data">
      <h2 id="tools-heading" className="mb-2 text-subhead font-semibold text-fg">
        Tools
      </h2>
      <p className="text-sm text-fg-muted">
        {src
          ? `Integrasi ini tidak mencantumkan daftar tool di katalog. Keterlengkapan yang tersedia bisa dilihat di ${src}.`
          : "Integrasi ini tidak mencantumkan daftar tool di katalog."}
      </p>
      {item.source_url && (
        <a
          href={item.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-block text-sm text-fg underline underline-offset-4"
        >
          Lihat sumber integrasi &rarr;
        </a>
      )}
    </section>
  );
}

export default function IntegrationDetailClient() {
  const params = useParams<{ slug: string }>(); const router = useRouter();
  const [item, setItem] = useState<Server | null>(null); const [error, setError] = useState(false);
  // `?slug=` (query) menang atas segmen route. Alasannya hanya ada SATU
  // halaman yang di-prerender: `generateStaticParams` hanya menghasilkan
  // "catalog", jadi /integrations/<apa-pun> selain itu 404 di static
  // export. Dengan query, semua slug berbagi satu file HTML yang sudah
  // ada di cache edge.
  //
  // Query dibaca dari `window.location`, bukan `useSearchParams`, mengikuti
  // pola yang sudah dipakai halaman /settings. `useSearchParams` memaksa
  // Suspense boundary, dan di `output: "export"` itu menambah berat
  // tanpa manfaat.
  //
  // PENTING: state awal adalah `null`, bukan `params.slug`. Kalau diisi
  // `params.slug` sejak awal, ada DUA request: yang pertama untuk "catalog"
  // (yang 404), yang kedua untuk slug asli. Yang 404 itu men-set `error`
  // lebih dulu, dan karena `if (error)` diperiksa sebelum `if (item)`,
  // halaman menampilkan "tidak ditemukan" walau request yang benar
  // sudah 200. Itu terjadi sungguhan dan ketahuan lewat log jaringan.
  const [slug, setSlug] = useState<string | null>(null);
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("slug");
    setSlug(q || params.slug || null);
  }, [params.slug]);
  useEffect(() => {
    if (!slug) return;
    let cancelled = false;
    setItem(null);
    setError(false);
    apiFetch(`/mcp/registry/${encodeURIComponent(slug)}`, { timeoutMs: 12_000 })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => { if (!cancelled) setItem(d); })
      .catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [slug]);
  if (error) return <SimplePage title="Integrasi tidak ditemukan"><p>Server ini tidak tersedia di registry.</p></SimplePage>;
  if (!item) return <SimplePage title="Memuat integrasi…"><p className="text-sm text-fg-muted">Mengambil detail server…</p></SimplePage>;
  return <SimplePage title={item.name} subtitle={item.category}>
    <Card><CardHeader><CardTitle>{item.name}</CardTitle><CardDescription>{item.description}</CardDescription></CardHeader><CardContent className="flex flex-col gap-4"><p className="text-sm text-fg-muted">Transport metadata: {item.install_config?.transport ?? "unknown"}</p><ToolsSection item={item} /><div className="flex gap-2"><Button onClick={() => window.alert("Pemasangan membutuhkan konfirmasi pengguna.")}>Pasang integrasi</Button><Button variant="ghost" onClick={() => router.push("/integrations")}>Kembali</Button></div></CardContent></Card>
  </SimplePage>;
}
