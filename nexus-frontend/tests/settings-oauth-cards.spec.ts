import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * Pemisahan Settings vs Integrations (standar 2026).
 *
 * User complained: "/settings cuma punya 7 provider, padahal klaim 23K
 * katalog. Di mana connect Slack, di mana GitHub?" The cause was that
 * /settings mixed account settings with connections.
 *
 * These tests assert the SEPARATION itself, not just that a page renders:
 * OAuth cards must be gone from /settings and present on /integrations.
 */
const BASE = (process.env.AXE_TARGET || "https://katalir.de5.net").replace(/\/$/, "");
const SHOTS = "../docs/marketing/screenshots";

test.describe("Settings vs Integrations", () => {
  test("/settings TIDAK lagi memuat kartu OAuth", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/settings`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    await page.waitForTimeout(1200);

    // Kartu OAuth pindah ke /integrations. Kalau muncul lagi di sini, means
    // someone re-added them and the two pages drift apart again.
    await expect(page.locator('[data-testid="card-connections"]')).toHaveCount(0);
    await expect(page.locator('[data-testid="card-oauth-google"]')).toHaveCount(0);
    await expect(page.locator('[data-testid="card-oauth-slack"]')).toHaveCount(0);

    // Tapi pintasan ke /integrations harus ada, supaya tidak ada yang tiba
    // di /settings lalu bertanya "jadi di mana?".
    const link = page.locator('[data-testid="settings-integrations-link"]');
    await expect(link, "pintasan ke /integrations hilang").toBeVisible();
    await expect(link).toHaveAttribute("href", "/integrations");

    await page.screenshot({ path: `${SHOTS}/settings-clean-desktop.png`, fullPage: true });
  });

  test("/integrations memuat kartu OAuth simetris", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE}/integrations`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    await page.locator('[data-testid="card-oauth-google"]').waitFor({ state: "visible", timeout: 45_000 });
    await page.waitForTimeout(1500);

    await expect(page.locator('[data-testid="card-connections"]')).toBeVisible();
    await expect(page.locator('[data-testid="card-oauth-google"]')).toBeVisible();
    await expect(page.locator('[data-testid="card-oauth-slack"]')).toBeVisible();

    // Simetri harus tetap berlaku setelah pindah halaman.
    const [g, s] = await Promise.all([
      page.locator('[data-testid="card-oauth-google"]').boundingBox(),
      page.locator('[data-testid="card-oauth-slack"]').boundingBox(),
    ]);
    if (!g || !s) throw new Error("kartu OAuth tidak ada di /integrations");
    const diff = Math.round(Math.abs(g.height - s.height));
    console.log(`INTEGRATIONS_CARD_HEIGHT google=${Math.round(g.height)} slack=${Math.round(s.height)} diff=${diff}`);
    expect(diff, `kartu OAuth tidak simetris di /integrations (selisih ${diff}px)`).toBeLessThanOrEqual(1);

    await page.locator('[data-testid="card-connections"]').screenshot({ path: `${SHOTS}/integrations-connections-desktop.png` });
  });


  test("axe /settings dan /integrations tetap 0 violation blocking", async ({ page }) => {
    for (const route of ["/settings", "/integrations"]) {
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(`${BASE}${route}`, { waitUntil: "load", timeout: 90_000 });
      await page.waitForSelector("#main-content", { timeout: 45_000 });
      await page.waitForTimeout(1500);
      const results = await new AxeBuilder({ page }).analyze();
      const blocking = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
      console.log(`AXE ${route} total=${results.violations.length} blocking=${blocking.length}`);
      if (blocking.length) {
        // Cetak node DETAIL, bukan hanya jumlah: "color-contrast di 9 tempat"
        // tidak bisa diperbaiki tanpa tahu elemen apa yang terlibat.
        console.log(
          "AXE_NODES " +
            route +
            " " +
            JSON.stringify(
              blocking.flatMap((v) =>
                v.nodes.slice(0, 12).map((n) => ({ id: v.id, target: n.target.join(" "), msg: (n.failureSummary || "").slice(0, 160) })),
              ),
            ),
        );
      }
      expect(blocking, `${route}: ${JSON.stringify(blocking.map((v) => v.id))}`).toHaveLength(0);
    }
  });

  test("mobile 375px: kedua halaman tidak meluber", async ({ page }) => {
    for (const route of ["/settings", "/integrations"]) {
      await page.setViewportSize({ width: 375, height: 812 });
      await page.goto(`${BASE}${route}`, { waitUntil: "load", timeout: 90_000 });
      await page.waitForSelector("#main-content", { timeout: 45_000 });
      await page.waitForTimeout(1200);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      console.log(`MOBILE ${route} overflow=${overflow}px`);
      expect(overflow, `${route} meluber ${overflow}px`).toBeLessThanOrEqual(0);
      if (route === "/integrations") {
        await page.screenshot({ path: `${SHOTS}/integrations-mobile.png`, fullPage: false });
      }
    }
  });
});


/** Kartu koneksi. `id` bukan `data-testid` di JSX, jadi pakai yang benar. */
const CONNECTIONS = '[data-testid="card-connections"]';


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
    await page.goto(`${BASE}/integrations`, { waitUntil: "load", timeout: 90_000 });
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
    await page.goto(`${BASE}/integrations`, { waitUntil: "load", timeout: 90_000 });
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
    await page.goto(`${BASE}/integrations`, { waitUntil: "load", timeout: 90_000 });
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
    await page.goto(`${BASE}/integrations`, { waitUntil: "load", timeout: 90_000 });
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
    // Setel tema lewat localStorage milik next-themes (kunci `theme`), bukan
    // lewat klik. Kontrol `app-theme-dark` hanya ada di /settings, sedangkan
    // kartu OAuth kini ada di /integrations -- jadi test ini harus cara yang
    // bekerja di kedua halaman. Kunci `katalir.theme` milik ThemeToggle lama
    // dan TIDAK dibaca next-themes; menyetelnya membuat test mengukur mode
    // terang sambil mengira ia mode gelap.
    await page.addInitScript(() => {
      try {
        window.localStorage.setItem("theme", "dark");
      } catch {
        /* storage diblokir: kelas di bawah yang menentukan */
      }
      document.documentElement.classList.add("dark");
      document.documentElement.style.colorScheme = "dark";
    });
    await page.goto(`${BASE}/integrations`, { waitUntil: "load", timeout: 90_000 });
    await page.locator(GOOGLE).waitFor({ state: "visible", timeout: 45_000 });
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
