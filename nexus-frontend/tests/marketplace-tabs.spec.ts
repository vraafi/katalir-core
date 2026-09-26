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
    for (const k of TABS.map((t) => t.key).filter((k) => k !== "all" && k !== "native")) {
      expect(sources, `source key "${k}" missing from /mcp/registry/sources`).toHaveProperty(k);
    }
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

    // the OpenAPI source is small, so the filtered grid must agree with its count
    const openapiCount = parseCount(await page.getByTestId("source-tab-openapi-generated").innerText());
    await expect(page.getByTestId("integration-card")).toHaveCount(openapiCount);
  });
});
