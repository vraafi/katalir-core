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
const BASE = (process.env.AXETARGET || process.env.AXE_TARGET || "https://katalir.de5.net").replace(/\/$/, "");
const SHOTS = "../docs/marketing/screenshots/navigation-logged-in";

/** Halaman akun; semua memakai SimplePage. */
const ACCOUNT_PAGES = ["/settings", "/billing", "/help", "/integrations"];

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
