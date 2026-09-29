import { test, expect } from "@playwright/test";

/**
 * Badge runtime di kartu integrasi.
 *
 * Badge adalah `<span>` INLINE di dalam `<h2 class="truncate">`, dan
 * `truncate` = `overflow:hidden; text-overflow:ellipsis; white-space:nowrap`.
 * Dengan `white-space:nowrap`, nama panjang TIDAK membungkus - seluruh baris
 * jadi satu string panjang yang melebar melewati tepi h2, lalu terpotong
 * `overflow:hidden`. Badge berada DI AKHIR baris itu, jadi yang pertama
 * keluar dari area potong adalah badge-nya.
 *
 * Test ini mengukur geometri sungguhan, bukan menebak: untuk tiap card, badge
 * harus (1) terlihat, (2) berada di dalam kotak card, dan (3) tidak
 * terpotong oleh kotak h2 induknya.
 */

const TARGET = process.env.E2E_TARGET ?? "https://katalir.de5.net";
const CARD = '[data-testid="integration-card"]';

type Geom = {
  cards: number;
  badgesTotal: number;
  badgesVisible: number;
  badgesOutsideCard: string[];
  badgesClippedByTitle: string[];
  sample: { name: string; titleW: number; badgeRight: number; titleRight: number }[];
};

async function measure(page: import("@playwright/test").Page): Promise<Geom> {
  return page.evaluate((cardSel) => {
    const cards = Array.from(document.querySelectorAll(cardSel));
    const outside: string[] = [];
    const clipped: string[] = [];
    const sample: Geom["sample"] = [];
    let visible = 0;
    let total = 0;

    for (const card of cards) {
      const title = card.querySelector("h2");
      const badge = title?.querySelector<HTMLElement>('[data-testid^="badge-"]');
      if (!title || !badge) continue;
      total += 1;

      const cr = card.getBoundingClientRect();
      const tr = title.getBoundingClientRect();
      const br = badge.getBoundingClientRect();
      const cs = getComputedStyle(badge);
      if (br.width > 0 && br.height > 0 && cs.visibility !== "hidden" && cs.display !== "none") visible += 1;

      if (br.right > cr.right + 0.5) {
        outside.push(`${(title.textContent ?? "").trim().slice(0, 40)} | badge.right=${br.right.toFixed(0)} card.right=${cr.right.toFixed(0)}`);
      }
      const style = getComputedStyle(title);
      const clips = style.overflow === "hidden" || style.overflowX === "hidden";
      if (clips && br.right > tr.right + 0.5) {
        clipped.push(`${(title.textContent ?? "").trim().slice(0, 40)} | badge.right=${br.right.toFixed(0)} h2.right=${tr.right.toFixed(0)}`);
      }
      if (sample.length < 5) {
        sample.push({
          name: (title.textContent ?? "").trim().slice(0, 46),
          titleW: Math.round(tr.width),
          badgeRight: Math.round(br.right),
          titleRight: Math.round(tr.right),
        });
      }
    }
    return { cards: cards.length, badgesTotal: total, badgesVisible: visible, badgesOutsideCard: outside, badgesClippedByTitle: clipped, sample };
  }, CARD);
}

async function search(page: import("@playwright/test").Page, term: string) {
  await page.goto(`${TARGET}/integrations`, { waitUntil: "domcontentloaded" });
  await page.locator(CARD).first().waitFor({ timeout: 45000 });
  // Pakai testid, bukan `getByPlaceholder` dengan regex: placeholder-nya
  // berisi "23.474+ integrasi" yang bisa berubah, dan regex `/cari|search/i`
  // ikut cocok ke input lain. Testid stabil.
  await page.getByTestId("integrations-search").fill(term);
  await page.waitForResponse((r) => r.url().includes("/mcp/registry?") && r.url().includes("search="), { timeout: 45000 });
  await page.waitForTimeout(800);
}


test("badge terlihat untuk judul panjang (desktop)", async ({ page }) => {
  await search(page, "openrouter");
  const g = await measure(page);
  console.log(`DESKTOP cards=${g.cards} badges=${g.badgesTotal} visible=${g.badgesVisible}`);
  console.log(`DESKTOP outside=${JSON.stringify(g.badgesOutsideCard.slice(0, 3))}`);
  console.log(`DESKTOP clipped=${JSON.stringify(g.badgesClippedByTitle.slice(0, 3))}`);
  for (const s of g.sample) console.log(`DESKTOP sample="${s.name}" titleW=${s.titleW} badgeRight=${s.badgeRight} titleRight=${s.titleRight}`);

  expect(g.badgesTotal).toBeGreaterThan(0);
  expect(g.badgesVisible).toBe(g.badgesTotal);
  expect(g.badgesClippedByTitle).toEqual([]);
  expect(g.badgesOutsideCard).toEqual([]);
  await page.locator(CARD).first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await page.screenshot({ path: "badge-layout-desktop.png", fullPage: false });
  console.log("SHOT=badge-layout-desktop.png");
});

test("badge terlihat untuk judul panjang (mobile 375px)", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await search(page, "openrouter");
  const g = await measure(page);
  console.log(`MOBILE cards=${g.cards} badges=${g.badgesTotal} visible=${g.badgesVisible}`);
  console.log(`MOBILE outside=${JSON.stringify(g.badgesOutsideCard.slice(0, 3))}`);
  console.log(`MOBILE clipped=${JSON.stringify(g.badgesClippedByTitle.slice(0, 3))}`);

  expect(g.badgesTotal).toBeGreaterThan(0);
  expect(g.badgesVisible).toBe(g.badgesTotal);
  expect(g.badgesClippedByTitle).toEqual([]);
  expect(g.badgesOutsideCard).toEqual([]);
  await page.locator(CARD).first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await page.screenshot({ path: "badge-layout-mobile.png", fullPage: false });
  console.log("SHOT=badge-layout-mobile.png");
});

test("judul buatan sangat panjang tidak menyembunyikan badge", async ({ page }) => {
  await page.goto(`${TARGET}/integrations`, { waitUntil: "domcontentloaded" });
  await page.locator(CARD).first().waitFor({ timeout: 45000 });

  await page.evaluate((cardSel) => {
    const t = document.querySelector(`${cardSel} [data-testid="integration-title"]`);
    if (!t) throw new Error("card title span not found");
    // Ganti HANYA teks judul. Versi pertama yang mencoba set textContent
    // pada <h2> ikut menghapus <span> badge, jadi test "lolos" padahal badge
    // masih hidup dan tetap diuji.
    t.textContent = "Very Long Title That Should Not Break Layout At All Costs Even On Mobile 375px";
  }, CARD);
  await page.waitForTimeout(300);

  const g = await measure(page);
  console.log(`INJECT cards=${g.cards} visible=${g.badgesVisible}`);
  console.log(`INJECT outside=${JSON.stringify(g.badgesOutsideCard.slice(0, 2))}`);
  console.log(`INJECT clipped=${JSON.stringify(g.badgesClippedByTitle.slice(0, 2))}`);
  for (const s of g.sample) console.log(`INJECT sample="${s.name.slice(0, 70)}" titleW=${s.titleW} badgeRight=${s.badgeRight} titleRight=${s.titleRight}`);

  expect(g.badgesClippedByTitle).toEqual([]);
  expect(g.badgesOutsideCard).toEqual([]);
  // 50/50: SETIAP kartu harus punya badge yang terlihat, termasuk kartu yang
  // judulnya kita replaced. Kalau ini 49, berarti ada kartu yang badge-nya
  // hilang dan test sebelumnya hanya kebetulan tidak menangkapnya.
  expect(g.badgesTotal).toBe(g.cards);
  expect(g.badgesVisible).toBe(g.badgesTotal);
  await page.locator(CARD).first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await page.screenshot({ path: "badge-layout-injected.png", fullPage: false });
  console.log("SHOT=badge-layout-injected.png");
});
