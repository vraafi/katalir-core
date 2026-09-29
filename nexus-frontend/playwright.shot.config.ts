import { defineConfig } from "@playwright/test";

/**
 * Config KHSUS screenshot Task D.
 *
 * `playwright.config.ts` repo utama TIDAK bisa dipakai. Ia memiliki dua
 * `webServer`: backend uvicorn (port 8123) + `e2e-prod-server.mjs`, keduanya
 * `reuseExistingServer: false` -- jadi selalu mencoba menyalakan server
 * sendiri dan gagal dengan "port already used" kalau ada yang jalan.
 * Dan `globalSetup` memanggil auth Supabase lewat jaringan.
 *
 * Di sini tidak ada `webServer` dan tidak ada `globalSetup`: dev server
 * (`npm run dev`) sudah jalan terpisah, dan SELURUH endpoint backend
 * di-stub `page.route` di dalam spec -- jadi tidak butuh database sama
 * sekali. One-off ini tidak mengubah file konfigurasi repo.
 */
const PORT = Number(process.env.E2E_SHOT_PORT || 3000);

export default defineConfig({
  testDir: "./tests",
  testMatch: /screenshot-task-d\.spec\.ts/,
  timeout: 120000,
  reporter: [["line"]],
  use: {
    baseURL: `http://localhost:${PORT}`,
    // Screenshot layar penuh: kartu laporan punya beberapa baris.
    viewport: { width: 1280, height: 900 },
  },
  projects: [{ name: "shot" }],
});
