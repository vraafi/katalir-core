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
  testMatch: /(execution-report-healing|repro-integrations|repro-detail|badge-layout)\.spec\.ts/,
  // Spec badge-layout memverifikasi produksi nyata: setiap test menunggu
  // kartu pertama + respons registry, yang bisa >15s saat katalog besar.
  // Timeout global 15s (default config repo ini) akan membunuh test yang
  // sebenarnya sedang menunggu data, bukan catch bug.
  timeout: 90000,
  reporter: [["line"]],
  use: {},
});
