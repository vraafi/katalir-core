import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Purely client-side app (backend on FastAPI) => static export for Cloudflare Pages.
  // `next build` emits a fully static `out/` directory that Wrangler deploys.
  output: "export",
};

export default nextConfig;