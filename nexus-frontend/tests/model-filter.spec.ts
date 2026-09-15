import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const BASE = "http://localhost:3000";
const REF = "qmukkphwaajzbqjrcvaz";
const KEY = `sb-${REF}-auth-token`;
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

function loadSession(): any | null {
  try {
    return JSON.parse(readFileSync(join(process.cwd(), "_e2e_session.extended.json"), "utf-8"));
  } catch {
    return null;
  }
}

/** Payload NYATA: 12 model dari roster gateway (hasil GET /models lokal). */
function realModels(): any {
  return JSON.parse(readFileSync(join(process.cwd(), "models-real.fixture.json"), "utf-8"));
}

/** Buka dropdown dengan retry: pada dev server, klik pertama bisa mendarat
 *  sebelum React menempelkan handler (chunk masih dikompilasi) sehingga menu
 *  tidak terbuka. Retry sampai menu benar-benar muncul. */
async function openMenu(page: any) {
  const trigger = page.locator("button[aria-label='Pilih model AI']");
  await expect(trigger).toBeVisible({ timeout: 15000 });
  const menu = page.getByRole("menu");
  for (let i = 0; i < 8; i++) {
    if (await menu.isVisible().catch(() => false)) return trigger;
    await trigger.click({ force: true }).catch(() => {});
    await sleep(1200);
  }
  await expect(menu).toBeVisible({ timeout: 5000 });
  return trigger;
}

/**
 * TUGAS 1 + 3 — verifikasi UI:
 *   - model paid-only (Pro) TIDAK ada di selector;
 *   - model free valid (flash-lite) ADA;
 *   - item yang dikunci server diredupkan + berlabel alasan.
 *
 * Auth: sesi E2E di-inject dengan `exp` yang diperpanjang LOKAL (token tidak
 * diverifikasi tanda tangannya oleh `supabase.auth.getSession()`), dan seluruh
 * endpoint backend di-route-intercept — jadi tes ini tidak menyentuh produksi.
 * Filter backend sendiri diverifikasi terpisah lewat Python (lihat ringkasan).
 */
test("MODEL-FILTER: Pro tidak muncul, free valid muncul, locked jelas", async ({ page }) => {
  const session = loadSession();
  test.skip(!session, "jalankan _e2e_extend.py dulu (butuh _e2e_session.json)");

  await page.addInitScript(
    (kv) => {
      try {
        window.localStorage.setItem(kv.key, JSON.stringify(kv.value));
      } catch {
        /* ignore */
      }
    },
    { key: KEY, value: session }
  );

  // Semua panggilan backend dilayani lokal: tidak ada trafik ke produksi.
  await page.route("**/models", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(realModels()) })
  );
  await page.route("**/sessions*", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ sessions: [] }) })
  );
  await page.route("**/chat", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "success", reply: "ok" }) })
  );

  await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" }).catch(() => {});
  await sleep(2500);

  const trigger = await openMenu(page);
  await sleep(600);

  const items = await page.getByRole("menuitem").allInnerTexts();
  const joined = items.join(" | ").toLowerCase();
  console.log("MENU_ITEMS=" + JSON.stringify(items));
  console.log("ITEM_COUNT=" + items.length);

  // 1) Tidak ada model paid-only / Pro di selector.
  const proHits = items.filter((t) => /-pro\b|pro preview|\bpro\b/i.test(t));
  console.log("PRO_HITS=" + JSON.stringify(proHits));
  expect(proHits, "model paid-only masih tampil di selector").toHaveLength(0);

  // 2) Model free valid tetap ada (flash & flash-lite TIDAK boleh hilang).
  expect(joined).toContain("flash lite");
  expect(joined).toContain("flash");

  await page.screenshot({ path: "test-results/selector-real-catalog.png" });
  await page.keyboard.press("Escape");
});

/**
 * TUGAS 3 — locked state: item dengan `locked:true` dari server harus redup +
 * berlabel alasan. Fixture di sini SENGAJA sintetis (tier plus) karena roster
 * nyata kita semuanya free-tier; yang diuji adalah jalur render `locked`.
 */
test("MODEL-LOCKED: item terkunci redup + berlabel alasan", async ({ page }) => {
  const session = loadSession();
  test.skip(!session, "jalankan _e2e_extend.py dulu");

  await page.addInitScript(
    (kv) => {
      try {
        window.localStorage.setItem(kv.key, JSON.stringify(kv.value));
      } catch {
        /* ignore */
      }
    },
    { key: KEY, value: session }
  );

  const base = realModels();
  const payload = {
    ...base,
    models: [
      ...base.models,
      { id: "gemini-3.1-pro-preview", name: "Gemini 3.1 Pro Preview", provider: "Gateway \u00b7 google_gemini", tier: "plus", hint: "locked-fixture", locked: true },
    ],
  };
  await page.route("**/models", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) })
  );
  await page.route("**/sessions*", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ sessions: [] }) })
  );

  await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" }).catch(() => {});
  await sleep(2500);
  await openMenu(page);
  await sleep(600);

  // Label alasan tampil dan item benar-benar ter-disable.
  await expect(page.getByText("Tidak tersedia di tier Anda")).toBeVisible();
  const lockedItem = page.getByRole("menuitem", { name: /Gemini 3\.1 Pro Preview/ });
  await expect(lockedItem).toHaveAttribute("aria-disabled", "true");

  await page.screenshot({ path: "test-results/selector-locked.png" });
  await page.keyboard.press("Escape");
});
