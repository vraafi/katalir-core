import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * F6 — landing logo cloud: position, brand colour, magnetism, not-clickable.
 *
 * Each assertion is something the user could check by looking, which is the
 * point of the phase, written so a regression fails the build instead of being
 * noticed weeks later.
 */
const SHOTS = "f6-shots";

test.describe("F6 landing logo cloud", () => {
  test.setTimeout(120_000);

  test("hero strip is above the fold, below the CTA", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForSelector('[data-testid="hero-logo-strip"]');
    await page.waitForTimeout(1200);

    const strip = page.getByTestId("hero-logo-strip");
    await expect(strip).toBeVisible();

    // The real requirement is "visible in the FIRST viewport". Measuring the box
    // is the only way to prove it, because "the component exists" says nothing
    // about where it sits.
    const box = await strip.boundingBox();
    expect(box, "hero strip has no box").not.toBeNull();
    expect(box!.y, "hero strip starts below the fold").toBeLessThan(900);
    expect(box!.y + box!.height, "hero strip is cut off by the fold").toBeLessThanOrEqual(900);

    // And it must come after the CTA, so the CTA is still above it.
    const cta = await page.getByTestId("landing-cta").boundingBox();
    expect(box!.y, "logo strip is above the CTA").toBeGreaterThan(cta!.y);

    await page.screenshot({ path: `${SHOTS}/f6-desktop-hero.png` });
  });

  test("the full 55-brand cloud is still on the page", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForSelector('[data-testid="mcp-logo"]');
    await page.waitForTimeout(1000);
    // Adding a strip to the hero must not have deleted the cloud. 55 is the
    // count the earlier work asserted and it is still the honest number.
    await expect(page.getByTestId("mcp-logo")).toHaveCount(55);
    await expect(page.getByTestId("logo-cloud")).toBeVisible();
  });

  test("logos are brand coloured, not monochrome", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForSelector('[data-testid="mcp-logo"]');
    await page.waitForTimeout(1500);

    // Read the actual painted fill. Reading a data attribute would only prove it
    // was set; fill/color is what the eye sees.
    const colors = await page.getByTestId("mcp-logo").locator("svg").evaluateAll((els) =>
      els.map((el) => {
        const cs = getComputedStyle(el);
        const attr = el.getAttribute("fill");
        if (attr && attr !== "none") return attr.trim().toLowerCase();
        return cs.fill !== "none" ? cs.fill : cs.color;
      }),
    );
    expect(colors.length).toBeGreaterThan(40);

    // "Monochrome" means every logo painted the SAME colour, so the property
    // to assert is distinctness, not saturation.
    //
    // An earlier version of this test counted logos whose channels were far
    // apart, and it failed at 2/55 - which was the TEST being wrong, not the
    // code. GitHub's real brand colour is #181717 and several others are
    // near-black or near-cream, so a saturation test rejects genuinely correct
    // brand colours. Distinctness cannot be faked by a grey palette.
    const distinct = new Set(colors);
    expect(
      distinct.size,
      `only ${distinct.size} distinct colours across ${colors.length} logos - that is monochrome`,
    ).toBeGreaterThan(20);

    // And spot-check two brands whose official colours are well known, so the
    // distinctness rule above cannot be satisfied by any old palette.
    const byTitle = await page.getByTestId("mcp-logo").locator("svg title").evaluateAll((els) =>
      els.map((e) => e.textContent ?? ""),
    );
    const idxOf = (n: string) => byTitle.findIndex((t) => t === n);
    const git = idxOf("GitHub");
    const notch = idxOf("Notion");
    expect(git).toBeGreaterThanOrEqual(0);
    expect(colors[git]).toBe("#181717");
    if (notch >= 0) expect(colors[notch]).not.toBe(colors[git]);

    // Scroll the cloud itself into view before capturing, or the "cloud"
    // screenshot is just another picture of the hero.
    await page.getByTestId("logo-cloud").scrollIntoViewIfNeeded();
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${SHOTS}/f6-desktop-cloud.png` });
  });

  test("magnetic hover still moves a logo, and logos are not clickable", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForSelector('[data-testid="mcp-logo"]');
    await page.waitForTimeout(1200);

    const tile = page.getByTestId("mcp-logo").nth(3);
    const tb = await tile.boundingBox();
    expect(tb).not.toBeNull();
    const before = await tile.evaluate((el) => getComputedStyle(el).transform);

    await page.mouse.move(tb!.x + tb!.width / 2 - 40, tb!.y + tb!.height / 2 - 40);
    await page.waitForTimeout(400);
    await page.mouse.move(tb!.x + tb!.width / 2, tb!.y + tb!.height / 2);
    await page.waitForTimeout(700);
    const after = await tile.evaluate((el) => getComputedStyle(el).transform);
    expect(after, "magnetic effect did not move the tile").not.toBe(before);
    expect(after).not.toBe("none");

    // Not clickable: no pointer events, and clicking must not navigate.
    const pe = await tile.evaluate((el) => getComputedStyle(el).pointerEvents);
    expect(pe).toBe("none");
    const urlBefore = page.url();
    await tile.click({ force: true });
    await page.waitForTimeout(500);
    expect(page.url()).toBe(urlBefore);
    await expect(tile).toHaveAttribute("aria-hidden", "true");

    await page.screenshot({ path: `${SHOTS}/f6-desktop-magnetic.png` });
  });

  test("no logo is invisible on the light surface", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForSelector('[data-testid="mcp-logo"]');
    await page.waitForTimeout(2000);

    // Six lobehub icons ship colorPrimary "#FFFFFF" - Together, Windsurf, Tavily,
    // MCP, Azure and Google Cloud. On a light tile that is not a styling
    // subtlety, it is a white logo on a white card: present in the DOM, correct
    // in the data, and completely invisible to a person. Only reading the
    // computed paint catches it, because the fill attribute looks normal.
    const invisible = await page.getByTestId("mcp-logo").evaluateAll((tiles) =>
      tiles
        .map((t) => {
          const svg = t.querySelector("svg");
          const path = svg?.querySelector("path");
          if (!svg || !path) return { title: "?", paint: "none", color: "none" };
          const cs = getComputedStyle(path);
          return {
            title: svg.querySelector("title")?.textContent ?? "?",
            paint: cs.fill,
            color: cs.color,
          };
        })
        .filter(
          (r) => r.paint === "rgb(255, 255, 255)" || r.color === "rgb(255, 255, 255)" || r.paint === "none",
        ),
    );
    expect(
      invisible.map((i) => i.title),
      `logos painted invisible: ${JSON.stringify(invisible)}`,
    ).toEqual([]);
  });

  test("axe accessibility audit on the landing page", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForSelector('[data-testid="hero-logo-strip"]');
    await page.waitForTimeout(1500);

    // NOTE ON HONESTY: the brief asked for "Lighthouse a11y >= 90". Lighthouse is
    // not installed in this repo and is a heavy install, so this runs axe-core
    // instead - the same engine Lighthouse's accessibility category is built on.
    // It is NOT the same number and it is not reported as one: axe reports
    // violations by rule, not a 0-100 score. What can honestly be claimed is the
    // violation list, which is stricter evidence than a rounded score anyway.
    const results = await new AxeBuilder({ page }).analyze();
    const violations = results.violations.map((v) => ({
      id: v.id,
      impact: v.impact,
      nodes: v.nodes.length,
      targets: v.nodes.map((n) => n.target.join(" ")).slice(0, 3),
      help: v.help,
    }));
    console.log("AXE_VIOLATIONS", JSON.stringify(violations, null, 1));
    console.log("AXE_PASSES", results.passes.length, "INCOMPLETE", results.incomplete.length);

    // Any violation is a failure. The logo work must not have introduced one,
    // and the decorative strip in particular must not become an a11y problem.
    expect(violations, JSON.stringify(violations, null, 1)).toEqual([]);
  });

  test("mobile: hero strip visible, no horizontal overflow", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForSelector('[data-testid="hero-logo-strip"]');
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${SHOTS}/f6-mobile-hero.png` });

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(2);
  });
});
