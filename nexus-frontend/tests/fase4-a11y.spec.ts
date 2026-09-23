/**
 * FASE 4.5 — audit aksesibilitas otomatis.
 *
 * Tiga lapis bukti:
 *   1. axe-core (WCAG 2.1 A/AA) di 6 rute: 0 pelanggaran `critical`/`serious`.
 *   2. Kontras teks diukur dari computed style (rasio WCAG dihitung sendiri,
 *      bukan dari klaim desain).
 *   3. Focus ring terlihat (outline/box-shadow berubah saat fokus keyboard) dan
 *      tombol ikon-saja punya nama aksesibel.
 *
 * axe disuntik dari `node_modules/axe-core/axe.min.js` (devDependency) supaya
 * tidak bergantung jaringan saat tes berjalan.
 */
import { test, expect, type Page } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const AXE_PATH = join(process.cwd(), "node_modules", "axe-core", "axe.min.js");
const ROUTES = ["/", "/chat", "/settings", "/billing", "/help", "/builder"];

function supabaseRef(): string {
  for (const f of [".env.local", ".env"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    const m = readFileSync(p, "utf-8").match(/NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/);
    if (m) return m[1];
  }
  return "qmukkphwaajzbqjrcvaz";
}

async function seedSession(page: Page) {
  const p = join(process.cwd(), "_e2e_session.refreshed.json");
  if (!existsSync(p)) return;
  const sess = JSON.parse(readFileSync(p, "utf-8"));
  await page.addInitScript(
    (kv: { key: string; value: unknown }) => {
      try { window.localStorage.setItem(kv.key, JSON.stringify(kv.value)); } catch { /* abaikan */ }
    },
    { key: `sb-${supabaseRef()}-auth-token`, value: sess }
  );
}

/** Jalankan axe pada DOM saat ini; kembalikan pelanggaran + TARGET elemennya. */
async function axeScan(page: Page) {
  if (!existsSync(AXE_PATH)) throw new Error("axe-core tidak ada di node_modules (jalankan npm i -D axe-core)");
  await page.addScriptTag({ path: AXE_PATH });
  return page.evaluate(async () => {
    // @ts-expect-error axe disuntik runtime
    const axe = window.axe;
    const res = await axe.run(document, {
      resultTypes: ["violations"],
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
    });
    return (res.violations as {
      id: string;
      impact: string | null;
      nodes: { target: unknown; html: string; failureSummary?: string }[];
    }[]).map((v) => ({
      id: v.id,
      impact: v.impact,
      nodes: v.nodes.length,
      // Target + ringkasan warna: tanpa ini, pesan gagal hanya bilang "ada
      // pelanggaran" dan perbaikannya jadi menebak (pelajaran dari run pertama).
      targets: v.nodes.map((n) => ({
        target: JSON.stringify(n.target).slice(0, 90),
        html: String(n.html).replace(/\s+/g, " ").slice(0, 90),
        why: String(n.failureSummary ?? "").replace(/\s+/g, " ").slice(0, 150),
      })),
    }));
  });
}

// ===========================================================================
// 1. axe-core di 6 rute
// ===========================================================================
for (const route of ROUTES) {
  test(`axe ${route}: 0 pelanggaran critical/serious`, async ({ page }) => {
    await seedSession(page);
    await page.goto(route, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
    await page.waitForTimeout(2500); // beri waktu query/animasi selesai

    const violations = await axeScan(page);
    const severe = violations.filter((v) => v.impact === "critical" || v.impact === "serious");
    console.log(`AXE ${route} total=${violations.length} severe=${severe.length} ${JSON.stringify(violations)}`);
    expect(severe, `pelanggaran serius di ${route}: ${JSON.stringify(severe)}`).toHaveLength(0);
  });
}

// ===========================================================================
// 2. Kontras teks (dihitung dari computed style)
// ===========================================================================
/** Rasio kontras WCAG dari dua warna `rgb(...)`/`rgba(...)`. */
function contrastRatio(fg: string, bg: string): number {
  const parse = (c: string) => {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return [0, 0, 0];
    return m[1].split(",").slice(0, 3).map((n) => Number(n.trim()));
  };
  const lum = (rgb: number[]) => {
    const [r, g, b] = rgb.map((v) => {
      const s = v / 255;
      return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const l1 = lum(parse(fg));
  const l2 = lum(parse(bg));
  const [hi, lo] = l1 > l2 ? [l1, l2] : [l2, l1];
  return (hi + 0.05) / (lo + 0.05);
}

test("kontras: teks utama & sekunder halaman akun >= 4.5:1 (WCAG AA)", async ({ page }) => {
  await seedSession(page);
  await page.goto("/settings", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
  await page.waitForTimeout(1200);

  const samples = await page.evaluate(() => {
    const bgOf = (el: Element | null): string => {
      let cur: Element | null = el;
      while (cur) {
        const c = getComputedStyle(cur).backgroundColor;
        if (c && !/rgba?\(0, 0, 0, 0\)|transparent/.test(c)) return c;
        cur = cur.parentElement;
      }
      return getComputedStyle(document.body).backgroundColor;
    };
    const pick = (sel: string) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const cs = getComputedStyle(el);
      return { sel, color: cs.color, bg: bgOf(el), size: cs.fontSize, weight: cs.fontWeight };
    };
    return [
      pick("h1"),
      pick('[data-testid="settings-email"]'),
      pick("main p"),
      pick('[data-testid="vault-key-hint"]'),
      pick("nav a"),
    ].filter(Boolean) as { sel: string; color: string; bg: string; size: string; weight: string }[];
  });

  for (const s of samples) {
    const ratio = contrastRatio(s.color, s.bg);
    const large = parseFloat(s.size) >= 18.66 || (parseFloat(s.size) >= 14 && Number(s.weight) >= 700);
    const min = large ? 3 : 4.5;
    console.log(`CONTRAST ${s.sel} ${s.color} on ${s.bg} = ${ratio.toFixed(2)}:1 (min ${min})`);
    expect(ratio, `kontras ${s.sel} = ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(min);
  }
  expect(samples.length).toBeGreaterThanOrEqual(4);
});


// ===========================================================================
// 3. Focus ring + nama aksesibel tombol ikon
// ===========================================================================
test("focus: elemen fokusable punya indikator fokus yang terlihat", async ({ page }) => {
  await seedSession(page);
  await page.goto("/settings", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
  await page.waitForTimeout(1000);

  const targets = ['[data-testid="app-theme-light"]', '[data-testid="canvas-theme-radio-midnight"]', '[data-testid="vault-save"]'];
  let checked = 0;
  for (const sel of targets) {
    const el = page.locator(sel).first();
    if ((await el.count()) === 0) continue;
    const read = (n: Element) => {
      const cs = getComputedStyle(n);
      return { outline: `${cs.outlineWidth} ${cs.outlineStyle}`, shadow: cs.boxShadow };
    };
    const before = await el.evaluate(read);
    await el.focus();
    await page.waitForTimeout(180);
    const after = await el.evaluate(read);
    const changed = before.outline !== after.outline || before.shadow !== after.shadow;
    console.log(`FOCUS ${sel} before=${JSON.stringify(before)} after=${JSON.stringify(after)} changed=${changed}`);
    expect(changed, `tidak ada indikator fokus pada ${sel}`).toBe(true);
    checked += 1;
  }
  expect(checked, "tidak ada kontrol yang berhasil diuji fokusnya").toBeGreaterThanOrEqual(2);
});

test("a11y: tombol ikon-saja punya nama aksesibel; input punya label", async ({ page }) => {
  await seedSession(page);
  await page.goto("/settings", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
  await page.waitForTimeout(1000);

  const unnamed = await page.$$eval("button", (els) => {
    const named = (b: Element) =>
      (b.textContent ?? "").trim().length > 0 ||
      !!b.getAttribute("aria-label") ||
      !!b.getAttribute("aria-labelledby") ||
      !!b.getAttribute("title");
    return els.filter((b) => !named(b)).map((b) => (b.className || "").slice(0, 40));
  });
  console.log("UNNAMED_BUTTONS=" + JSON.stringify(unnamed));
  expect(unnamed, "tombol tanpa nama aksesibel").toHaveLength(0);

  const inputs = await page.$$eval("input, select", (els) =>
    els.map((el) => {
      const id = el.getAttribute("id");
      const labelled =
        !!el.getAttribute("aria-label") ||
        (!!id && !!document.querySelector(`label[for="${id}"]`)) ||
        !!el.closest("label");
      return { tag: el.tagName.toLowerCase(), id, labelled };
    })
  );
  console.log("INPUTS=" + JSON.stringify(inputs));
  expect(inputs.length).toBeGreaterThan(0);
  expect(inputs.filter((i) => !i.labelled), "input tanpa label").toHaveLength(0);
});

