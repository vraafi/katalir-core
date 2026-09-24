import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const routes = ["/", "/chat", "/builder", "/settings", "/billing", "/help"];
const out = join(process.cwd(), "test-results", "live-verify");
mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
let failures = 0;
for (const route of routes) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(`PAGEERROR: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error") errors.push(`CONSOLE: ${m.text()}`); });
  page.on("requestfailed", (r) => errors.push(`REQFAIL: ${r.url()} ${r.failure()?.errorText ?? ""}`));
  try {
    await page.goto(`http://localhost:3000${route}`, { waitUntil: "networkidle", timeout: 30000 });
    await page.waitForTimeout(1500);
    const body = await page.locator("body").innerText();
    const crash = /__webpack_modules__|Runtime TypeError/i.test(body);
    // /chat is intentionally a short unauthenticated empty state; >150 is the
    // non-blank guard. The real runtime gates are errors and webpack crash.
    if (body.length <= 150 || errors.length || crash) failures++;
    console.log(`${route} BODY=${body.length} ERRORS=${errors.length} CRASH=${crash}`);
    errors.slice(0, 3).forEach((e) => console.log(`  ${e.slice(0, 200)}`));
  } catch (e) {
    failures++;
    console.log(`${route} BODY=0 ERRORS=1 CRASH=false PROBE=${String(e).slice(0, 200)}`);
  }
  await page.screenshot({ path: join(out, `${route === "/" ? "root" : route.slice(1)}.png`), fullPage: true });
  await page.close();
}
console.log(`LIVE_ROUTES=${routes.length} LIVE_FAILURES=${failures}`);
await browser.close();
process.exitCode = failures ? 1 : 0;
