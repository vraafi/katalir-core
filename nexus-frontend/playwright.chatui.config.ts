import { defineConfig } from "@playwright/test";

/**
 * Hard test UI chat (composer mobile) — 5 viewport × 2 tema + simulasi keyboard.
 *
 * Pola sama dengan `playwright.templates.config.ts`:
 *  - outputDir DI LUAR workspace (guard `safe-delete` memblokir penghapusan
 *    massal >50 berkas dan pernah menggagalkan build),
 *  - menguji BUNDLE PRODUKSI (`out/`) lewat `scripts/serve-out.mjs`, bukan
 *    `next dev` — perilaku dev berbeda dan itu yang dulu meloloskan bug.
 *
 * `webServer` otomatis dilewati bila `E2E_BASE_URL` diisi (mis. untuk menguji
 * situs live).
 */
const PORT = Number(process.env.E2E_PORT || 3100);
const BASE_URL = process.env.E2E_BASE_URL || `http://127.0.0.1:${PORT}`;

const OUTPUT_DIR =
  process.env.PW_OUTPUT_DIR ||
  `${process.env.TEMP || process.env.TMPDIR || "/tmp"}/katalir_pw_out/chatui`;

export default defineConfig({
  testDir: "./tests",
  testMatch: /chat-composer-mobile\.spec\.ts/,
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
  projects: [{ name: "chatui" }],
});
