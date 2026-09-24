/**
 * Probe C5 (connect handle). Mencetak: geometri handle, elemen teratas di titik
 * tengahnya, rantai ancestor + pointer-events, dan 4 cara memulai koneksi.
 * Pakai: node scripts/fase3-probe-c5.mjs
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
const errs = [];
page.on("pageerror", (e) => errs.push(String(e).slice(0, 150)));
const sess = JSON.parse(readFileSync(join(process.cwd(), "_e2e_session.refreshed.json"), "utf-8"));
await page.addInitScript((kv) => { try { window.localStorage.setItem(kv.key, JSON.stringify(kv.value)); } catch {} }, { key: `sb-${ref}-auth-token`, value: sess });

await page.goto("http://localhost:3000/builder?demo=1", { waitUntil: "domcontentloaded" });
await page.waitForSelector('[data-testid="node-card"]', { timeout: 45000 });
await page.waitForTimeout(2500);

const info = await page.evaluate(() => {
  const hs = [...document.querySelectorAll(".react-flow__handle")];
  const pick = (pred) => hs.find(pred);
  const src = pick((h) => h.classList.contains("k-handle--out") && h.closest(".react-flow__node")?.getAttribute("data-id") === "demo-agent-2");
  const dst = pick((h) => h.classList.contains("k-handle--in") && h.closest(".react-flow__node")?.getAttribute("data-id") === "demo-mcp");
  const describe = (h) => {
    if (!h) return null;
    const r = h.getBoundingClientRect();
    const cx = Math.round(r.x + r.width / 2);
    const cy = Math.round(r.y + r.height / 2);
    const top = document.elementFromPoint(cx, cy);
    const cs = getComputedStyle(h);
    const chain = [];
    let el = h;
    while (el && chain.length < 6) {
      chain.push(`${el.tagName}.${String(el.getAttribute("class") || "").split(" ").slice(0, 2).join(".")}[pe=${getComputedStyle(el).pointerEvents}]`);
      el = el.parentElement;
    }
    return {
      rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
      center: [cx, cy],
      topmost: top ? `${top.tagName}.${String(top.getAttribute("class") || "").split(" ").slice(0, 2).join(".")}` : null,
      isHandle: top === h,
      pe: cs.pointerEvents,
      z: cs.zIndex,
      chain,
    };
  };
  return { src: describe(src), dst: describe(dst), nodeCount: document.querySelectorAll(".react-flow__node").length };
});
console.log("HANDLES=" + JSON.stringify(info, null, 1));

const srcSel = '.react-flow__node[data-id="demo-agent-2"] .k-handle--out';
const dstSel = '.react-flow__node[data-id="demo-mcp"] .k-handle--in';

// Cara 1: hover + mouse
{
  const before = await page.locator(".react-flow__edge").count();
  await page.locator(srcSel).hover();
  await page.mouse.down();
  await page.waitForTimeout(200);
  const started = await page.evaluate(() => document.querySelectorAll(".react-flow__handle.connectingfrom").length);
  await page.locator(dstSel).hover();
  await page.waitForTimeout(200);
  const hov = await page.evaluate(() => document.querySelectorAll(".react-flow__handle.connectingto").length);
  await page.mouse.up();
  await page.waitForTimeout(700);
  console.log(`METHOD1 hover+mouse started=${started} hovered=${hov} edges ${before}->${await page.locator(".react-flow__edge").count()}`);
}

// Cara 2: pointer events langsung di elemen handle
{
  const before = await page.locator(".react-flow__edge").count();
  const cb = await page.locator(srcSel).boundingBox();
  const db = await page.locator(dstSel).boundingBox();
  const sx = cb.x + cb.width / 2, sy = cb.y + cb.height / 2;
  const dx = db.x + db.width / 2, dy = db.y + db.height / 2;
  await page.evaluate(({ sx, sy, dx, dy }) => {
    const src = document.querySelector('.react-flow__node[data-id="demo-agent-2"] .k-handle--out');
    const mk = (type, x, y) => new PointerEvent(type, { bubbles: true, cancelable: true, composed: true, pointerId: 1, pointerType: "mouse", isPrimary: true, clientX: x, clientY: y, button: 0, buttons: 1 });
    src.dispatchEvent(mk("pointerdown", sx, sy));
    src.dispatchEvent(mk("pointermove", dx, dy));
    document.dispatchEvent(mk("pointermove", dx, dy));
    document.dispatchEvent(mk("pointerup", dx, dy));
  }, { sx, sy, dx, dy });
  await page.waitForTimeout(800);
  console.log(`METHOD2 pointer-events edges ${before}->${await page.locator(".react-flow__edge").count()}`);
}

// Cara 3: dragTo (Playwright menggerakkan mouse bertahap lalu drop)
{
  const before = await page.locator(".react-flow__edge").count();
  try {
    await page.locator(srcSel).dragTo(page.locator(dstSel), { force: true });
    await page.waitForTimeout(800);
    console.log(`METHOD3 dragTo edges ${before}->${await page.locator(".react-flow__edge").count()}`);
  } catch (e) {
    console.log("METHOD3 gagal: " + String(e).slice(0, 120));
  }
}

console.log("ERRS=" + JSON.stringify(errs));
await browser.close();
