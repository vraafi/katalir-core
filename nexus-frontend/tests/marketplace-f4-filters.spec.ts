/**
 * F4.3 — category and runtime-tier filters.
 *
 * The assertion that carries the weight is the first one: a filter that
 * disagrees with the badge is worse than no filter, because the user clicks
 * "call_verified", gets N rows, and N rows are not the ones badged
 * call_verified. Everything else checks the controls exist and move real state.
 */
import { test, expect } from "@playwright/test";
import { skipIfBackendDown } from "./helpers/backend";

test.beforeEach(async ({ request }) => {
  await skipIfBackendDown(request);
});

const API_ORIGIN = process.env.E2E_BACKEND_URL || "http://127.0.0.1:8000";
const TIERS = ["call_verified", "auth_required", "tools_listed", "discovered"] as const;

test.describe("F4.3 filters", () => {
  test("tier filter returns only rows carrying that tier", async ({ request }) => {
    for (const tier of TIERS) {
      const res = await request.get(`${API_ORIGIN}/mcp/registry?view=all&limit=100&tier=${tier}`);
      expect(res.status(), `tier=${tier}`).toBe(200);
      const body = await res.json();
      for (const item of body.items ?? []) {
        // The backend must agree with itself before the UI is even involved.
        expect(item.runtime_tier, `${item.id} filtered under ${tier}`).toBe(tier);
      }
    }
  });

  test("tiers partition the catalogue with no gaps and no double counting", async ({ request }) => {
    const all = await (await request.get(`${API_ORIGIN}/mcp/registry?view=all&limit=1`)).json();
    let sum = 0;
    for (const tier of TIERS) {
      const b = await (await request.get(`${API_ORIGIN}/mcp/registry?view=all&limit=1&tier=${tier}`)).json();
      sum += b.total;
    }
    // Every row belongs to exactly one tier, so the four counts must add up to
    // the catalogue. If they do not, some rows fall through unclassified.
    expect(sum).toBe(all.total);
  });

  test("an unknown tier is a 400, not a silent empty result", async ({ request }) => {
    const res = await request.get(`${API_ORIGIN}/mcp/registry?view=all&tier=bogus`);
    expect(res.status()).toBe(400);
  });

  test("category facet only offers categories that have rows", async ({ request }) => {
    const facets = await (await request.get(`${API_ORIGIN}/mcp/registry/categories?limit=25`)).json();
    expect(facets.categories.length).toBeGreaterThan(0);
    for (const c of facets.categories.slice(0, 8)) {
      const grid = await (
        await request.get(`${API_ORIGIN}/mcp/registry?view=all&limit=1&category=${encodeURIComponent(c.category)}`)
      ).json();
      // A dropdown option that returns nothing is a dead control.
      expect(grid.total, `category "${c.category}" offered but yields ${grid.total} rows`).toBe(c.count);
    }
  });

  test("tier and category compose rather than overwrite", async ({ request }) => {
    const t = await (await request.get(`${API_ORIGIN}/mcp/registry?view=all&limit=1&tier=discovered`)).json();
    const f = await (await request.get(`${API_ORIGIN}/mcp/registry/categories?limit=1`)).json();
    const cat = f.categories[0].category;
    const both = await (
      await request.get(`${API_ORIGIN}/mcp/registry?view=all&limit=1&tier=discovered&category=${encodeURIComponent(cat)}`)
    ).json();
    expect(both.total).toBeLessThanOrEqual(t.total);
    const got = await (
      await request.get(`${API_ORIGIN}/mcp/registry?view=all&limit=50&tier=discovered&category=${encodeURIComponent(cat)}`)
    ).json();
    for (const item of got.items ?? []) {
      expect(item.runtime_tier).toBe("discovered");
      expect(String(item.category)).toBe(cat);
    }
  });

  test("the UI exposes both filters and the tier filter narrows the grid", async ({ page }) => {
    await page.goto("/integrations", { waitUntil: "load" });
    await page.waitForSelector('[data-testid^="source-tab-"]');
    await expect(page.getByTestId("integrations-filters")).toBeVisible();
    await expect(page.getByTestId("category-filter")).toBeVisible();
    for (const tier of TIERS) {
      await expect(page.getByTestId(`tier-filter-${tier}`)).toBeVisible();
    }

    // The badge on screen must be the tier we just filtered by.
    await page.getByTestId("tier-filter-call_verified").click();
    await expect(page.getByTestId("tier-filter-call_verified")).toHaveAttribute("aria-pressed", "true");

    // The grid reloads asynchronously, so reading the badges immediately samples
    // the PREVIOUS render and proves nothing. Poll the whole set instead: it is
    // only settled once no badge disagrees with the filter. This failure was
    // real - an earlier version read "discovered" here, from the stale render.
    const badges = page.locator('[data-testid^="badge-"]');
    await expect
      .poll(
        async () => {
          const seen = await badges.evaluateAll((els) => els.map((e) => e.textContent?.trim() ?? ""));
          return seen.length > 0 && seen.every((l) => l === "call_verified");
        },
        { timeout: 25_000 },
      )
      .toBe(true);

    const labels = await badges.evaluateAll((els) => els.map((e) => e.textContent?.trim() ?? ""));
    expect(labels.length).toBeGreaterThan(0);
    for (const l of labels) expect(l).toBe("call_verified");

    await page.getByTestId("filters-clear").click();
    await expect(page.getByTestId("tier-filter-any")).toHaveAttribute("aria-pressed", "true");
  });

  test("a Nango card must not claim to be a Glama listing", async ({ page }) => {
    await page.goto("/integrations", { waitUntil: "load" });
    await page.waitForSelector('[data-testid^="source-tab-"]');
    await page.getByTestId("source-tab-nango").click();
    await expect(page.getByTestId("source-tab-nango")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("integration-card").first()).toBeVisible();

    // This was a real defect: every item with a source_url rendered the same
    // hardcoded "View on Glama ->" link, so all 1.024 Nango cards pointed at
    // Nango while claiming to be Glama listings. A link that names the wrong
    // vendor is worse than no link, because the reader trusts it.
    const links = page.getByTestId("attribution-link");
    // Wait for the filtered reload to land; reading count() immediately can
    // sample the previous tab's DOM and report a stale zero.
    await expect
      .poll(async () => links.count(), { timeout: 15_000 })
      .toBeGreaterThan(0);
    const n = await links.count();
    for (let i = 0; i < Math.min(n, 10); i++) {
      const text = (await links.nth(i).innerText()).trim();
      expect(text, `Nango card ${i} mislabels its source`).not.toBe("View on Glama →");
    }
  });

  test("Glama listings keep the licensed attribution link", async ({ page }) => {
    await page.goto("/integrations", { waitUntil: "load" });
    await page.waitForSelector('[data-testid^="source-tab-"]');
    await page.getByTestId("source-tab-glama").click();
    await expect(page.getByTestId("integration-card").first()).toBeVisible();

    // The nofollow/sponsored rel is a Glama Data License requirement, so the
    // fix above must not have quietly dropped it from the links that qualify.
    const link = page.getByTestId("attribution-link").first();
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("rel", /sponsored/);
  });
});
