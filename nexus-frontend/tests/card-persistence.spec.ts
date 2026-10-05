/**
 * Bukti BROWSER untuk Bug #3 — kartu kredensial hilang setelah navigasi/refresh.
 *
 * KENAPA SPEC INI ADA
 * -------------------
 * `docs/BUGFIX-3-KRITIS-2026-10-06.md` §"Yang BELUM terverifikasi" mencatat
 * jujur bahwa perbaikan Bug #3 HANYA terbukti di level backend (6 tes bahwa
 * baris `role="system"` + envelope `{__katalir_card}` ditulis dengan benar) dan
 * di level tipe (`tsc --noEmit` exit 0). Yang TIDAK pernah dibuktikan:
 * bahwa kartunya benar-benar muncul kembali di browser setelah user me-refresh.
 *
 * Rantai yang diuji di sini adalah rantai yang persis dipakai user:
 *   1. kirim prompt yang butuh kredensial -> backend balas `requires_credential`
 *      dan MEMPERSIST kartunya sebagai baris `role="system"`;
 *   2. `GET /messages/{sid}` mengembalikan baris itu bersama pesan biasa;
 *   3. `fetchMessages` mendekodenya (`decodePersistedCard`) menjadi ChatMessage
 *      bertipe dengan `_localId` stabil;
 *   4. `ChatApp` merender kartunya — TANPA ada state klien yang tersisa.
 *
 * Langkah 4 itulah inti bugnya: kartu dulu hanya hidup di cache TanStack
 * (`_localId`) dan tidak pernah dipersist, jadi reload = kartu lenyap.
 *
 * MENGAPA SPEC INI GAGAL DI KODE LAMA
 * -----------------------------------
 * Sebelum perbaikan, server tidak pernah menulis baris kartu, sehingga jawaban
 * `GET /messages` di langkah 2 hanya berisi baris user+assistant -> kartu tidak
 * bisa dibangun ulang -> assertion `credential-form-submit` setelah reload
 * GAGAL. Spec ini mengunci kontrak itu supaya regresi tidak lolos lagi.
 *
 * Jalankan dengan `playwright.approval.config.ts` (stub `page.route`, tanpa
 * backend/database/akun), terhadap `out/` hasil `next build` ATAU situs live:
 *
 *   PORT=3000 node scripts/serve-out.mjs &          # build produksi lokal
 *   npx playwright test -c playwright.approval.config.ts tests/card-persistence.spec.ts
 */
import { test, expect, type Page, type Route, type Request } from "@playwright/test";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const SHOTS = join(process.cwd(), "..", "docs", "marketing", "screenshots");
const SHOT = process.env.E2E_SHOT_PREFIX || "card-persistence";
const shot = (name: string) => join(SHOTS, `${SHOT}-${name}.png`);
const ONB_KEY = "katalir.onboarding.v1";
const LOCALE_KEY = "katalir.locale.v1";

/** Session id yang dipakai seluruh stub. Bukan id nyata di database mana pun. */
const SID = "sess-persist-stub";

const PROVIDER = "supabase";
const DISPLAY_NAME = "Supabase";
const FIELDS = [
  { name: "project_url", type: "url", label: "Project URL" },
  { name: "service_role_key", type: "password", label: "Service Role Key" },
];

/** Token resume DUMMY — tidak pernah dikirim ke server nyata. */
const RESUME_TOKEN = "resume-persist-stub";

/**
 * Envelope yang MEMANG ditulis `_persist_card` di backend:
 *   payload = {__katalir_card: <type>, **card}
 * Jadi `type` dan `__katalir_card` keduanya ada. Bentuk ini di-hardcode di sini
 * supaya spec menguji KONTRAK yang disepakati, bukan sekadar menyalin apa pun
 * yang kebetulan dikirim backend.
 */
function persistedCardRow(id: string) {
  return {
    id,
    role: "system",
    content: JSON.stringify({
      __katalir_card: "credential_form",
      type: "credential_form",
      provider: PROVIDER,
      display_name: DISPLAY_NAME,
      icon: "supabase",
      fields: FIELDS,
      resume_token: RESUME_TOKEN,
      original: "sambungkan supabase, isi kredensialnya",
    }),
  };
}

/** Baris biasa (user + assistant) yang selalu ada di sesi ini. */
const PLAIN_ROWS = [
  { id: "m-user", role: "user", content: "sambungkan supabase, isi kredensialnya" },
  { id: "m-asst", role: "assistant", content: "Butuh kredensial Supabase Anda." },
];

function supabaseRef(): string {
  for (const f of [".env.local", ".env"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    const m = readFileSync(p, "utf-8").match(
      /NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/,
    );
    if (m) return m[1];
  }
  return "qmukkphwaajzbqjrcvaz";
}

/** Sesi DUMMY: hanya memenuhi gate login sisi-klien; semua API di-stub. */
function dummySession() {
  const b64 = (o: unknown) =>
    Buffer.from(JSON.stringify(o))
      .toString("base64")
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
  const now = Math.floor(Date.now() / 1000);
  return {
    access_token: `${b64({ alg: "HS256", typ: "JWT" })}.${b64({
      sub: "00000000-0000-0000-0000-000000000002",
      aud: "authenticated",
      role: "authenticated",
      exp: now + 60 * 60 * 24 * 365,
      iat: now,
      email: "e2e-persist@local.test",
      user_metadata: {},
    })}.local-tests-only`,
    token_type: "bearer",
    expires_in: 60 * 60 * 24 * 365,
    expires_at: now + 60 * 60 * 24 * 365,
    refresh_token: "local-tests-only",
    user: { id: "00000000-0000-0000-0000-000000000002", email: "e2e-persist@local.test" },
  };
}

async function seed(page: Page) {
  const real = join(process.cwd(), "_e2e_session.refreshed.json");
  const sess = existsSync(real) ? JSON.parse(readFileSync(real, "utf-8")) : dummySession();
  const entries: [string, string][] = [
    [LOCALE_KEY, "id"],
    [ONB_KEY, "done"],
    [`sb-${supabaseRef()}-auth-token`, JSON.stringify(sess)],
  ];
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

function isApi(req: Request): boolean {
  const path = new URL(req.url()).pathname;
  return /^\/(chat|sessions|workflows|executions|preferences|api\/vault|messages)/.test(path);
}

interface StubControl {
  /** `GET /messages` dipanggil berapa kali (bukti refresh benar-benar fetch). */
  messagesCalls: number;
  /** Baris kartu ikut dikirim? Set `false` untuk mensimulasikan kode LAMA. */
  persistCard: boolean;
}

async function stubApi(page: Page, control: StubControl) {
  await page.route("**/*", async (route: Route) => {
    const req = route.request();
    if (!isApi(req)) return route.continue();
    const path = new URL(req.url()).pathname;
    const json = (status: number, body: unknown) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    if (path === "/sessions") return json(200, { sessions: [] });

    if (path === "/chat" && req.method() === "POST") {
      return json(200, {
        status: "requires_credential",
        provider: PROVIDER,
        display_name: DISPLAY_NAME,
        fields: FIELDS,
        resume_token: RESUME_TOKEN,
        session_id: SID,
      });
    }

    // INTI SPEC INI. Inilah yang dulu tidak pernah ada: kartu dipersist server.
    if (path === `/messages/${SID}`) {
      control.messagesCalls += 1;
      const rows = control.persistCard
        ? [...PLAIN_ROWS, persistedCardRow("m-card")]
        : [...PLAIN_ROWS];
      return json(200, { status: "success", messages: rows });
    }

    if (path === "/preferences" && req.method() === "PUT") return json(200, { status: "success", prefs: {} });
    return route.continue();
  });
}

async function openChat(page: Page) {
  await seed(page);
  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
}

test.beforeAll(() => {
  if (!existsSync(SHOTS)) mkdirSync(SHOTS, { recursive: true });
});

test("kartu kredensial muncul kembali setelah refresh (baris kartu dipersist server)", async ({ page }) => {
  test.setTimeout(120000);
  const control: StubControl = { messagesCalls: 0, persistCard: true };
  await stubApi(page, control);
  await openChat(page);

  // 1. Kirim prompt yang memicu `requires_credential`.
  await page.getByTestId("composer-input").fill("sambungkan supabase, isi kredensialnya");
  await page.getByTestId("composer-send").click();
  await expect(page.getByTestId("credential-form-submit").last()).toBeVisible({ timeout: 30000 });

  // 2. REFRESH. Di sinilah bug lama muncul: kartu hanya di cache klien -> hilang.
  //    `addInitScript` dari `seed()` otomatis jalan lagi, jadi sesi tetap ada
  //    dan app melakukan fetch server biasa (inilah yang kita ingin uji).
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });

  // 3. Kartu HARUS bisa dibangun ulang MURNI dari jawaban `GET /messages`.
  const form = page.getByTestId("credential-form-submit").last();
  await expect(form).toBeVisible({ timeout: 30000 });

  // 4. Board-nya lengkap: provider benar, judul benar, field-nya benar.
  //    testid input mengikuti pola `${inputId}-input` dengan
  //    `inputId = cred-<provider>-<nama field>` (CredentialForm.tsx).
  await expect(page.getByTestId(`credential-form-${PROVIDER}`).last()).toBeVisible();
  await expect(page.getByTestId(`cred-${PROVIDER}-project_url-input`).last()).toBeVisible();
  await expect(page.getByTestId(`cred-${PROVIDER}-service_role_key-input`).last()).toBeVisible();

  // 5. Bukti bahwa kartunya memang datang dari SERVER, bukan dari sisa cache:
  //    browser benar-benar memanggil /messages/:sid dan isinya memuat kartu.
  expect(control.messagesCalls).toBeGreaterThan(0);

  await page.screenshot({ path: shot("after-reload"), fullPage: true });
  console.log(`SHOT=${SHOT}-after-reload.png`);
});

test("kontra-regresi: tanpa baris kartu di server, kartu memang TIDAK muncul", async ({ page }) => {
  test.setTimeout(120000);
  // Spec ini ada supaya tes di atas terbukti TAJAM: kalau server tidak
  // mengembalikan baris kartu (perilaku KODE LAMA sebelum perbaikan), kartunya
  // hilang setelah refresh. Kalau tes ini justru menampilkan kartu, berarti
  // kartu masih hidup di cache klien dan tes pertama tidak membuktikan apa pun.
  const control: StubControl = { messagesCalls: 0, persistCard: false };
  await stubApi(page, control);
  await openChat(page);

  await page.getByTestId("composer-input").fill("sambungkan supabase, isi kredensialnya");
  await page.getByTestId("composer-send").click();
  await expect(page.getByTestId("credential-form-submit").last()).toBeVisible({ timeout: 30000 });

  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });

  expect(control.messagesCalls).toBeGreaterThan(0);
  // Beri waktu render selesai sebelum menyimpulkan "tidak ada".
  await expect(page.getByText("Butuh kredensial Supabase Anda.").last()).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId("credential-form-submit")).toHaveCount(0);
});
