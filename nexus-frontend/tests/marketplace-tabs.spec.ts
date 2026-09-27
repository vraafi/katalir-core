/**
 * F2.3 — marketplace source tabs.
 *
 * The page must expose one tab per real `source` value the registry reports, and
 * every tab must show a NON-ZERO count. A tab whose key is missing from
 * /mcp/registry/sources renders "(0)", which is indistinguishable from "this
 * source is empty" — so asserting the tab exists is not enough, the count is
 * the part that catches a half-wired tab.
 *
 * Harness: `playwright.dev.config.ts` (dev :3000, backend :8000).
 */
import { test, expect } from "@playwright/test";
import { skipIfBackendDown } from "./helpers/backend";

test.beforeEach(async ({ request }) => {
  await skipIfBackendDown(request);
});

const API_ORIGIN = process.env.E2E_BACKEND_URL || "http://127.0.0.1:8000";

/** Must match the real `source` keys returned by mcp_registry.source_counts(). */
const TABS: Array<{ key: string; label: string }> = [
  { key: "all", label: "All" },
  { key: "native", label: "Native MCP" },
  { key: "glama", label: "Glama" },
  { key: "glama-connector", label: "Glama Connector" },
  { key: "openconnector", label: "OpenConnector" },
  { key: "composio", label: "Composio" },
  { key: "toolsdk", label: "ToolSDK" },
  { key: "openapi-generated", label: "OpenAPI" },
  { key: "nango", label: "Nango (OAuth)" },
  { key: "metorial", label: "Metorial" },
];

/** id-ID grouping, which is what the UI renders. */
function parseCount(label: string): number {
  const m = label.match(/\(([\d.,]+)\)/);
  return m ? Number(m[1].replace(/\./g, "")) : 0;
}

test.describe("F2.3 marketplace source tabs", () => {
  test("backend exposes every source key the tabs filter on", async ({ request }) => {
    const res = await request.get(`${API_ORIGIN}/mcp/registry/sources`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    const sources = body.sources ?? {};
    const sourcesUnique = body.sources_unique ?? {};
    for (const k of TABS.map((t) => t.key).filter((k) => k !== "all" && k !== "native")) {
      expect(sources, `source key "${k}" missing from /mcp/registry/sources`).toHaveProperty(k);
      expect(
        sourcesUnique,
        `source key "${k}" missing from sources_unique`,
      ).toHaveProperty(k);
    }
  });

  test("dedup toggle: unique is strictly smaller and tab counts follow the view", async ({ request }) => {
    const all = await (await request.get(`${API_ORIGIN}/mcp/registry?view=all&limit=1`)).json();
    const uniq = await (await request.get(`${API_ORIGIN}/mcp/registry?view=unique&limit=1`)).json();

    expect(uniq.total).toBeGreaterThan(0);
    expect(uniq.total).toBeLessThan(all.total);
    expect(all.total - uniq.total).toBeGreaterThan(0);

    // a tab count must equal the grid it filters, in BOTH views
    const src = await (await request.get(`${API_ORIGIN}/mcp/registry/sources`)).json();
    for (const [view, pool] of [
      ["all", src.sources],
      ["unique", src.sources_unique],
    ] as const) {
      for (const k of ["glama", "glama-connector", "composio", "toolsdk", "nango", "metorial"]) {
        const grid = await (
          await request.get(`${API_ORIGIN}/mcp/registry?view=${view}&limit=1&source=${k}`)
        ).json();
        expect(grid.total, `view=${view} source=${k} grid ${grid.total} != tab ${pool[k]}`).toBe(
          pool[k],
        );
      }
    }
  });

  test("an unknown view is rejected rather than silently falling back", async ({ request }) => {
    const res = await request.get(`${API_ORIGIN}/mcp/registry?view=bogus`);
    expect(res.status()).toBe(400);
  });

  test("runtime badge shows the four real tiers, not a merged one", async ({ page }) => {
    await page.goto("/integrations", { waitUntil: "load" });
    await page.waitForSelector('[data-testid^="source-tab-"]');
    await page.getByTestId("source-tab-glama-connector").click();
    await expect(page.getByTestId("source-tab-glama-connector")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect
      .poll(async () => page.locator('[data-testid^="badge-"]').count(), { timeout: 20_000 })
      .toBeGreaterThan(0);

    // every badge must be one of the four named tiers
    const labels = await page
      .locator('[data-testid^="badge-"]')
      .evaluateAll((els) => els.map((e) => e.textContent?.trim() ?? ""));
    const allowed = new Set(["call_verified", "auth_required", "tools_listed", "discovered"]);
    for (const l of labels) expect(allowed, `unexpected badge label "${l}"`).toContain(l);
    // the collapsed "Ready"/"Auth required"/"Catalog" wording must be gone
    expect(labels.some((l) => l === "Ready" || l === "Catalog")).toBe(false);
  });

  test("dedup toggle is clickable and re-renders the grid", async ({ page }) => {
    await page.goto("/integrations", { waitUntil: "load" });
    await page.waitForSelector('[data-testid="view-toggle-all"]');
    await expect(page.getByTestId("view-toggle-all")).toHaveAttribute("aria-pressed", "true");

    const before = await page.getByTestId("view-hint").innerText();
    await page.getByTestId("view-toggle-unique").click();
    await expect(page.getByTestId("view-toggle-unique")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("view-toggle-all")).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("view-hint")).not.toHaveText(before);
    await expect(page.getByTestId("integration-card").first()).toBeVisible();
  });

  test("8 tabs render, each with a non-zero count", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));

    await page.goto("/integrations", { waitUntil: "load" });
    await page.waitForSelector('[data-testid^="source-tab-"]');

    const tabs = page.getByRole("tab");
    await expect(tabs).toHaveCount(TABS.length);

    for (const t of TABS) {
      const tab = page.getByTestId(`source-tab-${t.key}`);
      await expect(tab, `tab ${t.key} missing`).toBeVisible();
      // The tabs render before /mcp/registry/sources resolves, so a one-shot
      // read would catch the initial "(0)" and report a false failure. Poll.
      await expect
        .poll(async () => parseCount((await tab.innerText()) ?? ""), {
          message: `tab ${t.key} (${t.label}) never showed a non-zero count`,
          timeout: 20_000,
        })
        .toBeGreaterThan(0);
    }
    expect(errors, errors.join("\n")).toHaveLength(0);
  });

  test("clicking a tab filters the grid and swaps the note", async ({ page }) => {
    await page.goto("/integrations", { waitUntil: "load" });
    await page.waitForSelector('[data-testid^="source-tab-"]');

    await page.getByTestId("source-tab-openapi-generated").click();
    await expect(page.getByTestId("source-tab-openapi-generated")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("tab-note")).toContainText("OpenAPI");

    // Poll the count first: reading it once can catch the pre-fetch "(0)" and
    // then assert against a number the page has not settled on yet.
    const tab = page.getByTestId("source-tab-openapi-generated");
    await expect
      .poll(async () => parseCount((await tab.innerText()) ?? ""), { timeout: 20_000 })
      .toBeGreaterThan(0);
    const openapiCount = parseCount(await tab.innerText());
    await expect(page.getByTestId("integration-card")).toHaveCount(openapiCount);
  });
});
