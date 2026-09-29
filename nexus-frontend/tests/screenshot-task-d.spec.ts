/**
 * Screenshot Task D -- kartu retry / escalate / credential dari self-healing.
 *
 * Alur SEPENUHNYA nyata: `/chat` -> ketik perintah -> kartu draf -> klik
 * "Jalankan Langsung" -> polling `/executions/{id}` -> `buildExecutionReport`
 * -> `ExecutionReportCard`. Yang di-stub hanya JAWABAN backend (termasuk
 * `logs`), persis seperti `fase5-ai-surfaces.spec.ts`.
 *
 * CATATAN BENTUK PAYLOAD: backend tidak pernah mengembalikan `steps`.
 * `GET /executions/{id}` mengembalikan `{execution:{status}, logs, report}`
 * dan `buildExecutionReport` membaca `logs` (lihat `auto-run.ts` L103-118).
 * Fixture draf di prompt memakai `steps`; kalau dipakai apa adanya, `logs`
 * jadi undefined dan kartu jatuh ke fallback parse teks -- badge healing
 * tidak akan pernah muncul.
 */
import { test, expect, type Page, type Route, type Request } from "@playwright/test";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const SHOTS = join(process.cwd(), "..", "docs", "marketing", "screenshots");
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

/** Bentuk `HealingPlan.to_dict()` dari `self_healing.py`. */
function healing(o: Record<string, unknown>) {
  return { node_id: "mcp-1", changes: {}, trace: [], ...o };
}

function retryRow(n: number, category: string, reason: string, delay: number, s: object[] = []) {
  return {
    node_id: "mcp-1",
    status: "retrying",
    payload: {
      healing: healing({
        action: "retry", attempt: n, max_attempts: 5, category, reason,
        provider: "openai", delay_ms: delay, search_hits: s.length, suggestions: s,
      }),
    },
  };
}

const RETRY_SUGGESTIONS = [
  { kind: "github_issue", text: "Retry dengan exponential backoff untuk 503", link: "https://github.com/example/issue/1" },
  { kind: "stackoverflow", text: "Menangani 503 transien di client HTTP", link: "https://stackoverflow.com/q/1" },
];

/** Skenario 1: 503 dua kali lalu BERHASIL -> harus tampil RETRY, bukan GAGAL. */
const LOGS_RETRY_THEN_OK = [
  { node_id: "trigger-1", status: "completed", payload: { summary: "dipicu" } },
  retryRow(1, "server_5xx", "HTTP 503 Service Unavailable dari provider", 1000, RETRY_SUGGESTIONS),
  retryRow(2, "server_5xx", "HTTP 503 Service Unavailable dari provider", 2000, RETRY_SUGGESTIONS),
  { node_id: "mcp-1", status: "completed", payload: { summary: "Berhasil setelah 2 percobaan" } },
];

/** Skenario 2: 429 terus-menerus -> escalate dengan saran. */
const LOGS_ESCALATE = [
  { node_id: "trigger-1", status: "completed", payload: { summary: "dipicu" } },
  ...[1, 2, 3, 4, 5].map((n) => retryRow(n, "rate_limit", "HTTP 429 Too Many Requests", 1000 * 2 ** (n - 1))),
  {
    node_id: "mcp-1",
    status: "error",
    payload: {
      healing: healing({
        action: "escalate", attempt: 5, max_attempts: 5, category: "rate_limit",
        reason: "Menyerah setelah 5 percobaan: rate limit tidak pulih",
        provider: "openai", delay_ms: 0, search_hits: 2,
        suggestions: [
          { kind: "forum", text: "Periksa kuota dan billing di dashboard provider" },
          { kind: "github_issue", text: "Diskusi: 429 tidak pernah pulih setelah 5 retry", link: "https://github.com/example/issue/2" },
        ],
      }),
    },
  },
];

/** Skenario 3: kredensial rusak -> gagal-cepat, tanpa retry, dengan saran. */
const LOGS_CREDENTIAL = [
  { node_id: "trigger-1", status: "completed", payload: { summary: "dipicu" } },
  {
    node_id: "mcp-1",
    status: "error",
    payload: {
      healing: healing({
        action: "credential", attempt: 1, max_attempts: 5, category: "auth",
        reason: "OAuth gagal: invalid_grant (token kedaluwarsa)",
        provider: "anthropic", delay_ms: 0, search_hits: 1,
        suggestions: [{ kind: "fix", text: "Hubungkan ulang provider di halaman Integrations" }],
      }),
    },
  },
];

function supabaseRef(): string {
  for (const f of [".env.local", ".env"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    const m = readFileSync(p, "utf-8").match(/NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/);
    if (m) return m[1];
  }
  return "qmukkphwaajzbqjrcvaz";
}

/**
 * Sesi DUMMY untuk melewati gate login di `/chat`.
 *
 * PENTING & jujur: ini BUKAN kredensial asli. Semua endpoint backend
 * di-stub `page.route` di spec ini, jadi token ini tidak pernah dikirim
 * ke server mana pun dan tidak memverifikasi apa pun terhadap Supabase.
 * Yang ia lakukan hanya memenuhi pemeriksaan sisi-klien ("apakah ada
 * sesi di localStorage") supaya alur render bisa diuji tanpa akun.
 *
 * Expiry sengaja di masa depan. `exp` asli membuat `getSession()` mengembalikan
 * null dan aplikasi kembali menampilkan "Silakan masuk dulu" -- persis
 * kegagalan run sebelumnya.
 *
 * File ini tidak pernah di-commit bersama kredensial nyata mana pun.
 */
function dummySession() {
  const b64 = (o: unknown) =>
    Buffer.from(JSON.stringify(o)).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const now = Math.floor(Date.now() / 1000);
  return {
    access_token: `${b64({ alg: "HS256", typ: "JWT" })}.${b64({
      sub: "00000000-0000-0000-0000-000000000001",
      aud: "authenticated",
      role: "authenticated",
      exp: now + 60 * 60 * 24 * 365,
      iat: now,
      email: "e2e-screenshot@local.test",
      user_metadata: {},
    })}.local-tests-only`,
    token_type: "bearer",
    expires_in: 60 * 60 * 24 * 365,
    expires_at: now + 60 * 60 * 24 * 365,
    refresh_token: "local-tests-only",
    user: { id: "00000000-0000-0000-0000-000000000001", email: "e2e-screenshot@local.test" },
  };
}

async function seed(page: Page) {
  const real = join(process.cwd(), "_e2e_session.refreshed.json");
  const sess = existsSync(real) ? JSON.parse(readFileSync(real, "utf-8")) : dummySession();
  const key = `sb-${supabaseRef()}-auth-token`;
  const entries: [string, string][] = [
    [LOCALE_KEY, "id"],
    [ONB_KEY, "done"],
    [key, JSON.stringify(sess)],
  ];
  await page.addInitScript((kv: [string, string][]) => {
    for (const [k, v] of kv) {
      try { window.localStorage.setItem(k, v); } catch { /* abaikan */ }
    }
  }, entries);
}

function isApi(req: Request): boolean {
  // PENTING: jangan samakan dengan `E2E_BACKEND_URL` seperti di
  // fase5-ai-surfaces.spec.ts. Bundle produksi meng-inline
  // `NEXT_PUBLIC_API_URL` SAAT BUILD -- saat ini menunjuk ke Railway
  // produksi, bukan 127.0.0.1:8123. Kalau stub hanya mencocokkan port
  // 8123, SEMUA request bocor ke Railway dan chat menampilkan
  // "Gagal mengirim / Koneksi lambat" (persis yang terjadi di run
  // sebelumnya). Di sini backend dib-stub berdasarkan PATH, jadi
  // origin produksi mana pun tetap tertangkap.
  const path = new URL(req.url()).pathname;
  return /^\/(chat|sessions|workflows|executions|preferences|api\/vault)/.test(path);
}

async function stubApi(page: Page, logs: Record<string, unknown>[]) {
  await page.route("**/*", async (route: Route) => {
    const req = route.request();
    if (!isApi(req)) return route.continue();
    const path = new URL(req.url()).pathname;
    const json = (status: number, body: unknown) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/sessions") return json(200, { sessions: [] });
    if (path === "/chat" && req.method() === "POST")
      return json(200, {
        status: "success", reply: "Siap! Saya sudah menyusun workflow-nya untuk Anda.",
        session_id: "sess-stub", meta: { model: "gemma-4-31b-it", latency_ms: 1200, workflow: DRAFT },
      });
    if (path === "/api/vault/save") return json(200, { status: "success" });
    if (path === "/workflows" && req.method() === "POST") return json(200, { workflow: { id: "wf-stub" } });
    if (/^\/workflows\/[^/]+\/execute$/.test(path)) return json(202, { execution_id: "ex-stub" });
    if (path === "/executions/ex-stub")
      return json(200, {
        execution: { status: logs.some((l) => l.status === "error") ? "failed" : "completed" },
        logs,
        report: "Workflow selesai. Rincian per langkah ada di kartu laporan.",
      });
    if (path === "/preferences" && req.method() === "PUT") return json(200, { status: "success", prefs: {} });
    return route.continue();
  });
}

/** Jalankan alur nyata sampai kartu laporan muncul. */
async function runToReport(page: Page) {
  await seed(page);
  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
  await page.getByTestId("composer-input").fill("buat workflow kirim telegram setiap jam 9");
  await page.getByTestId("composer-send").click();
  await expect(page.getByTestId("draft-run-now")).toBeVisible({ timeout: 30000 });
  await page.getByTestId("draft-run-now").click();
  const rcard = page.getByTestId("execution-report-card").last();
  await expect(rcard).toBeVisible({ timeout: 60000 });
  return rcard;
}

/**
 * Buka blok rincian healing.
 *
 * `ExecutionReportCard` adalah accordion SATU-jendela (`openStep` tunggal),
 * jadi tidak semua langkah bisa terbuka bersamaan. Strategi: untuk setiap
 * baris, buka -> cek apakah rincian muncul -> tutup lagi. Mengklik semua
 * tanpa mengecek membuat baris berikutnya MENUTUP baris sebelumnya
 * (itulah penyebab test escalate gagal: baris dengan `id` sama, klik
 * genap menutup semuanya).
 */
async function openHealingDetails(rcard: ReturnType<Page["getByTestId"]>) {
  const steps = rcard.getByTestId("report-step");
  const n = await steps.count();
  let opened = 0;
  for (let i = 0; i < n; i++) {
    await steps.nth(i).click();
    if ((await rcard.getByTestId("healing-detail").count()) > 0) {
      opened += 1;
      await steps.nth(i).click(); // tutup lagi
    }
  }
  return opened;
}

/** Buka rincian pada baris TERAKHIR yang punya healing, lalu biarkan terbuka. */
async function openLastHealing(rcard: ReturnType<Page["getByTestId"]>) {
  const steps = rcard.getByTestId("report-step");
  const n = await steps.count();
  for (let i = n - 1; i >= 0; i--) {
    await steps.nth(i).click();
    if ((await rcard.getByTestId("healing-detail").count()) > 0) return true;
    await steps.nth(i).click();
  }
  return false;
}

test.beforeAll(() => {
  if (!existsSync(SHOTS)) mkdirSync(SHOTS, { recursive: true });
});

test("retry: 503 dua kali lalu sukses tampil RETRY 1/5 dan 2/5", async ({ page }) => {
  test.setTimeout(120000);
  await stubApi(page, LOGS_RETRY_THEN_OK);
  const rcard = await runToReport(page);

  const steps = rcard.getByTestId("report-step");
  const count = await steps.count();
  // trigger + 2 retry + 1 sukses = 4. Kalau `collapse()` menelan retry,
  // ini jadi 2 -- itulah regresi yang dikunci 94a5d1d.
  expect(count).toBe(4);
  console.log(`RETRY_STEPS=${count}`);

  const retrying = rcard.locator('[data-step-status="retrying"]');
  expect(await retrying.count()).toBe(2);
  await expect(retrying.first()).toContainText("RETRY 1/5");
  await expect(retrying.nth(1)).toContainText("RETRY 2/5");
  // Status akhir harus sukses: retry tidak boleh dihitung sebagai gagal.
  await expect(rcard).toHaveAttribute("data-status", "success");
  expect(await rcard.locator('[data-step-status="error"]').count()).toBe(0);

  // Skenario ini punya 2 baris retry (keduanya dengan saran).
  expect(await openHealingDetails(rcard)).toBe(2);
  expect(await openLastHealing(rcard)).toBe(true);
  const detail = rcard.getByTestId("healing-detail").first();
  await expect(detail).toContainText("server_5xx");
  await expect(detail).toContainText("jeda 2000 ms"); // retry ke-2
  // Alasan lengkap tampil sebagai `detail` baris, bukan di blok healing.
  await expect(rcard).toContainText("HTTP 503 Service Unavailable");
  expect(await rcard.getByTestId("healing-suggestions").locator("li").count()).toBe(2);

  await page.screenshot({ path: join(SHOTS, "self-healing-retry.png"), fullPage: true });
  console.log("SHOT=self-healing-retry.png");
});

test("escalate: 5x 429 lalu menyerah, saran dan backoff tampil", async ({ page }) => {
  test.setTimeout(120000);
  await stubApi(page, LOGS_ESCALATE);
  const rcard = await runToReport(page);

  const retrying = rcard.locator('[data-step-status="retrying"]');
  expect(await retrying.count()).toBe(5);
  await expect(retrying.nth(0)).toContainText("RETRY 1/5");
  await expect(retrying.nth(4)).toContainText("RETRY 5/5");
  console.log("ESCALATE_RETRIES=5");

  await expect(rcard).toHaveAttribute("data-status", "partial");
  expect(await rcard.locator('[data-step-status="error"]').count()).toBe(1);

  // 5 baris retry + 1 baris escalate = 6 blok rincian.
  expect(await openHealingDetails(rcard)).toBe(6);
  expect(await openLastHealing(rcard)).toBe(true);
  const last = rcard.getByTestId("healing-detail").first();
  await expect(last).toHaveAttribute("data-healing-action", "escalate");
  // Alasan lengkap tampil sebagai `detail` baris; blok healing berisi
  // kategori / provider / jeda / saran.
  await expect(rcard).toContainText("Menyerah setelah 5 percobaan");
  await expect(last).toContainText("rate_limit");
  const sugg = rcard.getByTestId("healing-suggestions").first();
  expect(await sugg.locator("li").count()).toBe(2);
  console.log(`ESCALATE_SUGGESTIONS=${await sugg.locator("li").count()}`);

  await page.screenshot({ path: join(SHOTS, "self-healing-escalate.png"), fullPage: true });
  console.log("SHOT=self-healing-escalate.png");
});

test("credential: invalid_grant gagal-cepat, tanpa retry, dengan saran", async ({ page }) => {
  test.setTimeout(120000);
  await stubApi(page, LOGS_CREDENTIAL);
  const rcard = await runToReport(page);

  // Tidak ada retry sama sekali untuk kategori auth.
  expect(await rcard.locator('[data-step-status="retrying"]').count()).toBe(0);
  expect(await rcard.locator('[data-step-status="error"]').count()).toBe(1);
  console.log("CREDENTIAL_RETRIES=0");

  expect(await openHealingDetails(rcard)).toBe(1);
  expect(await openLastHealing(rcard)).toBe(true);
  const detail = rcard.getByTestId("healing-detail").first();
  await expect(detail).toHaveAttribute("data-healing-action", "credential");
  await expect(detail).toContainText("anthropic");
  await expect(rcard).toContainText("invalid_grant");
  await expect(rcard.getByTestId("healing-suggestions").first()).toContainText("Integrations");

  await page.screenshot({ path: join(SHOTS, "self-healing-credential.png"), fullPage: true });
  console.log("SHOT=self-healing-credential.png");
});
