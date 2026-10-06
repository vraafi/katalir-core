import { defineConfig } from "@playwright/test";

/**
 * Config bukti-browser integrasi MCP (2026-10-06).
 *
 * Sama polanya dengan `playwright.approval.config.ts`: TANPA `webServer` dan
 * TANPA `globalSetup`, karena SELURUH endpoint backend di-stub `page.route` di
 * dalam spec. Server (build produksi / dev server / situs yang sudah
 * di-deploy) dijalankan terpisah dan ditunjuk lewat `E2E_BASE_URL`:
 *
 *   E2E_BASE_URL=https://proyek-agent.pages.dev  -> situs live
 *   (default)                                    -> http://127.0.0.1:3000
 *
 * `playwright.config.ts` repo tidak dipakai: ia menyalakan uvicorn +
 * e2e-prod-server sendiri dengan `reuseExistingServer: false`, sehingga selalu
 * bentrok dengan server yang sudah jalan.
 */
const PORT = Number(process.env.E2E_PORT || 3000);
const BASE_URL = process.env.E2E_BASE_URL || `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./tests",
  testMatch: /mcp-workflow\.spec\.ts/,
  timeout: 180000,
  reporter: [["line"]],
  use: {
    baseURL: BASE_URL,
    viewport: { width: 1440, height: 1000 },
    screenshot: "off",
  },
  projects: [{ name: "mcp" }],
});
