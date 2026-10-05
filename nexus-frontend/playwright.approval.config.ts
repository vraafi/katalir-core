import { defineConfig } from "@playwright/test";

/**
 * Config bukti-browser kartu persetujuan (2026-10-05).
 *
 * `playwright.config.ts` repo TIDAK dipakai: ia menyalakan backend uvicorn +
 * `e2e-prod-server.mjs` sendiri (`reuseExistingServer: false`) dan
 * `globalSetup` memanggil Supabase lewat jaringan. Spec ini men-stub SELURUH
 * endpoint backend lewat `page.route`, jadi tidak butuh keduanya.
 *
 * SAMA SEPERTI `playwright.shot.config.ts`, TANPA `webServer`: server sudah
 * dijalankan terpisah supaya spec ini bisa menembak DUA bentuk build yang
 * berbeda —
 *
 *   PORT=3000  + `node scripts/serve-out.mjs`  -> PRODUCTION BUILD (`out/`)
 *   PORT=3000  + `npm run dev`                 -> dev server
 *
 * Default di sini adalah yang PERTAMA, karena itulah yang akan di-deploy.
 * Dev server tetap boleh dipakai untuk iterasi cepat, tapi hasil dari dev
 * TIDAK boleh diklaim setara produksi.
 */
const PORT = Number(process.env.E2E_PORT || 3000);

// `E2E_BASE_URL` menembak SITUS LAIN (mis. https://proyek-agent.pages.dev)
// dengan spec yang sama. Berguna untuk menjawab pertanyaan yang tidak bisa
// dijawab oleh build lokal: "apakah versi yang SUDAH DI-DEPLOY juga bisa
// menampilkan kartunya?" Stub `page.route` bekerja lintas origin, jadi tidak
// ada request /chat yang benar-benar dikirim ke backend mana pun.
const BASE_URL = process.env.E2E_BASE_URL || `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./tests",
  // Dua spec memakai harness yang sama (stub `page.route`, tanpa backend):
  //   * approval-card.spec.ts     — tiga status baru + tetangga terdekatnya
  //   * card-persistence.spec.ts  — Bug #3: kartu bertahan setelah refresh
  testMatch: /(approval-card|card-persistence)\.spec\.ts/,
  timeout: 120000,
  reporter: [["line"]],
  use: {
    baseURL: BASE_URL,
    viewport: { width: 1280, height: 900 },
    screenshot: "off",
  },
  projects: [{ name: "approval" }],
});
