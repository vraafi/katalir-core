import { test, expect } from "@playwright/test";

/**
 * Kartu OAuth tidak boleh berbohong soal status.
 *
 * Bug yang dikunci di sini: `catch` lama menulis `connected: false`,
 * dan render memperlakukannya sama dengan "terputus". Akibatnya satu
 * request yang gagal (timeout, 401, blip) mengubah kartu hijau jadi
 * "Not connected" padahal vault utuh -- persis laporan user.
 *
 * Test ini sengaja MEMATIKAN endpoint status, jadi ketiga state bisa
 * diuji tanpa OAuth consent interaktif yang tidak bisa dijalankan di
 * runner ini.
 */
const BASE = (process.env.AXETARGET || process.env.AXE_TARGET || "https://katalir.de5.net").replace(/\/$/, "");
const SHOTS = "../docs/marketing/screenshots/oauth-status";

test.describe("Status OAuth: jangan salah label", () => {
  test("request gagal -> 'unknown', BUKAN 'Not connected'", async ({ page }) => {
    // Gagalkan SEMUA panggilan status. Ini yang terjadi di dunia nyata
    // saat timeout atau token kedaluwarsa.
    await page.route("**/oauth/*/status", (route) => route.abort("failed"));

    await page.goto(`${BASE}/integrations`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    await page.waitForTimeout(3500);

    const badges = page.locator('[data-testid^="oauth-badge-"]');
    const n = await badges.count();
    console.log(`BADGE_COUNT = ${n}`);
    expect(n, "kartu OAuth tidak muncul").toBeGreaterThan(0);

    for (let i = 0; i < n; i++) {
      const b = badges.nth(i);
      const state = await b.getAttribute("data-state");
      const text = (await b.innerText()).trim();
      console.log(`BADGE[${i}] state=${state} text=${text}`);

      // Ini inti dari fix: saat status tidak bisa dipastikan, badge
      // TIDAK BOLEH berarti "not connected".
      expect(state, `badge ${i} salah label saat request gagal: "${text}"`).not.toBe("disconnected");
      expect(state).toBe("unknown");
    }

    // Dan aksi harus offered, bukan user terkunci di "Not connected".
    const retry = page.locator('[data-testid^="oauth-retry-"]');
    await expect(retry.first(), "tidak ada tombol Retry saat status gagal").toBeVisible();

    await page.screenshot({ path: `${SHOTS}/status-unknown.png` });
  });

  test("endpoint 401 lalu 200 -> retry memulihkan status", async ({ page }) => {
    // Skenario token Supabase kedaluwarsa: satu balasan 401, lalu 200.
    // Fix harus mencoba ulang; tanpa itu kartu akan tersangkut
    // "unknown" padahal tokennya tokennya sehat.
    let calls = 0;
    await page.route("**/oauth/*/status", async (route) => {
      calls++;
      if (calls === 1) return route.fulfill({ status: 401, contentType: "application/json", body: "{}" });
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ connected: true, team_name: "acme", keys_present: 1, keys_total: 1, configured: true }),
      });
    });

    await page.goto(`${BASE}/integrations`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    await page.waitForTimeout(4000);

    const badges = page.locator('[data-testid^="oauth-badge-"]');
    const n = await badges.count();
    console.log(`RETRY_CALLS = ${calls}`);
    for (let i = 0; i < n; i++) {
      const b = badges.nth(i);
      const state = await b.getAttribute("data-state");
      console.log(`RETRY_BADGE[${i}] state=${state}`);
      expect(state, `badge ${i} tidak pulih setelah 401 -> retry`).toBe("connected");
    }

    await page.screenshot({ path: `${SHOTS}/status-401-retry.png` });
  });

  test("benar-benar terputus -> tetap 'Not connected'", async ({ page }) => {
    // Kebalikannya harus tetap bisa dibedakan. Kalau semua error jadi
    // "unknown", kartu yang benar-benar putus jadi tidak bisa
    // dibedakan -- itu regresi ke arah lain.
    await page.route("**/oauth/*/status", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ connected: false, keys_present: 0, keys_total: 1, configured: false }),
      })
    );

    await page.goto(`${BASE}/integrations`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    await page.waitForTimeout(3500);

    const badges = page.locator('[data-testid^="oauth-badge-"]');
    const n = await badges.count();
    for (let i = 0; i < n; i++) {
      const state = await badges.nth(i).getAttribute("data-state");
      console.log(`DISCONNECTED_BADGE[${i}] state=${state}`);
      expect(state).toBe("disconnected");
    }
  });
});
