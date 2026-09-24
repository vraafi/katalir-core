/**
 * FASE 3 — 14 interaksi kanvas + sistem tema (DEV harness).
 *
 * Setiap tes WAJIB punya assertion kuantitatif (angka/koordinat/computed style).
 * Tidak ada "kelihatan bagus": koordinat diukur dari `getBoundingClientRect`,
 * transform viewport, dan `getComputedStyle`.
 *
 * Jalankan: npx playwright test -c playwright.dev.config.ts
 * (dev server 3000 + backend 8000 harus hidup; lihat playwright.dev.config.ts
 *  untuk alasan memakai harness dev, bukan build produksi.)
 */
import { test, expect, type Page } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const CANVAS = ".react-flow";

function supabaseRef(): string {
  const fromEnv = (process.env.NEXT_PUBLIC_SUPABASE_URL || "").trim();
  const m0 = fromEnv.match(/https?:\/\/([a-z0-9]+)\.supabase/);
  if (m0) return m0[1];
  for (const f of [".env.local", ".env"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    const m = readFileSync(p, "utf-8").match(/NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/);
    if (m) return m[1];
  }
  return "qmukkphwaajzbqjrcvaz";
}

const LS_KEY = `sb-${supabaseRef()}-auth-token`;

/** Sesi uji disemai untuk ORIGIN yang sama dengan baseURL harness ini. */
async function seedSession(page: Page) {
  const p = join(process.cwd(), "_e2e_session.refreshed.json");
  if (!existsSync(p)) return;
  const sess = JSON.parse(readFileSync(p, "utf-8"));
  await page.addInitScript(
    (kv: { key: string; value: unknown }) => {
      try { window.localStorage.setItem(kv.key, JSON.stringify(kv.value)); } catch { /* abaikan */ }
    },
    { key: LS_KEY, value: sess }
  );
}

/** Tunggu hidrasi React selesai (marker `data-hydrated` di <html>). */
async function waitHydrated(page: Page) {
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
}

/** Buka kanvas berisi contoh (4 node, 3 edge, 4 state status). */
async function openDemo(page: Page, query = "?demo=1") {
  await seedSession(page);
  await page.goto(`/builder${query}`, { waitUntil: "domcontentloaded" });
  await waitHydrated(page);
  await page.waitForSelector('[data-testid="node-card"]', { timeout: 45000 });
  await page.waitForTimeout(1800);
}

/** Posisi node di layar + koordinat alur (dari inline transform React Flow). */
async function nodeGeometry(page: Page) {
  return page.$$eval(".react-flow__node", (els) =>
    els.map((el) => {
      const b = el.getBoundingClientRect();
      const m = /translate\(([-\d.]+)px,\s*([-\d.]+)px\)/.exec((el as HTMLElement).style.transform || "");
      return {
        id: el.getAttribute("data-id") ?? "",
        screenX: Math.round(b.x + b.width / 2),
        screenY: Math.round(b.y + b.height / 2),
        flowX: m ? Math.round(Number(m[1])) : null,
        flowY: m ? Math.round(Number(m[2])) : null,
      };
    })
  );
}

async function viewportTransform(page: Page) {
  return page.$eval(".react-flow__viewport", (el) => (el as HTMLElement).style.transform);
}

/**
 * Cari titik kanvas yang BENAR-BENAR kosong (elementFromPoint = `.react-flow__pane`).
 *
 * Kenapa tidak memakai offset tetap: kanvas punya beberapa overlay
 * (`pointer-events-auto`) — toolbar kanvas di kanan-atas, Controls di kiri-bawah,
 * MiniMap di kanan-bawah. Offset tetap seperti (30,30) mendarat di toolbar dan
 * kliknya diblokir (gejala: tes timeout 90s seolah aplikasi rusak).
 */
async function findEmptyPanePoint(page: Page, prefer: "bottomRight" | "centerBottom" = "bottomRight") {
  const point = await page.evaluate((where) => {
    const canvas = document.querySelector(".react-flow");
    if (!canvas) return null;
    const b = canvas.getBoundingClientRect();
    const candidates =
      where === "bottomRight"
        ? [
            [b.x + b.width - 40, b.y + b.height - 220],
            [b.x + b.width / 2, b.y + b.height - 30],
            [b.x + b.width - 40, b.y + 200],
          ]
        : [
            [b.x + b.width / 2, b.y + b.height - 30],
            [b.x + b.width - 40, b.y + b.height - 220],
            [b.x + 30, b.y + b.height - 220],
          ];
    for (const [x, y] of candidates) {
      const el = document.elementFromPoint(x, y);
      if (String(el?.getAttribute("class") || "").includes("react-flow__pane")) {
        return { x: Math.round(x), y: Math.round(y) };
      }
    }
    return null;
  }, prefer);
  if (!point) throw new Error("tidak menemukan titik pane yang kosong");
  return point;
}

/** Drop node dengan DragEvent nyata pada titik klien tertentu. */
async function dropAt(page: Page, x: number, y: number, kind: string) {
  await page.evaluate(
    ({ x, y, kind }) => {
      const rf = document.querySelector(".react-flow");
      if (!rf) throw new Error("canvas tidak ditemukan");
      const dt = new DataTransfer();
      dt.setData("application/reactflow", kind);
      const mk = (type: string) =>
        new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: y });
      rf.dispatchEvent(mk("dragover"));
      rf.dispatchEvent(mk("drop"));
    },
    { x, y, kind }
  );
  await page.waitForTimeout(600);
}

// ===========================================================================
// C1  Drag palette -> titik drop
// ===========================================================================
test("C1 drag palette -> node mendarat di titik drop (toleransi 15px)", async ({ page }) => {
  await openDemo(page);
  const before = (await nodeGeometry(page)).length;
  const box = (await page.locator(CANVAS).first().boundingBox())!;
  const tx = Math.round(box.x + box.width * 0.4);
  const ty = Math.round(box.y + box.height * 0.75);
  await dropAt(page, tx, ty, "agent");
  const after = await nodeGeometry(page);
  expect(after.length, "drop tidak menambah node").toBe(before + 1);
  const last = after[after.length - 1];
  expect(Math.abs(last.screenX - tx), `dx node=${Math.abs(last.screenX - tx)}`).toBeLessThanOrEqual(15);
  expect(Math.abs(last.screenY - ty), `dy node=${Math.abs(last.screenY - ty)}`).toBeLessThanOrEqual(15);
});

// ===========================================================================
// C2  Click-to-place (palette diklik -> node baru muncul di kanvas)
// ===========================================================================
test("C2 klik item palette -> node baru bertambah tepat 1", async ({ page }) => {
  await openDemo(page);
  const before = (await nodeGeometry(page)).length;
  await page.click('[data-testid="palette-item-mcp"]');
  await page.waitForTimeout(700);
  const after = await nodeGeometry(page);
  expect(after.length).toBe(before + 1);
  // Node baru harus punya kartu, bukan node default React Flow tanpa isi.
  const lastCard = page.locator('[data-testid="node-card"]').last();
  await expect(lastCard).toBeVisible();
  expect(await lastCard.getAttribute("data-kind")).toBe("mcp");
});

// ===========================================================================
// C3  Drag node existing (desktop: draggable=true)
// ===========================================================================
test("C3 drag node menggeser posisi mengikuti pointer", async ({ page }) => {
  await openDemo(page);
  const card = page.locator('[data-testid="node-card"]').first();
  const box = (await card.boundingBox())!;

  // Diukur dalam KOORDINAT LAYAR (getBoundingClientRect), bukan koordinat alur:
  // perubahan zoom (fitView Auto Layout) mengalikan koordinat alur, sehingga
  // delta alur ≠ delta mouse. Yang diuji di sini adalah janji ke pengguna:
  // node MENGIKUTI jari/mouse.
  //
  // DUA FASE: React Flow baru menganggap drag dimulai setelah ambang gerak
  // terlampaui (`nodeDragThreshold`), jadi gerakan awal "termakan" ambang.
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(cx + 20, cy + 12, { steps: 4 });
  await page.waitForTimeout(150);
  const start = (await card.boundingBox())!;

  await page.mouse.move(cx + 140, cy + 110, { steps: 16 });
  await page.waitForTimeout(150);
  await page.mouse.up();
  await page.waitForTimeout(400);
  const end = (await card.boundingBox())!;

  const dx = Math.round(end.x - start.x);
  const dy = Math.round(end.y - start.y);
  console.log(`C3 delta layar=(${dx},${dy}) target≈(120,98)`);
  expect(dx, "node tidak bergeser ke kanan").toBeGreaterThan(40);
  expect(dy, "node tidak bergeser ke bawah").toBeGreaterThan(40);
  // Harus MENGIKUTI pointer (toleransi 30px), bukan sekadar "berubah".
  expect(Math.abs(dx - 120), `dx=${dx} tidak mengikuti pointer`).toBeLessThanOrEqual(30);
  expect(Math.abs(dy - 98), `dy=${dy} tidak mengikuti pointer`).toBeLessThanOrEqual(30);
});

// ===========================================================================
// C4  Delete node (toolbar node) + edge yang menempel ikut hilang
// ===========================================================================
test("C4 hapus node: node -1 dan edge yang menempel ikut hilang", async ({ page }) => {
  await openDemo(page);
  const nodesBefore = (await nodeGeometry(page)).length;
  const edgesBefore = await page.locator(".react-flow__edge").count();

  await page.locator('[data-testid="node-card"]').first().click();
  await page.waitForTimeout(400);
  await page.click('[aria-label="Hapus node"]');
  await page.waitForTimeout(700);

  const nodesAfter = (await nodeGeometry(page)).length;
  const edgesAfter = await page.locator(".react-flow__edge").count();
  expect(nodesAfter).toBe(nodesBefore - 1);
  expect(edgesAfter, "edge ke node terhapus harus ikut dibuang").toBe(edgesBefore - 1);
});


// ===========================================================================
// C5  Connect handle (drag dari handle kanan ke handle kiri node lain)
// ===========================================================================
test("C5 sambung handle -> edge bertambah 1 dan bertipe flow", async ({ page }) => {
  await openDemo(page);
  const edgesBefore = await page.locator(".react-flow__edge").count();

  // Pasangan yang BELUM tersambung: demo-agent-2 -> demo-mcp.
  // Selector memakai `data-id` (BUKAN `nth()`): React Flow menyusun ulang node
  // di DOM (urutan ikut z-index/interaksi), sehingga indeks bisa menunjuk node
  // lain — penyebab C5 gagal padahal probe dengan selector data-id berhasil
  // (edges 3 -> 4).
  const src = page.locator('.react-flow__node[data-id="demo-agent-2"] .k-handle--out');
  const dst = page.locator('.react-flow__node[data-id="demo-mcp"] .k-handle--in');

  const srcBox = (await src.boundingBox())!;
  const dstBox = (await dst.boundingBox())!;
  const topAt = (x: number, y: number) =>
    page.evaluate(({ x, y }) => {
      const el = document.elementFromPoint(x, y);
      return el ? `${el.tagName}.${String(el.getAttribute("class") || "").split(" ").slice(0, 2).join(".")}` : null;
    }, { x: Math.round(x), y: Math.round(y) });
  console.log(`C5 srcBox=${JSON.stringify(srcBox)} topAtSrc=${await topAt(srcBox.x + 6, srcBox.y + 6)} topAtDst=${await topAt(dstBox.x + 6, dstBox.y + 6)}`);

  // Urutan ini MENIRU probe yang terbukti berhasil (hover() Playwright kadang
  // menggeser mouse lewat jalur berbeda): move ke titik tengah -> down ->
  // gerakkan bertahap ke target -> up.
  await page.mouse.move(srcBox.x + srcBox.width / 2, srcBox.y + srcBox.height / 2);
  await page.mouse.down();
  await page.waitForTimeout(250);
  await page.mouse.move(dstBox.x + dstBox.width / 2, dstBox.y + dstBox.height / 2, { steps: 12 });
  await page.waitForTimeout(250);
  const hovered = await page.evaluate(() => document.querySelectorAll(".react-flow__handle.connectingto").length);
  await page.mouse.up();
  await page.waitForTimeout(800);

  const edgesAfter = await page.locator(".react-flow__edge").count();
  console.log(`C5 connectingto=${hovered} edges ${edgesBefore} -> ${edgesAfter}`);
  expect(hovered, "handle target tidak menyala saat pointer di atasnya").toBeGreaterThan(0);
  expect(edgesAfter, "edge tidak bertambah setelah connect").toBe(edgesBefore + 1);
  const types = await page.$$eval(".react-flow__edge", (els) => els.map((e) => e.getAttribute("class")));
  expect(types.some((c) => /react-flow__edge-flow/.test(String(c))), "edge baru bukan tipe kustom `flow`").toBe(true);
});

// ===========================================================================
// C6  Delete edge (pilih edge + Delete)
// ===========================================================================
test("C6 hapus edge: jumlah edge berkurang 1, node tetap", async ({ page }) => {
  await openDemo(page);
  const nodesBefore = (await nodeGeometry(page)).length;
  const edgesBefore = await page.locator(".react-flow__edge").count();

  // Pilih edge lewat `.react-flow__edge-interaction` — path TAK TERLIHAT
  // (stroke-width 20, opacity 0) yang MEMANG disediakan React Flow sebagai
  // sasaran klik. Klik pada `.react-flow__edge-path` (yang terlihat) DITOLAK
  // Playwright karena tertutup elemen interaksi itu (timeout 90s), padahal
  // secara visual terlihat sama.
  await page.locator(".react-flow__edge-interaction").first().click();
  await page.waitForTimeout(400);
  const selected = await page.locator(".react-flow__edge.selected").count();
  expect(selected, "edge tidak terseleksi setelah diklik").toBe(1);
  await page.keyboard.press("Delete");
  await page.waitForTimeout(600);

  const edgesAfter = await page.locator(".react-flow__edge").count();
  const nodesAfter = (await nodeGeometry(page)).length;
  console.log(`C6 edges ${edgesBefore} -> ${edgesAfter}, nodes ${nodesBefore} -> ${nodesAfter}`);
  expect(edgesAfter).toBe(edgesBefore - 1);
  expect(nodesAfter).toBe(nodesBefore);
});

// ===========================================================================
// C7  Pan (drag di area kosong -> transform viewport berubah)
// ===========================================================================
test("C7 pan kanvas mengubah transform viewport", async ({ page }) => {
  await openDemo(page);
  const t0 = await viewportTransform(page);
  // Titik "kosong" TIDAK diasumsikan: dicari dengan elementFromPoint sampai
  // benar-benar menemukan `.react-flow__pane`. Tanpa ini, drag bisa mendarat di
  // node (node contoh ada dekat tepi kiri) atau di panel Controls (kiri-bawah),
  // dan tes gagal seolah pan rusak padahal yang salah titik ujinya.
  const empty = await page.evaluate(() => {
    const canvas = document.querySelector(".react-flow");
    if (!canvas) return null;
    const b = canvas.getBoundingClientRect();
    const candidates = [
      [b.x + b.width - 40, b.y + b.height - 200],
      [b.x + b.width / 2, b.y + b.height - 30],
      [b.x + b.width - 40, b.y + 200],
      [b.x + 30, b.y + b.height - 200],
    ];
    for (const [x, y] of candidates) {
      const el = document.elementFromPoint(x, y);
      if (String(el?.getAttribute("class") || "").includes("react-flow__pane")) {
        return { x: Math.round(x), y: Math.round(y) };
      }
    }
    return null;
  });
  expect(empty, "tidak menemukan titik pane yang kosong").not.toBeNull();

  await page.mouse.move(empty!.x, empty!.y);
  await page.mouse.down();
  for (let i = 1; i <= 20; i++) await page.mouse.move(empty!.x + i * 8, empty!.y - i * 5);
  await page.mouse.up();
  await page.waitForTimeout(600);
  const t1 = await viewportTransform(page);
  console.log(`C7 point=${JSON.stringify(empty)} viewport ${t0} -> ${t1}`);
  expect(t1).not.toBe(t0);
});

// ===========================================================================
// C8  Zoom (tombol toolbar + wheel)
// ===========================================================================
test("C8 zoom in/out mengubah skala viewport dan kembali ke skala awal", async ({ page }) => {
  await openDemo(page);
  const scale = async () => {
    const t = await viewportTransform(page);
    const m = /scale\(([-\d.]+)\)/.exec(t || "");
    return m ? Number(m[1]) : NaN;
  };
  const s0 = await scale();
  await page.click('[data-testid="btn-zoom-in"]');
  await page.waitForTimeout(600);
  const s1 = await scale();
  await page.click('[data-testid="btn-zoom-out"]');
  await page.waitForTimeout(600);
  const s2 = await scale();
  console.log(`C8 scale ${s0} -> ${s1} -> ${s2}`);
  expect(s1).toBeGreaterThan(s0);
  expect(Math.abs(s2 - s0)).toBeLessThan(0.05);
});

// ===========================================================================
// C9  Minimap konsisten dengan jumlah node
// ===========================================================================
test("C9 minimap menampilkan jumlah node yang sama + 1 node per posisi", async ({ page }) => {
  await openDemo(page);
  const nodes = (await nodeGeometry(page)).length;
  const mm = await page.$$eval(".react-flow__minimap-node", (els) =>
    els.map((el) => `${Math.round(el.getBoundingClientRect().x)},${Math.round(el.getBoundingClientRect().y)}`)
  );
  console.log(`C9 nodes=${nodes} minimapNodes=${mm.length}`);
  expect(mm.length).toBe(nodes);
  expect(new Set(mm).size, "minimap menumpuk node di titik yang sama").toBe(nodes);
});


// ===========================================================================
// C10 Save -> reload persist (modul terkait: save/load + store)
// ===========================================================================
test("C10 simpan -> reload ?w= -> jumlah node & edge identik", async ({ page }) => {
  test.setTimeout(120000);
  await openDemo(page);
  const nodesBefore = (await nodeGeometry(page)).length;
  const edgesBefore = await page.locator(".react-flow__edge").count();

  // Alert dari save() membawa ID; dialog harus diterima agar handler lanjut.
  let savedAlert = "";
  page.on("dialog", async (d) => { savedAlert = d.message(); await d.accept(); });

  await page.click('[data-testid="btn-save"]');
  await page.waitForTimeout(6000);
  const idMatch = /ID:\s*([0-9a-f-]{8,})/i.exec(savedAlert);
  console.log(`C10 savedAlert="${savedAlert}" id=${idMatch ? idMatch[1] : "?"}`);
  expect(idMatch, `save tidak mengembalikan ID (alert="${savedAlert}")`).toBeTruthy();
  const id = idMatch![1];

  await page.goto(`/builder?w=${id}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="node-card"]', { timeout: 45000 });
  await page.waitForTimeout(3000);
  const nodesAfter = (await nodeGeometry(page)).length;
  const edgesAfter = await page.locator(".react-flow__edge").count();
  console.log(`C10 nodes ${nodesBefore} -> ${nodesAfter}, edges ${edgesBefore} -> ${edgesAfter}`);
  expect(nodesAfter).toBe(nodesBefore);
  expect(edgesAfter).toBe(edgesBefore);

  // Bersihkan: workflow uji dihapus supaya tidak menumpuk di sidebar user.
  const token = JSON.parse(readFileSync(join(process.cwd(), "_e2e_session.refreshed.json"), "utf-8")).access_token;
  await page.request.delete(`http://127.0.0.1:8000/workflows/${id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
});

// ===========================================================================
// C11 Undo/Redo (tombol + keyboard)
// ===========================================================================
test("C11 undo mengembalikan node yang dihapus, redo menghapusnya lagi", async ({ page }) => {
  await openDemo(page);
  const n0 = (await nodeGeometry(page)).length;

  await page.locator('[data-testid="node-card"]').first().click();
  await page.waitForTimeout(300);
  await page.click('[aria-label="Hapus node"]');
  await page.waitForTimeout(600);
  const n1 = (await nodeGeometry(page)).length;
  expect(n1).toBe(n0 - 1);

  await page.click('[data-testid="btn-undo"]');
  await page.waitForTimeout(700);
  const n2 = (await nodeGeometry(page)).length;
  expect(n2, "undo tidak mengembalikan node").toBe(n0);

  await page.click('[data-testid="btn-redo"]');
  await page.waitForTimeout(700);
  const n3 = (await nodeGeometry(page)).length;
  expect(n3, "redo tidak menerapkan ulang penghapusan").toBe(n0 - 1);

  // Keyboard: Ctrl+Z harus sama dengan tombol undo. Klik dulu area pane yang
  // SUDAH diverifikasi kosong (bukan offset tetap): offset (30,30) mendarat di
  // toolbar kanvas (overlay) sehingga klik diblokir dan tes timeout.
  const pane = await findEmptyPanePoint(page);
  await page.mouse.click(pane.x, pane.y);
  await page.keyboard.press("Control+z");
  await page.waitForTimeout(700);
  const n4 = (await nodeGeometry(page)).length;
  expect(n4, "Ctrl+Z tidak meng-undo").toBe(n0);
});


// ===========================================================================
// C12 Mobile: tap node -> panel konfigurasi
// ===========================================================================
test("C12 mobile tap node membuka panel konfigurasi (sheet) + ?n=<id>", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  const page = await ctx.newPage();
  await seedSession(page);
  await page.goto("/builder?demo=1", { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="node-card"]', { timeout: 45000 });
  await page.waitForTimeout(2200);

  await waitHydrated(page);

  // Panel desktop tidak boleh muncul di mobile (kalau muncul, kanvas terjepit).
  expect(await page.locator('[data-testid="config-aside"]').isVisible()).toBe(false);

  await page.locator('[data-testid="node-card"]').first().click();
  await page.waitForTimeout(1000);
  const dialog = page.locator('[role="dialog"]');
  await expect(dialog).toBeVisible();
  const urlNode = new URL(page.url()).searchParams.get("n");
  console.log(`C12 dialog=${await dialog.count()} urlNode=${urlNode}`);
  expect(urlNode, "?n= tidak di-set saat node dipilih").toBeTruthy();
  // Panel konfigurasi ada di Sheet (dialog) di mobile. Di-scope ke dialog:
  // saat ada node terpilih, elemen panel desktop (aside) juga ter-render walau
  // `hidden` di mobile — tanpa scope, locator ambigu. Testid `config-panel-host`
  // menggantikan kelas `.k-config-host` yang DIHAPUS di FASE 4 (backlog #5).
  await expect(page.locator('[role="dialog"] [data-testid="config-panel-host"]')).toBeVisible();
  await ctx.close();
});

// ===========================================================================
// C13 Mobile: long-press -> drag mode + menu konteks
// ===========================================================================
test("C13 mobile long-press 500ms -> data-armed=true + menu konteks", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  const page = await ctx.newPage();
  await seedSession(page);
  await page.goto("/builder?demo=1", { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="node-card"]', { timeout: 45000 });
  await page.waitForTimeout(2200);

  await waitHydrated(page);

  const card = page.locator('[data-testid="node-card"]').first();
  expect(await card.getAttribute("data-armed")).toBe("false");

  const box = (await card.boundingBox())!;
  const cdp = await ctx.newCDPSession(page);
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [{ x: Math.round(box.x + box.width / 2), y: Math.round(box.y + box.height / 2) }],
  });
  await page.waitForTimeout(700); // > 500ms LONG_PRESS_MS
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await page.waitForTimeout(500);

  const armed = await card.getAttribute("data-armed");
  const menu = await page.locator('[data-testid="node-context-menu"]').count();
  console.log(`C13 armed=${armed} menu=${menu} (metode: CDP Input.dispatchTouchEvent)`);
  expect(armed, "long-press tidak mengaktifkan drag mode").toBe("true");
  expect(menu, "menu konteks tidak muncul").toBeGreaterThan(0);

  // Sentuhan SINGKAT tidak boleh mengaktifkan drag mode.
  await page.keyboard.press("Escape");
  await page.locator('[role="dialog"] [aria-label="Tutup"]').first().click({ timeout: 3000 }).catch(() => {});
  await page.waitForTimeout(400);
  const second = page.locator('[data-testid="node-card"]').nth(1);
  const b2 = (await second.boundingBox())!;
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [{ x: Math.round(b2.x + b2.width / 2), y: Math.round(b2.y + b2.height / 2) }],
  });
  await page.waitForTimeout(120);
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await page.waitForTimeout(400);
  expect(await second.getAttribute("data-armed"), "sentuhan singkat tidak boleh mengarm node").toBe("false");
  await ctx.close();
});


// ===========================================================================
// C14 Mobile: bottom-sheet palette (drag-up) + tap target 44px
// ===========================================================================
test("C14 mobile bottom-sheet palette terbuka lewat drag-up dan menambah node", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  const page = await ctx.newPage();
  await seedSession(page);
  await page.goto("/builder?demo=1", { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="node-card"]', { timeout: 45000 });
  await page.waitForTimeout(2200);

  await waitHydrated(page);

  // Sidebar desktop tidak boleh tampil di mobile.
  expect(await page.locator('[data-testid="palette"]').isVisible()).toBe(false);

  const trigger = page.locator('[data-testid="palette-sheet-trigger"]');
  await expect(trigger).toBeVisible();
  const tb = (await trigger.boundingBox())!;
  await trigger.dispatchEvent("pointerdown", { pointerType: "touch", clientX: tb.x + 40, clientY: tb.y + 20, bubbles: true });
  await trigger.dispatchEvent("pointermove", { pointerType: "touch", clientX: tb.x + 40, clientY: tb.y - 60, bubbles: true });
  await trigger.dispatchEvent("pointerup", { pointerType: "touch", clientX: tb.x + 40, clientY: tb.y - 60, bubbles: true });
  await page.waitForTimeout(600);

  const sheet = page.locator('[data-testid="palette-sheet"]');
  await expect(sheet).toBeVisible();
  const before = await page.locator('[data-testid="node-card"]').count();
  await sheet.locator('[data-testid="palette-item-trigger"]').click();
  await page.waitForTimeout(700);
  const after = await page.locator('[data-testid="node-card"]').count();
  console.log(`C14 sheet=open nodes ${before} -> ${after}`);
  expect(after).toBe(before + 1);

  // Tap target 44x44 di perangkat sentuh (kontrak misi).
  const sizes = await page.$$eval('[data-testid="canvas-toolbar"] button', (els) =>
    els.map((e) => {
      const b = e.getBoundingClientRect();
      return [Math.round(b.width), Math.round(b.height)];
    })
  );
  const tooSmall = sizes.filter(([w, h]) => w < 44 || h < 44);
  console.log(`C14 toolbar sizes=${JSON.stringify(sizes)} tooSmall=${tooSmall.length}`);
  expect(tooSmall, "tombol toolbar < 44px di perangkat sentuh").toHaveLength(0);
  await ctx.close();
});

