import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const TARGET = process.env.E2E_TARGET || "https://proyek-agent.pages.dev";
const REF = "qmukkphwaajzbqjrcvaz";
const KEY = `sb-${REF}-auth-token`;
// Batas tunggu respons /chat. Latensi produksi terukur 20-30s (saat fallback
// Gemini lewat gateway bahkan ~49s), sedangkan nilai lama 25s membuat
// `waitForResponse` sering timeout -> `chatStatus` tetap -1 -> assertion 5xx
// di bawah TIDAK PERNAH dievaluasi (hijau palsu). 45s memberi margin tanpa
// membuat suite lambat (batas keras task: <= 60s).
const CHAT_WAIT_MS = 45000;

let session: any;
// PENTING: dahulukan `_e2e_session.refreshed.json` (ditulis globalSetup
// `scripts/e2e-auth-setup.mjs`). Sebelumnya spec ini hanya membaca
// `_e2e_session.json` yang bisa tertinggal berhari-hari (pernah exp -194087s),
// sehingga injeksi token mati -> aplikasi tidak menampilkan email -> gagal
// dengan pesan menyesatkan "injeksi session gagal" padahal injeksinya benar.
{
  const candidates = [
    "_e2e_session.refreshed.json",
    // `_e2e_session.extended.json` DIHAPUS dari kandidat (2026-09-16): file itu
    // berisi token dengan `exp` hasil suntingan lokal tanpa tanda tangan baru
    // (dibuat `_e2e_extend.py`), sehingga signature-nya TIDAK sah. Dulu spec ini
    // menerimanya -> 401 dari backend lokal dengan pesan menyesatkan, dan
    // `globalSetup` ikut menyebarkannya ke `_e2e_storage.json`. Kini `globalSetup`
    // memverifikasi signature terhadap JWKS dan menyingkirkannya otomatis.
    "_e2e_session.json",
  ];
  for (const f of candidates) {
    try {
      const s = JSON.parse(readFileSync(join(process.cwd(), f), "utf-8"));
      if (s?.access_token) {
        session = s;
        console.log(`SESSION_FILE=${f}`);
        break;
      }
    } catch {
      /* lanjut ke kandidat berikutnya */
    }
  }
  if (!session) console.log("NO_SESSION_FILE — jalankan node scripts/e2e-auth-setup.mjs dulu");
}

test("E2E supabase asli: login ter-inject + kirim pesan TIDAK 401 & TIDAK 5xx", async ({ page }) => {
  test.skip(!session, "session file tidak ada");

  // Inject session SEBELUM app script jalan (di page yang sama yang akan di-goto)
  await page.addInitScript(
    (kv) => {
      const { key, value } = kv as any;
      try {
        window.localStorage.setItem(key, JSON.stringify(value));
      } catch (e) {
        console.log("LS_ERR", String((e as any)?.message));
      }
    },
    { key: KEY, value: session }
  );

  // `method` ikut dicatat supaya status POST /chat masih bisa dipulihkan dari
  // sini bila `waitForResponse` kalah lomba dengan latensi upstream.
  const responses: { url: string; method: string; status: number }[] = [];
  page.on("response", (r) => {
    const u = r.url();
    if (u.includes("/chat") || u.includes("/sessions")) {
      responses.push({ url: u, method: r.request().method(), status: r.status() });
    }
  });
  // TANGKAP request headers untuk lihat Authorization
  const reqHdrs: { url: string; auth: string | null }[] = [];
  page.on("request", (req) => {
    const u = req.url();
    if (u.includes("/sessions") || u.includes("/chat")) {
      reqHdrs.push({ url: u.split("?")[0], auth: req.headers()["authorization"] ?? null });
    }
  });
  const perrs: string[] = [];
  page.on("pageerror", (e) => perrs.push(String(e as object)));
  const cons: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") cons.push(m.text().slice(0, 120));
  });

  await page.goto(TARGET + "/", { waitUntil: "domcontentloaded", timeout: 60000 }).catch((e) => {
    console.log("GOTO_ERR=" + String(e));
  });
  await page.waitForTimeout(4000);

  const shell = await page.getByText("Katalir").count();
  const input2 = await page.locator('[aria-label="Pesan"]').count();
  const bodyLen = await page.evaluate(() => document.body.innerText.length).catch(() => -1);
  const bodyText = await page.evaluate(() => document.body.innerText).catch(() => "");
  const ls = await page.evaluate(() => {
    const o: Record<string, string> = {};
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)!;
      o[k] = localStorage.getItem(k)!.slice(0, 40);
    }
    return o;
  }).catch(() => ({}));
  console.log("SHELL=" + shell + " INPUT=" + input2 + " BODYLEN=" + bodyLen);
  console.log("BODY=" + bodyText.slice(0, 220).replace(/\n+/g, " | "));
  console.log("LS=" + JSON.stringify(ls));
  console.log("PAGEERROR=" + JSON.stringify(perrs));
  console.log("CONSOLE_ERR=" + JSON.stringify(cons.slice(0, 5)));

  // email test-user tampil?
  const emailShown = await page.getByText(session.user.email).count();
  console.log("EMAIL_VISIBLE=" + emailShown);

  // isi input chat + kirim
  const input = page.locator('[aria-label="Pesan"]');
  const hasInput = await input.count();
  console.log("HAS_INPUT=" + hasInput);
  // Status /chat disimpan di luar blok supaya bisa di-ASSERT (bukan hanya di-log).
  let chatStatus = -1;
  let chatBody = "";
  if (hasInput) {
    await input.fill("halo");
    await page.locator('button[type="submit"]').click();
    const chatResp = await page
      .waitForResponse((r) => r.url().includes("/chat") && r.request().method() === "POST", {
        timeout: CHAT_WAIT_MS,
      })
      .catch((e) => null);
    if (chatResp) {
      chatStatus = chatResp.status();
      try {
        chatBody = (await chatResp.text()).slice(0, 200);
      } catch {}
      console.log("CHAT_STATUS=" + chatStatus + " body=" + chatBody);
    } else {
      // Fallback: respons bisa saja sudah lewat sebelum `waitForResponse`
      // sempat mencocokkannya. Ambil dari listener `page.on("response")`
      // daripada membiarkan `chatStatus=-1` (yang membuat assert di bawah vakum).
      const seen = responses.filter((r) => r.method === "POST" && r.url.includes("/chat"));
      if (seen.length) {
        chatStatus = seen[seen.length - 1].status;
        console.log("CHAT_STATUS_FROM_RESPONSES=" + chatStatus);
        // SPEC_ASSERT_v2: assertion NON-VAKUM (dulu spec hijau padahal /chat 500 / tak tertangkap)
        if (chatStatus === -1) {
          throw new Error("SPEK GAGAL: /chat tidak tertangkap (timeout waitForResponse) -> status tidak dinilai");
        }
        if (chatStatus !== 200 && chatStatus !== 503) {
          throw new Error(`SPEK GAGAL: /chat -> ${chatStatus}, harus 200 atau 503`);
        }
      } else {
        console.log("CHAT_RESP_NONE");
      }
    }
  }

  console.log("RESPONSES=" + JSON.stringify(responses));
  console.log("REQ_HEADERS=" + JSON.stringify(reqHdrs));

  // Assert: email user tampil = login sukses (injeksi berhasil)
  if (!emailShown) throw new Error("email test-user tidak tampil → injeksi session gagal");

  // Assert: `/chat` prod TIDAK boleh 5xx — KECUALI 503.
  // Sebelumnya spec ini HANYA memeriksa "email tampil" (dan dulu "bukan 401"),
  // sehingga **500 nyata lolos hijau**: Railway menjawab
  //   {"detail":"Terjadi kesalahan internal: AttributeError: module
  //    'google.genai.types' has no attribute 'HttpRetryOptions'"}
  // karena requirements.txt memasang google-genai 1.6.0.
  // 503 (`Model sedang sibuk (quota/overload)`) adalah kondisi upstream yang
  // WAJAR dan justru kontrak yang benar untuk kuota habis / upstream transien —
  // jadi yang DILARANG adalah 500/501/502/504/dst, bukan 503.
  // Assert #1: status harus KONKLUSIF. `-1` = respons tak tertangkap — dulu ini
  // dibiarkan lolos sehingga spec hijau tanpa memverifikasi apa pun.
  if (hasInput && chatStatus === -1) {
    throw new Error(
      `POST /chat tidak tertangkap dalam ${CHAT_WAIT_MS}ms (CHAT_RESP_NONE) — ` +
        "kegagalan harness, bukan bukti sehat. Periksa latensi upstream lalu ulangi."
    );
  }
  // Assert #2 (HARD, non-vakum): di titik ini `chatStatus` sudah pasti konkret
  // karena guard `-1` di atas sudah melempar lebih dulu. Sebelumnya blok ini
  // berbentuk `if (chatStatus >= 500 && chatStatus !== 503)` sehingga saat
  // request tidak tertangkap (`-1`) assertion-nya TIDAK PERNAH dievaluasi ->
  // spec hijau palsu. 200 = sukses, 503 = upstream transien (kontrak sah).
  console.log(`CHAT_STATUS=${chatStatus}`);
  expect(
    [200, 503],
    `POST /chat -> HTTP ${chatStatus} body=${chatBody}`
  ).toContain(chatStatus);

  await page.screenshot({ path: "test-results/e2e-auth.png" });
});
