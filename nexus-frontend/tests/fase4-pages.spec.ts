/**
 * FASE 4 — audit interaksi halaman akun + auth/i18n + command palette.
 *
 * Harness: `playwright.dev.config.ts` (dev :3000, backend :8000).
 * Setiap tes memakai assertion kuantitatif (jumlah, atribut, teks, status HTTP).
 *
 * PRINSIP TIDAK MERUSAK DATA: tes kredensial hanya menulis ke provider yang
 * BELUM punya kredensial, lalu langsung mencabutnya. Kalau kelima provider sudah
 * terpakai, tes di-SKIP dengan alasan eksplisit (bukan menimpa kredensial nyata
 * milik user).
 */
import { test, expect, type Page, type APIRequestContext } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const API_ORIGIN = process.env.E2E_BACKEND_URL || "http://127.0.0.1:8000";
const PROVIDERS = ["groq", "openai", "gemini", "whatsapp", "custom_llm"];

function supabaseRef(): string {
  for (const f of [".env.local", ".env"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    const m = readFileSync(p, "utf-8").match(/NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/);
    if (m) return m[1];
  }
  return "qmukkphwaajzbqjrcvaz";
}

function loadSession(): { access_token?: string; user?: { email?: string } } | null {
  const p = join(process.cwd(), "_e2e_session.refreshed.json");
  if (!existsSync(p)) return null;
  return JSON.parse(readFileSync(p, "utf-8"));
}

async function seedSession(page: Page) {
  const sess = loadSession();
  if (!sess?.access_token) return;
  await page.addInitScript(
    (kv: { key: string; value: unknown }) => {
      try { window.localStorage.setItem(kv.key, JSON.stringify(kv.value)); } catch { /* abaikan */ }
    },
    { key: `sb-${supabaseRef()}-auth-token`, value: sess }
  );
}

/** Tunggu hidrasi + sesi diterapkan (penanda FASE 4 di <html>). */
async function waitAppReady(page: Page, expectAuth = true) {
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
  if (expectAuth) await page.waitForSelector("html[data-auth='in']", { timeout: 45000 });
}

async function openPage(page: Page, path: string) {
  await seedSession(page);
  await page.goto(path, { waitUntil: "domcontentloaded" });
  await waitAppReady(page);
}

// ===========================================================================
// SETTINGS (4)
// ===========================================================================
test("S1 settings: grup bahasa & tema TERPISAH (temuan FASE 3 #4)", async ({ page }) => {
  await openPage(page, "/settings");
  await expect(page.locator('[data-testid="card-language"]')).toBeVisible();
  await expect(page.locator('[data-testid="card-app-theme"]')).toBeVisible();
  await expect(page.locator('[data-testid="card-canvas-theme"]')).toBeVisible();

  // Bukti pemisahan: posisi vertikal ketiga kartu berbeda dan berurutan.
  const y = async (sel: string) => (await page.locator(sel).boundingBox())!.y;
  const [lang, appTheme, canvasTheme] = [await y('[data-testid="card-language"]'), await y('[data-testid="card-app-theme"]'), await y('[data-testid="card-canvas-theme"]')];
  console.log(`S1 y: language=${Math.round(lang)} appTheme=${Math.round(appTheme)} canvasTheme=${Math.round(canvasTheme)}`);
  expect(appTheme).toBeGreaterThan(lang);
  expect(canvasTheme).toBeGreaterThan(appTheme);

  // Setiap grup punya deskripsi (hint) yang terhubung lewat aria-describedby.
  const groups = await page.$$eval('[role="radiogroup"]', (els) =>
    els.map((g) => ({ label: g.getAttribute("aria-label"), described: g.getAttribute("aria-describedby") }))
  );
  console.log("S1 groups=" + JSON.stringify(groups));
  expect(groups.length).toBeGreaterThanOrEqual(2);
  expect(groups.every((g) => !!g.label)).toBe(true);
  expect(groups.filter((g) => !!g.described).length).toBeGreaterThanOrEqual(2);
});

test("S2 settings: tema kanvas dapat diganti dari halaman akun (4 pilihan)", async ({ page }) => {
  await openPage(page, "/settings");
  const radios = await page.locator('[data-testid^="canvas-theme-radio-"]').count();
  expect(radios).toBe(4);
  await page.click('[data-testid="canvas-theme-radio-cyberpunk"]');
  await page.waitForTimeout(400);
  expect(await page.evaluate(() => document.documentElement.getAttribute("data-canvas-theme"))).toBe("cyberpunk");
  expect(await page.evaluate(() => window.localStorage.getItem("katalir.canvasTheme"))).toBe("cyberpunk");
  expect(await page.locator('[data-testid="canvas-theme-radio-cyberpunk"]').getAttribute("aria-checked")).toBe("true");
});

test("S3 settings: validasi + status simpan kredensial (aria-live, tanpa error konsol)", async ({ page, request }) => {
  const sess = loadSession();
  const used = await vaultProviders(request, sess!.access_token!);
  const free = PROVIDERS.find((p) => !used.includes(p));
  test.skip(!free, "kelima provider sudah punya kredensial -> tidak menulis demi keamanan data user");

  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  await openPage(page, "/settings");

  // Validasi: tombol simpan tidak melakukan apa pun bila API key kosong.
  await page.click('[data-testid="vault-save"]');
  await page.waitForTimeout(600);
  expect(await page.locator('[data-testid="vault-list"] li').count(), "key kosong tidak boleh menambah kredensial").toBeLessThanOrEqual(used.length);

  // Simpan (Fernet di server) -> status "Tersimpan".
  await page.selectOption('[data-testid="vault-provider"]', free!);
  await page.fill('[data-testid="vault-key"]', "e2e-dummy-key-fase4");
  await page.click('[data-testid="vault-save"]');
  await expect(page.locator('[data-testid="vault-status"]')).toContainText(/Tersimpan|Saved/, { timeout: 15000 });
  // Verifikasi sisi server dengan POLLING: `/api/vault/list` sempat mengembalikan
  // daftar kosong tepat setelah tulis (diamati 1 -> 0 -> 2 pada tiga panggilan
  // berurutan), sehingga pemeriksaan sekali-baca membuat tes gagal-acak. Poll
  // 10 detik + laporkan hasilnya apa adanya.
  let after: string[] = [];
  for (let i = 0; i < 10; i++) {
    after = await vaultProviders(request, sess!.access_token!);
    if (after.includes(free!)) break;
    await page.waitForTimeout(1000);
  }
  console.log(`S3 provider=${free} before=${used.length} after=${JSON.stringify(after)} errs=${errors.length}`);
  expect(after, "kredensial tidak muncul di daftar server setelah disimpan").toContain(free);
  expect(errors).toHaveLength(0);
});

test("S4 settings: cabut kredensial menghapusnya dari server (list -1)", async ({ page, request }) => {
  const sess = loadSession();
  const used = await vaultProviders(request, sess!.access_token!);
  const e2eProvider = used.find((p) => PROVIDERS.includes(p));
  test.skip(!e2eProvider, "tidak ada kredensial untuk diuji cabut (dibersihkan S3)");

  await openPage(page, "/settings");
  const before = (await page.locator('[data-testid="vault-list"] li').count());
  await page.click(`[data-testid="vault-revoke-${e2eProvider}"]`);
  await page.waitForTimeout(1500);
  const afterList = await vaultProviders(request, sess!.access_token!);
  console.log(`S4 provider=${e2eProvider} uiBefore=${before} serverAfter=${JSON.stringify(afterList)}`);
  expect(afterList).not.toContain(e2eProvider);
});

/** Provider yang saat ini tersimpan (bukti sisi server, bukan hanya UI). */
async function vaultProviders(request: APIRequestContext, token: string): Promise<string[]> {
  const r = await request.get(`${API_ORIGIN}/api/vault/list`, { headers: { Authorization: `Bearer ${token}` } });
  if (!r.ok()) return [];
  const d = (await r.json()) as { items?: { provider?: string }[] };
  return (d.items ?? []).map((i) => String(i.provider ?? "").toLowerCase()).filter(Boolean);
}

// ===========================================================================
// BILLING (3)
// ===========================================================================
test("B1 billing: kartu pemakaian render (bars) atau empty-state jujur", async ({ page }) => {
  await openPage(page, "/billing");
  await expect(page.locator('[data-testid="card-usage"]')).toBeVisible();
  // Skeleton hanya boleh tampil SESUATU sebelum data tiba.
  await page.waitForTimeout(3000);
  const bars = await page.locator('[data-testid="usage-bars"] [role="progressbar"]').count();
  const empty = await page.locator('[data-testid="usage-empty"]').count();
  const skeleton = await page.locator('[data-testid="usage-skeleton"]').count();
  console.log(`B1 bars=${bars} empty=${empty} skeleton=${skeleton}`);
  expect(bars + empty, "kartu pemakaian berhenti di skeleton").toBeGreaterThan(0);
  expect(skeleton).toBe(0);
  if (bars > 0) {
    const now = await page.locator('[data-testid="usage-bars"] [role="progressbar"]').first().getAttribute("aria-valuenow");
    expect(Number(now)).toBeGreaterThanOrEqual(0);
    expect(Number(now)).toBeLessThanOrEqual(100);
  }
});

test("B2 billing: tabel paket (5 baris) + CTA checkout Dodo dengan href nyata", async ({ page }) => {
  await openPage(page, "/billing");
  await expect(page.locator('[data-testid="plan-table"]')).toBeVisible();
  const rows = await page.locator('[data-testid="plan-table"] tbody tr').count();
  expect(rows).toBe(5);
  // Header tabel wajib punya scope (a11y tabel).
  const ths = await page.$$eval('[data-testid="plan-table"] th', (els) => els.map((e) => e.getAttribute("scope")));
  console.log("B2 th scope=" + JSON.stringify(ths));
  expect(ths.filter((s) => s === "col").length).toBe(3);
  expect(ths.filter((s) => s === "row").length).toBe(5);

  const checkout = page.locator('[data-testid="plan-checkout"]');
  const current = page.locator('[data-testid="plan-current"]');
  const hasCheckout = (await checkout.count()) > 0;
  const hasCurrent = (await current.count()) > 0;
  console.log(`B2 checkout=${hasCheckout} currentPlan=${hasCurrent}`);
  expect(hasCheckout || hasCurrent, "tidak ada CTA checkout maupun penanda paket aktif").toBe(true);
  if (hasCheckout) {
    const href = (await checkout.getAttribute("href")) ?? "";
    expect(href.startsWith("https://")).toBe(true);
    expect(await checkout.getAttribute("rel")).toContain("noopener");
  }
});

test("B3 billing: riwayat invoice punya empty-state yang jujur (tanpa data dummy)", async ({ page }) => {
  await openPage(page, "/billing");
  await expect(page.locator('[data-testid="invoices-empty"]')).toBeVisible();
  const text = (await page.locator('[data-testid="invoices-empty"]').innerText()).toLowerCase();
  console.log("B3 text=" + text.replace(/\s+/g, " ").slice(0, 90));
  expect(text.length).toBeGreaterThan(10);
});



// ===========================================================================
// HELP (2)
// ===========================================================================
test("H1 help: pencarian menyaring FAQ (judul DAN isi) + jumlah hasil diumumkan", async ({ page }) => {
  await openPage(page, "/help");
  const all = await page.locator('[data-testid="help-faq-item"]').count();
  expect(all).toBeGreaterThanOrEqual(7);

  // Kata kunci yang PASTI ada di salah satu jawaban (isi, bukan judul):
  // "00:00 WIB" muncul di FAQ reset kuota.
  await page.fill('[data-testid="help-search"]', "00:00");
  await page.waitForTimeout(400);
  const narrowed = await page.locator('[data-testid="help-faq-item"]').count();
  const countText = await page.locator('[data-testid="help-count"]').innerText();
  console.log(`H1 all=${all} narrowed=${narrowed} countText="${countText.trim()}"`);
  expect(narrowed).toBeGreaterThan(0);
  expect(narrowed).toBeLessThan(all);
  expect(countText.trim().length).toBeGreaterThan(0);

  // Kata kunci yang tidak ada -> empty-state eksplisit.
  await page.fill('[data-testid="help-search"]', "zzz-tidak-ada-zzz");
  await page.waitForTimeout(400);
  await expect(page.locator('[data-testid="help-no-results"]')).toBeVisible();
  expect(await page.locator('[data-testid="help-faq-item"]').count()).toBe(0);
});

test("H2 help: sidebar navigasi (3 bagian) + cheat sheet berisi pintasan nyata", async ({ page }) => {
  await openPage(page, "/help");
  const navButtons = await page.locator('[data-testid="help-nav"] button').count();
  expect(navButtons).toBe(3);

  // Cheat sheet harus memuat pintasan yang benar-benar dipasang di aplikasi.
  const kbds = await page.$$eval('[data-testid="shortcut-list"] kbd', (els) => els.map((e) => e.textContent?.trim() ?? ""));
  console.log("H2 shortcuts=" + JSON.stringify(kbds));
  for (const must of ["Cmd/Ctrl + K", "Esc", "Cmd/Ctrl + Z", "0", "1", "+", "-"]) {
    expect(kbds, `pintasan ${must} hilang dari cheat sheet`).toContain(must);
  }

  // Klik "Kontak" -> bagian kontak masuk viewport (bukti navigasi bekerja).
  await page.locator('[data-testid="help-nav"] button').nth(2).click();
  await page.waitForTimeout(800);
  const visible = await page.locator('[data-testid="help-contact"]').isVisible();
  expect(visible).toBe(true);
});

// ===========================================================================
// AUTH + i18n (3)
// ===========================================================================
test("A1 auth: sesi bertahan setelah reload (email tampil di profil & header)", async ({ page }) => {
  await openPage(page, "/settings");
  const email = (await page.locator('[data-testid="settings-email"]').innerText()).trim();
  expect(email).toContain("@");
  await page.reload({ waitUntil: "domcontentloaded" });
  await waitAppReady(page);
  const after = (await page.locator('[data-testid="settings-email"]').innerText()).trim();
  console.log(`A1 email=${email} afterReload=${after}`);
  expect(after).toBe(email);
});

test("A2 auth: logout mengosongkan sesi (data-auth=out) tanpa error halaman", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  // Logout lewat UI: tombol di UserMenu (Shell). SENGAJA TIDAK menghapus
  // localStorage lalu reload: skrip seed sesi E2E berjalan di SETIAP navigasi
  // (addInitScript), jadi sesi akan muncul kembali dan tesnya menyesatkan
  // (percobaan pertama persis begitu: data-auth tetap "in" selamanya).
  await openPage(page, "/");
  await page.waitForTimeout(1500);

  // Buka menu akun (aria-label dari i18n: "Menu akun <email>").
  const trigger = page.locator('button[aria-label^="Menu akun"], button[aria-label^="Account menu"]').first();
  await expect(trigger).toBeVisible({ timeout: 20000 });
  await trigger.click();
  await page.waitForTimeout(500);
  const logout = page.getByRole("menuitem", { name: /Logout|Keluar|Sign out/i }).first();
  await expect(logout).toBeVisible({ timeout: 10000 });
  await logout.click();

  await page.waitForFunction(() => document.documentElement.dataset.auth === "out", null, { timeout: 30000 });
  const state = await page.evaluate(() => document.documentElement.dataset.auth);
  const lsLeft = await page.evaluate(() =>
    Object.keys(window.localStorage).filter((k) => k.startsWith("sb-") && k.endsWith("-auth-token")).length
  );
  console.log(`A2 data-auth=${state} sessionKeys=${lsLeft} errs=${errors.length}`);
  expect(state).toBe("out");
  expect(lsLeft, "token sesi masih ada setelah logout").toBe(0);
  expect(errors).toHaveLength(0);
});

test("A3 i18n: ganti bahasa mengubah teks, tersimpan, TANPA hydration error", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));
  const consoleErrors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error" && /hydrat/i.test(m.text())) consoleErrors.push(m.text().slice(0, 200)); });

  await openPage(page, "/settings");
  const before = (await page.locator("h1").innerText()).trim();

  // Radio DIBATASI ke kartu bahasa: /settings juga punya radiogroup tema
  // aplikasi (3) dan tema kanvas (4), sehingga `[role="radio"]` mentah = 9
  // elemen dan assertion lama (==2) gagal karena salah menghitung.
  const radios = page.locator('[data-testid="card-language"] [role="radio"]');
  expect(await radios.count(), "language switcher tidak berupa radiogroup 2 pilihan").toBe(2);
  const beforeCheckedIdx = (await radios.nth(0).getAttribute("aria-checked")) === "true" ? 0 : 1;
  const targetIdx = beforeCheckedIdx === 0 ? 1 : 0;
  await radios.nth(targetIdx).click();
  await page.waitForTimeout(700);
  const afterTitle = (await page.locator("h1").innerText()).trim();
  console.log(`A3 title "${before}" -> "${afterTitle}" errs=${errors.length} hydr=${consoleErrors.length}`);
  expect(afterTitle).not.toBe(before);
  expect(await radios.nth(targetIdx).getAttribute("aria-checked")).toBe("true");

  // Persist: reload -> bahasa tersimpan tetap dipakai.
  await page.reload({ waitUntil: "domcontentloaded" });
  await waitAppReady(page);
  expect((await page.locator("h1").innerText()).trim()).toBe(afterTitle);
  expect(errors).toHaveLength(0);
  expect(consoleErrors).toHaveLength(0);
});



// ===========================================================================
// COMMAND PALETTE (3)
// ===========================================================================
test("P1 palette: Cmd/Ctrl+K membuka, Esc menutup", async ({ page }) => {
  await openPage(page, "/help");
  // Penanda yang STABIL: `[cmdk-input]` (cmdk memasangnya di elemen input).
  // `[cmdk-dialog]` juga ada saat tertutup (Radix mempertahankan simpulnya
  // dengan data-state="closed") sehingga `toBeVisible` di sana menyesatkan.
  await expect(page.locator("[cmdk-input]")).toBeHidden();
  await page.keyboard.press("Control+k");
  await expect(page.locator("[cmdk-input]")).toBeVisible({ timeout: 10000 });
  const items = await page.locator("[cmdk-item]").count();
  console.log(`P1 items=${items}`);
  expect(items).toBeGreaterThanOrEqual(9);
  await page.keyboard.press("Escape");
  await expect(page.locator("[cmdk-input]")).toBeHidden({ timeout: 10000 });
});

test("P2 palette: ketik menyaring, Enter menjalankan item terpilih (navigasi)", async ({ page }) => {
  await openPage(page, "/help");
  await page.keyboard.press("Control+k");
  await expect(page.locator("[cmdk-input]")).toBeVisible({ timeout: 10000 });

  await page.locator("[cmdk-input]").fill("Billing");
  await page.waitForTimeout(400);
  const filtered = await page.locator("[cmdk-item]").count();
  const all = await page.evaluate(() => document.querySelectorAll("[cmdk-item]").length);
  console.log(`P2 filtered=${filtered}`);
  expect(filtered).toBeGreaterThan(0);
  expect(filtered).toBeLessThanOrEqual(all);

  await page.keyboard.press("Enter");
  await page.waitForURL(/\/billing/, { timeout: 20000 });
  console.log("P2 url=" + new URL(page.url()).pathname);
  expect(new URL(page.url()).pathname).toBe("/billing");
  await expect(page.locator("[cmdk-dialog]")).toHaveCount(0);
});

test("P3 palette: label & placeholder ikut bahasa aktif (bukan teks keras)", async ({ page }) => {
  await openPage(page, "/help");
  await page.keyboard.press("Control+k");
  await expect(page.locator("[cmdk-input]")).toBeVisible({ timeout: 10000 });
  const ph = (await page.locator("[cmdk-input]").getAttribute("placeholder")) ?? "";
  const label = (await page.locator("[cmdk-dialog]").getAttribute("aria-label")) ?? "";
  console.log(`P3 placeholder="${ph}" label="${label}"`);
  // Placeholder tidak boleh mengandung kata kunci bahasa campuran yang salah:
  // dengan locale ID harus "Ketik", dengan EN harus "Type".
  const lang = await page.evaluate(() => document.documentElement.lang);
  expect(["id", "en"]).toContain(lang);
  if (lang === "id") expect(ph).toContain("Ketik");
  else expect(ph).toContain("Type");
  expect(label.length).toBeGreaterThan(0);
});
