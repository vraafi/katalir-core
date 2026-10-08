import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/**
 * /templates di PRODUKSI dengan backend NYATA (tanpa `page.route`).
 *
 * Ini pasangan dari `templates-gallery.spec.ts`: di sana seluruh endpoint
 * /templates di-stub supaya tes deterministik; di sini TIDAK ada stub sama
 * sekali — halaman harus benar-benar memuat 10 template bawaan dari backend
 * Railway memakai JWT Supabase asli. Kalau wiring frontend↔backend putus
 * (URL API salah, CORS, token tidak terkirim), hanya tes ini yang menangkapnya.
 *
 * Sesi diambil dari fixture `_e2e_session.refreshed.json` dan disuntikkan ke
 * localStorage dengan kunci default Supabase (`sb-<project-ref>-auth-token`),
 * lalu di-refresh lebih dulu bila sudah kedaluwarsa.
 */
const BASE = (process.env.E2E_BASE || "https://katalir.de5.net").replace(/\/$/, "");
const ROOT = path.resolve(__dirname, "..");
const FIXTURE = path.join(ROOT, "_e2e_session.refreshed.json");
const SHOTS = "../docs/marketing/screenshots/templates-gallery";

function readEnv(file: string): Record<string, string> {
  const out: Record<string, string> = {};
  if (!fs.existsSync(file)) return out;
  for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
    const t = line.trim();
    if (!t || t.startsWith("#") || !t.includes("=")) continue;
    const i = t.indexOf("=");
    out[t.slice(0, i).trim()] = t.slice(i + 1).trim().replace(/^["']|["']$/g, "");
  }
  return out;
}

const ENV = readEnv(path.join(ROOT, "..", ".env"));
const SB_URL = (ENV.SUPABASE_URL || "").replace(/\/$/, "");
const SB_KEY = (ENV.SUPABASE_PUBLISHABLE_KEY || ENV.SUPABASE_KEY || "").trim();
const PROJECT_REF = SB_URL.split("//")[1]?.split(".")[0] || "";
const STORAGE_KEY = `sb-${PROJECT_REF}-auth-token`;

async function freshSession(): Promise<Record<string, unknown>> {
  const sess = JSON.parse(fs.readFileSync(FIXTURE, "utf8"));
  const exp = Number(sess.expires_at || 0);
  if (exp > Date.now() / 1000 + 120) return sess;
  const r = await fetch(`${SB_URL}/auth/v1/token?grant_type=refresh_token`, {
    method: "POST",
    headers: { "Content-Type": "application/json", apikey: SB_KEY },
    body: JSON.stringify({ refresh_token: sess.refresh_token }),
  });
  if (!r.ok) throw new Error(`refresh gagal: ${r.status} ${(await r.text()).slice(0, 160)}`);
  const d = await r.json();
  const merged = { ...sess, ...d };
  fs.writeFileSync(FIXTURE, JSON.stringify(merged, null, 2));
  return merged;
}

test.describe("/templates PRODUKSI (backend nyata)", () => {
  test("memuat 10 template bawaan dari backend Railway tanpa stub", async ({ page }) => {
    const sess = await freshSession();
    console.log(`PROD_LIVE storageKey=${STORAGE_KEY} user=${sess.user?.email}`);

    await page.addInitScript(
      ([k, v]) => window.localStorage.setItem(k, v),
      [STORAGE_KEY, JSON.stringify(sess)] as const,
    );

    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));

    await page.goto(`${BASE}/templates`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });

    // Bukti sesi benar-benar terpakai: logo mengarah ke /chat untuk user login.
    await page.waitForTimeout(3000);
    const logoHref = await page.locator('[data-testid="account-logo"]').getAttribute("href");
    console.log(`PROD_LIVE account-logo href=${logoHref}`);
    expect(logoHref, "sesi tidak terpakai — sisa asersi tidak valid").toBe("/chat");

    const grid = page.locator('[data-testid="template-grid"]');
    await expect(grid, "grid tidak muncul: wiring API/CORS/token bermasalah").toBeVisible({
      timeout: 60_000,
    });

    const cards = page.locator('[data-testid="template-card"]');
    const n = await cards.count();
    console.log(`PROD_LIVE jumlah kartu = ${n}`);
    expect(n, "template bawaan dari backend produksi tidak termuat").toBeGreaterThanOrEqual(10);

    // Isi harus benar-benar dari backend: nama template bawaan yang dikenal.
    const names = await cards.locator("h3").allInnerTexts();
    console.log(`PROD_LIVE nama: ${JSON.stringify(names.slice(0, 5))}`);
    expect(names.join(" | ")).toContain("RSS → Slack");

    // Badge "Kustom" hanya muncul bila ada template kustom milik user.
    const custom = await page.locator('[data-testid="template-badge-custom"]').count();
    console.log(`PROD_LIVE kartu kustom = ${custom}`);

    await page.screenshot({ path: `${SHOTS}/13-live-prod.png`, fullPage: true });

    // Buka pratinjau salah satu template nyata -> node dari backend.
    await page
      .locator('[data-template-id="tpl-rss-ke-slack"]')
      .locator('[data-testid="template-preview-btn"]')
      .click();
    await expect(page.locator('[data-testid="template-preview"]')).toBeVisible({ timeout: 20_000 });
    const nodeCount = await page.locator('[data-testid="preview-node"]').count();
    console.log(`PROD_LIVE node di pratinjau = ${nodeCount}`);
    expect(nodeCount).toBeGreaterThanOrEqual(3);
    await page.screenshot({ path: `${SHOTS}/14-live-preview.png` });

    expect(errors, `pageerror: ${JSON.stringify(errors)}`).toHaveLength(0);
  });
});
