/**
 * FASE 4 — bukti visual + angka.
 *
 * Menghasilkan (di %TEMP%\fase4_shots):
 *   - before/after untuk /settings, /billing, /help (desktop + mobile).
 *     "before" DIAMBIL dari screenshot audit FASE 0 (%TEMP%\uiux_f0) supaya
 *     perbandingannya nyata, bukan direkonstruksi.
 *   - motion: page transition (opacity/transform terukur), hover tombol
 *     (background berubah), skeleton saat data lambat (/quota ditahan 3 dtk),
 *     dan mode prefers-reduced-motion (tanpa pergeseran).
 * Pakai: node scripts/fase4-shots.mjs
 */
import { chromium } from "@playwright/test";
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const BASE = "http://localhost:3000";
const OUT = join(tmpdir(), "fase4_shots");
const BEFORE = join(tmpdir(), "uiux_f0");
const PAGES = ["settings", "billing", "help"];
mkdirSync(OUT, { recursive: true });

const ref = (readFileSync(join(process.cwd(), ".env.local"), "utf-8").match(
  /NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/
) || [])[1];
const sess = JSON.parse(readFileSync(join(process.cwd(), "_e2e_session.refreshed.json"), "utf-8"));

const evidence = { beforeCopied: [], after: [], motion: {}, reducedMotion: null };

async function seed(page) {
  await page.addInitScript(
    (kv) => { try { window.localStorage.setItem(kv.key, JSON.stringify(kv.value)); } catch {} },
    { key: `sb-${ref}-auth-token`, value: sess }
  );
}

// 1. Salin baseline FASE 0 sebagai "before"
for (const p of PAGES) {
  for (const [suffix, label] of [["desktop", "desktop"], ["mobile", "mobile"]]) {
    const src = join(BEFORE, `shots_${suffix}_${p}.png`);
    if (!existsSync(src)) continue;
    const dst = join(OUT, `before_${label}_${p}.png`);
    copyFileSync(src, dst);
    evidence.beforeCopied.push(`before_${label}_${p}.png`);
  }
}

const browser = await chromium.launch();

// 2. "after" desktop + mobile
for (const vp of [
  { name: "desktop", viewport: { width: 1440, height: 900 }, mobile: false },
  { name: "mobile", viewport: { width: 390, height: 844 }, mobile: true },
]) {
  const ctx = await browser.newContext({ viewport: vp.viewport, hasTouch: vp.mobile, isMobile: vp.mobile });
  const page = await ctx.newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e).slice(0, 140)));
  for (const p of PAGES) {
    await seed(page);
    await page.goto(`${BASE}/${p}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
    await page.waitForTimeout(2200);
    // Skeleton pemakaian ditahan supaya TIDAK ikut terpotret sebagai isi final.
    await page.screenshot({ path: join(OUT, `after_${vp.name}_${p}.png`), fullPage: false });
    const h = await page.evaluate(() => document.body.scrollHeight);
    evidence.after.push({ name: `after_${vp.name}_${p}.png`, scrollHeight: h });
  }
  evidence[`pageerrors_${vp.name}`] = errs;
  await ctx.close();
}

// 3. Motion: page transition, hover, skeleton, reduced-motion
{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await seed(page);

  // 3a. Transisi halaman: elemen ada + animasi mengubah opacity/transform.
  await page.goto(`${BASE}/settings`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
  const t0 = await page.evaluate(() => {
    const el = document.querySelector('[data-testid="page-transition"]');
    if (!el) return null;
    const cs = getComputedStyle(el);
    return { opacity: cs.opacity, transform: cs.transform };
  });
  await page.waitForTimeout(400);
  const t1 = await page.evaluate(() => {
    const el = document.querySelector('[data-testid="page-transition"]');
    if (!el) return null;
    const cs = getComputedStyle(el);
    return { opacity: cs.opacity, transform: cs.transform };
  });
  await page.screenshot({ path: join(OUT, "motion_page_transition.png") });
  evidence.motion.pageTransition = { t0, t1 };

  // 3b. Skeleton saat data lambat: tahan /quota 3 detik lalu potret.
  const page2 = await ctx.newPage();
  await seed(page2);
  await page2.route("**/quota", async (route) => {
    await new Promise((r) => setTimeout(r, 3000));
    await route.continue();
  });
  await page2.goto(`${BASE}/billing`, { waitUntil: "domcontentloaded" });
  await page2.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
  await page2.waitForSelector('[data-testid="usage-skeleton"]', { timeout: 10000 }).catch(() => {});
  const skeletonVisible = (await page2.locator('[data-testid="usage-skeleton"]').count()) > 0;
  await page2.screenshot({ path: join(OUT, "motion_loading_skeleton.png") });
  await page2.waitForTimeout(4200);
  const barsAfter = await page2.locator('[data-testid="usage-bars"] [role="progressbar"]').count();
  evidence.motion.skeleton = { skeletonVisible, barsAfter };

  // 3c. Hover tombol: background berubah saat pointer di atasnya.
  const btn = page2.locator('[data-testid="plan-checkout"]').first();
  if ((await btn.count()) > 0) {
    const before = await btn.evaluate((el) => getComputedStyle(el).backgroundColor);
    await btn.hover();
    await page2.waitForTimeout(300);
    const after = await btn.evaluate((el) => getComputedStyle(el).backgroundColor);
    await page2.screenshot({ path: join(OUT, "motion_button_hover.png") });
    evidence.motion.hover = { before, after, changed: before !== after };
  }
  await ctx.close();
}

// 4. prefers-reduced-motion: transisi TANPA pergeseran (y=0), fade tetap ada.
{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
  const page = await ctx.newPage();
  await seed(page);
  await page.goto(`${BASE}/settings`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
  const reduced = await page.evaluate(() => {
    const el = document.querySelector('[data-testid="page-transition"]');
    if (!el) return null;
    const cs = getComputedStyle(el);
    return { transform: cs.transform, opacity: cs.opacity };
  });
  evidence.reducedMotion = reduced;
  await page.screenshot({ path: join(OUT, "motion_reduced.png") });
  await ctx.close();
}

await browser.close();
writeFileSync(join(OUT, "fase4_shots.json"), JSON.stringify(evidence, null, 2));
console.log(JSON.stringify(evidence, null, 2));
console.log(`\nSCREENSHOTS -> ${OUT}`);

