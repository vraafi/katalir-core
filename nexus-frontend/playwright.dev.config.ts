import { defineConfig, devices } from "@playwright/test";

/**
 * Harness E2E FASE 3 — menembak DEV server yang sudah hidup (localhost:3000).
 *
 * KENAPA TAMBAHAN CONFIG, BUKAN MEMAKAI playwright.config.ts:
 * config utama membangun PRODUKSI lewat `scripts/e2e-prod-server.mjs`
 * (`webServer`), dan build-nya butuh >300 detik di mesin ini (font Google) —
 * sudah terdokumentasi macet di FASE 2. Untuk menguji 14 interaksi kanvas
 * sambil mengembangkan, itu terlalu berat dan terbukti menghambat verifikasi.
 *
 * KONSEKUENSI YANG DISADARI: tes di sini berjalan di DEV, jadi yang diuji
 * adalah perilaku runtime + DOM nyata, BUKAN bundle produksi. Karena itu
 * `playwright.config.ts` (produksi) TETAP menjadi jalur regresi resmi, dan
 * hasil dev-config TIDAK boleh diklaim setara produksi.
 *
 * CATATAN ORIGIN (akar masalah `model-filter 0/3`): `globalSetup`
 * `scripts/e2e-auth-setup.mjs` menulis storageState untuk
 * `http://localhost:${E2E_PORT||3000}`. Karena config ini memakai port 3000 —
 * sementara dev server juga 3000 — sesi tersimpan dan sesi yang dibaca app
 * BERADA DI ORIGIN YANG SAMA. Dengan `playwright.config.ts` (port 3201 lewat
 * E2E_PORT) sesi ditulis untuk 3201 sementara app membaca :3000, sehingga
 * `/models` tak pernah dipanggil. Di sini ketidakcocokan itu hilang.
 */
const FRONTEND_PORT = Number(process.env.E2E_PORT || 3000);
const FRONTEND_URL = `http://localhost:${FRONTEND_PORT}`;

// Spec menghitung API_ORIGIN dari env ini; dev FE dijalankan dengan
// NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 (lihat handoff §I.4).
process.env.E2E_BACKEND_URL = process.env.E2E_BACKEND_URL || "http://127.0.0.1:8000";

export default defineConfig({
  testDir: "./tests",
  testMatch: [
    "canvas-fase3.spec.ts",
    "canvas-theme.spec.ts",
    "fase4-pages.spec.ts",
    "fase4-a11y.spec.ts",
    "fase5-a11y.spec.ts",
    // FASE 5 (B1-B6): permukaan AI-native + onboarding. Deterministik karena
    // jaringan di-stub (lihat catatan di kepala spec).
    "fase5-ai-surfaces.spec.ts",
    // FASE 6: matriks mobile 6 halaman x 3 device (pageerror, tap >=44, axe).
    "final-mobile.spec.ts",
    // Regresi yang diminta misi FASE 3 + rute menyeluruh; ikut di harness dev
    // karena harness build-produksi tidak selesai di mesin ini (lihat catatan
    // di atas dan docs/audit/fase3-verification.md).
    "model-filter.spec.ts",
    "routes-no-crash.spec.ts",
    "chat-auth.spec.ts",
    // Audit axe 6 rute terhadap SITUS YANG SUDAH DEPLOY (bukan dev), jadi
    // yang diukur adalah yang benar-benar diterima pengunjung. Menembak
    // production dari harness dev yang sama-sama memakai port 3000 aman:
    // spec ini mengabaikan baseURL dan memakai AXE_TARGET.
    "axe-audit.spec.ts",
    // FASE 5: spec ini DISENTUH fase 5 (selector model pindah ke data-testid)
    // tetapi TIDAK ada di harness mana pun yang bisa dijalankan di mesin ini —
    // `playwright.config.ts` (satu-satunya yang memuatnya sebelumnya) mem-build
    // produksi >300 detik dan menolak port yang sudah terpakai. Tanpa baris ini
    // perubahan pada spec-nya tidak pernah diuji, jadi ia ikut di harness dev.
    "hydration.spec.ts",
    // F2.3: tab sumber marketplace. Dibuat saat menambah tab ke-8
    // (glama-connector + openapi-generated) yang sebelumnya tertumpuk di tab
    // "Glama". Di sini karena butuh backend :8000 yang hidup, dan harness
    // build-produksi tidak selesai di mesin ini (lihat catatan di kepala file).
    "marketplace-tabs.spec.ts",
    // F3.5: bukti visual multi-protocol. Hanya menghasilkan screenshot + cek
    // bahwa 10 tab, toggle, dan 4 tier benar-benar ter-render. Di harness dev
    // karena butuh backend :8000 hidup seperti spec di atasnya.
    "marketplace-f3-evidence.spec.ts",
    // F4.3: filter kategori + status runtime. Butuh backend :8000 hidup
    // (meny recount via /mcp/registry) seperti spec di atasnya.
    "marketplace-f4-filters.spec.ts",
    // F6: logo cloud landing — posisi di hero, warna brand, magnetik, non-click.
    "landing-logo-f6.spec.ts",
    // F6: rekam bukti efek magnetik (frame sebelum/sesudah + angka jarak).
    // Hanya screenshot dan mengukur displacement — TIDAK memakai video, jadi
    // tidak ada biaya kamera di setiap suite. Gated karena ia gagal kalau
    // magnet berhenti menggerakkan tile, dan itulah yang ingin dijaga.
    "landing-magnet-evidence.spec.ts",
    // CTA utama landing. Menutup bug yang dilaporkan: `<Link href="/chat">`
    // mengirim pengunjung anonim ke tembok login. Dua cabang diuji — anonim
    // (modal terbuka) dan ber-session (langsung ke /chat).
    "landing-cta.spec.ts",
    // CATATAN: launch-demo.spec.ts sengaja TIDAK ada di testMatch. Ia bukan
    // assertion, melainkan rekaman video untuk launch, dan menambahkannya di
    // sini akan membuat setiap test suite ikut menjalankan kamera. Jalankan
    // lewat `playwright.demo.config.ts`.
  ],
  testIgnore: ["**/_probes/**"],
  timeout: 90000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  globalSetup: "./scripts/e2e-auth-setup.mjs",
  use: {
    baseURL: FRONTEND_URL,
    headless: true,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  // PENTING: `viewport` di sini WAJIB, bukan hanya di `use` global.
  // `devices["Desktop Chrome"]` membawa viewport-nya sendiri (1280x720) dan
  // `use` tingkat PROJECT menang atas `use` tingkat config — sehingga nilai
  // 1440x900 yang ditulis di atas DIABAIKAN tanpa peringatan. Akibat nyatanya
  // terukur: node contoh terjepit di luar viewport 1280 (`elementFromPoint`
  // mengembalikan null, handle tidak bisa diklik) dan tes connect gagal seolah
  // bug UI. Ditulis eksplisit di sini supaya tidak bisa tertimpa lagi.
  projects: [
    { name: "chromium-dev", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
  ],
  // SENGAJA TANPA webServer: dev server dijalankan terpisah (handoff §I.4),
  // dan config ini tidak boleh menyalakan/tidak boleh membangun apa pun.
});
