import { test, expect } from "@playwright/test";

/**
 * /integrations di PRODUKSI dengan sesi nyata.
 *
 * Background: halaman ini timeout saat diuji lewat webServer lokal,
 * karena backend lokal (:8123) tidak menyajikan katalog registry
 * 23K entry secepat produksi. Timeout dinaikkan TIDAK akan
 * menyelesaikannya -- itu cuma menyembunyikan penyebabnya.
 *
 * Syarat penting: file ini hanya berarti kalau storageState-nya
 * ber-origin produksi. `scripts/e2e-auth-setup.mjs` menulis state untuk
 * localhost secara default, jadi di sini E2E_ORIGIN dipaksa ke domain
 * produksi lebih dulu. Tanpa itu, Playwright diam-diam mengabaikan
 * state-nya, tes berjalan sebagai guest, dan assertions "sudah login"
 * di bawah jadi tidak berarti. Guard di test pertama menangkap itu.
 */
const BASE = (process.env.E2E_BASE || "https://katalir.de5.net").replace(/\/$/, "");
const SHOTS = "../docs/marketing/screenshots/integrations-logged-in";

test.describe("/integrations produksi sebagai user login", () => {
  test("guard: storageState-nya benar-benar ber-origin produksi", async ({ page }) => {
    await page.goto(`${BASE}/integrations`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    await page.waitForTimeout(2500);

    const href = await page.locator('[data-testid="account-logo"]').getAttribute("href");
    console.log(`PROD_INTEGRATIONS_LOGO_HREF = ${href}`);
    // Guest -> "/" ; user login -> "/chat". Kalau masih "/", storageState
    // tidak kepakai dan SEMUA test di file ini tidak valid.
    expect(href, "storageState tidak terpakai di produksi — sisa test file ini tidak valid").toBe("/chat");
  });

  test("halaman memuat dan menampilkan kontrol filter", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/integrations`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    await page.waitForTimeout(3000);

    // Selector yang benar-benar ada di kode. Halaman ini memakai
    // tombol view dengan `aria-pressed`, bukan role="tab" — tidak ada
    // tab di sini sama sekali.
    const viewBtn = page.locator('[data-testid^="view-"]').first();
    await expect(viewBtn, "kontrol view tidak ditemukan").toBeVisible();
    const pressed = await viewBtn.getAttribute("aria-pressed");
    console.log(`VIEW_BUTTON_ARIA_PRESSED = ${pressed}`);

    const filters = page.locator('[data-testid="integrations-filters"]');
    await expect(filters, "panel filter tidak ditemukan").toBeVisible();

    await page.screenshot({ path: `${SHOTS}/integrations-logged-in.png` });
    await page.screenshot({ path: `${SHOTS}/integrations-logged-in-full.png`, fullPage: true });
  });

  test("tombol Back dari /integrations tidak melempar ke luar app", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/integrations`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    await page.waitForTimeout(2500);

    await page.locator('[data-testid="back-button"]').click();
    await page.waitForTimeout(2500);

    const url = page.url();
    console.log(`INTEGRATIONS_BACK_URL = ${url}`);
    expect(new URL(url).hostname, "Back melempar user keluar dari domain app").toBe(new URL(BASE).hostname);
    expect(url, "Back dari /integrations tidak boleh ke marketing").not.toBe(`${BASE}/`);
    console.log(`INTEGRATIONS_BACK_PATH = ${new URL(url).pathname}`);
  });
});
