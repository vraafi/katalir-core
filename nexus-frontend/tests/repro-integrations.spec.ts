import { test, expect } from "@playwright/test";

/**
 * Verifikasi produksi: halaman `/integrations` tidak lagi menampilkan
 * "Registry tidak dapat dimuat" dan tab source punya angka != 0.
 *
 * Halaman ini auth-gated, jadi test memakai sesi dummy yang dibuat lokal
 * (semua endpoint di-stub, tidak ada kredensial nyata). Yang diverifikasi
 * di sini adalah render dari data registry produksi yang asli.
 */
const TARGET = process.env.E2E_TARGET || "https://katalir.de5.net";

function dummySession() {
  const b64 = (o: unknown) =>
    Buffer.from(JSON.stringify(o)).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const now = Math.floor(Date.now() / 1000);
  return {
    access_token: `${b64({ alg: "HS256", typ: "JWT" })}.${b64({
      sub: "00000000-0000-0000-0000-000000000002",
      aud: "authenticated",
      role: "authenticated",
      exp: now + 60 * 60 * 24 * 365,
      iat: now,
      email: "e2e-verify@local.test",
      user_metadata: {},
    })}.local-tests-only`,
    token_type: "bearer",
    expires_in: 60 * 60 * 24 * 365,
    expires_at: now + 60 * 60 * 24 * 365,
    refresh_token: "local-tests-only",
    user: { id: "00000000-0000-0000-0000-000000000002", email: "e2e-verify@local.test" },
  };
}

test("registry termuat di produksi: tanpa error, source counts != 0", async ({ page }) => {
  test.setTimeout(120000);
  const calls: string[] = [];
  page.on("response", (r) => {
    if (r.url().includes("/mcp/registry")) calls.push(`${r.status()} ${r.url()}`);
  });
  await page.addInitScript((sess: string) => {
    try {
      window.localStorage.setItem("sb-qmukkphwaajzbqjrcvaz-auth-token", sess);
      window.localStorage.setItem("katalir.locale.v1", "id");
      window.localStorage.setItem("katalir.onboarding.v1", "done");
    } catch {
      /* abaikan */
    }
  }, JSON.stringify(dummySession()));

  await page.goto(`${TARGET}/integrations`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 60000 });
  await page.waitForTimeout(9000);

  const body = (await page.locator("body").innerText()).replace(/\s+/g, " ");
  console.log(`API_CALLS=${calls.length}`);
  for (const c of [...new Set(calls)]) console.log(`API=${c}`);
  console.log(`HAS_ERROR_MSG=${/Registry tidak dapat dimuat/.test(body)}`);
  console.log(`HAS_NATIVE_TAB=/Native MCP \((\d+)\)/.test(body)}`);
  const m = /Native MCP \((\d+)\)/.exec(body);
  if (m) console.log(`NATIVE_COUNT=${m[1]}`);

  await page.screenshot({ path: "integrations-live.png", fullPage: true });
  console.log("SHOT=integrations-live.png");

  expect(body).not.toContain("Registry tidak dapat dimuat");
  expect(Number(m?.[1] ?? 0)).toBeGreaterThan(0);
});
