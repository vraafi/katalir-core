import { test, expect } from "@playwright/test";

const BASE = "http://localhost:3000";
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** Sinyal hydration dari React 19 (recoverable error) + monitor kita. */
const HYDRATION_RE = /hydrat|did not match|server rendered|tree hydrated/i;

const SEED_MODEL = "gemma-4-9b-it"; // BUKAN default & tidak ada di fallback list
const SEED_QUEUE = [{ id: "hyd-1", text: "pesan antrean hydration" }];
// Rebrand 2026-09-18: app membaca "katalir.*" DULU, lalu fallback ke key
// lama "nexus.*" — jadi menanam key BARU menguji jalur utama yang baru.
const MODEL_KEY = "katalir.model.v1";
const QUEUE_KEY = "katalir.queue.v1";

/**
 * HYD-1: nilai localStorage yang ditanam SEBELUM app boot tidak boleh
 * menyebabkan hydration mismatch.
 *
 * Regresi yang dijaga: `useState` initializer yang membaca localStorage
 * (page.tsx selectedModel + messageQueue). Static export merender tanpa
 * `window`, sehingga HTML server tidak memuat antrean/pilihan tersimpan,
 * sedangkan render pertama client memuatnya -> React 19 melempar
 * "Hydration failed because the server rendered HTML didn't match the client"
 * dan seluruh tree di-regenerate (DOM yang di-flash user salah).
 *
 * Fix: initializer deterministik + restore di effect (post-mount).
 */
test("HYD-1: localStorage tersimpan tidak memicu hydration mismatch", async ({ page }) => {
  await page.addInitScript(
    (kv: { model: string; queue: string; mkey: string; qkey: string }) => {
      try {
        window.localStorage.setItem(kv.mkey, kv.model);
        window.localStorage.setItem(kv.qkey, kv.queue);
      } catch {
        /* ignore */
      }
    },
    { model: SEED_MODEL, queue: JSON.stringify(SEED_QUEUE), mkey: MODEL_KEY, qkey: QUEUE_KEY }
  );

  const pageErrors: string[] = [];
  const hydrationHits: string[] = [];
  const recovered: string[] = [];
  page.on("pageerror", (e) => {
    const text = String(e as object);
    pageErrors.push(text);
    if (HYDRATION_RE.test(text)) hydrationHits.push(text);
  });
  page.on("console", (m) => {
    const text = m.text();
    if (text.includes("[Hydration-Recovered]")) recovered.push(text);
    if (HYDRATION_RE.test(text)) hydrationHits.push(`[${m.type()}] ${text}`);
  });

  await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" }).catch(() => {});
  await sleep(2500);

  console.log("HYDRATION_HITS=" + hydrationHits.length);
  console.log("PAGEERRORS=" + JSON.stringify(pageErrors.slice(0, 3)));
  console.log("MONITOR_RECOVERED=" + recovered.length);

  // 1) Bukti utama: nol sinyal hydration.
  expect(
    hydrationHits,
    "hydration mismatch terdeteksi:\n" + hydrationHits.join("\n---\n").slice(0, 2000)
  ).toHaveLength(0);

  // 2) Pilihan model tersimpan TIDAK ditimpa balik ke default oleh effect persist
  //    (regresi gate `modelReady`: tanpa gate, commit pertama menulis DEFAULT).
  const storedAfter = await page.evaluate((k: string) => window.localStorage.getItem(k), MODEL_KEY);
  console.log("STORED_MODEL_AFTER=" + storedAfter);
  expect(storedAfter).toBe(SEED_MODEL);

  // 3) Gate `mounted` di ModelSelector (Lapis A) HARUS melepas: label netral
  //    hanya untuk render pertama, bukan placeholder permanen.
  const trigger = page.locator("button[aria-label='Pilih model AI']");
  await expect(trigger).toBeVisible();
  await expect(trigger.locator("span").first()).not.toHaveText(/Memuat/, { timeout: 5000 });

  // 4) Selector masih berfungsi (Slot/asChild tidak rusak + id kontekstual
  //    Radix stabil karena tree tidak di-regenerate).
  await trigger.click();
  await expect(page.getByRole("menu")).toBeVisible({ timeout: 3000 });
  await page.keyboard.press("Escape");

  // CATATAN: `queue-area` sengaja TIDAK di-assert. Item antrean tersimpan langsung
  // dikonsumsi efek FIFO (page.tsx:458-464 -> sendPrompt + slice(1)) sehingga
  // "Antrean (1)" lenyap sebelum sempat diperiksa; itu perilaku normal, bukan
  // regresi. Seed antrean tetap dipertahankan karena ia menambah tekanan
  // struktural pada hydration (client punya <div queue-area>, server tidak).
  console.log("QUEUE_AREA_COUNT=" + (await page.getByTestId("queue-area").count()));

  await page.screenshot({ path: "test-results/hydration-clean.png" });
});