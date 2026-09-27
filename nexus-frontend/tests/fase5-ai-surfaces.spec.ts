/**
 * FASE 5 — permukaan AI-native (B1-B4) + onboarding (B5) + microcopy (B6).
 *
 * KENAPA JARINGAN DI-STUB: tes ini menguji RENDER & INTERAKSI milik kita, bukan
 * kualitas jawaban LLM. Kalau memakai model sungguhan, hasilnya bergantung kuota
 * harian (dan pernah membuat suite merah palsu). Dengan `page.route` responsnya
 * deterministik: bentuk payload yang diuji tetap bentuk KONTRAK backend
 * (`meta.workflow`, `needs_credential`, `logs`/`report`), jadi render yang lulus
 * di sini adalah render dari data nyata.
 *
 * Semua klaim bisa dibaca ulang dari output: DRAFT_*, REPORT_*, COT_*, ONB_*.
 */
import { test, expect, type Page, type Route, type Request } from "@playwright/test";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const SHOTS = join(process.cwd(), "test-results", "fase5-ai");
const ONB_KEY = "katalir.onboarding.v1";
const LOCALE_KEY = "katalir.locale.v1";

const DRAFT = {
  name: "Laporan Harian Telegram",
  nodes: [
    { id: "trigger-1", type: "trigger", position: { x: 0, y: 0 }, data: { kind: "trigger", label: "Setiap jam 9", config: {} } },
    { id: "mcp-1", type: "mcp", position: { x: 0, y: 140 }, data: { kind: "mcp", label: "Kirim Telegram", config: { provider: "telegram" } } },
  ],
  edges: [{ id: "e1", source: "trigger-1", target: "mcp-1" }],
};

const EXEC_LOGS = [
  { node_id: "trigger-1", status: "running", payload: null },
  { node_id: "trigger-1", status: "completed", payload: { summary: "dipicu" } },
  { node_id: "mcp-1", status: "completed", payload: { result: { status: "sent", message: "Pesan Telegram terkirim" } } },
];
const EXEC_REPORT =
  "Workflow berhasil: 2 langkah berhasil, 0 gagal.\n1. trigger-1 — OK\n2. mcp-1 — OK: Pesan Telegram terkirim";

function supabaseRef(): string {
  for (const f of [".env.local", ".env"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    const m = readFileSync(p, "utf-8").match(/NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/);
    if (m) return m[1];
  }
  return "qmukkphwaajzbqjrcvaz";
}

/** Tanam sesi E2E + (opsional) locale & status onboarding SEBELUM app boot. */
async function seed(page: Page, opts: { locale?: "id" | "en"; onboardingDone?: boolean } = {}) {
  const p = join(process.cwd(), "_e2e_session.refreshed.json");
  const sess = existsSync(p) ? JSON.parse(readFileSync(p, "utf-8")) : null;
  const key = `sb-${supabaseRef()}-auth-token`;
  const entries: [string, string][] = [];
  if (sess) entries.push([key, JSON.stringify(sess)]);
  if (opts.locale) entries.push([LOCALE_KEY, opts.locale]);
  if (opts.onboardingDone) entries.push([ONB_KEY, "done"]);
  await page.addInitScript((kv: [string, string][]) => {
    for (const [k, v] of kv) {
      try {
        window.localStorage.setItem(k, v);
      } catch {
        /* abaikan */
      }
    }
  }, entries);
}

/**
 * Backend requests to stub.
 *
 * Derived from E2E_BACKEND_URL rather than hardcoded. The test backend runs
 * on 8123 (playwright.config.ts moved it off 8000 so a manually-started
 * uvicorn could never be tested by mistake), but this spec still compared
 * `u.port === "8000"`. Every stub was therefore bypassed and the tests hit
 * the real API: each one burned ~32s and failed. Comparing the full origin
 * fixes it and makes the spec immune to a future port change.
 */
function isApi(req: Request): boolean {
  const expected = new URL(process.env.E2E_BACKEND_URL || "http://127.0.0.1:8123");
  const u = new URL(req.url());
  return u.hostname === expected.hostname && u.port === expected.port;
}

type Stub = {
  chat?: (n: number) => Record<string, unknown>;
  vaultOk?: boolean;
  /** Riwayat chat yang dilaporkan GET /sessions (default: kosong = user baru). */
  sessions?: { id: string; title?: string }[];
};

/** Stub HANYA endpoint backend (E2E_BACKEND_URL); sisanya dibiarkan nyata. */
async function stubApi(page: Page, opts: Stub) {
  const seen: { chat: number; prefs: unknown[] } = { chat: 0, prefs: [] };
  await page.route("**/*", async (route: Route) => {
    const req = route.request();
    if (!isApi(req)) return route.continue();
    const path = new URL(req.url()).pathname;
    const json = (status: number, body: unknown) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/sessions") return json(200, { sessions: opts.sessions ?? [] });
    if (path === "/chat" && req.method() === "POST") {
      seen.chat += 1;
      const body = opts.chat?.(seen.chat) ?? { status: "success", reply: "ok", session_id: "sess-stub" };
      return json(200, body);
    }
    if (path === "/api/vault/save") return json(200, { status: "success" });
    if (path === "/workflows" && req.method() === "POST") return json(200, { workflow: { id: "wf-stub" } });
    if (/^\/workflows\/[^/]+\/execute$/.test(path)) return json(202, { execution_id: "ex-stub" });
    if (path === "/executions/ex-stub")
      return json(200, { execution: { status: "completed" }, logs: EXEC_LOGS, report: EXEC_REPORT });
    if (path === "/preferences" && req.method() === "PUT") {
      seen.prefs.push(JSON.parse(req.postData() ?? "{}"));
      return json(200, { status: "success", prefs: {} });
    }
    return route.continue();
  });
  return seen;
}

async function openChat(page: Page) {
  // FASE 6 final: aplikasi chat kini di `/chat` (`/` = landing ringan).
  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
  await expect(page.getByTestId("composer-input")).toBeVisible();
}

async function ask(page: Page, text: string) {
  await page.getByTestId("composer-input").fill(text);
  await page.getByTestId("composer-send").click();
}

test.beforeAll(() => {
  if (!existsSync(SHOTS)) mkdirSync(SHOTS, { recursive: true });
});

// ---------------------------------------------------------------------------
// B1 + B2 — draf workflow inline -> "Jalankan Langsung" -> kartu laporan
// ---------------------------------------------------------------------------
test("B1+B2 draf inline + tombol aksi + laporan eksekusi terstruktur", async ({ page }) => {
  test.setTimeout(120000);
  const seen = await stubApi(page, {
    chat: () => ({
      status: "success",
      reply: "Siap! Saya sudah menyusun workflow-nya untuk Anda.",
      session_id: "sess-stub",
      meta: { model: "gemma-4-31b-it", latency_ms: 1200, workflow: DRAFT },
    }),
  });
  await seed(page, { locale: "id", onboardingDone: true });
  await openChat(page);
  await ask(page, "buat workflow kirim telegram setiap jam 9");

  // B1: kartu draf DI DALAM pesan (bukan modal, bukan halaman lain).
  const card = page.getByTestId("workflow-draft-card");
  await expect(card).toBeVisible({ timeout: 30000 });
  expect(await card.getAttribute("data-nodes")).toBe("2");
  expect(await card.getAttribute("data-edges")).toBe("1");
  expect(await card.evaluate((el) => !!el.closest("[role='dialog']"))).toBe(false);
  await expect(page.getByTestId("draft-name")).toContainText(DRAFT.name);
  await expect(page.getByTestId("draft-open-canvas")).toBeVisible();
  await expect(page.getByTestId("draft-run-now")).toBeVisible();
  console.log(`DRAFT_CARD=nodes:${await card.getAttribute("data-nodes")} edges:${await card.getAttribute("data-edges")}`);
  await page.screenshot({ path: join(SHOTS, "b1_draft_inline.png") });

  // B2: "Jalankan Langsung" -> kartu laporan terstruktur (status + langkah).
  await page.getByTestId("draft-run-now").click();
  const report = page.locator('[data-testid="run-report"]').last();
  await expect(report).toBeVisible({ timeout: 60000 });
  const rcard = report.getByTestId("execution-report-card");
  await expect(rcard).toBeVisible({ timeout: 60000 });
  await expect(rcard).toHaveAttribute("data-status", "success");
  const steps = rcard.getByTestId("report-step");
  await expect(steps).toHaveCount(2);
  expect(await steps.nth(0).getAttribute("data-step-status")).toBe("success");
  console.log(`REPORT_STATUS=${await rcard.getAttribute("data-status")} STEPS=${await steps.count()}`);
  // Teks laporan backend harus TETAP ada (kontrak E2E L3 S1 + bisa disalin).
  await expect(report).toContainText(/Workflow berhasil/);
  await expect(rcard.getByTestId("report-duration")).not.toBeEmpty();
  await page.screenshot({ path: join(SHOTS, "b2_report_card.png") });
  console.log(`REPORT_TEXT=${(await report.textContent())?.replace(/\s+/g, " ").slice(0, 140)}`);
  console.log(`CHAT_POSTS=${seen.chat}`);

  // Tombol "Lihat di Kanvas" (footer kartu) harus berpindah halaman.
  await rcard.getByTestId("report-open-canvas").click();
  await page.waitForURL(/\/builder/, { timeout: 30000 });
  console.log(`NAV_AFTER_REPORT_OPEN=${new URL(page.url()).pathname}`);
});

test("B1 draf: tombol 'Buka di Kanvas' menyimpan draf lalu pindah halaman", async ({ page }) => {
  test.setTimeout(120000);
  await stubApi(page, {
    chat: () => ({
      status: "success",
      reply: "Ini workflow-nya.",
      session_id: "sess-stub",
      meta: { model: "gemma-4-31b-it", workflow: DRAFT },
    }),
  });
  await seed(page, { locale: "id", onboardingDone: true });
  await openChat(page);
  await ask(page, "buat workflow telegram");
  await expect(page.getByTestId("workflow-draft-card")).toBeVisible({ timeout: 30000 });
  await page.getByTestId("draft-open-canvas").click();
  await page.waitForURL(/\/builder/, { timeout: 30000 });
  // CATATAN (koreksi FASE 5): draf TIDAK dihapus dari localStorage oleh tombol
  // ini — Kanvas-lah yang mengonsumsinya saat mount (`peek` -> pakai -> `clear`).
  // Jadi bukti yang benar bukan "kunci masih ada", melainkan "node-nya sampai
  // ke kanvas". Assertion pertama (PENDING_SAVED=no) salah dan diganti ini.
  await expect(page.locator('[data-testid="node-card"]')).toHaveCount(2, { timeout: 30000 });
  const nodes = await page.locator('[data-testid="node-card"]').count();
  console.log(`CANVAS_NODES_FROM_DRAFT=${nodes}`);
  expect(nodes, "draf harus termuat ke kanvas").toBe(2);
});

// ---------------------------------------------------------------------------
// B3 — permintaan kredensial = form INLINE di bubble (bukan modal)
// ---------------------------------------------------------------------------
test("B3 kredensial: form inline di dalam pesan + submit mengulang prompt", async ({ page }) => {
  test.setTimeout(120000);
  const seen = await stubApi(page, {
    chat: () => ({ status: "needs_credential", provider: "telegram", message: "Butuh token Telegram." }),
  });
  await seed(page, { locale: "id", onboardingDone: true });
  await openChat(page);
  await ask(page, "kirim pesan telegram");

  const prompt = page.getByTestId("credential-prompt");
  await expect(prompt).toBeVisible({ timeout: 30000 });
  expect(await prompt.getAttribute("data-provider")).toBe("telegram");
  // INLINE: tidak ada dialog/modal yang membungkusnya.
  expect(await prompt.evaluate((el) => !!el.closest("[role='dialog']"))).toBe(false);
  await expect(prompt.getByTestId("credential-submit")).toBeDisabled(); // kosong -> tidak bisa kirim
  await prompt.getByTestId("credential-input").fill("123456:STUB-TOKEN");
  await expect(prompt.getByTestId("credential-submit")).toBeEnabled();
  console.log(`CRED_INLINE=provider:${await prompt.getAttribute("data-provider")} modal:false`);
  await page.screenshot({ path: join(SHOTS, "b3_credential_inline.png") });

  // Submit -> simpan ke vault (di-stub) -> prompt dikirim ULANG (chat kedua).
  const before = seen.chat;
  await prompt.getByTestId("credential-submit").click();
  await expect.poll(() => seen.chat, { timeout: 30000 }).toBeGreaterThan(before);
  console.log(`CHAT_POSTS_AFTER_CRED=${seen.chat}`);
});

// ---------------------------------------------------------------------------
// B4 — ChainOfThought: penalaran collapsible, default TERTUTUP di desktop
// ---------------------------------------------------------------------------
test("B4 ChainOfThought: tertutup di desktop, bisa dibuka, jawaban tetap tampil", async ({ page }) => {
  test.setTimeout(120000);
  await stubApi(page, {
    chat: () => ({
      status: "success",
      reply: "<thinking>Pertama saya cek provider.\nLalu saya susun node trigger + mcp.</thinking>Workflow siap di kanvas.",
      session_id: "sess-stub",
      meta: { model: "gemma-4-31b-it" },
    }),
  });
  await seed(page, { locale: "id", onboardingDone: true });
  await openChat(page);
  await ask(page, "buat workflow telegram");

  const cot = page.getByTestId("chain-of-thought");
  await expect(cot).toBeVisible({ timeout: 30000 });
  const toggle = cot.getByRole("button");
  await expect(toggle).toHaveAttribute("aria-expanded", "false"); // desktop default
  await expect(cot.getByTestId("chain-of-thought-body")).toHaveCount(0);
  // Jawaban final HARUS bersih dari blok penalaran.
  await expect(page.locator('[data-testid="msg-list"]')).toContainText("Workflow siap di kanvas");
  await expect(page.locator('[data-testid="msg-list"]')).not.toContainText("Pertama saya cek provider");
  console.log("COT_DEFAULT=collapsed_desktop answer_clean=true");

  await toggle.click();
  await expect(cot.getByTestId("chain-of-thought-body")).toBeVisible();
  await expect(cot).toContainText("Pertama saya cek provider");
  console.log(`COT_AFTER_CLICK=${await toggle.getAttribute("aria-expanded")}`);
  await page.screenshot({ path: join(SHOTS, "b4_chain_of_thought.png") });

  await toggle.click();
  await expect(cot.getByTestId("chain-of-thought-body")).toHaveCount(0);
  console.log(`COT_AFTER_SECOND_CLICK=${await toggle.getAttribute("aria-expanded")}`);
});

test("B4 ChainOfThought: TIDAK muncul bila model tidak mengirim penalaran", async ({ page }) => {
  test.setTimeout(120000);
  await stubApi(page, {
    chat: () => ({ status: "success", reply: "Jawaban biasa tanpa penalaran.", session_id: "sess-stub", meta: { model: "gemma-4-31b-it" } }),
  });
  await seed(page, { locale: "id", onboardingDone: true });
  await openChat(page);
  await ask(page, "halo");
  await expect(page.locator('[data-testid="msg-list"]')).toContainText("Jawaban biasa tanpa penalaran");
  await expect(page.getByTestId("chain-of-thought")).toHaveCount(0);
  console.log("COT_ABSENT_WHEN_NO_REASONING=true");
});

// ---------------------------------------------------------------------------
// B5 — onboarding 3 langkah: muncul untuk user baru, bisa dilewati, persist
// ---------------------------------------------------------------------------
test("B5 onboarding: 3 langkah, bisa dilewati, tidak muncul lagi setelah selesai", async ({ page }) => {
  test.setTimeout(120000);
  const seen = await stubApi(page, { chat: () => ({ status: "success", reply: "ok", session_id: "sess-stub" }) });
  await seed(page, { locale: "id" }); // TANPA onboardingDone -> user baru
  await openChat(page);

  const flow = page.getByTestId("onboarding-flow");
  await expect(flow).toBeVisible({ timeout: 30000 });
  expect(await flow.getAttribute("data-step")).toBe("0");
  await expect(flow.getByTestId("onboarding-step-1")).toBeVisible();
  console.log(`ONB_STEP0=visible options=${await flow.getByTestId("onboarding-model-option").count()}`);
  await page.screenshot({ path: join(SHOTS, "b5_onboarding_step1.png") });

  await flow.getByTestId("onboarding-next").click();
  await expect(flow.getByTestId("onboarding-step-2")).toBeVisible();
  await expect(flow.getByTestId("onboarding-sample-prompt")).toContainText("Telegram");
  await expect(flow.getByTestId("onboarding-skip")).toBeVisible(); // skip SELALU ada
  console.log(`ONB_STEP1=sample:${(await flow.getByTestId("onboarding-sample-prompt").textContent())?.slice(0, 40)}`);
  await page.screenshot({ path: join(SHOTS, "b5_onboarding_step2.png") });

  await flow.getByTestId("onboarding-next").click();
  await expect(flow.getByTestId("onboarding-step-3")).toBeVisible();
  await expect(flow.getByTestId("onboarding-done")).toBeVisible();
  await page.screenshot({ path: join(SHOTS, "b5_onboarding_step3.png") });

  await flow.getByTestId("onboarding-done").click();
  await expect(flow).toHaveCount(0);
  const local = await page.evaluate((k) => window.localStorage.getItem(k), ONB_KEY);
  console.log(`ONB_LOCAL=${local} PREFS_PUTS=${seen.prefs.length}`);
  expect(local).toBe("done");
  expect(seen.prefs.length, "status onboarding harus ikut tersimpan ke profil").toBeGreaterThan(0);
  expect(JSON.stringify(seen.prefs[0])).toContain("onboardingCompleted");

  // Reload: tidak boleh muncul lagi (persist lokal).
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
  await expect(page.getByTestId("onboarding-flow")).toHaveCount(0);
  console.log("ONB_NOT_SHOWN_AFTER_RELOAD=true");
});

test("B5 onboarding: 'Lewati' juga menyimpan pilihan (tidak muncul lagi)", async ({ page }) => {
  test.setTimeout(120000);
  await stubApi(page, { chat: () => ({ status: "success", reply: "ok", session_id: "sess-stub" }) });
  await seed(page, { locale: "id" });
  await openChat(page);
  const flow = page.getByTestId("onboarding-flow");
  await expect(flow).toBeVisible({ timeout: 30000 });
  await flow.getByTestId("onboarding-skip").click();
  await expect(flow).toHaveCount(0);
  const local = await page.evaluate((k) => window.localStorage.getItem(k), ONB_KEY);
  console.log(`ONB_SKIP_LOCAL=${local}`);
  expect(local).toBe("skipped");
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
  await expect(page.getByTestId("onboarding-flow")).toHaveCount(0);
  console.log("ONB_SKIP_PERSISTED=true");
});

test("B5 onboarding: TIDAK muncul untuk user yang sudah punya riwayat chat", async ({ page }) => {
  test.setTimeout(120000);
  // REGRESI YANG DIJAGA: versi pertama menampilkan dialog untuk SETIAP sesi yang
  // belum menandai selesai. Di E2E A2 (auth logout) overlay `fixed inset-0 z-50`
  // itu menutupi header sehingga klik menu akun tidak pernah sampai -> spec
  // timeout 1,5 menit. Definisi "user baru" sekarang: TANPA riwayat + belum selesai.
  await stubApi(page, { sessions: [{ id: "sess-lama", title: "halo" }] });
  await seed(page, { locale: "id" }); // tetap TANPA katalir.onboarding.v1
  await openChat(page);
  await page.waitForTimeout(1500); // beri kesempatan dialog muncul bila salah
  await expect(page.getByTestId("onboarding-flow")).toHaveCount(0);
  // Bukti tambahan: header tetap bisa diklik (bukan tertutup lapisan apa pun).
  const menu = page.locator('button[aria-label^="Menu akun"], button[aria-label^="Account menu"]').first();
  await expect(menu).toBeVisible();
  await menu.click();
  console.log("ONB_HIDDEN_FOR_EXISTING_USER=true header_clickable=true");
});

// ---------------------------------------------------------------------------
// B6 — microcopy: string yang sama mengikuti locale (tidak ada hardcode)
// ---------------------------------------------------------------------------
test("B6 microcopy: locale EN vs ID pada kartu kredensial", async ({ page }) => {
  test.setTimeout(120000);
  await stubApi(page, { chat: () => ({ status: "needs_credential", provider: "telegram" }) });
  await seed(page, { locale: "en", onboardingDone: true });
  await openChat(page);
  await ask(page, "send telegram message");
  const prompt = page.getByTestId("credential-prompt");
  await expect(prompt).toBeVisible({ timeout: 30000 });
  await expect(prompt).toContainText("Connect Telegram");
  await expect(prompt).not.toContainText("Hubungkan");
  console.log(`CRED_TITLE_EN=${(await prompt.textContent())?.replace(/\s+/g, " ").slice(0, 60)}`);
  await page.screenshot({ path: join(SHOTS, "b6_microcopy_en.png") });
});
