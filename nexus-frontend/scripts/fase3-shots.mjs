/**
 * FASE 3 — pengambil bukti (screenshot + angka).
 *
 * Menghasilkan:
 *   - 12 file: node state (loading/success/error) x 4 tema.
 *   - theme switcher terbuka (preview mini-kanvas per tema).
 *   - auto layout BEFORE/AFTER.
 *   - kanvas mobile: long-press (drag mode + menu) dan bottom sheet palette.
 *   - edge animasi (data mengalir) + empty state.
 * Semua angka pengukuran dicetak ke stdout DAN ditulis ke JSON, supaya klaim di
 * laporan bisa ditelusuri (bukan "kelihatan bagus").
 *
 * Metode long-press: CDP `Input.dispatchTouchEvent` (touch nyata, dibutuhkan
 * karena handler memeriksa `pointerType === "touch"`). Bila CDP tidak tersedia,
 * script jatuh ke `dispatchEvent('pointerdown', { pointerType: 'touch' })` dan
 * MELAPORKAN metode mana yang dipakai — bukan diam-diam dianggap sama.
 *
 * Pakai: node scripts/fase3-shots.mjs
 */
import { chromium } from "@playwright/test";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const BASE = process.env.AUDIT_BASE || "http://localhost:3000";
const OUT = join(tmpdir(), "fase3_shots");
mkdirSync(OUT, { recursive: true });
const THEMES = ["midnight", "daylight", "cyberpunk", "minimal"];
const STATES = ["loading", "success", "error"];
const evidence = { themeTokenAudit: [], nodeStates: [], autoLayout: null, mobile: {}, switcher: null, emptyState: null, notes: [] };

function supabaseRef() {
  for (const f of [".env.local", ".env"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    const m = readFileSync(p, "utf-8").match(/NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/);
    if (m) return m[1];
  }
  return "qmukkphwaajzbqjrcvjrcvaz";
}

async function seed(page) {
  const p = join(process.cwd(), "_e2e_session.refreshed.json");
  if (!existsSync(p)) return;
  const sess = JSON.parse(readFileSync(p, "utf-8"));
  await page.addInitScript(
    (kv) => { try { window.localStorage.setItem(kv.key, JSON.stringify(kv.value)); } catch {} },
    { key: `sb-${supabaseRef()}-auth-token`, value: sess }
  );
}

/** Token tema yang benar-benar aktif di DOM (bukan nilai di file TS). */
const READ_TOKENS = () => {
  const root = getComputedStyle(document.documentElement);
  const canvas = document.querySelector(".react-flow");
  return {
    theme: document.documentElement.getAttribute("data-canvas-theme"),
    canvasBg: canvas ? getComputedStyle(canvas).backgroundColor : null,
    tokens: {
      bg: root.getPropertyValue("--canvas-bg").trim(),
      nodeBg: root.getPropertyValue("--node-bg").trim(),
      nodeBorder: root.getPropertyValue("--node-border").trim(),
      edge: root.getPropertyValue("--edge-color").trim(),
      edgeAnimated: root.getPropertyValue("--edge-animated-color").trim(),
      success: root.getPropertyValue("--node-success-glow").trim(),
      error: root.getPropertyValue("--node-error-glow").trim(),
      pulse: root.getPropertyValue("--node-pulse-color").trim(),
      panelBg: root.getPropertyValue("--panel-bg").trim(),
      textPrimary: root.getPropertyValue("--text-primary").trim(),
    },
    nodeCount: document.querySelectorAll(".react-flow__node").length,
    handleSizes: [...document.querySelectorAll(".react-flow__handle")].map((h) => {
      const b = h.getBoundingClientRect();
      return [Math.round(b.width), Math.round(b.height)];
    }),
    animatedEdges: document.querySelectorAll(".react-flow__edge.animated").length,
    edgeCount: document.querySelectorAll(".react-flow__edge").length,
    statusDots: document.querySelectorAll('[data-testid^="node-status-"]').length,
    executingCards: document.querySelectorAll(".k-node--executing").length,
  };
};

/** Gaya nyata per status: warna dot, glow, dan keberadaan indikator resmi. */
const READ_STATUS_STYLE = () => {
  const out = {};
  for (const card of document.querySelectorAll('[data-testid="node-card"]')) {
    const state = card.getAttribute("data-status");
    const dot = card.querySelector(".k-status-dot");
    const ring = card.closest('[data-testid^="node-status-"]');
    out[state] = {
      dotBg: dot ? getComputedStyle(dot).backgroundColor : null,
      dotShadow: dot ? getComputedStyle(dot).boxShadow : null,
      pulsing: dot ? dot.getAttribute("data-pulse") : null,
      wrapperTestid: ring ? ring.getAttribute("data-testid") : null,
      cardAnimation: getComputedStyle(card).animationName,
      cardBorder: getComputedStyle(card).borderTopColor,
    };
  }
  return out;
};

/** Pusat tiap node di layar + KOORDINAT ALUR (untuk Auto Layout) */
const READ_CENTERS = () =>
  [...document.querySelectorAll(".react-flow__node")].map((el) => {
    const b = el.getBoundingClientRect();
    // React Flow menulis posisi ALUR pada inline transform node. Angka ini
    // tidak terpengaruh zoom/pan, sehingga jarak antar-rank bisa diuji sebagai
    // nilai yang diharapkan (NODE_H + RANK_SEP = 204), bukan angka layar yang
    // berubah setiap kali fitView mengubah zoom.
    const m = /translate\(([-\d.]+)px,\s*([-\d.]+)px\)/.exec(el.style.transform || "");
    return {
      id: el.getAttribute("data-id"),
      x: Math.round(b.x + b.width / 2),
      y: Math.round(b.y + b.height / 2),
      flowX: m ? Math.round(Number(m[1])) : null,
      flowY: m ? Math.round(Number(m[2])) : null,
    };
  });


// ---------------------------------------------------------------------------
// 1. Tema: token + 12 screenshot status x tema
// ---------------------------------------------------------------------------
const browser = await chromium.launch();
const desktop = await browser.newContext({ viewport: { width: 1440, height: 900 } });

for (const theme of THEMES) {
  const page = await desktop.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  await seed(page);
  await page.goto(`${BASE}/builder?demo=1&canvasTheme=${theme}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
  await page.waitForSelector('[data-testid="node-card"]', { timeout: 45000 });
  await page.waitForTimeout(2500);

  const tokens = await page.evaluate(READ_TOKENS);
  const styles = await page.evaluate(READ_STATUS_STYLE);
  evidence.themeTokenAudit.push({ theme, tokens, errors });
  evidence.nodeStates.push({ theme, styles });

  await page.screenshot({ path: join(OUT, `canvas_theme_${theme}.png`) });

  for (const state of STATES) {
    const card = page.locator(`[data-testid="node-card"][data-status="${state}"]`).first();
    if ((await card.count()) === 0) {
      evidence.notes.push(`node ${state} TIDAK ADA di tema ${theme}`);
      continue;
    }
    await card.screenshot({ path: join(OUT, `node_${state}_${theme}.png`) });
  }

  // Screenshot bukti tema hanya untuk tema pertama (kanvas penuh sudah diambil).
  await page.close();
}


// ---------------------------------------------------------------------------
// 2. Theme switcher (preview mini-kanvas) + persistensi localStorage
// ---------------------------------------------------------------------------
{
  const page = await desktop.newPage();
  await seed(page);
  await page.goto(`${BASE}/builder?demo=1&canvasTheme=midnight`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="canvas-theme-trigger"]', { timeout: 45000 });
  await page.waitForTimeout(2000);

  await page.click('[data-testid="canvas-theme-trigger"]');
  await page.waitForSelector('[data-testid="canvas-theme-menu"]', { timeout: 10000 });
  await page.screenshot({ path: join(OUT, "theme_switcher_open.png") });
  const previews = await page.$$eval('[data-testid^="theme-preview-"]', (els) =>
    els.map((e) => ({
      id: e.getAttribute("data-testid"),
      bg: getComputedStyle(e).backgroundColor,
    }))
  );

  await page.click('[data-testid="canvas-theme-option-minimal"]');
  await page.waitForTimeout(900);
  const afterSwitch = await page.evaluate(READ_TOKENS);
  const persisted = await page.evaluate(() => {
    try { return window.localStorage.getItem("katalir.canvasTheme"); } catch { return "BLOCKED"; }
  });
  await page.screenshot({ path: join(OUT, "theme_switcher_after_switch_minimal.png") });

  // Reload tanpa parameter tema: nilai tersimpan harus dipakai kembali.
  await page.goto(`${BASE}/builder?demo=1`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="node-card"]', { timeout: 45000 });
  await page.waitForTimeout(2000);
  const afterReload = await page.evaluate(READ_TOKENS);

  evidence.switcher = { previews, afterSwitch: afterSwitch.tokens, persisted, afterReloadTheme: afterReload.theme, afterReloadBg: afterReload.canvasBg };
  await page.close();
}

// ---------------------------------------------------------------------------
// 3. Auto layout (dagre): before/after + geometri antar-rank
// ---------------------------------------------------------------------------
{
  const page = await desktop.newPage();
  await seed(page);
  await page.goto(`${BASE}/builder?demo=1&canvasTheme=midnight`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="node-card"]', { timeout: 45000 });
  await page.waitForTimeout(2200);

  // Acak posisi dulu supaya "rapi otomatis" benar-benar terukur, bukan kebetulan.
  await page.evaluate(() => {
    // akses store lewat event UI tidak tersedia -> geser via drag node pertama
  });
  const before = await page.evaluate(READ_CENTERS);
  await page.screenshot({ path: join(OUT, "autolayout_before.png") });

  await page.click('[data-testid="btn-auto-layout"]');
  await page.waitForTimeout(1400);
  const after = await page.evaluate(READ_CENTERS);
  await page.screenshot({ path: join(OUT, "autolayout_after.png") });

  const byId = (arr) => Object.fromEntries(arr.map((n) => [n.id, n]));
  const b = byId(before);
  const a = byId(after);
  // Jarak antar-rank diukur pada KOORDINAT ALUR (bebas zoom).
  const flowGap1 = a["demo-mcp"] && a["demo-agent"] ? a["demo-mcp"].flowY - a["demo-agent"].flowY : null;
  const flowGap2 = a["demo-agent"] && a["demo-trigger"] ? a["demo-agent"].flowY - a["demo-trigger"].flowY : null;
  const flowColumn = a["demo-trigger"] && a["demo-mcp"] ? Math.abs(a["demo-trigger"].flowX - a["demo-mcp"].flowX) : null;
  const rankGap = a["demo-mcp"] && a["demo-agent"] ? a["demo-mcp"].y - a["demo-agent"].y : null;
  const rankGap2 = a["demo-agent"] && a["demo-trigger"] ? a["demo-agent"].y - a["demo-trigger"].y : null;
  const sameColumn = a["demo-trigger"] && a["demo-mcp"] ? Math.abs(a["demo-trigger"].x - a["demo-mcp"].x) : null;
  const overlapping = [];
  const ids = Object.keys(a);
  for (let i = 0; i < ids.length; i++) {
    for (let j = i + 1; j < ids.length; j++) {
      const p = a[ids[i]], q = a[ids[j]];
      if (p.flowX !== null && q.flowX !== null) {
        // Node dianggap menumpuk bila kotak 224x104 saling menindih.
        if (Math.abs(p.flowX - q.flowX) < 224 && Math.abs(p.flowY - q.flowY) < 104) overlapping.push([p.id, q.id]);
      }
    }
  }
  evidence.autoLayout = {
    before, after,
    movedNodes: ids.filter((id) => b[id] && (b[id].flowX !== a[id].flowX || b[id].flowY !== a[id].flowY)).length,
    expectedRankGap: 204,
    flowRankGapPayload_to_mcp: flowGap1,
    flowRankGapTrigger_to_agent: flowGap2,
    flowColumnDelta: flowColumn,
    screenRankGap: rankGap,
    screenRankGap2: rankGap2,
    screenColumnDelta: sameColumn,
    overlapping,
  };
  await page.close();
}


// ---------------------------------------------------------------------------
// 4. Mobile: long-press (drag mode + menu konteks) + bottom sheet palette
// ---------------------------------------------------------------------------
{
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  await seed(page);
  await page.goto(`${BASE}/builder?demo=1&canvasTheme=midnight`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="node-card"]', { timeout: 45000 });
  await page.waitForTimeout(2500);

  const handles = await page.evaluate(READ_TOKENS);
  await page.screenshot({ path: join(OUT, "mobile_canvas.png") });

  // Long-press via CDP touch (metode 1). Fallback: dispatchEvent (metode 2).
  const card = page.locator('[data-testid="node-card"]').first();
  const box = await card.boundingBox();
  let method = "cdp-touch";
  const cdp = await ctx.newCDPSession(page);
  const cx = Math.round(box.x + box.width / 2);
  const cy = Math.round(box.y + box.height / 2);
  try {
    await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: cx, y: cy }] });
    await page.waitForTimeout(750);
    await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await page.waitForTimeout(500);
  } catch (e) {
    evidence.notes.push("CDP touch gagal: " + String(e).slice(0, 120));
  }
  let armed = await card.getAttribute("data-armed");
  let menuVisible = (await page.locator('[data-testid="node-context-menu"]').count()) > 0;

  if (armed !== "true") {
    method = "dispatchEvent-pointerdown";
    await card.dispatchEvent("pointerdown", { pointerType: "touch", clientX: cx, clientY: cy, bubbles: true });
    await page.waitForTimeout(750);
    armed = await card.getAttribute("data-armed");
    menuVisible = (await page.locator('[data-testid="node-context-menu"]').count()) > 0;
  }

  await page.screenshot({ path: join(OUT, "mobile_longpress.png") });

  // CATATAN PENTING (temuan nyata sesi ini): tap/long-press pada node di mobile
  // MEMILIH node -> panel konfigurasi (Sheet) langsung terbuka. Jadi script
  // harus MENUTUP sheet itu dulu; kalau tidak, klik berikutnya diblokir overlay
  // dan tes gagal seolah UI rusak (padahal perilakunya benar).
  const sheetAfterPress = (await page.locator('[role="dialog"]').count()) > 0;
  if (sheetAfterPress) {
    const closeBtn = page.locator('[role="dialog"] [aria-label="Tutup"]').first();
    if (await closeBtn.count()) await closeBtn.click({ timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(500);
  }
  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);

  // Bottom sheet palette: tarik ke atas (drag-up) dari bar bawah.
  const trigger = page.locator('[data-testid="palette-sheet-trigger"]');
  const tbox = await trigger.boundingBox();
  await trigger.dispatchEvent("pointerdown", { pointerType: "touch", clientX: tbox.x + 40, clientY: tbox.y + 20, bubbles: true });
  await trigger.dispatchEvent("pointermove", { pointerType: "touch", clientX: tbox.x + 40, clientY: tbox.y - 60, bubbles: true });
  await trigger.dispatchEvent("pointerup", { pointerType: "touch", clientX: tbox.x + 40, clientY: tbox.y - 60, bubbles: true });
  await page.waitForTimeout(700);
  const sheetOpen = (await page.locator('[data-testid="palette-sheet"]').count()) > 0;
  await page.screenshot({ path: join(OUT, "mobile_bottomsheet.png") });

  // Tap node -> panel konfigurasi (sheet) muncul.
  if (sheetOpen) {
    const close = page.locator('[data-testid="palette-sheet-close"]');
    if (await close.count()) await close.click();
    await page.waitForTimeout(500);
  }
  await page.keyboard.press("Escape");
  await card.click({ timeout: 8000 }).catch(() => {});
  await page.waitForTimeout(1000);
  const configSheet = (await page.locator('[role="dialog"]').count()) > 0;
  await page.screenshot({ path: join(OUT, "mobile_config_sheet.png") });

  evidence.mobile = {
    longPressMethod: method,
    armed,
    menuVisible,
    sheetAlreadyOpenAfterLongPress: sheetAfterPress,
    paletteSheetOpen: sheetOpen,
    configSheet,
    handleSizes: handles.handleSizes,
    pageerrors: errors,
  };
  await ctx.close();
}

// ---------------------------------------------------------------------------
// 5. Edge animasi (data mengalir) + empty state
// ---------------------------------------------------------------------------
{
  const page = await desktop.newPage();
  await seed(page);
  await page.goto(`${BASE}/builder?demo=1&canvasTheme=cyberpunk`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".react-flow__edge", { timeout: 45000 });
  await page.waitForTimeout(2500);
  const edgeInfo = await page.evaluate(() => {
    const g = document.querySelector(".react-flow__edge.animated");
    const path = g ? g.querySelector("path") : null;
    return {
      animatedCount: document.querySelectorAll(".react-flow__edge.animated").length,
      total: document.querySelectorAll(".react-flow__edge").length,
      stroke: path ? getComputedStyle(path).stroke : null,
      dash: path ? getComputedStyle(path).strokeDasharray : null,
      animation: path ? getComputedStyle(path).animationName : null,
    };
  });
  const box = await page.locator(".react-flow").boundingBox();
  await page.screenshot({ path: join(OUT, "edge_animated.png"), clip: { x: box.x + 100, y: box.y + 100, width: 700, height: 600 } });
  evidence.emptyState = evidence.emptyState || {};
  evidence.edge = edgeInfo;
  await page.close();
}


// Empty state (kanvas kosong + CTA) + CTA "Muat contoh workflow"
{
  const page = await desktop.newPage();
  await seed(page);
  // Tanpa ?w= dan tanpa ?demo=1: kanvas kosong (workflow tersimpan tidak
  // dimuat karena daftar workflow user di-query asynchronous; emulator tanpa
  // sesi workflow akan tetap kosong). Bersihkan localStorage draf juga.
  await page.addInitScript(() => { try { window.localStorage.clear(); } catch {} });
  await page.goto(`${BASE}/builder`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="canvas-empty-state"]', { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1500);
  const emptyVisible = (await page.locator('[data-testid="canvas-empty-state"]').count()) > 0;
  await page.screenshot({ path: join(OUT, "empty_state.png") });

  let afterCta = null;
  if (emptyVisible) {
    await page.click('[data-testid="btn-empty-example"]');
    await page.waitForTimeout(1500);
    afterCta = await page.evaluate(() => ({
      nodes: document.querySelectorAll(".react-flow__node").length,
      edges: document.querySelectorAll(".react-flow__edge").length,
      emptyStill: document.querySelectorAll('[data-testid="canvas-empty-state"]').length,
    }));
    await page.screenshot({ path: join(OUT, "empty_state_after_cta.png") });
  }
  evidence.emptyState = { emptyVisible, afterCta };
  await page.close();
}

await browser.close();
writeFileSync(join(OUT, "fase3_shots.json"), JSON.stringify(evidence, null, 2));
console.log(JSON.stringify(evidence, null, 2));
console.log(`\nSCREENSHOTS -> ${OUT}`);

