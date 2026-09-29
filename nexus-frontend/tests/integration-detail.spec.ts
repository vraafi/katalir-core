import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * Detail page integrasi lewat query-param.
 *
 * Static export hanya meng-prerender satu slug ("catalog"), jadi
 * /integrations/<apa-pun> selain itu 404. Karena itu detail dibaca dari
 * `?slug=`. Test ini membuktikan query itu benar-benar dipakai: halaman
 * HARUS menampilkan detail server yang diminta, bukan cuma balas 200
 * dengan halaman kosong.
 */
const BASE = (process.env.AXE_TARGET || "https://katalir.de5.net").replace(/\/$/, "");
const SHOTS = "../docs/marketing/screenshots";

/** Id nyata dari registry produksi, bukan slug karangan. */
const REAL_SLUG = "@modelcontextprotocol/server-github";

test.describe("Integration detail via query-param", () => {
  test("/integrations/catalog?slug=... merender detail yang benar", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/integrations/catalog?slug=${encodeURIComponent(REAL_SLUG)}`, {
      waitUntil: "load",
      timeout: 90_000,
    });
    await page.waitForSelector("#main-content", { timeout: 45_000 });

    // Nama server harus muncul. Kalau query tidak dibaca, halaman akan
    // tetap menampilkan "Memuat integrasi..." atau "tidak ditemukan".
    await expect(
      page.getByText("server-github", { exact: false }),
      "detail server tidak pernah muncul -> ?slug= kemungkinan tidak dibaca",
    ).toBeVisible({ timeout: 45_000 });

    await expect(page.getByText("Integrasi tidak ditemukan")).toHaveCount(0);
    await expect(page.getByText("Memuat integrasi")).toHaveCount(0);

    const title = await page.locator("#main-content h1, #main-content h2").first().innerText();
    console.log(`DETAIL_TITLE = ${title.trim()}`);

    await page.screenshot({ path: `${SHOTS}/integration-detail-desktop.png` });
  });

  test("slug karangan memberi pesan tidak ditemukan, bukan halaman kosong", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/integrations/catalog?slug=definitely-not-a-real-slug-xyz`, {
      waitUntil: "load",
      timeout: 90_000,
    });
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    await expect(page.getByText("Integrasi tidak ditemukan")).toBeVisible({ timeout: 45_000 });
    console.log("DETAIL_BADS_SLUG = not-found message shown");
  });

  test("klik Detail dari /integrations mendarat ke URL query-param", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/integrations`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    await page.waitForTimeout(1500);

    const link = page.locator('[data-testid="integration-detail-link"]').first();
    await expect(link, "tombol Detail tidak ada di kartu integrasi").toBeVisible();

    await link.click();
    await page.waitForURL(/\/integrations\/catalog\?slug=/, { timeout: 45_000 });
    const url = page.url();
    console.log(`DETAIL_URL = ${url}`);

    expect(url, "klik Detail harus ke /integrations/catalog?slug=").toContain("/integrations/catalog?slug=");
    expect(url, "URL lama /integrations/<slug> akan 404").not.toMatch(/\/integrations\/[^?]+\?slug/);
  });

  test("axe pada halaman detail 0 violation blocking", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/integrations/catalog?slug=${encodeURIComponent(REAL_SLUG)}`, {
      waitUntil: "load",
      timeout: 90_000,
    });
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    await page.waitForTimeout(2000);
    const results = await new AxeBuilder({ page }).analyze();
    const blocking = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
    console.log(`AXE_DETAIL total=${results.violations.length} blocking=${blocking.length}`);
    if (blocking.length) console.log("AXE_DETAIL_NODES " + JSON.stringify(blocking.map((v) => ({ id: v.id, n: v.nodes.length }))));
    expect(blocking, JSON.stringify(blocking.map((v) => v.id))).toHaveLength(0);
  });
});
