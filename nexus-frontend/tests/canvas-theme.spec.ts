/**
 * FASE 3 — sistem visual: 4 tema, status node, auto layout, edge animasi,
 * empty state. Semua assertion memakai angka (computed style / koordinat alur).
 *
 * Jalankan: npx playwright test -c playwright.dev.config.ts
 */
import { test, expect, type Page } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

/** Token yang diharapkan — SUMBER SAMA dengan src/features/builder/themes/canvas-themes.ts.
 *  Divalidasi silang terhadap DOM supaya dua sumber (TS + CSS) tidak bisa menyimpang. */
const EXPECTED = {
  midnight: { bg: "rgb(27, 31, 35)", nodeBg: "rgb(40, 46, 54)", edge: "rgb(92, 157, 245)", edgeAnimated: "rgb(139, 92, 246)", accent: "#6366f1", success: "rgb(38, 189, 115)", error: "rgb(245, 92, 92)" },
  daylight: { bg: "rgb(250, 250, 248)", nodeBg: "rgb(255, 255, 255)", edge: "rgb(99, 102, 241)", edgeAnimated: "rgb(139, 92, 246)", accent: "#6366f1", success: "rgb(22, 163, 74)", error: "rgb(220, 38, 38)" },
  cyberpunk: { bg: "rgb(10, 10, 15)", nodeBg: "rgb(26, 26, 46)", edge: "rgb(0, 255, 213)", edgeAnimated: "rgb(255, 46, 99)", accent: "#00ffd5", success: "rgb(0, 255, 213)", error: "rgb(255, 46, 99)" },
  minimal: { bg: "rgb(255, 255, 255)", nodeBg: "rgb(245, 245, 245)", edge: "rgb(161, 161, 170)", edgeAnimated: "rgb(24, 24, 27)", accent: "#18181b", success: "rgb(24, 24, 27)", error: "rgb(24, 24, 27)" },
} as const;

const THEMES = ["midnight", "daylight", "cyberpunk", "minimal"] as const;

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

/** Tunggu hidrasi React selesai (marker `data-hydrated` di <html>). */
async function waitHydrated(page: Page) {
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
}

async function openDemo(page: Page, theme: string) {
  await seedSession(page);
  await page.goto(`/builder?demo=1&canvasTheme=${theme}`, { waitUntil: "domcontentloaded" });
  await waitHydrated(page);
  await page.waitForSelector('[data-testid="node-card"]', { timeout: 45000 });
  await page.waitForTimeout(1800);
}

// ===========================================================================
// 4 tema: token DOM harus sama dengan nilai TS yang diharapkan
// ===========================================================================
for (const theme of THEMES) {
  test(`tema ${theme}: data-canvas-theme + token DOM sesuai definisi`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));
    await openDemo(page, theme);

    const t = await page.evaluate(() => {
      const root = getComputedStyle(document.documentElement);
      const canvas = document.querySelector(".react-flow");
      // DUA jenis edge: yang DIAM memakai --edge-color, yang MENGALIR memakai
      // --edge-animated-color. Contoh (`?demo=1`) punya satu edge mengalir,
      // sehingga memakai selector `path` pertama saja akan selalu membaca warna
      // edge animasi — itulah yang membuat tes tema merah di run sebelumnya.
      const still = document.querySelector(".react-flow__edge:not(.animated) .k-edge");
      const flowing = document.querySelector(".react-flow__edge.animated .k-edge");
      const card = document.querySelector('[data-testid="node-card"]');
      return {
        attr: document.documentElement.getAttribute("data-canvas-theme"),
        canvasBg: canvas ? getComputedStyle(canvas).backgroundColor : null,
        nodeBg: card ? getComputedStyle(card).backgroundColor : null,
        stillStroke: still ? getComputedStyle(still).stroke : null,
        flowingStroke: flowing ? getComputedStyle(flowing).stroke : null,
        accent: root.getPropertyValue("--canvas-accent").trim(),
        nodeCount: document.querySelectorAll(".react-flow__node").length,
      };
    });

    expect(t.attr).toBe(theme);
    expect(t.canvasBg).toBe(EXPECTED[theme].bg);
    expect(t.nodeBg).toBe(EXPECTED[theme].nodeBg);
    expect(t.stillStroke).toBe(EXPECTED[theme].edge);
    expect(t.flowingStroke).toBe(EXPECTED[theme].edgeAnimated);
    expect(t.accent).toBe(EXPECTED[theme].accent);
    // 4 node contoh tetap render di setiap tema (bukan hanya tema default).
    expect(t.nodeCount).toBe(4);
    console.log(`THEME ${theme} canvasBg=${t.canvasBg} nodeBg=${t.nodeBg} edge=${t.stillStroke} edgeFlowing=${t.flowingStroke}`);
    expect(errors, `pageerror di tema ${theme}`).toHaveLength(0);
  });
}

test("theme switcher: pilih tema -> token berubah + persist localStorage + bertahan setelah reload", async ({ page }) => {
  await openDemo(page, "midnight");
  expect(await page.evaluate(() => getComputedStyle(document.querySelector(".react-flow")!).backgroundColor)).toBe(EXPECTED.midnight.bg);

  await page.click('[data-testid="canvas-theme-trigger"]');
  await page.waitForSelector('[data-testid="canvas-theme-menu"]');
  // Preview mini-kanvas: 4 item, latar masing-masing sesuai tema.
  const previews = await page.$$eval('[data-testid^="theme-preview-"]', (els) =>
    els.map((e) => ({ id: e.getAttribute("data-testid"), bg: getComputedStyle(e).backgroundColor }))
  );
  expect(previews).toHaveLength(4);
  for (const theme of THEMES) {
    const p = previews.find((x) => x.id === `theme-preview-${theme}`);
    expect(p, `preview ${theme} tidak ada`).toBeTruthy();
    expect(p!.bg).toBe(EXPECTED[theme].bg);
  }

  await page.click('[data-testid="canvas-theme-option-cyberpunk"]');
  await page.waitForTimeout(800);
  expect(await page.evaluate(() => document.documentElement.getAttribute("data-canvas-theme"))).toBe("cyberpunk");
  expect(await page.evaluate(() => getComputedStyle(document.querySelector(".react-flow")!).backgroundColor)).toBe(EXPECTED.cyberpunk.bg);
  expect(await page.evaluate(() => window.localStorage.getItem("katalir.canvasTheme"))).toBe("cyberpunk");

  // Tanpa parameter tema di URL, nilai tersimpan harus dipakai.
  await page.goto("/builder?demo=1", { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="node-card"]', { timeout: 45000 });
  await page.waitForTimeout(1500);
  expect(await page.evaluate(() => document.documentElement.getAttribute("data-canvas-theme"))).toBe("cyberpunk");
  expect(await page.evaluate(() => getComputedStyle(document.querySelector(".react-flow")!).backgroundColor)).toBe(EXPECTED.cyberpunk.bg);
});


// ===========================================================================
// Status node: 4 state, warna + glow + animasi executing
// ===========================================================================
test("status node: initial/loading/success/error punya dot+glow dan indikator resmi React Flow", async ({ page }) => {
  await openDemo(page, "midnight");
  const states = await page.$$eval('[data-testid="node-card"]', (cards) =>
    cards.map((card) => {
      const dot = card.querySelector(".k-status-dot");
      const wrapper = card.closest('[data-testid^="node-status-"]');
      return {
        status: card.getAttribute("data-status"),
        dotBg: dot ? getComputedStyle(dot).backgroundColor : null,
        dotShadow: dot ? getComputedStyle(dot).boxShadow : null,
        pulse: dot ? dot.getAttribute("data-pulse") : null,
        wrapper: wrapper ? wrapper.getAttribute("data-testid") : null,
        animation: getComputedStyle(card).animationName,
      };
    })
  );
  const by = Object.fromEntries(states.map((s) => [s.status, s]));
  console.log("STATUS=" + JSON.stringify(states));

  // initial: abu, TANPA glow
  expect(by.initial.dotBg).toBe("rgb(139, 144, 154)");
  expect(by.initial.dotShadow).toBe("none");
  expect(by.initial.animation).toBe("none");

  // loading: amber + pulse ring + glow-border executing + indikator `border`
  expect(by.loading.dotBg).toBe("rgb(245, 158, 11)");
  expect(by.loading.pulse).toBe("true");
  expect(by.loading.animation).toBe("node-executing-glow");
  expect(by.loading.wrapper).toBe("node-status-loading");

  // success: glow 8px memakai token success tema midnight (#26BD73)
  expect(by.success.dotBg).toBe(EXPECTED.midnight.success);
  expect(by.success.dotShadow).toContain("rgb(38, 189, 115)");
  expect(by.success.dotShadow).toContain("8px");
  expect(by.success.wrapper).toBe("node-status-success");

  // error: glow 8px memakai token error tema midnight (#F55C5C)
  expect(by.error.dotBg).toBe(EXPECTED.midnight.error);
  expect(by.error.dotShadow).toContain("rgb(245, 92, 92)");
  expect(by.error.wrapper).toBe("node-status-error");
});

test("status tidak direset ke `initial` ketika tidak ada eksekusi (guard demo)", async ({ page }) => {
  await openDemo(page, "midnight");
  await page.waitForTimeout(3000); // beri waktu efek pemetaan status berjalan
  const statuses = await page.$$eval('[data-testid="node-card"]', (c) => c.map((e) => e.getAttribute("data-status")).sort());
  expect(statuses).toEqual(["error", "initial", "loading", "success"]);
});


// ===========================================================================
// Auto Layout (dagre): invariant geometri, bukan "kelihatan rapi"
// ===========================================================================
test("auto layout dagre: kolom sejajar, jarak antar-rank ~204, tidak ada node menumpuk", async ({ page }) => {
  await openDemo(page, "midnight");
  const flow = () =>
    page.$$eval(".react-flow__node", (els) =>
      els.map((el) => {
        const m = /translate\(([-\d.]+)px,\s*([-\d.]+)px\)/.exec((el as HTMLElement).style.transform || "");
        return { id: el.getAttribute("data-id") ?? "", x: m ? Math.round(Number(m[1])) : null, y: m ? Math.round(Number(m[2])) : null };
      })
    );
  const before = await flow();
  await page.click('[data-testid="btn-auto-layout"]');
  await page.waitForTimeout(1200);
  const after = await flow();
  console.log("AUTOLAYOUT before=" + JSON.stringify(before) + " after=" + JSON.stringify(after));

  const a = Object.fromEntries(after.map((n) => [n.id, n]));
  const b = Object.fromEntries(before.map((n) => [n.id, n]));

  // (1) ada perubahan nyata pada minimal 3 node
  const moved = Object.keys(a).filter((id) => b[id] && (b[id].x !== a[id].x || b[id].y !== a[id].y)).length;
  expect(moved, "auto layout tidak memindahkan node").toBeGreaterThanOrEqual(3);

  // (2) rantai trigger -> agent sejajar pada kolom yang sama (delta 0)
  const colDelta = Math.abs(a["demo-trigger"].x! - a["demo-agent"].x!);
  expect(colDelta, `kolom trigger/agent tidak sejajar (delta ${colDelta})`).toBeLessThanOrEqual(2);

  // (3) dagre menaruh parent di TENGAH anak-anaknya (invariant layout berjenjang)
  const midChildren = Math.round((a["demo-mcp"].x! + a["demo-agent-2"].x!) / 2);
  const centerDelta = Math.abs(midChildren - a["demo-agent"].x!);
  expect(centerDelta, `parent tidak terpusat (delta ${centerDelta})`).toBeLessThanOrEqual(2);

  // (4) jarak antar-rank = NODE_H + RANK_SEP = 104 + 100 = 204 (toleransi 24:
  //     dagre menambah ruang saat ada percabangan)
  const gap1 = a["demo-agent"].y! - a["demo-trigger"].y!;
  const gap2 = a["demo-mcp"].y! - a["demo-agent"].y!;
  console.log(`AUTOLAYOUT gaps trigger->agent=${gap1} agent->mcp=${gap2} (nominal 204)`);
  expect(Math.abs(gap1 - 204), `gap rank 1 = ${gap1}`).toBeLessThanOrEqual(24);
  expect(Math.abs(gap2 - 204), `gap rank 2 = ${gap2}`).toBeLessThanOrEqual(24);

  // (5) tidak ada dua node yang saling menindih (kotak 224x104)
  const ids = Object.keys(a);
  const overlaps: string[][] = [];
  for (let i = 0; i < ids.length; i++) {
    for (let j = i + 1; j < ids.length; j++) {
      const p = a[ids[i]], q = a[ids[j]];
      if (Math.abs(p.x! - q.x!) < 224 && Math.abs(p.y! - q.y!) < 104) overlaps.push([p.id, q.id]);
    }
  }
  expect(overlaps, `node menumpuk: ${JSON.stringify(overlaps)}`).toHaveLength(0);
});


// ===========================================================================
// Edge: 3 edge bertipe `flow`, 1 di antaranya mengalir (animated)
// ===========================================================================
test("edge animasi: tepat 1 edge mengalir dengan dash + animasi edge-flow", async ({ page }) => {
  await openDemo(page, "cyberpunk");
  const info = await page.evaluate(() => {
    const animated = document.querySelector(".react-flow__edge.animated path");
    const plain = document.querySelector(".react-flow__edge:not(.animated) path");
    const cs = (el: Element | null) => (el ? getComputedStyle(el) : null);
    return {
      total: document.querySelectorAll(".react-flow__edge").length,
      animated: document.querySelectorAll(".react-flow__edge.animated").length,
      animatedDash: animated ? cs(animated)!.strokeDasharray : null,
      animatedStroke: animated ? cs(animated)!.stroke : null,
      animatedName: animated ? cs(animated)!.animationName : null,
      plainStroke: plain ? cs(plain)!.stroke : null,
      plainName: plain ? cs(plain)!.animationName : null,
    };
  });
  console.log("EDGE=" + JSON.stringify(info));
  expect(info.total).toBe(3);
  expect(info.animated).toBe(1);
  // mengalir: dash + animasi + warna token animated tema cyberpunk (#FF2E63)
  expect(info.animatedDash).toBe("8px, 4px");
  expect(info.animatedName).toBe("edge-flow");
  expect(info.animatedStroke).toBe(EXPECTED.cyberpunk.error);
  // diam: tanpa animasi, warna token edge
  expect(info.plainName).toBe("none");
  expect(info.plainStroke).toBe(EXPECTED.cyberpunk.edge);
});

// ===========================================================================
// Empty state: ilustrasi + CTA
// ===========================================================================
test("empty state: tampil saat kanvas kosong, CTA Tambah Node & contoh workflow bekerja", async ({ page }) => {
  await seedSession(page);
  await page.addInitScript(() => { try { window.localStorage.clear(); } catch { /* abaikan */ } });
  await page.goto("/builder", { waitUntil: "domcontentloaded" });
  await waitHydrated(page);
  await page.waitForSelector('[data-testid="canvas-empty-state"]', { timeout: 30000 });
  expect(await page.locator('[data-testid="node-card"]').count()).toBe(0);
  // Ilustrasi (satu SVG khusus) + dua CTA besar. Dipilih via data-testid, bukan
  // "semua svg": ikon Lucide di dalam tombol CTA juga SVG sehingga hitungan
  // mentahnya 3, bukan 1.
  expect(await page.locator('[data-testid="empty-illustration"]').count()).toBe(1);
  await expect(page.locator('[data-testid="btn-empty-add-node"]')).toBeVisible();
  await expect(page.locator('[data-testid="btn-empty-example"]')).toBeVisible();

  // CTA "Tambah Node": +1 node di titik tengah kanvas, empty state hilang.
  // Ditunggu dengan polling (bukan jeda tetap): aksi ini mengubah state React,
  // dan jeda tetap membuat tes gagal-acak bila render sedikit tertunda.
  const center = await page.locator('[data-testid="btn-empty-add-node"]').boundingBox();
  console.log(
    "EMPTY pre-click topAtBtn=" +
      (await page.evaluate(({ x, y }) => {
        const el = document.elementFromPoint(x, y);
        return el ? `${el.tagName}[${el.getAttribute("data-testid") || String(el.className).slice(0, 30)}]` : null;
      }, { x: Math.round(center!.x + center!.width / 2), y: Math.round(center!.y + center!.height / 2) }))
  );
  const errs: string[] = [];
  page.on("pageerror", (e) => errs.push(String(e).slice(0, 160)));
  await page.click('[data-testid="btn-empty-add-node"]');
  const seen: number[] = [];
  for (let i = 0; i < 8; i++) {
    await page.waitForTimeout(500);
    seen.push(await page.locator('[data-testid="node-card"]').count());
    if (seen[seen.length - 1] === 1) break;
  }
  console.log(`EMPTY counts over time=${JSON.stringify(seen)} errs=${JSON.stringify(errs.slice(0, 2))}`);
  expect(seen[seen.length - 1], "CTA Tambah Node tidak menambah node").toBe(1);
  const ids = await page.$$eval(".react-flow__node", (els) => els.map((e) => e.getAttribute("data-id")));
  console.log("EMPTY add-node ids=" + JSON.stringify(ids));
  expect(
    await page.locator('[data-testid="canvas-empty-state"]').count(),
    "empty state harus hilang setelah ada node"
  ).toBe(0);

  // Undo -> kanvas kosong lagi -> CTA "Muat contoh workflow" memuat 4 node + 3 edge
  await page.click('[data-testid="btn-undo"]');
  await page.waitForTimeout(800);
  expect(await page.locator('[data-testid="canvas-empty-state"]').count()).toBe(1);
  await page.click('[data-testid="btn-empty-example"]');
  await page.waitForTimeout(1200);
  expect(await page.locator('[data-testid="node-card"]').count()).toBe(4);
  expect(await page.locator(".react-flow__edge").count()).toBe(3);
  expect(await page.locator('[data-testid="canvas-empty-state"]').count()).toBe(0);
});

