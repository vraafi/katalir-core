import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// Axe audit against the DEPLOYED site, not the dev server: the point of the
// check is what a visitor actually receives. Runs against production by
// default; set AXE_TARGET=http://127.0.0.1:3000 to audit a local build.
const BASE = (process.env.AXE_TARGET || "https://katalir.de5.net").replace(/\/$/, "");
const ROUTES = ["/", "/chat", "/builder", "/settings", "/pricing", "/docs"];

// 401/redirect-to-login is a legitimate state for a signed-out visitor; a page
// that fails to render at all is not. Anything that is not a 200 is reported
// with its status so a 404 is never mistaken for a clean a11y pass.
for (const route of ROUTES) {
  test(`axe: ${route}`, async ({ page }) => {
    const res = await page.goto(BASE + route, { waitUntil: "load", timeout: 90_000 });
    const status = res?.status() ?? 0;
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    // Let client-rendered content settle so we do not scan a half-built DOM.
    await page.waitForTimeout(1200);

    const results = await new AxeBuilder({ page }).analyze();
    const blocking = results.violations.filter(
      (v) => v.impact === "critical" || v.impact === "serious",
    );

    const detail = blocking.map((v) => ({
      id: v.id,
      impact: v.impact,
      nodes: v.nodes.length,
      help: v.help,
      target: v.nodes.slice(0, 3).map((n) => n.target.join(" ")),
    }));

    console.log(
      `AXE ${route} status=${status} total=${results.violations.length} blocking=${blocking.length}`,
    );
    if (results.violations.length) {
      console.log(
        `AXE_ALL ${route} ${JSON.stringify(
          results.violations.map((v) => ({ id: v.id, impact: v.impact, n: v.nodes.length })),
        )}`,
      );
    }
    expect(detail, `blocking a11y violations on ${route} @ ${status}`).toEqual([]);
  });
}