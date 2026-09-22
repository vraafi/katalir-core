/**
 * Probe terakhir: (A) C5 connect dengan diagnostik titik pointer, (B) empty
 * state CTA add-node. Pakai: node scripts/fase3-probe-last.mjs
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
page.on("pageerror", (e) => console.log("PAGEERROR " + String(e).slice(0, 160)));
page.on("console", (m) => { if (m.type() === "error") console.log("CONSOLE " + m.text().slice(0, 160)); });
const sess = JSON.parse(readFileSync(join(process.cwd(), "_e2e_session.refreshed.json"), "utf-8"));
await page.addInitScript((kv) => { try { window.localStorage.setItem(kv.key, JSON.stringify(kv.value)); } catch {} }, { key: `sb-${ref}-auth-token`, value: sess });

// ---------- A. C5 connect (meniru persis langkah spec) ----------
await page.goto("http://localhost:3000/builder?demo=1", { waitUntil: "domcontentloaded" });
await page.waitForSelector('[data-testid="node-card"]', { timeout: 45000 });
await page.waitForTimeout(2500);

const src = page.locator('.react-flow__node[data-id="demo-agent-2"] .k-handle--out');
const dst = page.locator('.react-flow__node[data-id="demo-mcp"] .k-handle--in');
console.log("src count=" + (await src.count()) + " dst count=" + (await dst.count()));
const sb = await src.boundingBox();
const db = await dst.boundingBox();
console.log("srcBox=" + JSON.stringify(sb) + " dstBox=" + JSON.stringify(db));

const topAt = async (x, y) =>
  page.evaluate(({ x, y }) => {
    const el = document.elementFromPoint(x, y);
    return el ? `${el.tagName}.${String(el.getAttribute("class") || "").split(" ").slice(0, 3).join(".")}` : null;
  }, { x: Math.round(x), y: Math.round(y) });
console.log("top at src center=" + (await topAt(sb.x + sb.width / 2, sb.y + sb.height / 2)));
console.log("top at dst center=" + (await topAt(db.x + db.width / 2, db.y + db.height / 2)));

const before = await page.locator(".react-flow__edge").count();
await page.mouse.move(sb.x + sb.width / 2, sb.y + sb.height / 2);
await page.mouse.down();
await page.waitForTimeout(250);
await page.mouse.move(db.x + db.width / 2, db.y + db.height / 2, { steps: 12 });
await page.waitForTimeout(250);
const hov = await page.evaluate(() => document.querySelectorAll(".react-flow__handle.connectingto").length);
await page.mouse.up();
await page.waitForTimeout(800);
console.log(`A: connectingto=${hov} edges ${before}->${await page.locator(".react-flow__edge").count()}`);

// ---------- B. Empty state CTA (KONDISI SAMA seperti spec: sesi dibersihkan) ----------
const ctx2 = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page2 = await ctx2.newPage();
page2.on("pageerror", (e) => console.log("P2 PAGEERROR " + String(e).slice(0, 200)));
page2.on("console", (m) => { if (m.type() === "error") console.log("P2 CONSOLE " + m.text().slice(0, 200)); });
await page2.addInitScript((kv) => { try { window.localStorage.setItem(kv.key, JSON.stringify(kv.value)); } catch {} }, { key: `sb-${ref}-auth-token`, value: sess });
await page2.addInitScript(() => { try { window.localStorage.clear(); } catch {} });
await page2.goto("http://localhost:3000/builder", { waitUntil: "domcontentloaded" });
await page2.waitForSelector('[data-testid="canvas-empty-state"]', { timeout: 30000 });
await page2.waitForTimeout(1500);
console.log("B: cards before=" + (await page2.locator('[data-testid="node-card"]').count()) + " empty=" + (await page2.locator('[data-testid="canvas-empty-state"]').count()));
const btn = page2.locator('[data-testid="btn-empty-add-node"]');
console.log("B: btnVisible=" + (await btn.isVisible()));
await btn.click();
await page2.waitForTimeout(1500);
console.log("B: cards after=" + (await page2.locator('[data-testid="node-card"]').count()) + " emptyStill=" + (await page2.locator('[data-testid="canvas-empty-state"]').count()));
console.log("B: cardIds=" + JSON.stringify(await page2.$$eval(".react-flow__node", (els) => els.map((e) => e.getAttribute("data-id")))));

await browser.close();

