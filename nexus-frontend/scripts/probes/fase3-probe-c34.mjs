/**
 * Probe cepat untuk C3 (drag node) & C4 (hapus node) — mencetak mekanika DOM
 * apa adanya, tanpa auto-wait 90 detik.
 * Pakai: node scripts/fase3-probe-c34.mjs
 */
import { chromium } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const ref = (readFileSync(join(process.cwd(), ".env.local"), "utf-8").match(
  /NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/
) || [])[1];
const LS_KEY = `sb-${ref}-auth-token`;

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const sess = JSON.parse(readFileSync(join(process.cwd(), "_e2e_session.refreshed.json"), "utf-8"));
await page.addInitScript((kv) => { try { window.localStorage.setItem(kv.key, JSON.stringify(kv.value)); } catch {} }, { key: LS_KEY, value: sess });

await page.goto("http://localhost:3000/builder?demo=1", { waitUntil: "domcontentloaded" });
await page.waitForSelector('[data-testid="node-card"]', { timeout: 45000 });
await page.waitForTimeout(2500);

// --- Lingkungan -------------------------------------------------------------
const env = await page.evaluate(() => ({
  coarse: window.matchMedia("(pointer: coarse)").matches,
  fine: window.matchMedia("(pointer: fine)").matches,
  cardCount: document.querySelectorAll('[data-testid="node-card"]').length,
  toolbarBox: (() => {
    const t = document.querySelector('[data-testid="canvas-toolbar"]');
    const b = t.getBoundingClientRect();
    return { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) };
  })(),
}));
console.log("ENV=" + JSON.stringify(env));

// --- C4: tombol "Hapus node" ------------------------------------------------
await page.locator('[data-testid="node-card"]').first().click();
await page.waitForTimeout(700);

const del = await page.evaluate(() => {
  const btns = [...document.querySelectorAll('[aria-label="Hapus node"]')];
  return btns.map((b) => {
    const r = b.getBoundingClientRect();
    const cx = Math.round(r.x + r.width / 2);
    const cy = Math.round(r.y + r.height / 2);
    const top = document.elementFromPoint(cx, cy);
    return {
      visible: r.width > 0 && r.height > 0,
      rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
      topmost: top ? String(top.getAttribute("data-testid") || top.getAttribute("aria-label") || top.className).slice(0, 60) : null,
      isSelf: top === b || b.contains(top),
    };
  });
});
console.log("DELETE_BUTTONS=" + JSON.stringify(del, null, 1));

// --- C3: drag node ----------------------------------------------------------
const card = page.locator('[data-testid="node-card"]').first();
const box = await card.boundingBox();
const cx = box.x + box.width / 2;
const cy = box.y + box.height / 2;
const atCenter = await page.evaluate(({ x, y }) => {
  const el = document.elementFromPoint(x, y);
  return { tag: el?.tagName, cls: String(el?.className || "").slice(0, 60), testid: el?.getAttribute("data-testid") };
}, { x: Math.round(cx), y: Math.round(cy) });
console.log("CARD_CENTER_TOP=" + JSON.stringify(atCenter));

await page.mouse.move(cx, cy);
await page.mouse.down();
const steps = [10, 30, 60, 120];
for (const s of steps) {
  await page.mouse.move(cx + s, cy + Math.round(s * 0.8), { steps: 5 });
  await page.waitForTimeout(120);
  const r = await card.boundingBox();
  const cls = await page.evaluate(() => document.querySelector(".react-flow__node")?.getAttribute("class"));
  console.log(`DRAG +${s} card=(${Math.round(r.x)},${Math.round(r.y)}) nodeCls=${String(cls).slice(0, 70)}`);
}
await page.mouse.up();
await page.waitForTimeout(400);
const rEnd = await card.boundingBox();
console.log(`DRAG_END card=(${Math.round(rEnd.x)},${Math.round(rEnd.y)}) start=(${Math.round(box.x)},${Math.round(box.y)})`);

await browser.close();
