import { defineConfig, devices } from "@playwright/test";

/**
 * E2E WAJIB berjalan di PRODUCTION BUILD, bukan `next dev`.
 *
 * Dev server menyajikan data & perilaku yang berbeda (env NEXT_PUBLIC_* di-inline
 * saat build di mode produksi, minifikasi, hydration). Tes yang hanya dijalankan
 * di dev pernah melaporkan "lulus" padahal user — yang memakai build produksi —
 * tetap melihat model paid muncul di selector. Karena itu `webServer` di bawah
 * membangun app lalu menyajikannya sebagai produksi.
 *
 * CATATAN PENTING soal `npm run start`: app ini di-set `output: "export"`
 * (static export untuk Cloudflare Pages), sehingga `next start` TIDAK berlaku —
 * Next.js menolaknya karena tidak ada server Node yang merender halaman. Bentuk
 * produksi yang setara untuk app ini adalah "build lalu sajikan `out/` statis",
 * yang dilakukan `scripts/e2e-prod-server.mjs` (build + serve, tanpa dependensi
 * tambahan). Jadi maksud instruksi "build dulu, jangan dev" tetap dipenuhi.
 *
 * `reuseExistingServer: false` SENGAJA dipilih di kedua entri: server lama yang
 * masih hidup (dev server di port 3000, atau backend yang di-start sebelum kode
 * terakhir diedit) pernah membuat hasil tes menyesatkan. Lebih baik tes gagal
 * dengan keras karena port terpakai daripada lulus berdasarkan kode basi.
 *
 * JEBAKAN YANG TERBUKTI (2026-09): `reuseExistingServer: false` TIDAK cukup.
 * Bila port backend sudah dipegang proses lain (mis. uvicorn manual dari sesi
 * debug), uvicorn milik tes GAGAL bind — tetapi Playwright hanya memeriksa
 * bahwa URL menjawab, sehingga tes berjalan diam-diam melawan BACKEND LAMA.
 * Bukti nyata: 3 tes filter model gagal 401 dengan body 42 byte
 * `{"detail":"Token invalid: ConnectTimeout"}`, padahal `security.py` di disk
 * mengembalikan 503 berpesan panjang untuk kelas error yang sama. Artinya yang
 * diuji bukan kode repo ini, melainkan proses basi. Karena itu:
 *   1. Port backend tes dipindah ke port DEDIKAT (8123) yang tidak dipakai
 *      alur dev/manual, sehingga backend manual di 8000 tidak bisa tertukar.
 *   2. `E2E_BACKEND_URL` di-set ke process.env supaya spec memvalidasi origin
 *      yang SAMA dengan yang di-inline saat build (guard origin tidak meleset).
 */
const FRONTEND_PORT = Number(process.env.E2E_PORT || 3000);
const BACKEND_PORT = Number(process.env.E2E_BACKEND_PORT || 8123);
const FRONTEND_URL = `http://localhost:${FRONTEND_PORT}`;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;

// Spec menghitung API_ORIGIN dari env ini; di-set dari sini agar konsisten
// dengan E2E_API_URL yang di-inline ke bundle saat build.
process.env.E2E_BACKEND_URL = BACKEND_URL;

export default defineConfig({
  testDir: "./tests",
  // KARANTINA PROBE DIAGNOSTIK (2026-09-16): spec `tests/_probes/_*.spec.ts`
  // (dulu `tests/_*.spec.ts`) adalah harness diagnostik LOKAL — pernah dipakai
  // sebagai "bukti hijau" padahal bukan keluaran produksi (lihat HANDOFF §9.4).
  // Sekarang dipisah ke subfolder `_probes/` dan DIKECUALIKAN dari run normal
  // supaya `npm run e2e:prod` hanya menghitung spec sehat (10 file). Hasil run
  // normal karena itu tidak boleh ditafsirkan sebagai cakupan probe.
  // Jalankan probe secara sengaja (hanya saat diagnosis): E2E_PROBES=1 npx playwright test
  testIgnore: process.env.E2E_PROBES === "1" ? [] : ["**/_probes/**"],
  timeout: 60000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  // Fixture auth E2E (bearer token) adalah ARTEFAK: `_e2e_session*.json` &
  // `_e2e_storage*.json` ada di .gitignore dan TIDAK ikut ter-commit. Tanpa
  // langkah ini, fixture basi (pernah tertinggal 2,2 hari) membuat spec gagal
  // dengan pesan menyesatkan seperti "injeksi session gagal" atau ENOENT —
  // terbaca seolah bug produk, padahal harness-nya yang kosong. Script ini
  // memilih sesi paling sehat / menukar refresh_token, lalu menulis ulang
  // `_e2e_session.refreshed.json` + `_e2e_storage.json` sebelum tes jalan.
  globalSetup: "./scripts/e2e-auth-setup.mjs",

  use: {
    baseURL: FRONTEND_URL,
    headless: true,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: [
    {
      // Backend lokal (kode di repo ini, sudah berisi filter + meta fallback).
      // --app-dir .. : uvicorn menambahkan root repo ke sys.path; api_server
      // memuat .env dari direktorinya sendiri sehingga konfigurasi tetap benar.
      command: `python -m uvicorn api_server:app --app-dir .. --host 127.0.0.1 --port ${BACKEND_PORT}`,
      url: `${BACKEND_URL}/health`,
      reuseExistingServer: false,
      timeout: 180000,
    },
    {
      // Build produksi dengan NEXT_PUBLIC_API_URL diarahkan ke backend lokal,
      // lalu sajikan out/ di FRONTEND_PORT.
      command: "node scripts/e2e-prod-server.mjs",
      url: FRONTEND_URL,
      reuseExistingServer: false,
      timeout: 300000,
      env: { E2E_API_URL: BACKEND_URL },
    },
  ],
});