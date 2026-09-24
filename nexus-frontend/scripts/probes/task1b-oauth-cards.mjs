/**
 * scripts/probes/task1b-oauth-cards.mjs — BUKTI screenshot Task 1B + Task 1C.
 *
 * YANG DIAMBIL:
 *   1. `/settings` desktop + mobile, keadaan NYATA (belum terhubung);
 *   2. `/settings` desktop + mobile, keadaan TERHUBUNG (respons status di-mock,
 *      karena klik consent asli butuh akun Google/Slack milik user —
 *      NEEDS_USER_ACTION). Mock HANYA pada respons `/oauth/*​/status`; halaman,
 *      tombol, dan render tetap kode nyata;
 *   3. chat: bubble dengan tombol Connect (needs_oauth) — respons `/chat`
 *      di-mock supaya tidak perlu kuota LLM dan tidak bergantung pada model.
 *
 * ANTI-BLIND: setiap langkah mencetak angka/teks yang dibaca dari DOM dan
 * GAGAL (exit 1) bila elemennya tidak ada — bukan sekadar menyimpan gambar.
 *
 * Pakai: node scripts/probes/task1b-oauth-cards.mjs  (dev FE harus hidup di :3000)
 */
import { chromium } from "@playwright/test";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const ROOT = process.cwd();
const PORT = Number(process.env.E2E_PORT || 3000);
const BASE = `http://localhost:${PORT}`;
const SHOTS = process.env.SHOTS || join(ROOT, "test-results", "task1b-oauth");

/** Ref Supabase untuk nama kunci localStorage `sb-<ref>-auth-token`. */
function supabaseRef() {
  for (const f of [".env.local", ".env", "../.env"]) {
    const p = join(ROOT, f);
    if (!existsSync(p)) continue;
    const m = readFileSync(p, "utf-8").match(
      /NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/
    );
    if (m) return m[1];
  }
  return "qmukkphwaajzbqjrcvaz";
}

const LS_KEY = `sb-${supabaseRef()}-auth-token`;
const session = JSON.parse(
  readFileSync(join(ROOT, "_e2e_session.refreshed.json"), "utf-8")
);

const problems = [];
function check(ok, label, detail = "") {
  console.log(`${ok ? "OK  " : "FAIL"} ${label}${detail ? ` :: ${detail}` : ""}`);
  if (!ok) problems.push(label);
}

const CONNECTED_STATUS = {
  google: {
    status: "success",
    configured: true,
    google_sheets: { connected: true, provider: "google_sheets", has_refresh_token: true, expires_in_s: 3400 },
  },
  slack: {
    status: "success",
    configured: true,
    implemented: true,
    connected: true,
    team_name: "Katalir Workspace",
    keys_present: 5,
    keys_total: 5,
    slack: { connected: true, provider: "slack", team_name: "Katalir Workspace", has_bot_token: true },
  },
};

async function newPage(browser, { viewport, mockConnected = false }) {
  const context = await browser.newContext({ viewport });
  await context.addInitScript(
    (kv) => {
      try {
        window.localStorage.setItem(kv.key, JSON.stringify(kv.value));
      } catch {
        /* abaikan */
      }
    },
    { key: LS_KEY, value: session }
  );
  if (mockConnected) {
    await context.route("**/oauth/google/status*", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(CONNECTED_STATUS.google) })
    );
    await context.route("**/oauth/slack/status*", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(CONNECTED_STATUS.slack) })
    );
  }
  const page = await context.newPage();
  return { context, page };
}


async function assertCards(page, connected) {
  const google = page.getByText(/Google Sheets/i).first();
  const slack = page.getByText(/Slack/i).first();
  await google.waitFor({ state: "visible" });
  await slack.waitFor({ state: "visible" });
  const connectCount = await page.getByRole("button", { name: /Connect/i }).count();
  const disconnectCount = await page.getByRole("button", { name: /Disconnect/i }).count();
  check(connected ? disconnectCount >= 2 : connectCount >= 2,
        connected ? "settings connected buttons" : "settings connect buttons",
        `connect=${connectCount} disconnect=${disconnectCount}`);
  check(connected ? await page.getByText(/Connected/i).count() >= 2 : connectCount >= 2,
        connected ? "connected badges" : "disconnected state");
  await page.screenshot({ path: join(SHOTS, `settings-${connected ? "connected" : "disconnected"}-${page.viewportSize().width}.png`), fullPage: true });
}

async function assertNeedsOauth(page) {
  const connect = page.getByRole("button", { name: /Connect/i }).first();
  await connect.waitFor({ state: "visible" });
  check(await connect.isVisible(), "chat needs_oauth Connect button");
  await page.screenshot({ path: join(SHOTS, `chat-needs-oauth-${page.viewportSize().width}.png`), fullPage: true });
}

async function main() {
  mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      const a = await newPage(browser, { viewport });
      await a.page.goto(`${BASE}/settings`, { waitUntil: "networkidle" });
      await assertCards(a.page, false);
      await a.context.close();
    }
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      const a = await newPage(browser, { viewport, mockConnected: true });
      await a.page.goto(`${BASE}/settings`, { waitUntil: "networkidle" });
      await assertCards(a.page, true);
      await a.context.close();
    }
    const a = await newPage(browser, { viewport: { width: 1440, height: 900 } });
    await a.page.route("**/chat", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "needs_oauth", provider: "slack", message: "Slack belum terhubung.", connect_url: "/oauth/slack/authorize" }) }));
    await a.page.goto(`${BASE}/chat`, { waitUntil: "networkidle" });
    await assertNeedsOauth(a.page);
    await a.context.close();
  } finally {
    await browser.close();
  }
  if (problems.length) throw new Error(`Screenshot probe gagal: ${problems.join(", ")}`);
  console.log(`SCREENSHOT_DIR=${SHOTS}`);
}

main().catch(err => { console.error(err); process.exitCode = 1; });

