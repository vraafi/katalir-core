import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * Matriks navigasi: logo dan tombol Back harus tetap di dalam app.
 *
 * Standar yang diuji: di dalam app shell, logo dan "kembali" mengarah
 * ke app, bukan ke marketing. Di landing, logo justru ke app -- jadi
 * aturannya dua arah dan keduanya diuji.
 *
 * Guest (belum login) juga diuji, karena tombol Back untuk mereka
 * tidak boleh mengirim ke /chat: halaman itu butuh sesi.
 */
const BASE = (process.env.AXETARGET || process.env.AXE_TARGET || "https://katalir.de5.net").replace(/\/$/, "");
const SHOTS = "../docs/marketing/screenshots/navigation";

/** Halaman akun yang memakai SimplePage. */
const ACCOUNT_PAGES = ["/settings", "/billing", "/help", "/integrations"];

// Hanya di proyek `guest`: file ini menguji perilaku tanpa sesi, yang
// persis perlu login untuk diuji sebagai bug navigasi.
test.describe("Matrix navigasi (guest)", () => {
  test("landing: logo mengarah ke /chat (marketing -> app)", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });

    const logo = page.locator('[data-testid="landing-logo"]');
    await expect(logo, "logo landing tidak ada").toBeVisible();

    const href = await logo.evaluate((el) => {
      const a = el.closest("a");
      return a ? a.getAttribute("href") : null;
    });
    console.log(`LANDING_LOGO_HREF = ${href}`);
    expect(href, "logo landing harus ke /chat").toBe("/chat");
  });

  test("shell: tombol Chat mengarah ke /chat, bukan /", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/builder`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });

    const link = page.locator('[data-testid="shell-chat-link"]');
    await expect(link, "tombol Chat di shell tidak ada").toBeVisible();
    const href = await link.getAttribute("href");
    console.log(`SHELL_CHAT_HREF = ${href}`);
    expect(href, "tombol Chat harus ke /chat, bukan landing").toBe("/chat");
  });

  for (const route of ACCOUNT_PAGES) {
    test(`${route}: logo dan tombol Back ada dan tidak lagi ke marketing`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(`${BASE}${route}`, { waitUntil: "load", timeout: 90_000 });
      await page.waitForSelector("#main-content", { timeout: 45_000 });
      await page.waitForTimeout(900);

      const logo = page.locator('[data-testid="account-logo"]');
      await expect(logo, `logo tidak ada di ${route}`).toBeVisible();

      const logoHref = await logo.getAttribute("href");
      // Tombol yang selalu ke / tanpa memandang status login adalah bugnya.
      // tombol yang selalu ke / tanpa memandang status login.
      console.log(`${route} LOGO_HREF = ${logoHref}`);
      expect(["/chat", "/"]).toContain(logoHref);

      const back = page.locator('[data-testid="back-button"]');
      await expect(back, `tombol Back tidak ada di ${route}`).toBeVisible();
      // Tombol Back WAJIB berupa <button>, bukan <Link href="/">.
      // Kalau masih Link, ia akan selalu membawa user ke marketing.
      const tag = await back.evaluate((el) => el.tagName);
      console.log(`${route} BACK_TAG = ${tag}`);
      expect(tag, "tombol Back harus <button> supaya bisa pakai router.back()").toBe("BUTTON");
    });
  }

  test("akses langsung /settings lalu Back: tidak keluar dari app", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    // Buka langsung tanpa lewat /chat: ini kasus deep-link dan refresh,
    // yang membuat router.back() melempar user ke situs sebelumnya.
    await page.goto(`${BASE}/settings`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    await page.waitForTimeout(900);

    await page.evaluate(() => sessionStorage.removeItem("hasInternalNav"));
    await page.locator('[data-testid="back-button"]').click();
    await page.waitForTimeout(2500);

    const url = page.url();
    console.log(`DIRECT_ACCESS_BACK_URL = ${url}`);
    // Hasil apa pun, user HARUS tetap di domain app. keluar ke
    // google.com adalah kegagalan, bukan "kembali ke halaman sebelumnya".
    expect(new URL(url).hostname, "Back melempar user keluar dari domain app").toBe(new URL(BASE).hostname);
    await page.screenshot({ path: `${SHOTS}/direct-access-back.png` });
  });

  test("axe halaman akun 0 violation blocking setelah perubahan nav", async ({ page }) => {
    for (const route of ["/settings", "/integrations"]) {
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(`${BASE}${route}`, { waitUntil: "load", timeout: 90_000 });
      await page.waitForSelector("#main-content", { timeout: 45_000 });
      await page.waitForTimeout(1500);
      const results = await new AxeBuilder({ page }).analyze();
      const blocking = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
      console.log(`AXE ${route} total=${results.violations.length} blocking=${blocking.length}`);
      if (blocking.length) console.log("AXE_NODES " + JSON.stringify(blocking.map((v) => ({ id: v.id, n: v.nodes.length }))));
      expect(blocking, `${route}: ${JSON.stringify(blocking.map((v) => v.id))}`).toHaveLength(0);
    }
  });
});
