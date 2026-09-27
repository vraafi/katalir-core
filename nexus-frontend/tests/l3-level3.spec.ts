import { test, expect, type Page, type APIRequestContext } from "@playwright/test";
import { skipIfBackendDown } from "./helpers/backend";

test.beforeEach(async ({ request }) => {
  await skipIfBackendDown(request);
});
import { existsSync, readFileSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { tmpdir } from "node:os";

/**
 * LEVEL 3 — E2E DI BROWSER NYATA (production build, tanpa mock).
 *
 * KENAPA spec ini ada: sesi sebelumnya melaporkan S1/S2/S3 "PASS" dari skrip
 * probe ad-hoc yang dijalankan terhadap `next dev` yang `.next`-nya sudah
 * rusak karena `npm run build` dijalankan bersamaan. Hasilnya klaim tidak bisa
 * diverifikasi ulang. Spec ini memakai harness repo (build produksi +
 * backend lokal port 8123) sehingga setiap langkah benar-benar diklik di
 * browser dan hasilnya dibaca dari DOM — bukan dari API langsung.
 *
 * Alur yang diuji (satu berkas, berurutan; workers=1):
 *   S1 kredensial ADA   -> AI tanya -> bangun workflow -> auto-run -> report
 *   S2 kredensial HILANG-> AI minta -> form di UI -> user isi -> AI lanjut
 *   S3 token SALAH      -> laporan GAGAL yang jujur (bukan "berhasil")
 */

const SHOTS = process.env.L3_SHOTS || join(tmpdir(), "l3_evidence_v2");
const API_ORIGIN = process.env.E2E_BACKEND_URL || "http://127.0.0.1:8123";
const REPO_ROOT = join(process.cwd(), "..");

function supabaseRef(): string {
  const fromEnv = (process.env.NEXT_PUBLIC_SUPABASE_URL || "").trim();
  const m = fromEnv.match(/https?:\/\/([a-z0-9]+)\.supabase/);
  if (m) return m[1];
  for (const f of [".env.local", ".env"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    const mm = readFileSync(p, "utf-8").match(
      /NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/
    );
    if (mm) return mm[1];
  }
  return "qmukkphwaajzbqjrcvaz";
}

const LS_KEY = `sb-${supabaseRef()}-auth-token`;

type Session = { access_token?: string; user?: { email?: string } };

function loadSession(): Session {
  for (const f of ["_e2e_session.refreshed.json", "_e2e_session.json"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    try {
      const s = JSON.parse(readFileSync(p, "utf-8")) as Session;
      if (s?.access_token) return s;
    } catch {
      /* lanjut */
    }
  }
  throw new Error("sesi E2E tidak ditemukan (jalankan scripts/e2e-auth-setup.mjs)");
}

/** Rahasia Telegram: dibaca dari .env root repo, TIDAK pernah dicetak/di-assert. */
function telegramEnv(): { token: string; chatId: string } {
  const p = join(REPO_ROOT, ".env");
  const txt = existsSync(p) ? readFileSync(p, "utf-8") : "";
  const pick = (k: string) => {
    const m = txt.match(new RegExp(`^${k}\\s*=\\s*(.+)$`, "m"));
    return m ? m[1].trim().replace(/^["']|["']$/g, "") : "";
  };
  return { token: pick("TELEGRAM_BOT_TOKEN"), chatId: pick("TELEGRAM_CHAT_ID") };
}

const BAD_TOKEN = "123456789:TOKEN-PALSU-UNTUK-UJI-S3";

async function seedSession(page: Page, session: Session) {
  await page.addInitScript(
    (kv: { key: string; value: unknown }) => {
      try {
        window.localStorage.setItem(kv.key, JSON.stringify(kv.value));
      } catch {
        /* abaikan */
      }
    },
    { key: LS_KEY, value: session }
  );
  console.log(`LS_KEY=${LS_KEY} EMAIL=${session.user?.email ?? "?"}`);
}

/** Tunggu sampai indikator "berpikir" hilang (balasan benar-benar selesai). */
async function waitIdle(page: Page) {
  await page.waitForFunction(
    () => {
      const el = document.querySelector('[data-testid="msg-list"]');
      return el && el.querySelectorAll(".typing-dot").length === 0;
    },
    null,
    { timeout: 180000 }
  );
  await page.waitForTimeout(1200);
}

async function ask(page: Page, text: string): Promise<string> {
  const input = page.locator('[data-testid="composer-input"]');
  await input.waitFor({ state: "visible", timeout: 30000 });
  await input.fill(text);
  await input.press("Enter");
  await waitIdle(page);
  return (await page.locator('[data-testid="msg-list"]').innerText()).trim();
}

async function clearTelegramCredential(request: APIRequestContext, session: Session) {
  const res = await request.delete(`${API_ORIGIN}/api/vault/telegram`, {
    headers: { Authorization: `Bearer ${session.access_token}` },
  });
  console.log(`VAULT_DELETE_STATUS=${res.status()}`);
  expect(res.ok(), "gagal menghapus kredensial telegram (setup S2/S3)").toBeTruthy();
}

async function saveTelegramCredential(
  request: APIRequestContext,
  session: Session,
  value: string
) {
  const res = await request.post(`${API_ORIGIN}/api/vault/save`, {
    headers: { Authorization: `Bearer ${session.access_token}` },
    data: { provider: "telegram", api_key: value },
  });
  console.log(`VAULT_SAVE_STATUS=${res.status()}`);
  expect(res.ok(), "gagal menyimpan kredensial telegram (setup S1)").toBeTruthy();
}

test.beforeAll(() => {
  mkdirSync(SHOTS, { recursive: true });
  console.log(`SHOTS_DIR=${SHOTS} API_ORIGIN=${API_ORIGIN}`);
});



// ---------------------------------------------------------------------------
// S1 — kredensial ADA: AI tanya -> bangun workflow -> auto-run -> report
// ---------------------------------------------------------------------------
test("S1 chat -> AI tanya detail -> build workflow -> Telegram terkirim + report", async ({
  page,
  request,
}) => {
  test.setTimeout(300000);
  const session = loadSession();
  const { token, chatId } = telegramEnv();
  expect(token, "TELEGRAM_BOT_TOKEN tidak ada di .env").toBeTruthy();
  expect(chatId, "TELEGRAM_CHAT_ID tidak ada di .env").toBeTruthy();
  await saveTelegramCredential(request, session, token);
  await seedSession(page, session);

  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text().slice(0, 160));
  });

  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-testid="composer-input"]')).toBeVisible();

  // Langkah 1: permintaan samar -> AI HARUS bertanya dulu.
  const turn1 = await ask(page, "bikin workflow kirim pesan telegram tiap jam 9 pagi");
  await page.screenshot({ path: join(SHOTS, "s1_1_ai_bertanya.png") });
  const asked = /\?/.test(turn1) || /berapa|apa|mana|jam/i.test(turn1);
  console.log(`S1_TURN1_ASKED=${asked}`);
  expect(asked, `AI tidak bertanya, balasannya: ${turn1.slice(-200)}`).toBeTruthy();

  // Langkah 2: detail diberikan -> draf dibuat + dijalankan otomatis.
  const turn2 = await ask(
    page,
    `langsung buat saja: kirim ke chat ${chatId}, pesan 'Laporan harian Katalir S1'`
  );
  await expect(page.locator('[data-testid="ai-workflow-notice"]')).toBeVisible({
    timeout: 30000,
  });
  await page.screenshot({ path: join(SHOTS, "s1_2_workflow_dibuat.png") });

  // Laporan auto-run muncul SETELAH balasan chat selesai (eksekusi berjalan di
  // latar), jadi harus DITUNGGU — membaca sekali (innerText) adalah race yang
  // nyata: elemen sudah ada tetapi isinya belum sempat dirender.
  const reportEl = page.locator('[data-testid="run-report"]').last();
  await expect(reportEl).toContainText(/Workflow (berhasil|berhenti)/, { timeout: 90000 });
  const report = (await reportEl.textContent()) ?? "";
  const full = (await page.locator('[data-testid="msg-list"]').textContent()) ?? "";
  await page.screenshot({ path: join(SHOTS, "s1_3_report.png") });

  console.log(`S1_TURN2_TAIL=${turn2.slice(-160).replace(/\s+/g, " ")}`);
  console.log(`S1_REPORT=${report.replace(/\s+/g, " ")}`);

  expect(report, "report tidak mengaku sukses").toMatch(/Workflow berhasil/);
  expect(full, "bukti Telegram tidak muncul").toMatch(/Pesan Telegram terkirim/i);
  // Guard: UI tidak boleh melempar runtime error (build produksi).
  expect(errors.filter((e) => /__webpack_modules__|is not a function/.test(e))).toHaveLength(0);
});




// ---------------------------------------------------------------------------
// S2 — kredensial HILANG: AI minta -> user isi di UI -> AI lanjut
// ---------------------------------------------------------------------------
test("S2 kredensial hilang -> form muncul -> isi di UI -> AI lanjut kirim", async ({
  page,
  request,
}) => {
  test.setTimeout(300000);
  const session = loadSession();
  const { token, chatId } = telegramEnv();
  await clearTelegramCredential(request, session);
  await seedSession(page, session);

  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-testid="composer-input"]')).toBeVisible();

  await ask(
    page,
    `pakai tool kirim_telegram_message sekarang: kirim pesan ke chat ${chatId} ` +
      `berisi "Uji S2 Katalir Level 3". Jangan buat workflow, langsung kirim.`
  );

  // Kartu form kredensial HARUS terlihat di UI.
  const credInput = page.locator('[aria-label="Token / API key"]');
  await expect(credInput).toBeVisible({ timeout: 60000 });
  await page.screenshot({ path: join(SHOTS, "s2_1_form_kredensial.png") });

  // User mengisi token di UI (bukan via API).
  await credInput.fill(token);
  await page.getByRole("button", { name: /Simpan & Lanjutkan/ }).click();
  await page.waitForTimeout(3000);
  await waitIdle(page);
  await page.screenshot({ path: join(SHOTS, "s2_2_terkirim.png") });

  const full = (await page.locator('[data-testid="msg-list"]').innerText()).trim();
  console.log(`S2_TAIL=${full.slice(-220).replace(/\s+/g, " ")}`);
  expect(full, "AI tidak melanjutkan pengiriman setelah kredensial diisi").toMatch(
    /(terkirim|berhasil mengirim|berhasil dikirim)/i
  );
});

// ---------------------------------------------------------------------------
// S3 — token SALAH: laporan gagal yang jujur, bukan klaim sukses
// ---------------------------------------------------------------------------
test("S3 token salah -> laporan GAGAL jujur (bukan 'berhasil')", async ({
  page,
  request,
}) => {
  test.setTimeout(300000);
  const session = loadSession();
  const { chatId } = telegramEnv();
  await clearTelegramCredential(request, session);
  await seedSession(page, session);

  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-testid="composer-input"]')).toBeVisible();

  await ask(
    page,
    `pakai tool kirim_telegram_message sekarang: kirim pesan ke chat ${chatId} ` +
      `berisi "Uji S3 Katalir Level 3". Jangan buat workflow, langsung kirim.`
  );

  const credInput = page.locator('[aria-label="Token / API key"]');
  await expect(credInput).toBeVisible({ timeout: 60000 });
  await credInput.fill(BAD_TOKEN);
  await page.getByRole("button", { name: /Simpan & Lanjutkan/ }).click();
  await page.waitForTimeout(3000);
  await waitIdle(page);
  await page.screenshot({ path: join(SHOTS, "s3_gagal_jujur.png") });

  const full = (await page.locator('[data-testid="msg-list"]').innerText()).trim();
  console.log(`S3_TAIL=${full.slice(-260).replace(/\s+/g, " ")}`);
  expect(full, "kegagalan provider tidak dijelaskan").toMatch(/401|tidak valid|gagal/i);
  expect(full, "klaim sukses muncul untuk token yang salah").not.toMatch(
    /berhasil dikirim|Pesan Telegram terkirim/i
  );
});
