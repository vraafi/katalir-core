/**
 * FASE 3 audit probe — "SEBELUM" (baseline) dan "SESUDAH" (bukti) kanvas Builder.
 *
 * Kenapa script berdiri sendiri (bukan spec di tests/):
 *  - playwright.config.ts membangun PRODUKSI (build >300s) di webServer; itu
 *    berguna untuk regresi penuh tapi terlalu berat untuk iterasi visual.
 *  - Probe ini menembak DEV server (localhost:3000) yang sudah hidup, jadi bisa
 *    dijalankan berulang sambil mengembangkan, dan hasilnya ANGKA (bukan opini).
 *
 * Keluaran: JSON metrik ke stdout + screenshot ke %TEMP%\fase3_shots\.
 * Pakai: node scripts/fase3-audit.mjs [before|after]
 */
import { chromium } from "@playwright/test";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const TAG = process.argv[2] || "before";
const BASE = process.env.AUDIT_BASE || "http://localhost:3000";
const OUT = join(tmpdir(), "fase3_shots");
mkdirSync(OUT, { recursive: true });

function supabaseRef() {
  for (const f of [".env.local", ".env"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    const m = readFileSync(p, "utf-8").match(/NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/);
    if (m) return m[1];
  }
  return "qmukkphwaajzbqjrcvaz";
}

const LS_KEY = `sb-${supabaseRef()}-auth-token`;

async function seed(page) {
  const p = join(process.cwd(), "_e2e_session.refreshed.json");
  if (!existsSync(p)) return false;
  const sess = JSON.parse(readFileSync(p, "utf-8"));
  await page.addInitScript(
    (kv) => {
      try { window.localStorage.setItem(kv.key, JSON.stringify(kv.value)); } catch {}
    },
    { key: LS_KEY, value: sess }
  );
  return true;
}

/** Ukuran + warna yang benar-benar dilihat user (computed style, bukan state). */
const MEASURE = () => {
  const canvas = document.querySelector(".react-flow");
  const cs = canvas ? getComputedStyle(canvas) : null;
  const nodes = [...document.querySelectorAll(".react-flow__node")];
  const handles = [...document.querySelectorAll(".react-flow__handle")].map((h) => {
    const b = h.getBoundingClientRect();
    return { w: Math.round(b.width), h: Math.round(b.height) };
  });
  const smallTargets = [...document.querySelectorAll("button, a, [role=button]")]
    .map((el) => {
      const b = el.getBoundingClientRect();
      return { w: Math.round(b.width), h: Math.round(b.height) };
    })
    .filter((t) => t.w > 0 && t.h > 0 && (t.w < 44 || t.h < 44)).length;

  const root = getComputedStyle(document.documentElement);
  return {
    canvasBg: cs ? cs.backgroundColor : null,
    themeAttr: document.documentElement.getAttribute("data-canvas-theme"),
    nodeCount: nodes.length,
    nodeBg: nodes.slice(0, 4).map((n) => {
      const card = n.querySelector(".k-node") || n.firstElementChild;
      return card ? getComputedStyle(card).backgroundColor : null;
    }),
    handles,
    handleCount: handles.length,
    minimap: !!document.querySelector(".react-flow__minimap"),
    minimapNodes: document.querySelectorAll(".react-flow__minimap-node").length,
    controls: !!document.querySelector(".react-flow__controls"),
    edges: document.querySelectorAll(".react-flow__edge").length,
    animatedEdges: document.querySelectorAll(".react-flow__edge.animated").length,
    executingNodes: document.querySelectorAll(".react-flow__node .k-node--executing").length,
    statusDots: document.querySelectorAll('[data-testid^="node-status-"]').length,
    buttons: [...document.querySelectorAll("button")]
      .map((b) => (b.getAttribute("aria-label") || b.textContent || b.title || "").trim().slice(0, 34))
      .filter(Boolean),
    cssVarAccent: root.getPropertyValue("--canvas-accent").trim(),
    cssVarBg: root.getPropertyValue("--canvas-bg").trim(),
    canvasThemeLS: (() => {
      try {
        const k = Object.keys(window.localStorage).find((x) => /canvas.?theme/i.test(x));
        return k ? `${k}=${window.localStorage.getItem(k)}` : null;
      } catch { return null; }
    })(),
    smallTargets,
  };
};


async function viewportAudit(browser, name, viewport, opts = {}) {
  const ctx = await browser.newContext({ viewport, hasTouch: !!opts.touch, isMobile: !!opts.mobile });
  const page = await ctx.newPage();
  const errors = [];
  const consoleErrors = [];
  const hosts = new Set();
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text().slice(0, 200)); });
  page.on("request", (r) => { try { hosts.add(new URL(r.url()).host); } catch {} });

  const seeded = await seed(page);
  await page.goto(`${BASE}/builder${opts.query || ""}`, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 }).catch(() => {});
  await page.waitForSelector(".react-flow", { timeout: 45000 }).catch(() => {});
  await page.waitForTimeout(opts.settle ?? 4000);

  const metrics = await page.evaluate(MEASURE);
  await page.screenshot({ path: join(OUT, `${TAG}_${name}.png`) });

  // Bukti klik node -> panel konfigurasi (interaksi C2/C12)
  let nodeClickPanel = null;
  const firstNode = page.locator(".react-flow__node").first();
  if (await firstNode.count()) {
    await firstNode.click({ timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(900);
    nodeClickPanel = await page.evaluate(() => ({
      configVisible: /Konfigurasi Node|Node Config/i.test(document.body.innerText),
      urlNodeParam: new URLSearchParams(location.search).get("n"),
    }));
    await page.screenshot({ path: join(OUT, `${TAG}_${name}_nodeclick.png`) });
  }

  await ctx.close();
  return {
    name, viewport, seeded, errors, consoleErrors,
    apiHosts: [...hosts].filter((h) => /127\.0\.0\.1|localhost|railway|supabase/.test(h)).sort(),
    metrics, nodeClickPanel,
  };
}

const browser = await chromium.launch();
const results = [];
results.push(await viewportAudit(browser, "desktop", { width: 1440, height: 900 }));
results.push(await viewportAudit(browser, "mobile", { width: 390, height: 844 }, { touch: true, mobile: true }));
for (const theme of ["midnight", "daylight", "cyberpunk", "minimal"]) {
  results.push(await viewportAudit(browser, `theme_${theme}`, { width: 1440, height: 900 }, { query: `?demo=1&canvasTheme=${theme}` }));
}
await browser.close();

writeFileSync(join(OUT, `${TAG}_audit.json`), JSON.stringify(results, null, 2));
console.log(JSON.stringify(results, null, 2));
console.log(`\nSCREENSHOTS -> ${OUT}`);

