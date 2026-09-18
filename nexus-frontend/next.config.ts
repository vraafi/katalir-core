import type { NextConfig } from "next";

// Header keamanan bersama (dipakai `headers()` di bawah).
const securityHeaders = [
  { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  // TEMPORARY (deploy pipeline): static export untuk Cloudflare Pages (out/).
  // Kembalikan ke mode OpenNext (tanpa output:export) setelah deploy selesai.
  output: "export",
  images: { unoptimized: true },
  // PENTING: pada `output: "export"` fungsi ini DIABAIKAN untuk aset statis.
  // Dibuktikan dengan build pada task ini: `next build` SUKSES tetapi menulis
  // peringatan `export-no-custom-routes` ("...detected (headers). See more info
  // here: https://nextjs.org/docs/messages/export-no-custom-routes"), dan tidak
  // satu pun header muncul di response statis. Sumber kebenaran header untuk
  // produksi adalah `public/_headers` (Cloudflare Pages, ikut ke `out/_headers`).
  // Blok ini tetap ditulis supaya konfigurasi langsung efektif saat app kembali
  // ke OpenNext/Workers, dan agar dev-server (yang menghormati headers())
  // berperilaku sama dengan produksi.
  //
  // CSP sengaja TIDAK di sini melainkan di `public/_headers` sebagai
  // `Content-Security-Policy-Report-Only` (tahap kumpulkan pelanggaran dulu).
  async headers() {
    return [{ source: "/(.*)", headers: securityHeaders }];
  },
};

export default nextConfig;
