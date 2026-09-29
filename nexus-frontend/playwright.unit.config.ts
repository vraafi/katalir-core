import { defineConfig } from "@playwright/test";

/**
 * Config KHSUS untuk `execution-report.ts` (fungsi murni, tanpa browser).
 *
 * Config repo utama tidak bisa dipakai: `globalSetup` melakukan auth ke
 * Supabase lewat jaringan dan `webServer` menyalakan Next.js. Keduanya
 * tidak dibutuhkan untuk menguji fungsi murni, tapi menambah 30-60 detik
 * dan gagal total tanpa koneksi database. Test ini karena itu TIDAK
 * memverifikasi apa pun soal backend -- ia hanya mengunci bentuk data
 * yang mengalir dari `execution_logs` ke UI.
 */
export default defineConfig({
  testDir: "./tests",
  testMatch: /(execution-report-healing|repro-integrations|repro-detail)\.spec\.ts/,
  timeout: 15000,
  reporter: [["line"]],
  use: {},
});
