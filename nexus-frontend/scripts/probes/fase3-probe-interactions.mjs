/**
 * Probe diagnostik untuk 3 interaksi yang gagal di spec (C5 connect, C6 delete
 * edge, C7 pan). Tujuannya: menemukan SEBAB mekanis (bukan menebak), dengan
 * mencetak keadaan DOM + transform viewport pada setiap langkah.
 *
 * Pakai: node scripts/fase3-probe-interactions.mjs
 */
import { chromium } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const BASE = "http://localhost:3000";
const ref = (readFileSync(join(process.cwd(), ".env.local"), "utf-8").match(
  /NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/
) || [])[1];
const LS_KEY = `sb-${ref}-auth-token`;

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const errs = [];
page.on("pageerror", (e) => errs.push(String(e).slice(0, 200)));
page.on("console", (m) => { if (m.type() === "error") errs.push("CONSOLE " + m.text().slice(0, 200)); });

const sess = JSON.parse(readFileSync(join(process.cwd(), "_e2e_session.refreshed.json"), "utf-8"));
await page.addInitScript((kv) => { try { window.localStorage.setItem(kv.key, JSON.stringify(kv.value)); } catch {} }, { key: LS_KEY, value: sess });

await page.goto(`${BASE}/builder?demo=1`, { waitUntil: "domcontentloaded" });
await page.waitForSelector('[data-testid="node-card"]', { timeout: 45000 });
await page.waitForTimeout(2500);

// 0) Apakah API backend bisa dijangkau dari halaman? (bug env var spasi)
const api = await page.evaluate(async () => {
  try {
    const r = await fetch("http://127.0.0.1:8000/health");
    return { ok: r.ok, status: r.status };
  } catch (e) {
    return { ok: false, error: String(e).slice(0, 160) };
  }
});
console.log("API_HEALTH=" + JSON.stringify(api));

// 1) Handle: kelas + ukuran + posisi
const handles = await page.$$eval(".react-flow__handle", (els) =>
  els.map((e) => {
    const b = e.getBoundingClientRect();
    return {
      cls: e.getAttribute("class"),
      type: e.getAttribute("data-handletype"),
      pos: e.getAttribute("data-handlepos"),
      node: e.closest(".react-flow__node")?.getAttribute("data-id"),
      center: [Math.round(b.x + b.width / 2), Math.round(b.y + b.height / 2)],
      pe: getComputedStyle(e).pointerEvents,
    };
  })
);
console.log("HANDLES=" + JSON.stringify(handles, null, 1));

// 2) Connect: node trigger (source) -> node terakhir (target)
const edgesBefore = await page.locator(".react-flow__edge").count();
const out = await page.locator(".react-flow__node .react-flow__handle.k-handle--out").first().boundingBox();
const lastIn = await page.locator(".react-flow__node").last().locator(".react-flow__handle.k-handle--in").boundingBox();
console.log(`CONNECT OUT=${JSON.stringify(out)} LAST_IN=${JSON.stringify(lastIn)} edgesBefore=${edgesBefore}`);

if (out && lastIn) {
  await page.mouse.move(out.x + out.width / 2, out.y + out.height / 2);
  await page.mouse.down();
  await page.waitForTimeout(150);
  const during = await page.evaluate(() => ({
    hasConnectionLine: !!document.querySelector(".react-flow__connectionline, .react-flow__connection"),
    connectingfrom: document.querySelectorAll(".react-flow__handle.connectingfrom").length,
  }));
  console.log("DURING_CONNECT=" + JSON.stringify(during));
  await page.mouse.move(lastIn.x + lastIn.width / 2, lastIn.y + lastIn.height / 2, { steps: 20 });
  await page.waitForTimeout(200);
  const hover = await page.evaluate(() => document.querySelectorAll(".react-flow__handle.connectingto").length);
  await page.mouse.up();
  await page.waitForTimeout(900);
  const edgesAfter = await page.locator(".react-flow__edge").count();
  console.log(`CONNECT edges ${edgesBefore} -> ${edgesAfter}, hover_on_target=${hover}`);
}

// 3) Edge selection + delete
const eb = await page.locator(".react-flow__edge path").first().boundingBox();
console.log("EDGE_PATH_BOX=" + JSON.stringify(eb));
if (eb) {
  await page.mouse.click(eb.x + eb.width / 2, eb.y + eb.height / 2);
  await page.waitForTimeout(500);
  const sel = await page.evaluate(() => {
    const g = document.querySelector(".react-flow__edge");
    return {
      selected: document.querySelectorAll(".react-flow__edge.selected").length,
      hasInteractionPath: !!g?.querySelector("path.react-flow__edge-interaction"),
      strokeWidth: g ? getComputedStyle(g.querySelector("path")).strokeWidth : null,
    };
  });
  console.log("EDGE_SELECT=" + JSON.stringify(sel));
  await page.keyboard.press("Delete");
  await page.waitForTimeout(700);
  console.log("EDGE_AFTER_DELETE=" + (await page.locator(".react-flow__edge").count()));
}

// 4) Pan dengan mouse
const vb = await page.locator(".react-flow").boundingBox();
const t0 = await page.$eval(".react-flow__viewport", (el) => el.style.transform);
const pt = { x: Math.round(vb.x + 30), y: Math.round(vb.y + vb.height - 40) };
const at = await page.evaluate(({ x, y }) => {
  const el = document.elementFromPoint(x, y);
  return el ? { tag: el.tagName, cls: String(el.getAttribute("class")).slice(0, 70) } : null;
}, pt);
console.log(`PAN point=${JSON.stringify(pt)} elementFromPoint=${JSON.stringify(at)} t0=${t0}`);

await page.mouse.move(pt.x, pt.y);
await page.mouse.down();
for (let i = 1; i <= 20; i++) await page.mouse.move(pt.x + i * 8, pt.y - i * 5);
await page.mouse.up();
await page.waitForTimeout(700);
console.log("PAN t1=" + (await page.$eval(".react-flow__viewport", (el) => el.style.transform)));

// 3b) Occlusion check: apakah toolbar menutupi handle node?
const occ = await page.evaluate(({ x, y }) => {
  const el = document.elementFromPoint(x, y);
  return el ? { tag: el.tagName, testid: el.getAttribute("data-testid"), cls: String(el.getAttribute("class")).slice(0, 60) } : null;
}, { x: 863, y: 60 });
console.log("OCCLUSION_AT_TRIGGER_HANDLE=" + JSON.stringify(occ));

// 3c) Delete dengan Backspace (default React Flow v12) vs Delete
const eb2 = await page.locator(".react-flow__edge path").first().boundingBox();
await page.mouse.click(eb2.x + eb2.width / 2, eb2.y + eb2.height / 2);
await page.waitForTimeout(400);
console.log("SELECTED_BEFORE_BACKSPACE=" + (await page.locator(".react-flow__edge.selected").count()));
await page.keyboard.press("Backspace");
await page.waitForTimeout(700);
console.log("EDGE_AFTER_BACKSPACE=" + (await page.locator(".react-flow__edge").count()));

// 4b) Cari titik kosong nyata (bukan node, bukan panel) lalu pan
const empty = await page.evaluate(() => {
  const canvas = document.querySelector(".react-flow");
  const b = canvas.getBoundingClientRect();
  const candidates = [
    [b.x + 30, b.y + b.height - 200],
    [b.x + b.width - 30, b.y + b.height - 200],
    [b.x + b.width / 2, b.y + b.height - 30],
    [b.x + 30, b.y + 200],
  ];
  for (const [x, y] of candidates) {
    const el = document.elementFromPoint(x, y);
    const cls = String(el?.getAttribute("class") || "");
    if (cls.includes("react-flow__pane")) return { x: Math.round(x), y: Math.round(y), cls };
  }
  return null;
});
console.log("EMPTY_POINT=" + JSON.stringify(empty));
if (empty) {
  const t0b = await page.$eval(".react-flow__viewport", (el) => el.style.transform);
  await page.mouse.move(empty.x, empty.y);
  await page.mouse.down();
  for (let i = 1; i <= 20; i++) await page.mouse.move(empty.x + i * 8, empty.y - i * 5);
  await page.mouse.up();
  await page.waitForTimeout(700);
  const t1b = await page.$eval(".react-flow__viewport", (el) => el.style.transform);
  console.log(`PAN_ON_PANE t0=${t0b} t1=${t1b} changed=${t0b !== t1b}`);
}

console.log("ERRS=" + JSON.stringify(errs.slice(0, 8)));

// 5) DIAGNOSA HANDLE: apa yang benar-benar berada di titik tengah handle?
const diag = await page.evaluate(() => {
  const handle = document.querySelector(".react-flow__node .react-flow__handle.k-handle--out");
  const b = handle.getBoundingClientRect();
  const cx = Math.round(b.x + b.width / 2);
  const cy = Math.round(b.y + b.height / 2);
  const at = document.elementFromPoint(cx, cy);
  const chain = [];
  let el = handle;
  while (el && chain.length < 6) {
    chain.push({
      tag: el.tagName,
      cls: String(el.getAttribute("class") || "").slice(0, 50),
      pe: getComputedStyle(el).pointerEvents,
      z: getComputedStyle(el).zIndex,
      transform: getComputedStyle(el).transform.slice(0, 40),
    });
    el = el.parentElement;
  }
  return {
    handleRect: { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) },
    center: [cx, cy],
    topmost: at ? { tag: at.tagName, cls: String(at.getAttribute("class") || "").slice(0, 60) } : null,
    chain,
    nodeRect: (() => {
      const n = handle.closest(".react-flow__node");
      const r = n.getBoundingClientRect();
      return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
    })(),
  };
});
console.log("HANDLE_DIAG=" + JSON.stringify(diag, null, 1));

// 5b) Connect via hover() + mouse (Playwright menjamin titik tengah elemen)
try {
  const src = page.locator(".react-flow__node").nth(3).locator(".react-flow__handle.k-handle--out");
  const dst = page.locator(".react-flow__node").nth(2).locator(".react-flow__handle.k-handle--in");
  const before = await page.locator(".react-flow__edge").count();
  await src.hover();
  await page.mouse.down();
  await page.waitForTimeout(150);
  const started = await page.evaluate(() => document.querySelectorAll(".react-flow__handle.connectingfrom").length);
  await dst.hover();
  await page.waitForTimeout(150);
  const hovered = await page.evaluate(() => document.querySelectorAll(".react-flow__handle.connectingto").length);
  await page.mouse.up();
  await page.waitForTimeout(800);
  const after = await page.locator(".react-flow__edge").count();
  console.log(`CONNECT2 (hover) started=${started} hovered=${hovered} edges ${before} -> ${after}`);
} catch (e) {
  console.log("CONNECT2 gagal: " + String(e).slice(0, 200));
}

await browser.close();



