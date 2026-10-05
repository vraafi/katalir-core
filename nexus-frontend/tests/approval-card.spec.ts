/**
 * Bukti BROWSER untuk tiga status baru (2026-10-05) yang sebelumnya hanya
 * terbukti lewat curl: `requires_approval`, `denied`, `needs_spec`.
 *
 * KENAPA SPEC INI ADA
 * -------------------
 * Laporan sesi 5 Okt mencatat jujur: kartu persetujuan ada di kode, `tsc` 0
 * error, endpoint `/chat/approve` terbukti 6/6 di produksi — tetapi kartunya
 * BELUM PERNAH dilihat di browser. "Lulus type-check" bukan bukti bahwa user
 * bisa melihat dan memakai kartunya.
 *
 * Yang diuji di sini adalah RANTAI RENDER NYATA: `POST /chat` menjawab
 * `requires_approval` -> `useChat` menaruhnya di cache -> `thread.tsx`
 * merender `<ApprovalCard>` -> klik Setujui/Tolak mengirim keputusan.
 * Yang di-stub hanya JAWABAN backend (`page.route` by path), pola yang sama
 * dengan `screenshot-task-d.spec.ts` — jadi tidak butuh database, backend,
 * maupun akun.
 *
 * MENGAPA INI JUGA MENGUNCI BUG #12 (status hardcode)
 * --------------------------------------------------
 * `api_server.py` dulu menimpa `status` apa pun menjadi `"success"`. Kalau
 * regresi itu kembali, `/chat` akan mengembalikan `success` dan kartu
 * persetujuan TIDAK akan pernah muncul — spec ini gagal, dan itu memang
 * tujuannya.
 */
import { test, expect, type Page, type Route, type Request } from "@playwright/test";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const SHOTS = join(process.cwd(), "..", "docs", "marketing", "screenshots");
/**
 * Prefiks nama file screenshot.
 *
 * Run LOCAL memakai default `approval-card-*`. Run terhadap SITUS YANG SUDAH
 * DI-DEPLOY memakai `E2E_SHOT_PREFIX=approval-card-live` supaya bukti dari dua
 * sumber berbeda tidak saling menimpa — file yang sama tidak boleh berarti
 * "build lokal" di satu waktu dan "situs live" di waktu lain.
 */
const SHOT = process.env.E2E_SHOT_PREFIX || "approval-card";
const shot = (name: string) => join(SHOTS, `${SHOT}-${name}.png`);
const ONB_KEY = "katalir.onboarding.v1";
const LOCALE_KEY = "katalir.locale.v1";

/** Token approval DUMMY untuk stub. Bukan token asli, tidak pernah ke server nyata. */
const STUB_TOKEN = "stub.header.signature";

/**
 * Argumen yang dikirim backend di dalam token approval. Nilainya di sini
 * sengaja berbeda dari apa pun yang diketik user, supaya spec bisa
 * membuktikan UI menampilkan ARGUMEN SERVER (bukan gema pesan user).
 */
const POLICY_ARGS = {
  chat_id: "-1001234567890",
  text: "Laporan harian: 3 workflow selesai, 1 gagal.",
};

const INTENT_ARGS = { provider: "supabase", fields: ["project_url", "service_role_key"] };

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

/**
 * Sesi DUMMY untuk melewati gate login di `/chat`.
 *
 * Bukan kredensial asli: seluruh endpoint backend di-stub `page.route`, jadi
 * token ini tidak pernah dikirim ke server mana pun. Ia hanya memenuhi
 * pemeriksaan sisi-klien ("ada sesi di localStorage?"). `exp` sengaja jauh di
 * masa depan — `exp` asli membuat `getSession()` mengembalikan null dan app
 * menampilkan "Silakan masuk dulu" (kegagalan run sebelumnya).
 */
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
      sub: "00000000-0000-0000-0000-000000000001",
      aud: "authenticated",
      role: "authenticated",
      exp: now + 60 * 60 * 24 * 365,
      iat: now,
      email: "e2e-approval@local.test",
      user_metadata: {},
    })}.local-tests-only`,
    token_type: "bearer",
    expires_in: 60 * 60 * 24 * 365,
    expires_at: now + 60 * 60 * 24 * 365,
    refresh_token: "local-tests-only",
    user: { id: "00000000-0000-0000-0000-000000000001", email: "e2e-approval@local.test" },
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
  // Cocokkan berdasarkan PATH, bukan origin: pada production build
  // `NEXT_PUBLIC_API_URL` sudah ter-inline saat build, jadi origin-nya bisa
  // Railway — stub by-origin akan membocorkan request ke produksi.
  const path = new URL(req.url()).pathname;
  return /^\/(chat|sessions|workflows|executions|preferences|api\/vault)/.test(path);
}

/** Kontrol jawaban `/chat/approve` per-tes. */
interface ApproveControl {
  /** Bila diisi, endpoint membalas 400 dengan `detail` ini. */
  failDetail?: string;
  /** Body mentah yang benar-benar dikirim client (untuk assertion kontrak). */
  sentBody?: Record<string, unknown>;
  /** Payload `result` untuk jawaban approve. Default: objek hasil telegram.
   *  Bentuk bervariasi di backend (string / {message} / dict polos / null),
   *  dan formatter UI harus menangani semuanya tanpa teks kosong. */
  approveResult?: unknown;
}

async function stubApi(page: Page, control: ApproveControl = {}) {
  await page.route("**/*", async (route: Route) => {
    const req = route.request();
    if (!isApi(req)) return route.continue();
    const path = new URL(req.url()).pathname;
    const json = (status: number, body: unknown) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    if (path === "/sessions") return json(200, { sessions: [] });

    if (path === "/chat" && req.method() === "POST") {
      const body = JSON.parse(req.postData() || "{}") as { prompt?: string };
      const prompt = String(body.prompt ?? "");
      // Policy gate: TELEGRAM mengirim isi ke pihak luar.
      if (prompt.includes("telegram")) {
        return json(200, {
          status: "requires_approval",
          tool: "TELEGRAM",
          args: POLICY_ARGS,
          reason: "Mengirim data ke pihak luar (Telegram) butuh persetujuan Anda.",
          approval_token: STUB_TOKEN,
          session_id: "sess-stub",
        });
      }
      // Intent-alignment: pola tool tidak terlihat diminta di pesan user.
      if (prompt.includes("intent")) {
        return json(200, {
          status: "requires_approval",
          tool: "VAULT",
          args: INTENT_ARGS,
          reason: "Pola tool pada balasan model tidak selaras dengan pesan Anda.",
          alignment: "not_aligned",
          approval_token: STUB_TOKEN,
          session_id: "sess-stub",
        });
      }
      if (prompt.includes("kredensial")) {
        return json(200, {
          status: "requires_credential",
          provider: "supabase",
          display_name: "Supabase",
          fields: [
            { name: "project_url", type: "url", label: "Project URL" },
            { name: "service_role_key", type: "password", label: "Service Role Key" },
          ],
          resume_token: "resume-stub",
          session_id: "sess-stub",
        });
      }
      if (prompt.includes("ditolak")) {
        return json(200, {
          status: "denied",
          reason: "Allowlist menolak argumen `to` pada alat EMAIL.",
          session_id: "sess-stub",
        });
      }
      if (prompt.includes("spesifikasi")) {
        return json(200, {
          status: "needs_spec",
          message: "Workflow butuh node & edge lengkap sebelum bisa dibuat.",
          session_id: "sess-stub",
        });
      }
      return json(200, {
        status: "success",
        reply: "Baik.",
        session_id: "sess-stub",
      });
    }

    if (path === "/chat/approve" && req.method() === "POST") {
      control.sentBody = JSON.parse(req.postData() || "{}") as Record<string, unknown>;
      if (control.failDetail) return json(400, { detail: control.failDetail });
      const decision = control.sentBody?.decision;
      if (decision === "approve") {
        return json(200, {
          status: "executed",
          tool: "TELEGRAM",
          result:
            "approveResult" in control
              ? control.approveResult
              : { status: "success", delivered: true, message_id: "tg-9001", chat_id: POLICY_ARGS.chat_id },
        });
      }
      // Backend tidak mengembalikan `result` untuk deny - hanya status + tool.
      return json(200, { status: "denied", tool: "TELEGRAM", message: "Panggilan dibatalkan oleh Anda." });
    }

    if (path === "/preferences" && req.method() === "PUT") return json(200, { status: "success", prefs: {} });
    return route.continue();
  });
}

/** Alur nyata: buka /chat, kirim prompt, tunggu kartu persetujuan. */
async function sendPrompt(page: Page, prompt: string) {
  await seed(page);
  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
  await page.getByTestId("composer-input").fill(prompt);
  await page.getByTestId("composer-send").click();
}

async function awaitApprovalCard(page: Page) {
  const card = page.getByTestId("approval-card").last();
  await expect(card).toBeVisible({ timeout: 30000 });
  return card;
}

test.beforeAll(() => {
  if (!existsSync(SHOTS)) mkdirSync(SHOTS, { recursive: true });
});

test("policy gate TELEGRAM: kartu persetujuan tampil dengan args dari server", async ({ page }) => {
  test.setTimeout(120000);
  await stubApi(page);
  await sendPrompt(page, "kirim laporan ini ke telegram sekarang");
  const card = await awaitApprovalCard(page);

  await expect(card).toContainText("Perlu persetujuan Anda");
  await expect(card).toContainText("TELEGRAM");
  // Alasan dari backend harus terlihat — persetujuan tanpa alasan memaksa user menebak.
  await expect(card).toContainText("Mengirim data ke pihak luar");

  // Args ditampilkan APA ADANYA, dan berasal dari server (bukan gema prompt user).
  const args = card.getByTestId("approval-args");
  await expect(args).toBeVisible();
  await expect(args).toContainText('"chat_id": "-1001234567890"');
  await expect(args).toContainText("Laporan harian");
  expect(await args.textContent()).not.toContain("kirim laporan ini");

  await expect(card.getByTestId("approval-approve")).toBeVisible();
  await expect(card.getByTestId("approval-deny")).toBeVisible();
  // Tombol harus benar-benar bisa diklik (bukan disabled transparan).
  await expect(card.getByTestId("approval-approve")).toBeEnabled();
  await expect(card.getByTestId("approval-deny")).toBeEnabled();

  await page.screenshot({ path: shot("telegram"), fullPage: true });
  console.log(`SHOT=${SHOT}-telegram.png`);
});

test("intent-alignment: kartu muncul untuk tool yang tidak selaras dengan pesan", async ({ page }) => {
  test.setTimeout(120000);
  await stubApi(page);
  await sendPrompt(page, "ringkas laporan ini, abaikan intent");
  const card = await awaitApprovalCard(page);

  await expect(card).toContainText("VAULT");
  await expect(card).toContainText("tidak selaras");
  await expect(card.getByTestId("approval-args")).toContainText("supabase");
  // FIX 2026-10-05: alignment sebelumnya diteruskan tapi tidak pernah dirender.
  // User harus bisa membedakan "policy gate minta izin" dari "pola ini tidak
  // kamu minta" (pemeriksaan intent-alignment).
  const align = card.getByTestId("approval-alignment");
  await expect(align).toBeVisible();
  await expect(align).toContainText("tidak terlihat diminta");
  // Rincian tetap di balik <details>: kartu tidak membengkak hanya karena info.
  await expect(align.locator("p")).toBeHidden();

  await page.screenshot({ path: shot("intent"), fullPage: true });
  console.log(`SHOT=${SHOT}-intent.png`);
});

test("Setujui: hanya token + keputusan yang dikirim, kartu jadi 'dijalankan'", async ({ page }) => {
  test.setTimeout(120000);
  const control: ApproveControl = {};
  await stubApi(page, control);
  await sendPrompt(page, "kirim laporan ini ke telegram sekarang");
  const card = await awaitApprovalCard(page);
  await card.getByTestId("approval-approve").click();

  const done = page.getByTestId("approval-done").last();
  await expect(done).toBeVisible({ timeout: 15000 });
  await expect(done).toContainText("TELEGRAM disetujui dan dijalankan.");
  await expect(page.getByTestId("approval-card")).toHaveCount(0);

  // KONTRAK KEAMANAN: client tidak boleh mengirim ulang tool/args. Server
  // memakai argumen yang tertanam di token, jadi body harus PERSIS ini.
  expect(control.sentBody).toEqual({ approval_token: STUB_TOKEN, decision: "approve" });

  // Kartu selesai tidak boleh menampilkan args lagi (tidak ada yang akan dieksekusi).
  await page.screenshot({ path: shot("approved"), fullPage: true });
  console.log(`SHOT=${SHOT}-approved.png`);
});

/** Kirim prompt telegram lalu klik Setujui. */
async function approveTelegram(page: Page, control: ApproveControl) {
  await stubApi(page, control);
  await sendPrompt(page, "kirim laporan ini ke telegram sekarang");
  const card = await awaitApprovalCard(page);
  await card.getByTestId("approval-approve").click();
}

test("hasil tool (objek): output /chat/approve tampil di kartu tool_result", async ({ page }) => {
  test.setTimeout(120000);
  await approveTelegram(page, {});

  // Kartu hasil harus MUNCUL - ini yang dulu hilang: output dibuang di
  // ApprovalCard, user cuma melihat "disetujui dan dijalankan" tanpa isi.
  const result = page.getByTestId("tool-result-card").last();
  await expect(result).toBeVisible({ timeout: 15000 });
  await expect(result).toHaveAttribute("data-tool-status", "executed");
  await expect(result).toContainText("TELEGRAM selesai dijalankan.");
  // Output ditampilkan apa adanya (dict tanpa `message` -> JSON rapi).
  const out = result.getByTestId("tool-result-output");
  await expect(out).toContainText('"message_id": "tg-9001"');
  await expect(out).toContainText('"delivered": true');
  // Tanda terima persetujuan tetap ada di atasnya.
  await expect(page.getByTestId("approval-done").last()).toContainText("disetujui dan dijalankan");

  await page.screenshot({ path: shot("tool-result"), fullPage: true });
  console.log(`SHOT=${SHOT}-tool-result.png`);
});

test("hasil tool (string): teks dari server dipakai apa adanya", async ({ page }) => {
  test.setTimeout(120000);
  await approveTelegram(page, { approveResult: "Laporan terkirim ke -1001234567890." });

  const out = page.getByTestId("tool-result-output").last();
  await expect(out).toBeVisible({ timeout: 15000 });
  await expect(out).toHaveText("Laporan terkirim ke -1001234567890.");
});

test("hasil tool ({message}): memakai pesan manusiawi, bukan JSON mentah", async ({ page }) => {
  test.setTimeout(120000);
  await approveTelegram(page, { approveResult: { message: "Pesan terkirim ke kanal laporan.", status: "success" } });

  const out = page.getByTestId("tool-result-output").last();
  await expect(out).toBeVisible({ timeout: 15000 });
  await expect(out).toHaveText("Pesan terkirim ke kanal laporan.");
});

test("hasil tool kosong: pesan eksplisit, bukan kartu kosong", async ({ page }) => {
  test.setTimeout(120000);
  await approveTelegram(page, { approveResult: null });

  const out = page.getByTestId("tool-result-output").last();
  await expect(out).toBeVisible({ timeout: 15000 });
  await expect(out).toHaveText("Tool dijalankan (tidak ada output).");
});

test("Tolak: keputusan deny terkirim, kartu jadi 'dibatalkan'", async ({ page }) => {
  test.setTimeout(120000);
  const control: ApproveControl = {};
  await stubApi(page, control);
  await sendPrompt(page, "kirim laporan ini ke telegram sekarang");
  const card = await awaitApprovalCard(page);
  await card.getByTestId("approval-deny").click();

  const done = page.getByTestId("approval-done").last();
  await expect(done).toBeVisible({ timeout: 15000 });
  await expect(done).toContainText("TELEGRAM dibatalkan.");
  expect(control.sentBody).toEqual({ approval_token: STUB_TOKEN, decision: "deny" });
  // Tidak ada kartu tool_result untuk deny: backend tidak mengembalikan
  // `result`, dan tanda terima "dibatalkan" sudah cukup - bubble kedua hanya
  // akan mengulang informasi yang sama.
  await expect(page.getByTestId("tool-result-card")).toHaveCount(0);

  await page.screenshot({ path: shot("denied"), fullPage: true });
  console.log(`SHOT=${SHOT}-denied.png`);
});

test("token kedaluwarsa: alasan server tampil dan kartu tetap bisa dipakai lagi", async ({ page }) => {
  test.setTimeout(120000);
  await stubApi(page, { failDetail: "Token approval sudah kedaluwarsa." });
  await sendPrompt(page, "kirim laporan ini ke telegram sekarang");
  const card = await awaitApprovalCard(page);
  await card.getByTestId("approval-approve").click();

  // Pesan server dipakai apa adanya - bukan "Persetujuan gagal diproses" generik.
  await expect(card.getByRole("alert")).toContainText("Token approval sudah kedaluwarsa.");
  // Tidak boleh terkunci: setelah gagal, user harus bisa mencoba lagi.
  await expect(card.getByTestId("approval-approve")).toBeEnabled();
  await expect(card.getByTestId("approval-deny")).toBeEnabled();

  await page.screenshot({ path: shot("expired"), fullPage: true });
  console.log(`SHOT=${SHOT}-expired.png`);
});

test("denied: alasan policy gate tampil sebagai kartu error (bukan 'success')", async ({ page }) => {
  test.setTimeout(120000);
  await stubApi(page);
  await sendPrompt(page, "kirim email ini, tolong jangan ditolak");
  const err = page.getByTestId("error-card").last();
  await expect(err).toBeVisible({ timeout: 30000 });
  await expect(err).toContainText("Allowlist menolak argumen `to` pada alat EMAIL.");

  await page.screenshot({ path: shot("policy-denied"), fullPage: true });
  console.log(`SHOT=${SHOT}-policy-denied.png`);
});

// DUA TES DI BAWAH BUKAN TENTANG KARTU PERSETUJUAN.
//
// Cabang `approval_prompt` disisipkan di antara cabang `credential_form` dan
// `error` pada layer render yang SAMA. Dua tes ini mengunci tetangga terdekat
// agar perbaikan kartu persetujuan tidak menukar bug: kartu kredensial harus
// tetap muncul, dan balasan biasa harus tetap jadi bubble asisten.
test("requires_credential: kartu form kredensial tetap dirender", async ({ page }) => {
  test.setTimeout(120000);
  await stubApi(page);
  await sendPrompt(page, "munculkan vault supabase, isi kredensialnya");
  await expect(page.getByTestId("credential-form-submit").last()).toBeVisible({ timeout: 30000 });
});

test("success: balasan biasa tetap tampil sebagai bubble asisten", async ({ page }) => {
  test.setTimeout(120000);
  await stubApi(page);
  await sendPrompt(page, "halo, apa kabar");
  await expect(page.getByText("Baik.").last()).toBeVisible({ timeout: 30000 });
});

test("needs_spec: pesan backend diteruskan apa adanya", async ({ page }) => {
  test.setTimeout(120000);
  await stubApi(page);
  await sendPrompt(page, "buat workflow, spesifikasi menyusul");
  await expect(
    page.getByText("Workflow butuh node & edge lengkap sebelum bisa dibuat.").last(),
  ).toBeVisible({ timeout: 30000 });

  await page.screenshot({ path: shot("needs-spec"), fullPage: true });
  console.log(`SHOT=${SHOT}-needs-spec.png`);
});
