import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // TEMPORARY (deploy pipeline): static export untuk Cloudflare Pages (out/).
  // Kembalikan ke mode OpenNext (tanpa output:export) setelah deploy selesai.
  output: "export",
  images: { unoptimized: true },
};

export default nextConfig;
