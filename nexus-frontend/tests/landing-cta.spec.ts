import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test, expect, type Page } from "@playwright/test";

/**
 * CTA utama landing — "Mulai sekarang".
 *
 * BUG YANG DISERANG: CTA ini pernah `<Link href="/chat">`. Pengunjung yang
 * BELUM masuk mengkliknya dan langsung mendarat di /chat, yangmana hanya
 * menampilkan "Please sign in first" — persis laporan yang masuk. Link tidak
 * bisa membuka modal, jadi satu-satunya jalan yang tersedia bagi pengunjung
 * anonim adalah tembok login seperti itu sendiri.
 *
 * YANG DIUJI (dua cabang, keduanya harus bergantung pada SESI NYATA):
 *   1. Belum masuk → klik membuka modal, dan TIDAK berpindah ke /chat.
 *   2. Sudah masuk → klik langsung ke /chat, tanpa modal.
 *
 * Catatan kejujuran: cabang "sudah masuk" memakai sesi E2E yang sudah
 * diverifikasi signature-nya oleh `scripts/e2e-auth-setup.mjs` (globalSetup).
 * Tes ini tidak mengklaim alur login UI berfungsi — hanya bahwa CTA membaca
 * sesi dan mengarahkan ke tempat yang benar.
 */

function supabaseRef(): string {
  const fromEnv = (process.env.NEXT_PUBLIC_SUPABASE_URL || "").trim();
  if (fromEnv) {
    const m = fromEnv.match(/https?:\/\/([a-z0-9]+)\.supabase/);
    if (m) return m[1];
  }
  for (const f of [".env.local", ".env"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    const m = readFileSync(p, "utf-8").match(
      /NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/
    );
    if (m) return m[1];
  }
  return "qmukkphwaajzbqjrcvaz";
}

const REF = supabaseRef();
const LS_KEY = `sb-${REF}-auth-token`;

/**
 * Kredensial user E2E.
 *
 * Sengaja dibaca dari `_e2e_user.json` (sumber yang sama dengan
 * `scripts/e2e-auth-setup.mjs`) alih-alih env: variabel E2E_USER_EMAIL /
 * E2E_USER_PASSWORD boleh kosong di mesin ini, karena skrip membuat user
 * sendiri lalu menyimpannya. Kalau file itu tidak ada, tes ini gagal dengan
 * pesan yang jelas alih-alih diam-diam dilewati.
 */
function loadUserCreds(): { email: string; password: string } | null {
  for (const f of ["_e2e_user.json"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    try {
      const u = JSON.parse(readFileSync(p, "utf-8")) as {
        email?: string;
        password?: string;
      };
      if (u?.email && u?.password) return { email: u.email, password: u.password };
    } catch {
      /* coba kandidat berikutnya */
    }
  }
  const email = (process.env.E2E_USER_EMAIL || "").trim();
  const password = (process.env.E2E_USER_PASSWORD || "").trim();
  return email && password ? { email, password } : null;
}

type Session = { access_token?: string; user?: { email?: string }; [k: string]: unknown };

function loadSession(): Session | null {
  for (const f of ["_e2e_session.refreshed.json", "_e2e_session.json"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    try {
      const s = JSON.parse(readFileSync(p, "utf-8")) as Session;
      if (s?.access_token) {
        console.log(`CTA_SESSION_FILE=${f}`);
        return s;
      }
    } catch {
      /* lanjut ke kandidat berikutnya */
    }
  }
  return null;
}

/** exp (detik) dari JWT; token kedaluwarsa ditolak -> TTL -1. */
function expiresInSec(token: string): number {
  try {
    const seg = token.split(".")[1] ?? "";
    const b64 = seg.replace(/-/g, "+").replace(/_/g, "/");
    const pad = (4 - (b64.length % 4)) % 4;
    const payload = JSON.parse(
      Buffer.from(b64 + "=".repeat(pad), "base64").toString("utf-8")
    ) as { exp?: number };
    return typeof payload.exp === "number" ? payload.exp - Math.floor(Date.now() / 1000) : -1;
  } catch {
    return -1;
  }
}

/**
 * Tunggu aplikasi SIAP DIINTERAKSI.
 *
 * Markup hasil render server untuk "belum login" dan "sudah login" TERLIHAT
 * SAMA; sesi baru diterapkan setelah hidrasi. Tanpa titik tunggu ini, klik
 * pada tes bisa hilang tanpa error dan 보고annya menyesatkan ("tombol tidak
 * bekerja") padahal aplikasi belum sempat hidup. `data-hydrated` dipasang
 * HydrationReady; `data-auth` dipantulkan AuthProvider.
 */
async function waitAppReady(page: Page): Promise<void> {
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
}

test.describe("landing CTA", () => {
  test("belum masuk: klik membuka modal login, bukan login wall di /chat", async ({ page }) => {
    // Paksa anonim: honorkan storageState dari config kalau ada, tapi jangan
    // andalkan. Yang diuji adalah cabang tanpa sesi.
    await page.goto("/");
    await waitAppReady(page);

    // Bersihkan sisa sesi supaya cabang "belum masuk" benar-benar diuji.
    await page.evaluate((k) => {
      try {
        window.localStorage.removeItem(k);
        window.sessionStorage.clear();
      } catch {
        /* ignore */
      }
    }, LS_KEY);

    await page.getByTestId("landing-cta").click();

    // Modal terbuka…
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 20000 });
    await expect(page.getByTestId("login-github")).toBeVisible();

    // …dan kita TIDAK pernah mendarat di /chat. Inilah gejalanya yang dilaporkan.
    await page.waitForTimeout(1500);
    expect(
      new URL(page.url()).pathname,
      "CTA anonim tidak boleh mengarahkan ke /chat"
    ).not.toBe("/chat");
  });

  test("sudah masuk: klik langsung ke /chat tanpa modal", async ({ page }) => {
    const session = loadSession();
    const ttl = session?.access_token ? expiresInSec(session.access_token) : -1;
    console.log(`CTA_TOKEN_TTL_S=${ttl}`);
    expect(
      ttl,
      "sesi E2E kedaluwarsa/kosong -> mint sesi sah lewat scripts/e2e-auth-setup.mjs " +
        "(otomatis sebagai Playwright globalSetup)"
    ).toBeGreaterThan(30);

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

    await page.goto("/");
    await waitAppReady(page);

    await page.getByTestId("landing-cta").click();

    // Cara menunggu navigasi, bukan menebak: klik ini memakai
    // `window.location.assign`, jadi `waitForURL` menangkapnya. Menunggu URL
    // (bukan sekadar sleep) membuat tes tidak bergantung pada lamanya probe sesi.
    await page.waitForURL(/\/chat(\?.*)?$/, { timeout: 30000 });
    expect(new URL(page.url()).pathname).toBe("/chat");

    // Modal TIDAK boleh muncul untuk pengunjung yang sudah punya sesi.
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });

  test("email/password: sukses harus mendarat di tujuan, bukan tutup modal di tempat", async ({
    page,
  }) => {
    // Kredensial E2E dibuat globalSetup. Diuji dengan guard agar kredensial
    // yang hilang/expired menghasilkan pesan jelas, bukan kegagalan Misterius.
    const creds = loadUserCreds();
    expect(
      creds,
      "kredensial E2E tidak ditemukan -> globalSetup (scripts/e2e-auth-setup.mjs) tidak jalan"
    ).toBeTruthy();
    const { email, password } = creds!;

    await page.goto("/");
    await waitAppReady(page);
    await page.evaluate((k) => {
      try {
        window.localStorage.removeItem(k);
        window.sessionStorage.clear();
      } catch {
        /* ignore */
      }
    }, LS_KEY);

    await page.getByTestId("landing-cta").click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 20000 });

    // Kredensial diisi lewat UI yang sama dengan yang dipakai user, supaya tes
    // ini juga menangkap regresi pada submit form.
    await dialog.getByTestId("login-email").fill(email);
    await dialog.getByTestId("login-password").fill(password);
    await dialog.getByTestId("login-submit").click();

    // Before this fix the modal merely closed and the URL stayed on "/", which
    // read to the user as a button that did nothing. Assert the destination.
    await page.waitForURL(/\/chat(\?.*)?$/, { timeout: 60000 });
    expect(new URL(page.url()).pathname).toBe("/chat");
  });
});
