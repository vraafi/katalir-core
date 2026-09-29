import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * Seksi Tools di halaman detail integrasi.
 *
 * Bug yang diuji: `tools` dan `tools_count` bisa tidak sinkron. Cloudflare
 * mengembalikan `tools=[]` tapi `tools_count=20`; openai `tools=[]` tapi
 * `tools_count=126`. UI lama merender `{item.tools?.map(...)}` langsung,
 * jadi sebuah <ul> kosong tanpa judul dan tanpa penjelasan,
 * yang terlihat seperti "server ini tidak punya apa-apa".
 *
 * Yang jadi ASSERTION di sini: TIDAK PERNAH ada "0", dan selalu ada
 * penjelasan. Angka 0 tidak akan pernah dicetak, biarpun datanya 0.
 */
const BASE = (process.env.AXETARGET || process.env.AXE_TARGET || "https://katalir.de5.net").replace(/\/$/, "");
const DETAIL = (slug: string) => `${BASE}/integrations/catalog?slug=${encodeURIComponent(slug)}`;
const SHOTS = "../docs/marketing/screenshots/integrations-detail";

/** Slug yang mewakili ketiga cabang. */
const CASES = [
  { slug: "github", branch: "listed" },   // tools=[] array terisi
  { slug: "cloudflare", branch: "count" }, // array kosong, count=20
  { slug: "slack", branch: "listed" },
];

// Proyek `guest` saja: yang diuji di sini adalah tampilan tanpa sesi.
test.describe("Detail integrasi: seksi Tools (guest)", () => {
  for (const { slug, branch } of CASES) {
    test(`${slug}: seksi Tools informatif, tidak pernah "0"`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(DETAIL(slug), { waitUntil: "load", timeout: 90_000 });
      await page.waitForSelector("#main-content", { timeout: 45_000 });

      const body = page.locator("#main-content");
      await expect(body, `detail ${slug} tidak render`).toBeVisible();
      // Tunggu heading Tools muncul; kalau tidak, berarti fetch belum selesai.
      const toolsHeading = page.locator("#tools-heading");
      await expect(toolsHeading, `seksi Tools tidak ada di ${slug}`).toBeVisible({ timeout: 30_000 });

      const text = (await body.innerText()).toLowerCase();
      console.log(`${slug} BRANCH=${branch} TEXT_SNIP=${text.slice(0, 120).replace(/\n/g, " | ")}`);

      // Larangan keras: angka 0 tidak boleh muncul sebagai jumlah tool.
      expect(text, `${slug} menampilkan "tools (0)"`).not.toMatch(/tools\s*\(0\)/);
      expect(text, `${slug} menampilkan "0 tool"`).not.toMatch(/\b0\s+tool\b/);

      // Dan harus ada isi yang bisa dibaca manusia.
      const headingText = (await toolsHeading.innerText()).trim();
      expect(headingText.length, "judul Tools kosong").toBeGreaterThan(0);
      console.log(`${slug} HEADING=${headingText}`);

      await page.screenshot({ path: `${SHOTS}/${slug}.png` });
    });
  }

  test("cloudflare: 20 tool tercatat dan disebut, bukan disembunyikan jadi 0", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(DETAIL("cloudflare"), { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#tools-heading", { timeout: 45_000 });

    const heading = (await page.locator("#tools-heading").innerText()).trim();
    console.log(`CLOUDFLARE_HEADING = ${heading}`);
    // Backend melaporkan 20. Kalau UI bilang 0, itu regression.
    expect(heading, "cloudflare harus menampilkan jumlah tool yang sebenarnya").toContain("20");
  });

  test("tidak ada <ul> kosong menggantung di halaman detail", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(DETAIL("cloudflare"), { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#tools-heading", { timeout: 45_000 });
    const empties = await page.locator("ul:empty").count();
    console.log(`EMPTY_UL = ${empties}`);
    expect(empties, "ada <ul> kosong — itu bentuk symptom bug lama").toBe(0);
  });

  test("axe 0 blocking di halaman detail", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(DETAIL("github"), { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#tools-heading", { timeout: 45_000 });
    await page.waitForTimeout(1200);
    const results = await new AxeBuilder({ page }).analyze();
    const blocking = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
    console.log(`AXE detail total=${results.violations.length} blocking=${blocking.length}`);
    if (blocking.length) console.log("AXE_NODES " + JSON.stringify(blocking.map((v) => ({ id: v.id, n: v.nodes.length }))));
    expect(blocking).toHaveLength(0);
  });
});
