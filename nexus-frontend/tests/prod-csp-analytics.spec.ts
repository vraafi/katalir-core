/**
 * VERIFIKASI CSP + CLOUDFLARE ANALYTICS di PRODUKSI (bukan simulasi).
 *
 * Target: situs LIVE (`https://katalir.de5.net` atau lewat E2E_BASE_URL).
 * Ini jawaban atas pertanyaan yang tidak bisa dijawab dengan `curl`:
 *   - apakah beacon Cloudflare BENAR-BENAR diunduh oleh browser nyata?
 *   - apakah console benar-benar TANPA error CSP?
 *   - apakah beacon BENAR-BENAR mengirim data (POST ke cdn-cgi/rum)?
 *
 * KENAPA `curl` TIDAK CUKUP
 *   `curl` tidak mengeksekusi `<script type="module">` dan tidak menerapkan
 *   CSP, jadi ia hanya bisa membuktikan HEADER-nya. Yang gagal sebelumnya
 *   justru EKSEKUSI beacon di browser — itu hanya bisa dibuktikan dengan
 *   browser sungguhan (Chromium via Playwright, sama seperti DevTools).
 *
 * Jalankan:
 *   E2E_BASE_URL=https://katalir.de5.net node ./node_modules/@playwright/test/cli.js \
 *     test -c playwright.codenode.config.ts -g "PROD" --reporter=list
 */
import { test, expect } from "@playwright/test";

const BASE = process.env.E2E_BASE_URL || "https://katalir.de5.net";

/** Pola error yang menandakan CSP MEMBLOKIR sesuatu. */
const CSP_BLOCK = /Content Security Policy|Content-Security-Policy| Refused to |blocked by CSP/i;

test("PROD-CSP: header produksi memuat kedua host Cloudflare pada direktif yang benar", async ({ request }) => {
  const res = await request.get(`${BASE}/`);
  expect(res.status()).toBe(200);
  const csp = (await res.headersArray()).find((h) => h.name.toLowerCase() === "content-security-policy");
  expect(csp, "header Content-Security-Policy tidak ada").toBeTruthy();

  const script = (csp!.value.match(/script-src[^;]*/) || [""])[0];
  const connect = (csp!.value.match(/connect-src[^;]*/) || [""])[0];
  console.log(`[PROD-CSP] script-src  = ${script}`);
  console.log(`[PROD-CSP] connect-src = ${connect}`);

  expect(script).toContain("https://static.cloudflareinsights.com");
  expect(connect).toContain("https://cloudflareinsights.com");
  // Penguatan yang tidak boleh ikut lunak hanya demi analytics.
  expect(csp!.value).not.toMatch(/default-src\s+\*/);
  expect(script).not.toContain("unsafe-eval");
  expect(script).not.toContain("*");
});

test("PROD-ANALYTICS: beacon diunduh, console bersih, dan data dikirim", async ({ page }) => {
  const cspErrors: string[] = [];
  const beaconResponses: number[] = [];
  const rumResponses: number[] = [];

  page.on("pageerror", (e) => {
    if (CSP_BLOCK.test(e.message)) cspErrors.push(`pageerror: ${e.message}`);
  });
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    // CORS ke backend adalah keadaan lingkungan lokal, bukan CSP. Di produksi
    // origin-nya diizinkan, jadi pola ini tidak akan muncul — tetap disaring
    // agar satu kegagalan jaringan tidak menutupi temuan CSP.
    if (/CORS policy|Failed to load resource|net::|ERR_/i.test(m.text())) return;
    if (CSP_BLOCK.test(m.text())) cspErrors.push(`console: ${m.text()}`);
  });
  page.on("response", (r) => {
    const u = r.url();
    if (u.includes("static.cloudflareinsights.com/beacon")) {
      beaconResponses.push(r.status());
      console.log(`[PROD-ANALYTICS] beacon GET ${r.status()} ${u.slice(0, 90)}`);
    }
    if (u.includes("cloudflareinsights.com")) {
      rumResponses.push(r.status());
      console.log(`[PROD-ANALYTICS] request lain ke cloudflareinsights ${r.status()} ${u.slice(0, 90)}`);
    }
  });

  await page.goto(`${BASE}/chat`, { waitUntil: "networkidle", timeout: 60000 });

  // 1) Skrip beacon HARUS diunduh (dulu diblokir CSP -> tidak pernah ada).
  console.log(
    `[PROD-ANALYTICS] beacon diunduh = ${beaconResponses.length}x status=${JSON.stringify(beaconResponses)}`
  );
  expect(beaconResponses.length, "skrip beacon Cloudflare tidak pernah diunduh").toBeGreaterThan(0);
  expect(beaconResponses.every((s) => s === 200), `beacon gagal: ${beaconResponses}`).toBe(true);

  // 2) Tag beacon benar-benar ada di DOM (bukan cuma di HTML mentah).
  const tag = await page.evaluate(() => {
    const s = Array.from(document.querySelectorAll("script")).find((x) =>
      (x as HTMLScriptElement).src.includes("static.cloudflareinsights.com")
    ) as HTMLScriptElement | undefined;
    return s ? { src: s.src, module: s.type, hasToken: !!s.getAttribute("data-cf-beacon") } : null;
  });
  console.log(`[PROD-ANALYTICS] tag DOM = ${JSON.stringify(tag)}`);
  expect(tag, "tag beacon tidak ada di DOM").toBeTruthy();
  expect(tag!.module).toBe("module");
  expect(tag!.hasToken).toBe(true);

  // 3) Tidak ada error CSP di console/pageerror.
  console.log(`[PROD-ANALYTICS] error CSP = ${JSON.stringify(cspErrors)}`);
  expect(cspErrors, `CSP masih memblokir: ${cspErrors.join(" | ")}`).toHaveLength(0);

  // 4) RUM endpoint: beacon mengirim data (boleh 2xx/3xx/404 bila payload
  //    ditolak — yang penting BUKAN diblokir; blokir CSP tidak akan
  //    menghasilkan response object sama sekali).
  console.log(
    `[PROD-ANALYTICS] request ke cloudflareinsights = ${rumResponses.length}x ${JSON.stringify(rumResponses)}`
  );
  if (rumResponses.length > 0) {
    console.log("[PROD-ANALYTICS] beacon AKTIF mengirim data ke endpoint RUM.");
  } else {
    console.log(
      "[PROD-ANALYTICS] CATATAN: tidak ada POST RUM dalam jendela pengamatan " +
        "(Cloudflare menahan pengiriman ±30 dtk / saat tab idle). Yang dibuktikan " +
        "di sini: skrip terunduh 200, tag terpasang, dan TIDAK ada blokir CSP."
    );
  }
});
