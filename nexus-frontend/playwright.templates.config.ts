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

/**
 * Output dir sengaja DI LUAR workspace (default ke TEMP) agar Playwright tidak
 * menghapus ratusan artefak di dalam repo. Guard `safe-delete` memblokir
 * penghapusan massal (>50 berkas) dan dulu menggagalkan `next build`.
 * Override dengan PW_OUTPUT_DIR bila perlu.
 */
const OUTPUT_DIR =
  process.env.PW_OUTPUT_DIR ||
  `${process.env.TEMP || process.env.TMPDIR || "/tmp"}/katalir_pw_out/templates`;

/**
 * testMatch dapat di-override agar config yang sama bisa menjalankan suite
 * live (tanpa stub) maupun suite stub 12 tes.
 *   E2E_SPEC=templates-live  -> hanya tests/templates-live.spec.ts
 */
const SPEC = process.env.E2E_SPEC;
const TEST_MATCH = SPEC
  ? new RegExp(`${SPEC.replace(/\.spec\.ts$/, "")}\\.spec\\.ts`)
  : /templates-gallery\.spec\.ts/;

export default defineConfig({
  testDir: "./tests",
  testMatch: TEST_MATCH,
  outputDir: OUTPUT_DIR,
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
