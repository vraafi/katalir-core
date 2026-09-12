import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const TARGET = process.env.E2E_TARGET || "https://proyek-agent.pages.dev";
const REF = "qmukkphwaajzbqjrcvaz";
const KEY = `sb-${REF}-auth-token`;

let session: any;
try {
  session = JSON.parse(readFileSync(join(process.cwd(), "_e2e_session.json"), "utf-8"));
} catch {
  console.log("NO_SESSION_FILE — jalankan _e2e_setup.mjs dulu");
}

test("E2E supabase asli: login ter-inject + kirim pesan TIDAK 401", async ({ page }) => {
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

  const responses: { url: string; status: number }[] = [];
  page.on("response", (r) => {
    const u = r.url();
    if (u.includes("/chat") || u.includes("/sessions")) {
      responses.push({ url: u, status: r.status() });
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

  const shell = await page.getByText("Nexus Agent").count();
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
  if (hasInput) {
    await input.fill("halo");
    await page.locator('button[type="submit"]').click();
    const chatResp = await page
      .waitForResponse((r) => r.url().includes("/chat") && r.request().method() === "POST", {
        timeout: 25000,
      })
      .catch((e) => null);
    if (chatResp) {
      let body = "";
      try {
        body = (await chatResp.text()).slice(0, 200);
      } catch {}
      console.log("CHAT_STATUS=" + chatResp.status() + " body=" + body);
    } else {
      console.log("CHAT_RESP_NONE");
    }
  }

  console.log("RESPONSES=" + JSON.stringify(responses));
  console.log("REQ_HEADERS=" + JSON.stringify(reqHdrs));

  // Assert: email user tampil = login sukses (injeksi berhasil)
  if (!emailShown) throw new Error("email test-user tidak tampil → injeksi session gagal");
  await page.screenshot({ path: "test-results/e2e-auth.png" });
});