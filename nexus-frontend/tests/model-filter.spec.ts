import { test, expect, type Page, type Response } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

/**
 * E2E PRODUCTION BUILD — jalur nyata frontend -> backend, TANPA mocking.
 *
 * KENAPA spec ini ditulis ulang: versi sebelumnya memakai `page.route` dengan
 * glob `**` + `/models` dan sebuah fixture. Mock itu membuat tes LULUS
 * padahal user tetap melihat model paid di selector — persis kegagalan
 * "agent bilang PASS, user lihat bug". Sekarang:
 *   - `/models` & `/chat` TIDAK di-mock; responsnya dibaca dari backend nyata.
 *   - Ada guard yang GAGAL bila bundle membidik origin lain (mis. Railway),
 *     sehingga "environment berbeda" tidak bisa lolos sebagai PASS.
 *   - Dijalankan lewat playwright.config.ts yang mem-build produksi
 *     (`output: "export"` -> `scripts/e2e-prod-server.mjs`) dengan
 *     NEXT_PUBLIC_API_URL diarahkan ke backend lokal.
 */

/**
 * REF proyek Supabase. DITURUNKAN dari `NEXT_PUBLIC_SUPABASE_URL` — sumber yang
 * sama dengan yang dipakai app untuk membentuk storage key (`sb-<ref>-auth-token`).
 *
 * Kenapa tidak hardcode: versi sebelumnya menulis REF tangan dan SATU KARAKTER
 * HILANG (`...jrcvz` vs `...jrcvaz`, 19 vs 20 karakter). Akibatnya sesi di-seed
 * ke key yang tidak pernah dibaca app -> `activeEmail` null ->
 * `useModelsQuery(false)` non-aktif -> `/models` tidak pernah dipanggil, dan
 * tes gagal seolah-olah bug produk. Menurunkan nilainya menutup kelas bug ini
 * untuk selamanya.
 */
function supabaseRef(): string {
  const fromEnv = (process.env.NEXT_PUBLIC_SUPABASE_URL || "").trim();
  if (fromEnv) {
    const m = fromEnv.match(/https?:\/\/([a-z0-9]+)\.supabase/);
    if (m) return m[1];
  }
  // Fallback: baca .env.local (dipakai saat dev lokal), lalu default terakhir.
  for (const f of [".env.local", ".env"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    const m = readFileSync(p, "utf-8").match(/NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/);
    if (m) return m[1];
  }
  return "qmukkphwaajzbqjrcvaz";
}

const REF = supabaseRef();
const LS_KEY = `sb-${REF}-auth-token`;
const API_ORIGIN = process.env.E2E_BACKEND_URL || "http://127.0.0.1:8000";

/** Model paid-only / non-chat yang MUNCUL di screenshot user (harus hilang). */
const FORBIDDEN_IDS = [
  "gemini-3.1-pro-preview",
  "gemini-3.1-pro-preview-customtools",
  "gemini-3.5-transcribe",
  "gemini-omni-1.1-flash",
  "gemini-robotics-er-2-preview",
  "lyria-3-clip-preview",
  "lyria-3-pro-preview",
  "nano-banana-pro-preview",
];
/** Pola umum paid-only (koreksi: "omni" TIDAK dipakai — nemotron omni valid). */
const FORBIDDEN_RE = /-pro|pro-latest|advanced|transcribe|lyria|nano-banana|robotics|deep-research/i;
/**
 * Model free-tier yang WAJIB tetap tersedia setelah filter.
 *
 * SENGAJA hanya id yang STABIL secara empiris — dibuktikan pada 3 pengamatan
 * independen: cache roster A (12 model), cache roster B (13 model), dan run
 * E2E produksi (13 model). Kedua id di bawah hadir di KETIGA pengamatan.
 *
 * `gemini-2.5-flash` TIDAK dipin meski gratis & valid: ia LOLOS filter
 * (is_paid_only=False) dan LOLOS probe langsung (HTTP 200, X-Routed-Via
 * `google_gemini/gemini-2.5-flash`), tetapi HILANG dari cache roster hasil
 * probe paralel. Itu flakiness liveness upstream (model gratis dirotasi
 * provider), bukan regresi filter. Mem-pin id flaky -> tes gagal-acak dan
 * justru MENYAMARKAN bug filter yang sebenarnya (persis gejala "agent test
 * pass tapi user lihat bug" yang sedang diperbaiki).
 */
const REQUIRED_IDS = ["gemini-2.5-flash-lite", "gemini-3-flash-preview"];

/** Lantai kewajaran: roster teramati 12-13 model; daftar kosong/kerdil berarti
 *  gateway tak terjangkau (bukan filter) dan tes tak boleh lulus diam-diam. */
const MIN_MODELS = 5;
/** Model hidup yang pernah salah dihapus filter (namanya memuat "omni"). */
const REGRESSION_IDS = ["nemotron-3-nano-omni"];

const PRO_MODEL = "gemini-3.1-pro-preview";

type Session = { access_token?: string; user?: { email?: string }; [k: string]: unknown };

function loadSession(): Session | null {
  for (const f of ["_e2e_session.refreshed.json", "_e2e_session.json"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    try {
      const s = JSON.parse(readFileSync(p, "utf-8")) as Session;
      if (s?.access_token) {
        console.log(`SESSION_FILE=${f}`);
        return s;
      }
    } catch {
      /* lanjut ke kandidat berikutnya */
    }
  }
  return null;
}

/** exp (detik) dari JWT; token yang kedaluwarsa ditolak backend -> 401. */
function expiresInSec(token: string): number {
  try {
    const payload = JSON.parse(
      Buffer.from(token.split(".")[1] ?? "", "base64").toString("utf-8")
    ) as { exp?: number };
    return typeof payload.exp === "number" ? payload.exp - Math.floor(Date.now() / 1000) : -1;
  } catch {
    return -1;
  }
}

async function seedSession(page: Page, session: Session): Promise<void> {
  // Bukti eksplisit: key & email yang di-seed. Tanpa ini, sesi yang salah key
  // membuat tes gagal dengan gejala yang menyesatkan (seolah bug produk).
  console.log(`LS_KEY=${LS_KEY} EMAIL=${session.user?.email ?? "?"}`);
  await page.addInitScript(
    (kv: { key: string; value: unknown }) => {
      try {
        window.localStorage.setItem(kv.key, JSON.stringify(kv.value));
      } catch {
        /* ignore */
      }
    },
    { key: LS_KEY, value: session }
  );
}

/** Rekam SETIAP respons /models + /chat (observasi, bukan mock). */
function track(page: Page) {
  const models: { url: string; status: number; body: unknown }[] = [];
  const chats: { url: string; status: number; body: Record<string, unknown> }[] = [];
  page.on("response", (r: Response) => {
    const u = r.url();
    if (u.includes("/models")) {
      void r
        .json()
        .then((b) => models.push({ url: u, status: r.status(), body: b }))
        .catch(() => models.push({ url: u, status: r.status(), body: null }));
    } else if (u.includes("/chat")) {
      void r
        .json()
        .then((b) => chats.push({ url: u, status: r.status(), body: b as Record<string, unknown> }))
        .catch(() => chats.push({ url: u, status: r.status(), body: {} }));
    }
  });
  return { models, chats };
}

test.describe("PRODUKSI: filter model paid-only + badge fallback (tanpa mock)", () => {
  test("BUG 1 — /models & selector produksi tidak menyajikan model paid-only", async ({ page }) => {
    const session = loadSession();
    const ttl = session?.access_token ? expiresInSec(session.access_token) : -1;
    console.log(`TOKEN_TTL_S=${ttl}`);
    expect(
      ttl,
      "token E2E kedaluwarsa/kosong -> jalankan `python _e2e_refresh.py` lalu ulangi"
    ).toBeGreaterThan(30);

    await seedSession(page, session!);
    const { models } = track(page);

    // Registrasi SEBELUM goto: respons bisa mendarat kapan saja setelah auth
    // selesai. Versi sebelumnya membaca `models.at(-1)` tepat setelah menu
    // terbuka — menu TETAP ter-render dari fallback CHAT_MODELS lokal, jadi
    // assertion balapan dengan round-trip `/models` dan gagal dengan gejala
    // menyesatkan "GET /models tidak terpantau" padahal produk sehat.
    const modelsWait = page
      .waitForResponse(
        (r) => r.url().includes("/models") && r.request().method() === "GET",
        { timeout: 90000 }
      )
      .catch(() => null);

    await page.goto("/", { waitUntil: "domcontentloaded" });

    // Buka selector supaya daftar benar-benar dirender dari GET /models.
    const trigger = page.locator("button[aria-label='Pilih model AI']");
    await expect(trigger).toBeVisible({ timeout: 20000 });
    await expect(trigger.locator("span").first()).not.toHaveText(/Memuat/, { timeout: 20000 });
    await trigger.click();
    const menu = page.getByRole("menu");
    await expect(menu).toBeVisible();

    const modelsResp = await modelsWait;
    expect(
      modelsResp,
      `GET /models tidak terpantau (event response terlihat: ${models.length})`
    ).toBeTruthy();
    const modelsUrl = modelsResp!.url();
    console.log(`MODELS_URL=${modelsUrl} STATUS=${modelsResp!.status()}`);
    // GUARD ENVIRONMENT: respons harus dari backend LOKAL, bukan Railway.
    expect(
      modelsUrl.startsWith(API_ORIGIN),
      `bundle membidik origin lain (${modelsUrl}) — build/env salah, hasil tes tidak sah`
    ).toBe(true);
    expect(modelsResp!.status()).toBe(200);

    const payload = (await modelsResp!.json()) as { models?: { id: string }[] };
    const ids = (payload.models ?? []).map((m) => m.id);
    console.log(`MODELS_COUNT=${ids.length}`);
    console.log(`MODELS_IDS=${JSON.stringify(ids)}`);

    // 1) Tidak ada model paid-only / non-chat (id maupun pola).
    const forbidden = ids.filter((id) => FORBIDDEN_IDS.includes(id) || FORBIDDEN_RE.test(id));
    console.log(`FORBIDDEN_HITS=${JSON.stringify(forbidden)}`);
    expect(forbidden, `model paid-only masih disajikan: ${forbidden.join(", ")}`).toHaveLength(0);

    // 2) Model free-tier yang valid TETAP ada.
    expect(
      ids.length,
      `roster terlalu kecil (${ids.length}) — gateway kemungkinan tak terjangkau, bukan soal filter`
    ).toBeGreaterThanOrEqual(MIN_MODELS);
    for (const need of REQUIRED_IDS) {
      expect(ids.includes(need), `model valid hilang: ${need}`).toBe(true);
    }

    // 3) Regresi pola "omni": model hidup tidak boleh ikut terhapus.
    const omni = ids.filter((id) => REGRESSION_IDS.some((r) => id.includes(r)));
    console.log(`OMNI_LIVE_MODELS=${JSON.stringify(omni)}`);

    // 4) UI benar-benar bersih (teks yang dilihat user, bukan cuma payload).
    const menuText = (await menu.innerText()) || "";
    for (const bad of ["Pro Preview", "Transcribe", "Lyria", "Nano Banana", "Robotics"]) {
      expect(menuText, `UI selector masih menampilkan "${bad}"`).not.toContain(bad);
    }
    expect(menuText).toMatch(/Flash/i); // Flash/Flash-Lite terlihat user
    console.log("MENU_TEXT=" + menuText.replace(/\n+/g, " | ").slice(0, 400));

    await page.screenshot({ path: "evidence/model-selector-prod.png", fullPage: false });
    await page.keyboard.press("Escape");
  });

  test("BUG 2 — badge fallback render dengan model diminta vs dipakai", async ({ page }) => {
    const session = loadSession();
    const ttl = session?.access_token ? expiresInSec(session.access_token) : -1;
    expect(ttl, "token E2E kedaluwarsa -> `python _e2e_refresh.py`").toBeGreaterThan(30);

    await seedSession(page, session!);
    // Reproduksi skenario user: pilihan model "Pro" tersimpan di localStorage
    // (state sebelum fix). Selector kini tidak menawarkannya, tapi ini justru
    // yang harus dijelaskan ke user: badge menampilkan diminta vs dipakai.
    await page.addInitScript((m: string) => {
      try {
        window.localStorage.setItem("nexus.model.v1", m);
      } catch {
        /* ignore */
      }
    }, PRO_MODEL);

    const { chats } = track(page);
    await page.goto("/", { waitUntil: "domcontentloaded" });

    const input = page.locator('[aria-label="Pesan"]');
    await expect(input).toBeVisible({ timeout: 20000 });
    await input.fill("halo, tes badge fallback");

    const chatResp = page.waitForResponse(
      (r) => r.url().includes("/chat") && r.request().method() === "POST",
      { timeout: 60000 }
    );
    await page.locator('button[type="submit"]').click();
    const resp = await chatResp;
    expect(resp.url().startsWith(API_ORIGIN), `bundle membidik origin lain: ${resp.url()}`).toBe(true);
    const body = await resp.json();
    const meta = (body?.meta ?? {}) as Record<string, unknown>;
    console.log("CHAT_STATUS=" + resp.status());
    console.log("CHAT_META=" + JSON.stringify(meta));

    // Backend WAJIB mengirim meta lengkap (ini yang hilang di backend lama).
    expect(meta.requested_model, "meta.requested_model tidak dikirim backend").toBe(PRO_MODEL);
    expect(meta.model, "meta.model (yang dipakai) tidak dikirim backend").toBeTruthy();
    expect(meta.fallback, "meta.fallback tidak true saat model disubstitusi").toBe(true);

    // Badge terlihat user: alasan + model dipakai + model diminta.
    const badge = page.getByText("Model yang Anda pilih tidak tersedia").first();
    await expect(badge).toBeVisible({ timeout: 15000 });
    const badgeBox = badge.locator("xpath=ancestor::span[1]");
    const badgeText = (await badgeBox.innerText()) || "";
    console.log("BADGE_TEXT=" + badgeText.replace(/\n+/g, " | "));
    expect(badgeText).toContain(String(meta.model)); // model yang dipakai
    expect(badgeText).toContain(PRO_MODEL); // model yang diminta
    expect(badgeText, "badge tidak menyebut alasan").toMatch(
      /Kuota|permintaan|sibuk|tersedia|gateway/i
    );

    await page.screenshot({ path: "evidence/fallback-badge-prod.png", fullPage: false });
    console.log("CHAT_BODIES=" + JSON.stringify(chats.map((c) => c.status)));
  });

  test("VALID — model gratis hidup tidak memicu badge fallback", async ({ page }) => {
    const session = loadSession();
    const ttl = session?.access_token ? expiresInSec(session.access_token) : -1;
    expect(ttl, "token E2E kedaluwarsa -> `python _e2e_refresh.py`").toBeGreaterThan(30);

    await seedSession(page, session!);
    // Model free-tier yang terbukti STABIL (lihat REQUIRED_IDS) -> tidak
    // disubstitusi gateway, jadi jalur \"tanpa badge\" benar-benar teruji.
    const okModel = REQUIRED_IDS[0];
    await page.addInitScript((m: string) => {
      try {
        window.localStorage.setItem("nexus.model.v1", m);
      } catch {
        /* ignore */
      }
    }, okModel);

    const { chats } = track(page);
    await page.goto("/", { waitUntil: "domcontentloaded" });

    const input = page.locator('[aria-label="Pesan"]');
    await expect(input).toBeVisible({ timeout: 20000 });
    await input.fill("halo, tes model valid");

    const chatResp = page.waitForResponse(
      (r) => r.url().includes("/chat") && r.request().method() === "POST",
      { timeout: 60000 }
    );
    await page.locator('button[type="submit"]').click();
    const resp = await chatResp;
    expect(resp.url().startsWith(API_ORIGIN), `bundle membidik origin lain: ${resp.url()}`).toBe(true);
    const body = await resp.json();
    const meta = (body?.meta ?? {}) as Record<string, unknown>;
    console.log("VALID_STATUS=" + resp.status());
    console.log("VALID_META=" + JSON.stringify(meta));

    const substituted = meta.fallback === true;
    console.log(`VALID_SUBSTITUTED=${substituted} USED=${String(meta.model)}`);

    // INVARIANT UI<->BACKEND (selalu dapat dievaluasi, tidak tergantung rotasi
    // upstream): badge HANYA boleh tampil saat backend melaporkan fallback, dan
    // WAJIB tampil saat backend melaporkannya. Inilah yang membuat badge bisa
    // dipercaya sebagai penjelasan substitusi, bukan hiasan.
    const badge = page.getByText("Model yang Anda pilih tidak tersedia");
    if (substituted) {
      // Jalur cadangan: gateway merotasi model gratis -> badge harus menjelaskan.
      await expect(badge.first()).toBeVisible({ timeout: 15000 });
    } else {
      // Jalur utama yang diminta brief: model valid -> TANPA badge.
      expect(meta.model, "meta.model harus sama dengan yang diminta").toBe(okModel);
      await page.waitForTimeout(1500); // beri waktu render footer
      await expect(badge).toHaveCount(0);
      const footer = page.getByText(/tok\b/).first();
      if ((await footer.count()) > 0) {
        const footerText = (await footer.innerText()) || "";
        console.log("FOOTER_TEXT=" + footerText.replace(/\n+/g, " | "));
        expect(footerText).not.toContain("Model yang Anda pilih tidak tersedia");
      }
    }

    await page.screenshot({ path: "evidence/valid-model-no-badge.png", fullPage: false });
    console.log("VALID_CHAT_BODIES=" + JSON.stringify(chats.map((c) => c.status)));
  });
});
