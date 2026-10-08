import { defineConfig } from "@playwright/test";

/**
 * Config bukti-browser Template Gallery (Fitur #10) — 12 tes.
 *
 * Sama polanya dengan `playwright.mcp.config.ts` & `playwright.approval.config.ts`:
 * TANPA `webServer` dan TANPA `globalSetup`. Seluruh endpoint backend /templates
 * di-stub `page.route` di dalam spec, sehingga tes deterministik dan tidak
 * bergantung pada sesi. Yang diuji = bundle PRODUKSI yang benar-benar di-deploy,
 * ditunjuk lewat `E2E_BASE_URL`:
 *
 *   E2E_BASE_URL=https://katalir.de5.net          -> situs live (default)
 *   E2E_BASE_URL=https://proyek-agent.pages.dev   -> domain pages.dev
 *   E2E_BASE_URL=http://127.0.0.1:3000            -> out/ lokal
 */
const PORT = Number(process.env.E2E_PORT || 3000);
const BASE_URL = process.env.E2E_BASE_URL || "https://katalir.de5.net";

export default defineConfig({
  testDir: "./tests",
  testMatch: /templates-gallery\.spec\.ts/,
  timeout: 180000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: BASE_URL,
    viewport: { width: 1440, height: 1000 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [{ name: "templates" }],
});
