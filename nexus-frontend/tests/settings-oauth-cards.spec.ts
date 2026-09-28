import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// Mengukur, bukan Assume: klaim "kartu simetris" hanya sah kalau
// getBoundingClientRect() kedua kartu benar-benar sama tinggi.
//
// Jalankan terhadap produksi secara default (AXE_TARGET), atau lokal:
//   AXE_TARGET=http://127.0.0.1:3000 npx playwright test -c playwright.config.ts tests/settings-oauth-cards.spec.ts
const BASE = (process.env.AXE_TARGET || "https://katalir.de5.net").replace(/\/$/, "");

/** Kartu koneksi. `id` bukan `data-testid` di JSX, jadi pakai yang benar. */
const CONNECTIONS = '[data-testid="card-connections"]';

/** Folder bukti. Di-commit supaya screenshot bisa dibandingkan lewat `git diff`. */
const SHOTS = "../docs/marketing/screenshots";

const GOOGLE = '[data-testid="card-oauth-google"]';
const SLACK = '[data-testid="card-oauth-slack"]';

type Heights = { google: number; slack: number; diff: number };

async function measure(page: import("@playwright/test").Page): Promise<Heights> {
  const [g, s] = await Promise.all([
    page.locator(GOOGLE).boundingBox(),
    page.locator(SLACK).boundingBox(),
  ]);
  if (!g || !s) throw new Error("kedua kartu OAuth tidak ada di DOM");
  return { google: Math.round(g.height), slack: Math.round(s.height), diff: Math.round(Math.abs(g.height - s.height)) };
}

test.describe("OAuth cards symmetry", () => {
  test("desktop 1440x900: tinggi kedua kartu sama", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/settings`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    await page.locator(GOOGLE).waitFor({ state: "visible", timeout: 45_000 });
    await page.waitForTimeout(1500);

    const m = await measure(page);
    console.log(`CARD_HEIGHT desktop google=${m.google} slack=${m.slack} diff=${m.diff}`);
    expect(m.diff, `kartu tidak simetris (selisih ${m.diff}px)`).toBeLessThanOrEqual(1);

    await page.locator(CONNECTIONS).screenshot({ path: `${SHOTS}/settings-oauth-cards-desktop.png` });
    // Halaman penuh untuk audit polish Task E (kredensial, zona berbahaya, spacing).
    await page.screenshot({ path: `${SHOTS}/settings-full-desktop.png`, fullPage: true });
  });

  test("footer tiap kartu membumi (mt-auto bekerja)", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/settings`, { waitUntil: "load", timeout: 90_000 });
    await page.locator(GOOGLE).waitFor({ state: "visible", timeout: 45_000 });
    await page.waitForTimeout(1200);

    // Alas kaki tiap kartu harus berakhir di tinggi yang sama, karena keduanya
    // duduk di dasar kartu yang sama tingginya.
    const bottoms = await page.evaluate(
      ([g, s]) => {
        const gb = document.querySelector(g)?.getBoundingClientRect();
        const sb = document.querySelector(s)?.getBoundingClientRect();
        return [gb ? gb.bottom : 0, sb ? sb.bottom : 0];
      },
      [GOOGLE, SLACK],
    );
    const diff = Math.abs(bottoms[0] - bottoms[1]);
    console.log(`CARD_BOTTOM google=${Math.round(bottoms[0])} slack=${Math.round(bottoms[1])} diff=${Math.round(diff)}`);
    expect(diff, `alas kaki kartu tidak sejajar (selisih ${Math.round(diff)}px)`).toBeLessThanOrEqual(2);
  });

  test("disclaimer ada di SETIAP kartu, bukan hanya Slack", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/settings`, { waitUntil: "load", timeout: 90_000 });
    await page.locator(GOOGLE).waitFor({ state: "visible", timeout: 45_000 });
    await page.waitForTimeout(1200);

    for (const id of ["google", "slack"]) {
      const el = page.locator(`[data-testid="oauth-revoke-${id}"]`);
      await expect(el, `disclaimer ${id} tidak ada`).toBeVisible();
      const text = (await el.innerText()).trim();
      expect(text.length, `disclaimer ${id} kosong`).toBeGreaterThan(20);
      console.log(`DISCLAIMER ${id} = ${text}`);
    }

    // Keduanya harus menyebut tempat pencabutan yang BENAR, tidak tertukar.
    await expect(page.locator('[data-testid="oauth-revoke-google"]')).toContainText("Google");
    await expect(page.locator('[data-testid="oauth-revoke-slack"]')).toContainText("Slack");
  });

  test("mobile 375x812: tidak ada overflow horizontal", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(`${BASE}/settings`, { waitUntil: "load", timeout: 90_000 });
    await page.locator(GOOGLE).waitFor({ state: "visible", timeout: 45_000 });
    await page.waitForTimeout(1200);

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    console.log(`MOBILE_OVERFLOW = ${overflow}px`);
    expect(overflow, `halaman meluber ${overflow}px`).toBeLessThanOrEqual(0);

    await page.screenshot({ path: `${SHOTS}/settings-oauth-cards-mobile.png`, fullPage: false });
  });

  test("dark mode: kartu tetap simetris dan tidak kehilangan disclaimer", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/settings`, { waitUntil: "load", timeout: 90_000 });
    await page.locator(GOOGLE).waitFor({ state: "visible", timeout: 45_000 });

    // Tekan kontrol tema yang BENAR-BENAR ada di halaman, bukan menebak
    // localStorage. Halaman ini pakai next-themes (kunci `theme`), sementara
    // ThemeToggle lama memakai `katalir.theme`; menyetel kunci yang salah
    // membuat test mengukur mode terang sambil mengira ia mode gelap.
    await page.locator('[data-testid="app-theme-dark"]').click();
    // Tunggu kelas benar-benar menempel di <html> sebelum mengukur apa pun.
    await page.waitForFunction(
      () => document.documentElement.classList.contains("dark"),
      undefined,
      { timeout: 10_000 },
    );
    await page.waitForTimeout(600);

    const m = await measure(page);
    console.log(`CARD_HEIGHT dark google=${m.google} slack=${m.slack} diff=${m.diff}`);
    expect(m.diff, `kartu tidak simetris di dark mode (selisih ${m.diff}px)`).toBeLessThanOrEqual(1);

    // Disclaimer tidak boleh hilang hanya karena tema gelap.
    for (const id of ["google", "slack"]) {
      await expect(page.locator(`[data-testid="oauth-revoke-${id}"]`)).toBeVisible();
    }

    // Kontras teks disclaimer harus nyata di dark mode. Yang diukur adalah
    // luminance WCAG, bukan sekadar "warnanya berbeda" -- teks abu tua di atas
    // kartu gelap lolos pemeriksaan mata tapi gagal WCAG.
    const ratio = await page.evaluate(() => {
      // WAJIB: kembalikan alpha juga. `rgba(0,0,0,0)` adalah "transparan",
      // bukan hitam; kalau alpha dibuang, layer transparan terbaca sebagai
      // rgb(0,0,0) dan hasil kontrasnya palsu.
      const parse = (s: string) => {
        const n = s.match(/[\d.]+/g);
        if (!n || n.length < 3) return null;
        return { rgb: [Number(n[0]), Number(n[1]), Number(n[2])], a: n.length > 3 ? Number(n[3]) : 1 };
      };
      const lum = (rgb: number[]) => {
        const [r, g, b] = rgb.map((v) => {
          const c = v / 255;
          return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
        });
        return 0.2126 * r + 0.7152 * g + 0.0722 * b;
      };
      const el = document.querySelector('[data-testid="oauth-revoke-google"]');
      if (!el) return null;
      const fg = parse(getComputedStyle(el).color);
      if (!fg) return null;

      // Naik sampai menemukan latar yang benar-benar opaque. Mengambil
      // `.closest("div")` saja tidak cukup: kartu sering transparan dan
      // hasilnya ikut parent's background yang juga belum tentu opaque.
      let node: HTMLElement | null = el as HTMLElement;
      let bg: number[] | null = null;
      while (node) {
        const c = parse(getComputedStyle(node).backgroundColor);
        if (c && c.a > 0) {
          bg = c.rgb;
          break;
        }
        node = node.parentElement;
      }
      if (!bg) return null;
      const a = lum(fg.rgb);
      const b = lum(bg);
      return {
        fg: fg.rgb,
        bg,
        dark: document.documentElement.classList.contains("dark"),
        ratio: Math.round(((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)) * 100) / 100,
      };
    });

    console.log(`DARK_CONTRAST ${JSON.stringify(ratio)}`);
    expect(ratio, "warna disclaimer tidak bisa dihitung").not.toBeNull();
    // Guard: kalau kelas dark tidak benar-benar aktif, pengukuran ini bohong.
    expect(ratio!.dark, "kelas .dark tidak aktif -> pengukuran tidak valid").toBe(true);
    // 4.5 = WCAG AA untuk teks normal. Disclaimer font kecil, jadi ini batasnya.
    expect(
      ratio!.ratio,
      `kontras disclaimer ${ratio!.ratio}:1 di bawah WCAG AA (4.5:1), fg=${ratio!.fg} bg=${ratio!.bg}`,
    ).toBeGreaterThanOrEqual(4.5);

    await page.locator(CONNECTIONS).screenshot({ path: `${SHOTS}/settings-oauth-cards-dark.png` });
  });

  test("catatan bahasa tidak tampil dua kali", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/settings`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    await page.locator(GOOGLE).waitFor({ state: "visible", timeout: 45_000 });
    await page.waitForTimeout(1200);

    // `LanguageSwitcher` sudah merender note-nya sendiri, dan `/settings`
    // pernah merendernya sekali lagi -> dua baris identik berturut-turut yang
    // terbaca seperti salah ketik, bukan pesan.
    const note = page.getByText(/Saved automatically on this device|Tersimpan otomatis di perangkat ini/);
    const count = await note.count();
    console.log(`LANGUAGE_NOTE_COUNT = ${count}`);
    expect(count, `catatan bahasa muncul ${count}x, harus tepat 1`).toBe(1);
  });

  test("axe pada /settings tetap 0 violation blocking", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/settings`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    await page.waitForTimeout(1500);

    const results = await new AxeBuilder({ page }).analyze();
    const blocking = results.violations.filter(
      (v) => v.impact === "critical" || v.impact === "serious",
    );
    console.log(`AXE_SETTINGS total=${results.violations.length} blocking=${blocking.length}`);
    if (blocking.length) {
      console.log("AXE_DETAIL " + JSON.stringify(blocking.map((v) => ({ id: v.id, n: v.nodes.length, target: v.nodes[0]?.target }))));
    }
    expect(blocking, JSON.stringify(blocking.map((v) => v.id))).toHaveLength(0);
  });
});
