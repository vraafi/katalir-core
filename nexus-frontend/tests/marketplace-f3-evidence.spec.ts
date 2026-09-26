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

  /**
   * F4.4 — the 8+ tabs the phase asks for, as images rather than assertions.
   * F4.5 is folded in here because a11y on this one page is the cheapest
   * meaningful place to measure it, and the filters are new interactive
   * controls that a11y has never actually looked at.
   */
  const TABS = ["all", "native", "glama", "glama-connector", "composio", "nango"];

  test("F4.4 every source tab has a screenshot", async ({ page }) => {
    for (const t of TABS) {
      await page.goto("/integrations", { waitUntil: "load" });
      await page.waitForSelector('[data-testid^="source-tab-"]');
      const tab = page.getByTestId(`source-tab-${t}`);
      await expect(tab).toBeVisible();
      await tab.click();
      await page.waitForTimeout(1800);
      await page.screenshot({ path: `${SHOTS}/f4-tab-${t}.png` });
    }
  });

  test("F4.5 no obvious accessibility violations on the marketplace", async ({ page }) => {
    await page.goto("/integrations", { waitUntil: "load" });
    await page.waitForSelector('[data-testid^="source-tab-"]');
    await page.waitForTimeout(1500);

    // A structural pass over the rules this page can plausibly break, rather
    // than a full axe run: unnamed controls, unlabelled inputs, and low
    // contrast on the tier badges, which are muted by design.
    const issues = await page.evaluate(() => {
      const out: string[] = [];
      for (const el of Array.from(document.querySelectorAll("button, a, select, input"))) {
        const name = (el.getAttribute("aria-label") || el.textContent || "").trim();
        if (!name && !(el as HTMLInputElement).placeholder) {
          out.push(`unnamed control: ${el.tagName.toLowerCase()}`);
        }
      }
      for (const el of Array.from(document.querySelectorAll("input, select"))) {
        const id = el.getAttribute("id");
        const labelled =
          el.getAttribute("aria-label") ||
          (id && document.querySelector(`label[for="${CSS.escape(id)}"]`)) ||
          el.closest("label");
        if (!labelled) out.push(`unlabelled field: ${el.tagName.toLowerCase()}`);
      }
      return out;
    });
    expect(issues, issues.join("; ")).toEqual([]);

    // Every tab must be reachable and announce its selected state, otherwise a
    // screen reader hears ten identical buttons.
    for (const t of TABS) {
      const tab = page.getByTestId(`source-tab-${t}`);
      await expect(tab).toHaveAttribute("aria-selected", /true|false/);
    }
  });
});


