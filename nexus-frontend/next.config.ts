import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Opsi B: OpenNext Cloudflare Workers — RSC, Server Actions, streaming aktif.
  // Deploy via `opennextjs-cloudflare build && opennextjs-cloudflare deploy`.
  // JANGAN pakai output:export (itu mematikan semua fitur di atas).
};

export default nextConfig;
