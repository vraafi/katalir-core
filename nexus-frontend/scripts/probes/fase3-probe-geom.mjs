/**
 * Geometri kanvas: viewport transform, posisi alur+layar tiap node, batas
 * kanvas, dan toolbar. Untuk memastikan koordinat contoh benar-benar terlihat.
 * Pakai: node scripts/fase3-probe-geom.mjs
 */
import { chromium } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const ref = (readFileSync(join(process.cwd(), ".env.local"), "utf-8").match(
  /NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/
) || [])[1];

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const sess = JSON.parse(readFileSync(join(process.cwd(), "_e2e_session.refreshed.json"), "utf-8"));
await page.addInitScript((kv) => { try { window.localStorage.setItem(kv.key, JSON.stringify(kv.value)); } catch {} }, { key: `sb-${ref}-auth-token`, value: sess });

await page.goto("http://localhost:3000/builder?demo=1", { waitUntil: "domcontentloaded" });
await page.waitForSelector('[data-testid="node-card"]', { timeout: 45000 });
await page.waitForTimeout(2500);

const g = await page.evaluate(() => {
  const canvas = document.querySelector(".react-flow").getBoundingClientRect();
  const vp = document.querySelector(".react-flow__viewport").style.transform;
  const nodes = [...document.querySelectorAll(".react-flow__node")].map((el) => {
    const r = el.getBoundingClientRect();
    return {
      id: el.getAttribute("data-id"),
      flow: el.style.transform,
      screen: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
    };
  });
  const tb = document.querySelector('[data-testid="canvas-toolbar"]').getBoundingClientRect();
  const aside = document.querySelector('[data-testid="config-aside"]');
  return {
    canvas: { x: Math.round(canvas.x), y: Math.round(canvas.y), w: Math.round(canvas.width), h: Math.round(canvas.height) },
    viewport: vp,
    toolbar: { x: Math.round(tb.x), y: Math.round(tb.y), w: Math.round(tb.width), h: Math.round(tb.height) },
    asideVisible: aside ? aside.getBoundingClientRect().width > 0 : false,
    asideBox: aside ? { x: Math.round(aside.getBoundingClientRect().x), w: Math.round(aside.getBoundingClientRect().width) } : null,
    nodes,
  };
});
console.log(JSON.stringify(g, null, 1));
await browser.close();
