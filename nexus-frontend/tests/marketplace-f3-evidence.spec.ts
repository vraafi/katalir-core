import { test, expect } from "@playwright/test";

/**
 * F3.5 visual evidence for the marketplace.
 *
 * This captures structure a number cannot: that the 10 tabs, the All/Unique
 * toggle and the 4 runtime tiers are actually rendered and legible. The
 * behavioural contract is already asserted in marketplace-tabs.spec.ts, so
 * nothing here re-tests that - it is the screenshot artefact F3.5 asks for.
 */
const SHOTS = "f3-shots";

test.describe("F3 marketplace evidence", () => {
  test.setTimeout(120_000);

  test("desktop: 10 tabs, toggle changes the rendered total, tiers are real", async ({ page }) => {
    await page.goto("/integrations", { waitUntil: "load" });
    await page.waitForSelector('[data-testid^="source-tab-"]');
    await expect(page.getByRole("tab")).toHaveCount(10);

    await page.waitForSelector('[data-testid="view-toggle-all"]');
    await expect(page.getByTestId("view-toggle-all")).toHaveAttribute("aria-pressed", "true");
    const rawHint = await page.getByTestId("view-hint").innerText();

    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${SHOTS}/f3-desktop-all.png` });

    // The toggle must change real state, not just repaint the same numbers.
    await page.getByTestId("view-toggle-unique").click();
    await expect(page.getByTestId("view-hint")).not.toHaveText(rawHint);
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${SHOTS}/f3-desktop-unique.png` });

    // And a tier badge has to be on screen under one of the four real names.
    const badges = page.locator('[data-testid^="badge-"]');
    await expect
      .poll(async () => badges.count(), { timeout: 20_000 })
      .toBeGreaterThan(0);
    const labels = await badges.evaluateAll((els) => els.map((e) => e.textContent?.trim() ?? ""));
    const allowed = new Set(["call_verified", "auth_required", "tools_listed", "discovered"]);
    for (const l of labels) expect(allowed, `unexpected tier "${l}"`).toContain(l);

    // A Nango tab exists only because the sync really ran; prove it is clickable.
    await page.getByTestId("source-tab-nango").click();
    await expect(page.getByTestId("source-tab-nango")).toHaveAttribute("aria-selected", "true");
    await page.waitForTimeout(1200);
    await page.screenshot({ path: `${SHOTS}/f3-desktop-nango.png` });
  });

  test("mobile: renders without horizontal overflow", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/integrations", { waitUntil: "load" });
    await page.waitForSelector('[data-testid^="source-tab-"]');
    await page.waitForTimeout(2000);
    await page.screenshot({ path: `${SHOTS}/f3-mobile.png` });

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(2);
  });
});

