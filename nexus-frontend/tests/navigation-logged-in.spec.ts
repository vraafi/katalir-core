import { test, expect } from "@playwright/test";

/**
 * Matrix navigasi UNTUK USER YANG SUDAH LOGIN.
 *
 * File ini hanya ada karena `playwright.config.ts` punya proyek `logged-in`
 * dengan `storageState`. Tanpa itu, semua spec berjalan sebagai guest dan
 * cabang `email ? "/chat" : "/"` pada logo tidak pernah teruji — cabang
 * yang justru dilaporkan user sebagai bug.
 *
 * Kalau file ini gagal dengan "not signed in", itu harness (fixture auth),
 * bukan produk. Periksa `_e2e_storage.json`.
 */
/**
 * Target logged-in adalah build produksi LOKAL, bukan domain ter-deploy.
 *
 * Alasannya menentukan, bukan teknis: `storageState` di-scope per origin.
 * `scripts/e2e-auth-setup.mjs` menulis state untuk `http://localhost:3000`
 * (dia banter dengan webServer di playwright.config.ts), sedangkan
/**
 * Halaman akun yang memakai SimplePage dan punya logo + tombol Back.
 *
 * /integrations sengaja TIDAK ada di sini: lewat webServer lokal
 * halaman itu timeout, karena backend :8123 tidak menyajikan katalog
 * registry 23K entry secepat produksi. Kasus itu diuji di produksi
 * oleh tests/integrations-logged-in.spec.ts, yang juga sudah hijau.
 *
 * /builder juga bukan di sini: dia memakai Shell, bukan SimplePage,
 * jadi tidak punya logo maupun tombol Back. Punya test sendiri di bawah.
 */
const BASE = (process.env.E2E_BASE || `http://localhost:${process.env.E2E_PORT || 3000}`).replace(/\/$/, "");
const SHOTS = "../docs/marketing/screenshots/navigation-logged-in";
const ACCOUNT_PAGES = ["/settings", "/billing", "/help"];

test.describe("Matrix navigasi (logged-in)", () => {
  test("sanity: sesi benar-benar terpakai, bukan guest diam-diam", async ({ page }) => {
    await page.goto(`${BASE}/settings`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    await page.waitForTimeout(2500);

    const href = await page.locator('[data-testid="account-logo"]').getAttribute("href");
    console.log(`SANITY_LOGO_HREF = ${href}`);
    // Kalau ini masih "/", storageState tidak terpakai dan SEMUA test lain
    // di file ini jadi tidak bermakna. Gagal di sini lebih baik daripada
    // melaporkan lulus palsu.
    expect(href, "storageState tidak terpakai — sisa test file ini tidak valid").toBe("/chat");
  });

  for (const route of ACCOUNT_PAGES) {
    test(`${route}: logo ke /chat saat login`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(`${BASE}${route}`, { waitUntil: "load", timeout: 90_000 });
      await page.waitForSelector("#main-content", { timeout: 45_000 });
      await page.waitForTimeout(2200);

      const href = await page.locator('[data-testid="account-logo"]').getAttribute("href");
      console.log(`${route} LOGO_HREF = ${href}`);
      expect(href, `${route}: logo untuk user login harus ke /chat`).toBe("/chat");

      await page.screenshot({ path: `${SHOTS}/logo-${route.replace(/\//g, "")}.png` });
    });
  }

  test("/settings → Back: kembali ke /chat, tidak ke marketing", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/settings`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    await page.waitForTimeout(2200);

    await page.locator('[data-testid="back-button"]').click();
    await page.waitForTimeout(2500);

    const url = page.url();
    console.log(`BACK_AFTER_SETTINGS = ${url}`);
    // Fallback untuk user login adalah /chat, dan tidak boleh keluar domain.
    expect(new URL(url).hostname).toBe(new URL(BASE).hostname);
    expect(url, "Back dari /settings untuk user login tidak boleh ke marketing").not.toBe(`${BASE}/`);
    console.log(`BACK_PATH = ${new URL(url).pathname}`);

    await page.screenshot({ path: `${SHOTS}/back-from-settings.png` });
  });

  test("/chat: tombol Chat di shell menuju /chat", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/chat`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    await page.waitForTimeout(2200);

    const link = page.locator('[data-testid="shell-chat-link"]');
    await expect(link, "tombol Chat tidak ada di shell /chat").toBeVisible();
    const href = await link.getAttribute("href");
    console.log(`SHELL_CHAT_HREF = ${href}`);
    expect(href).toBe("/chat");
  });

  test("/builder: tombol Chat di shell tetap ke /chat (halaman ini tanpa logo & back)", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/builder`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    await page.waitForTimeout(2500);

    // /builder memakai Shell, bukan SimplePage, jadi TIDAK punya logo
    // maupun tombol Back. Menuntut keduanya di sini akan salah. Yang
    // bisa diuji di halaman ini adalah nav shell-nya.
    await expect(page.locator('[data-testid="account-logo"]'), "/builder tidak punya logo (memakai Shell)").toHaveCount(0);
    await expect(page.locator('[data-testid="back-button"]'), "/builder tidak punya tombol Back").toHaveCount(0);

    const href = await page.locator('[data-testid="shell-chat-link"]').getAttribute("href");
    console.log(`/builder SHELL_CHAT_HREF = ${href}`);
    expect(href, "nav Chat di /builder harus ke /chat").toBe("/chat");

    await page.screenshot({ path: `${SHOTS}/builder.png` });
  });

  test("landing saat login: tombol menuju app ada dan leading ke /chat", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    await page.waitForTimeout(2500);

    // Landing TIDAK boleh auto-redirect. Marketing tetap untuk SEO.
    console.log(`LANDING_URL_LOGGED_IN = ${new URL(page.url()).pathname}`);
    expect(new URL(page.url()).pathname, "landing auto-redirect — itu merusak share link").toBe("/");

    const logo = page.locator('[data-testid="landing-logo"]');
    const href = await logo.evaluate((el) => el.closest("a")?.getAttribute("href") ?? null);
    console.log(`LANDING_LOGO_HREF = ${href}`);
    expect(href, "logo landing harus ke /chat").toBe("/chat");

    await page.screenshot({ path: `${SHOTS}/landing-logged-in.png` });
  });
});

