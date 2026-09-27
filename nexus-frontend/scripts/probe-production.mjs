/**
 * Production evidence for the login modal (F9/F7 release check).
 *
 * Opens the real site, clicks the landing CTA, and screenshots the modal on
 * desktop and mobile, plus a post-OAuth screenshot of the callback route.
 *
 * WHAT THIS DOES NOT PROVE: a real GitHub/Google authorisation. That needs a
 * human to complete the provider consent screen with a real account. This
 * probe proves the modal renders, the three options are present and
 * labelled, and that the OAuth start issues a redirect to the real provider
 * (the redirect is asserted; the consent screen is not completed).
 */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const base = process.env.PROD_BASE || "https://katalir.de5.net";
const out = join(process.cwd(), "test-results", "login-prod");
mkdirSync(out, { recursive: true });

const VIEWPORTS = [
  { name: "desktop", width: 1280, height: 900 },
  { name: "mobile", width: 390, height: 844 },
];

const browser = await chromium.launch();
let failures = 0;

for (const vp of VIEWPORTS) {
  const page = await browser.newPage({
    viewport: { width: vp.width, height: vp.height },
  });
  const consoleErrors = [];
  page.on("pageerror", (e) => consoleErrors.push(`PAGEERROR:${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(`CONSOLE:${m.text()}`);
  });

  await page.goto(base + "/", { waitUntil: "networkidle", timeout: 45000 });
  await page.waitForTimeout(1200);

  // The modal trigger on the landing page. NOTE this is NOT `landing-cta`,
  // which is a plain <Link href="/chat"> navigation - clicking it correctly
  // leaves the landing page, so it can never open the modal.
  const cta = page.locator('[data-testid="landing-signin-trigger"]');
  await cta.click();
  await page.waitForTimeout(700);

  const dialog = page.getByRole("dialog");
  const visible = await dialog.isVisible().catch(() => false);
  const text = visible ? await dialog.innerText() : "";

  // The three auth options the release criteria require.
  const github = await dialog
    .locator('[data-testid="login-github"]')
    .isVisible()
    .catch(() => false);
  const google = await dialog
    .locator('[data-testid="login-google"]')
    .isVisible()
    .catch(() => false);
  const emailField = await dialog
    .locator('[data-testid="login-email"]')
    .isVisible()
    .catch(() => false);

  // Centring: the dialog must be horizontally centred within 24px.
  const vw = vp.width;
  const box = visible ? await dialog.boundingBox() : null;
  const offCentre = box ? Math.abs((box.x + box.width / 2) - vw / 2) : -1;

  await page.screenshot({
    path: join(out, `login-modal-${vp.name}.png`),
    fullPage: false,
  });

  const ok = visible && github && google && emailField && offCentre >= 0 && offCentre <= 24;
  if (!ok) failures += 1;
  console.log(
    `MODAL_${vp.name.toUpperCase()} dialog=${visible} github=${github} google=${google} ` +
      `email=${emailField} offCentrePx=${offCentre.toFixed(1)} consoleErrors=${consoleErrors.length} ${ok ? "OK" : "FAIL"}`
  );
  if (!ok) console.log(`  visibleText=${text.slice(0, 200).replace(/\n/g, " | ")}`);
  consoleErrors.slice(0, 3).forEach((e) => console.log(`  ${e.slice(0, 200)}`));

  // OAuth start: confirm the app hands off to the REAL provider endpoint.
  // We do NOT complete the consent screen - that needs a real account.
  if (vp.name === "desktop") {
    for (const [testid, host] of [
      ["login-github", "github.com"],
      ["login-google", "accounts.google.com"],
    ]) {
      const [nav] = await Promise.all([
        Promise.all([
          page.waitForRequest(/oauth|authorize/i, { timeout: 8000 }).catch(() => null),
        ]).then((r) => r[0]),
        page.locator(`[data-testid="${testid}"]`).click().catch(() => null),
      ]);
      await page.waitForTimeout(2500);
      const url = page.url();
      const redirected = url.includes(host);
      if (!redirected) failures += 1;
      console.log(
        `OAUTH_${testid} host=${host} redirected=${redirected} ${redirected ? "OK" : "FAIL"} url=${url.slice(0, 90)}`
      );
      if (redirected) {
        await page.screenshot({ path: join(out, `oauth-${testid}.png`) });
      }
      await page.goto(base + "/", { waitUntil: "networkidle" });
      await page.waitForTimeout(600);
      await page.locator('[data-testid="landing-signin-trigger"]').click();
      await page.waitForTimeout(500);
    }
  }

  await page.close();
}

await browser.close();
console.log(`PROD_LOGIN_FAILURES=${failures}`);
process.exitCode = failures ? 1 : 0;
