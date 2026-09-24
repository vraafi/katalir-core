import { test, expect, type Page } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

/**
 * Lifecycle workflow di UI Builder (FASE B).
 *
 * Spec ini SELF-CLEANING: workflow yang dibuat untuk pengujian dihapus kembali
 * di akhir, supaya akun uji tidak menumpuk data (kesalahan sesi sebelumnya:
 * data uji menumpuk lalu dibersihkan dengan DELETE berbasis NAMA tanpa filter
 * pemilik, yang ikut menghapus baris lain).
 */

const BASE = "http://localhost:3000";

function supabaseRef(): string {
  for (const f of [".env.local", ".env"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    const m = readFileSync(p, "utf-8").match(/NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/);
    if (m) return m[1];
  }
  return "qmukkphwaajzbqjrcvaz";
}

const LS_KEY = `sb-${supabaseRef()}-auth-token`;

async function boot(page: Page) {
  test.setTimeout(180000);
  const sess = JSON.parse(readFileSync(join(process.cwd(), "_e2e_session.refreshed.json"), "utf-8"));
  await page.addInitScript(
    (kv: { key: string; value: unknown }) => {
      try { window.localStorage.setItem(kv.key, JSON.stringify(kv.value)); } catch { /* abaikan */ }
    },
    { key: LS_KEY, value: sess }
  );
  const calls: Array<{ url: string; method: string; status: number; body: string }> = [];
  page.on("response", async (r) => {
    const u = r.url();
    if (!/\/workflows/.test(u)) return;
    let body = "";
    try { body = await r.text(); } catch { /* abaikan */ }
    calls.push({ url: u.replace(/^https?:\/\/[^/]+/, ""), method: r.request().method(), status: r.status(), body });
  });
  page.on("dialog", (d) => { void d.accept().catch(() => {}); });
  await page.goto(`${BASE}/builder`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".react-flow", { timeout: 40000 });
  await page.waitForTimeout(5000);
  return calls;
}

async function dropNode(page: Page, kind = "trigger", fx = 0.45, fy = 0.45) {
  const box = await page.locator(".react-flow").first().boundingBox();
  const x = Math.round(box!.x + box!.width * fx);
  const y = Math.round(box!.y + box!.height * fy);
  await page.evaluate(({ x, y, kind }) => {
    const rf = document.querySelector(".react-flow");
    const dt = new DataTransfer();
    dt.setData("application/reactflow", kind);
    const mk = (t: string) => new DragEvent(t, { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: y });
    rf!.dispatchEvent(mk("dragover"));
    rf!.dispatchEvent(mk("drop"));
  }, { x, y, kind });
  await page.waitForTimeout(700);
}

async function itemCount(page: Page) {
  return page.locator('[data-testid="workflow-item"]').count();
}


test("lifecycle UI: save idempoten, rename, reload, delete (self-cleaning)", async ({ page }) => {
  const calls = await boot(page);

  // Mulai dari kanvas kosong: "Alur Baru" -> selectWorkflow(null) -> clearWork + lepas ?w=
  await page.getByRole("button", { name: /Alur Baru/i }).click();
  await page.waitForTimeout(1200);
  const before = await itemCount(page);
  console.log("SIDEBAR_BEFORE=" + before);

  // --- 1) CREATE: drop node + Simpan Alur -> baris BARU
  await dropNode(page);
  await page.getByRole("button", { name: /Simpan Alur/i }).click();
  await page.waitForTimeout(3500);
  const createCall = calls.filter((c) => c.method === "POST" && c.url === "/workflows").pop();
  console.log("SAVE1=" + JSON.stringify(createCall && { status: createCall.status, body: createCall.body.slice(0, 110) }));
  expect(createCall?.status, "POST /workflows tidak 201").toBe(201);
  expect(createCall!.body).toContain('"updated":false');
  const newId = JSON.parse(createCall!.body).workflow.id as string;
  console.log("NEW_ID=" + (newId || "").slice(0, 8));

  await expect.poll(async () => itemCount(page), { timeout: 15000 }).toBe(before + 1);
  const row = page.locator(`[data-testid="workflow-item"][data-workflow-id="${newId}"]`);
  await expect(row).toHaveCount(1);

  // --- 2) SAVE ULANG = UPDATE (tidak menambah baris)
  calls.length = 0;
  await page.getByRole("button", { name: /Simpan Alur/i }).click();
  await page.waitForTimeout(3000);
  const save2 = calls.filter((c) => c.method === "POST" && c.url === "/workflows").pop();
  console.log("SAVE2=" + JSON.stringify(save2 && { status: save2.status, body: save2.body.slice(0, 110) }));
  expect(save2?.status).toBe(201);
  expect(save2!.body, "save ulang tidak mengirim update (bug INSERT-always)").toContain('"updated":true');
  expect(save2!.body).toContain(newId);
  await page.waitForTimeout(1200);
  expect(await itemCount(page), "save ulang menambah baris baru").toBe(before + 1);

  // --- 3) RENAME via UI (ikon pensil -> ketik -> Enter)
  const uniq = "Rename-" + Date.now().toString().slice(-6);
  calls.length = 0;
  await row.locator('[data-testid="workflow-rename"]').click();
  const input = row.locator('[data-testid="workflow-rename-input"]');
  await input.fill(uniq);
  await input.press("Enter");
  await page.waitForTimeout(2500);
  const patch = calls.find((c) => c.method === "PATCH");
  console.log("PATCH=" + JSON.stringify(patch && { url: patch.url, status: patch.status }));
  expect(patch?.status, "PATCH rename gagal").toBe(200);
  await expect(row.locator('[data-testid="workflow-name"]')).toHaveText(uniq);

  // --- 4) RELOAD: nama tetap, klik item memuat isi graf (detail fetch)
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForSelector(".react-flow", { timeout: 40000 });
  await page.waitForTimeout(6000);
  const rowAfter = page.locator(`[data-testid="workflow-item"][data-workflow-id="${newId}"]`);
  await expect(rowAfter.locator('[data-testid="workflow-name"]')).toHaveText(uniq);
  await rowAfter.locator("button").first().click();
  await page.waitForTimeout(4500);
  const nodeCount = await page.locator(".react-flow__node").count();
  console.log("NODES_AFTER_LOAD=" + nodeCount);
  expect(nodeCount, "workflow tersimpan tidak termuat ke kanvas setelah reload").toBeGreaterThan(0);

  // --- 5) DELETE via UI (konfirmasi di-accept oleh handler dialog)
  calls.length = 0;
  await rowAfter.locator('[data-testid="workflow-delete"]').click();
  await page.waitForTimeout(3000);
  const del = calls.find((c) => c.method === "DELETE");
  console.log("DELETE=" + JSON.stringify(del && { url: del.url, status: del.status }));
  expect(del?.status, "DELETE gagal").toBe(200);
  await expect(rowAfter, "baris masih ada setelah delete").toHaveCount(0);
  console.log("SIDEBAR_AFTER=" + (await itemCount(page)));
});
