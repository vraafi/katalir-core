import { defineConfig } from "@playwright/test";

/**
 * Hard test UI node "code" di Canvas Builder — menguji BUNDLE PRODUKSI (`out/`).
 *
 * KENAPA BUNDLE PRODUKSI, BUKAN `next dev`:
 * fitur node code menyentuh `canvas-store` (default config saat node ditambah),
 * `ConfigPanel` (selector bahasa + editor + timeout), `Palette` (warna token
 * `--node-code-color`), dan `CanvasNode` (subtitle/preview). Semua itu adalah
 * perilaku RUNTIME BUNDLE. Dev server pernah meloloskan bug badge/filter karena
 * perilakunya berbeda dari hasil build (lihat kepala `playwright.chatui.config.ts`).
 *
 * KENAPA PORT 3110, BUKAN 3000/3100:
 * harness dev fase 3 memakai 3000 dan harness chat-ui memakai 3100. Memakai port
 * ketiga menghindari `reuseExistingServer` menyambung ke server yang salah
 * (kejadian nyata: tes menembak dev server lalu mengukur perilaku dev).
 *
 * CATATAN CSP: `scripts/serve-out.mjs` menyajikan file statis dan TIDAK
 * menerapkan `_headers` (Cloudflare Pages yang melakukannya). Karena itu spec
 * ini TIDAK boleh dipakai untuk membuktikan header CSP — untuk itu ada
 * `tests/test_csp_headers.py` dan verifikasi `curl -I` ke produksi.
 */
const PORT = Number(process.env.E2E_PORT || 3110);
const BASE_URL = process.env.E2E_BASE_URL || `http://127.0.0.1:${PORT}`;

const OUTPUT_DIR =
  process.env.PW_OUTPUT_DIR ||
  `${process.env.TEMP || process.env.TMPDIR || "/tmp"}/katalir_pw_out/codenode`;

export default defineConfig({
  testDir: "./tests",
  testMatch: /builder-code-node\.spec\.ts/,
  outputDir: OUTPUT_DIR,
  timeout: 180000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: BASE_URL,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: "node scripts/serve-out.mjs",
        url: BASE_URL,
        reuseExistingServer: true,
        timeout: 90000,
        env: { PORT: String(PORT) },
      },
  projects: [{ name: "codenode" }],
});
