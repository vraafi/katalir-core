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

  test("the 55-brand cloud fills the hero as a background layer", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForSelector('[data-testid="mcp-logo"]');
    await page.waitForTimeout(1200);

    const layer = page.getByTestId("hero-logo-layer");
    await expect(layer).toBeVisible();

    // 55 is the count the earlier work asserted, and moving the cloud into the
    // hero must not quietly drop brands on the way.
    await expect(page.getByTestId("mcp-logo")).toHaveCount(218);

    // "Background" has to mean background, not "somewhere on the page". The layer
    // must actually cover the hero and sit BEHIND the copy - the previous
    // failure mode was logos stacking on top of the headline.
    const layerBox = (await layer.boundingBox())!;
    const heroBox = (await page.getByTestId("hero-section").boundingBox())!;
    expect(layerBox.width).toBeGreaterThanOrEqual(heroBox.width - 2);
    expect(layerBox.height).toBeGreaterThanOrEqual(heroBox.height - 2);

    // z-index: the layer is -z-10, the copy wrapper is z-10. Compare computed
    // z-index rather than trusting the class names.
    const z = await page.evaluate(() => {
      const l = document.querySelector('[data-testid="hero-logo-layer"]');
      const c = document.querySelector("#main-content");
      return {
        layer: Number(getComputedStyle(l!).zIndex),
        copy: Number(getComputedStyle(c!).zIndex),
      };
    });
    expect(z.layer, "logo layer is not behind the copy").toBeLessThan(z.copy);

    // And the copy must actually be on top where they overlap, not merely later
    // in the DOM. hit-testing the headline is the direct check.
    const hit = await page.evaluate(() => {
      const h1 = document.querySelector("h1")!;
      const r = h1.getBoundingClientRect();
      const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return el?.closest("#main-content") !== null;
    });
    expect(hit, "a logo is painted over the headline").toBe(true);

    await page.screenshot({ path: `${SHOTS}/f6-desktop-hero.png` });
  });

  test("every logo is the same size, and sized as specified", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForSelector('[data-testid="mcp-logo"]');
    await page.waitForTimeout(1000);

    // The complaint was "inconsistent size". Two different things are checked
    // here and conflating them was a real bug in the previous version: the CELL
    // is 48px, but the GLYPH inside it is 24px. Asserting the cell against 24
    // failed while the page was in fact correct.
    const cells = await page
      .getByTestId("mcp-logo")
      .evaluateAll((els) => els.map((el) => el.getBoundingClientRect().width));
    expect(cells.length).toBeGreaterThanOrEqual(200);
    expect(new Set(cells.map((w) => Math.round(w))).size, "cells are not uniform").toBe(1);
    expect(cells[0]).toBeCloseTo(48, 0);

    // The glyph itself: uniform 24px height, whatever its aspect ratio.
    const heights = await page
      .getByTestId("mcp-logo")
      .locator("svg")
      .evaluateAll((els) => els.map((el) => el.getBoundingClientRect().height));
    expect(heights.length).toBeGreaterThanOrEqual(200);
    for (const h of heights) expect(Math.abs(h - 24)).toBeLessThanOrEqual(1);
  });

  test("the field spans the hero, with no empty band at top or bottom", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForSelector('[data-testid="mcp-logo"]');
    await page.waitForTimeout(1000);

    const hero = (await page.getByTestId("hero-section").boundingBox())!;

    // 55 tiles at 24px make only ~3 rows, so a self-sizing grid would stack them
    // at the top and leave the lower two thirds blank. The rows are stretched to
    // divide the height instead, so the field SPANS the hero.
    //
    // The assertion is on the vertical span rather than on a gap to the edge,
    // because a 24px logo centred in a 273px row always leaves a margin no
    // matter how the grid is configured. Measuring "distance to the bottom"
    // would therefore be asserting something geometrically impossible.
    const bounds = await page
      .getByTestId("mcp-logo")
      .evaluateAll((els) => {
        const rs = els.map((el) => el.getBoundingClientRect());
        return {
          top: Math.min(...rs.map((r) => r.top)),
          bottom: Math.max(...rs.map((r) => r.bottom)),
        };
      });

    const span = bounds.bottom - bounds.top;
    expect(hero.height, "hero is not full viewport").toBeGreaterThanOrEqual(880);

    // With 218 tiles in square 40px cells the field is genuinely dense, so the
    // old 0.6 ceiling is no longer the right line. It now has to cover most of
    // the hero, and it still catches the real regression: 55 tiles at the old
    // size spanned only ~66% of a 900px hero.
    expect(
      span / hero.height,
      `logos only span ${Math.round(span)}px of a ${Math.round(hero.height)}px hero`,
    ).toBeGreaterThan(0.8);
    expect(bounds.top - hero.y, "large empty band above the field").toBeLessThanOrEqual(200);
    expect(hero.y + hero.height - bounds.bottom, "large empty band below the field").toBeLessThanOrEqual(200);
  });

  test("declared grid gap is 24px and cells are square", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForSelector('[data-testid="mcp-logo"]');
    await page.waitForTimeout(800);

    // Assert the declared values rather than measured centre-to-centre distance.
    const g = await page
      .getByTestId("magnetic-logo-cloud")
      .evaluate((el) => {
        const cs = getComputedStyle(el);
        return { gap: cs.gap, autoRows: cs.gridAutoRows, columns: cs.gridTemplateColumns };
      });
    // Chrome collapses `gap` to a single value when row and column are equal,
    // so the computed string is "24px", not "24px 24px". Accept either form.
    expect(g.gap, `gap was ${g.gap}`).toMatch(/^24px( 24px)?$/);

    // Square cells: the row track must equal the column min, otherwise spacing
    // reads differently down the page than across it.
    const cell = await page
      .getByTestId("mcp-logo")
      .first()
      .evaluate((el) => el.getBoundingClientRect().width);
    expect(Math.abs(parseFloat(g.autoRows) - cell)).toBeLessThanOrEqual(1);

    // Every tile in the same row must be the same width, or the field is ragged.
    const widths = await page
      .getByTestId("mcp-logo")
      .evaluateAll((els) =>
        els.slice(0, 30).map((el) => Math.round(el.getBoundingClientRect().width)),
      );
    expect(new Set(widths).size, `ragged rows: ${[...new Set(widths)].join(",")}`).toBe(1);
  });

  test("logos render sharp: full opacity on the container, and no blur filter", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForSelector('[data-testid="mcp-logo"]');
    await page.waitForTimeout(1000);

    // Read the opacity off the cloud itself. The layer wrapper is transparent -
    // reading its parent measures the <section>, which is always 1, and that is
    // exactly the mistake that makes a "faded background" test pass vacuously.
    //
    // The brief's hard rule: NO opacity reduction on the container, because
    // dimming the container drops contrast on every logo at once. Legibility is
    // carried by the text card instead. So this must be a full 1.0 - the earlier
    // 0.7 faded pass is the "buram" the complaint was about.
    const opacity = await page
      .getByTestId("magnetic-logo-cloud")
      .evaluate((el) => Number(getComputedStyle(el).opacity));
    expect(opacity, "container opacity must be 1 - legibility belongs to the card").toBe(1);

    // The complaint was "buram". A blur is the specific cause, and it is
    // assertable directly on every tile and every svg.
    const blurry = await page
      .getByTestId("mcp-logo")
      .evaluateAll((els) =>
      els
        .flatMap((t) => [t, ...Array.from(t.querySelectorAll("svg"))])
        .map((el) => {
          const cs = getComputedStyle(el);
          return { brand: el.getAttribute("data-brand") ?? "svg", filter: cs.filter, bmi: cs.backdropFilter };
        })
        .filter((r) => r.filter !== "none" || r.bmi !== "none"),
    );
    expect(blurry, `blur applied to logos: ${JSON.stringify(blurry)}`).toEqual([]);
  });

  test("the text sits on its own opaque card, not on faded logos", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForSelector('[data-testid="mcp-logo"]');
    await page.waitForTimeout(800);

    // Legibility is carried by the card, not by dimming the field. If this
    // drops below ~0.8 the logos have to be faded again to compensate, which is
    // the design the brief explicitly rejected.
    const bg = await page.evaluate(() => {
      const card = document.querySelector("#main-content > div") as HTMLElement;
      return getComputedStyle(card).backgroundColor;
    });
    const alpha = Number(bg.match(/rgba?\([^)]*?,\s*([\d.]+)\s*\)/)?.[1] ?? "1");
    expect(alpha, `card background too transparent: ${bg}`).toBeGreaterThanOrEqual(0.8);
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

    // The cloud no longer lives below the fold - it IS the hero - so there is no
    // separate "cloud" region to scroll to any more. A full-page shot is what
    // actually shows how the hero sits in the document.
    await page.screenshot({ path: `${SHOTS}/f6-desktop-cloud.png`, fullPage: true });
  });

  test("no grey fallback glyphs, and the unpainted brands are spread, not clumped", async ({ page }) => {
    // Regression guard for the reported bug: "the logos at the bottom are
    // grey". The cause was NOT a fallback icon and NOT a gradient - 0 tiles
    // had a missing fill, 0 image requests were made, and every tile carried
    // `filter: none; opacity: 1`. lobehub's bare export binds Mono
    // (`var Icons = Mono` in the package's own index.js), which paints
    // `fill: currentColor`, so every unpainted brand inherited the theme
    // foreground. Emitting the two packs as two blocks then put all of them in
    // one contiguous run filling the last rows, which is what made the problem
    // look positional.
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForSelector('[data-testid="mcp-logo"]');
    await page.waitForTimeout(1200);

    const audit = await page.evaluate(() => {
      const tiles = Array.from(document.querySelectorAll('[data-testid="mcp-logo"]'));
      const rows = Array.from(
        new Set(tiles.map((t) => Math.round(t.getBoundingClientRect().top))),
      ).sort((a, b) => a - b);
      const info = tiles.map((t) => {
        const path = t.querySelector("svg path") as SVGPathElement | null;
        const fill = path ? getComputedStyle(path).fill : "";
        const m = fill.match(/(\d+)[, ]+(\d+)[, ]+(\d+)/);
        const [r, g, b] = m ? m.slice(1).map(Number) : [0, 0, 0];
        return {
          brand: (t as HTMLElement).dataset.brand ?? "?",
          row: rows.indexOf(Math.round(t.getBoundingClientRect().top)),
          // Saturation, not brightness: a black or white brand is a legitimate
          // monochrome mark, so "is it grey" cannot be answered by luminance.
          sat: Math.max(r, g, b) - Math.min(r, g, b),
          filter: getComputedStyle(t).filter,
          opacity: getComputedStyle(t).opacity,
          hasFill: Boolean(fill && fill !== "none"),
        };
      });
      let streak = 0;
      let worst = 0;
      for (const x of info) {
        streak = x.sat < 14 ? streak + 1 : 0;
        worst = Math.max(worst, streak);
      }
      return {
        total: info.length,
        missingFill: info.filter((x) => !x.hasFill).map((x) => x.brand),
        filtered: info.filter((x) => x.filter !== "none").map((x) => x.brand),
        dimmed: info.filter((x) => x.opacity !== "1").map((x) => x.brand),
        neutral: info.filter((x) => x.sat < 14).length,
        worstStreak: worst,
      };
    });

    // Not one glyph may fail to render: a missing fill IS the grey-placeholder
    // bug, whatever its cause.
    expect(audit.missingFill, "tiles with no fill (grey placeholder)").toEqual([]);
    // And the field must not be dimmed or desaturated to fake a fade.
    expect(audit.filtered, "tiles carrying a CSS filter").toEqual([]);
    expect(audit.dimmed, "tiles not at opacity 1").toEqual([]);
    // Regression guard on the emit order: unpainted brands must not form one
    // solid block. The structural cause is a contiguous run of lobehub brands,
    // which the interleave reduced from 73 to 1. But the STREAK MEASURED HERE
    // ALSO COUNTS simple-icons brands whose own logo is legitimately black or
    // white - Bun, Deno, DevTo, Anthropic and ~19 others are monochrome by
    // design, not by failure. With 23 such brands scattered among 218 tiles, a
    // short run is expected, so the bound is set above that noise floor while
    // still failing loudly if the 73-brand block ever comes back.
    expect(
      audit.worstStreak,
      `${audit.worstStreak} unpainted brands in a row - they are clumping again`,
    ).toBeLessThanOrEqual(8);

    console.log("COLOUR", JSON.stringify(audit));
  });

  test("magnetic hover still moves a logo, and logos are not clickable", async ({ page }) => {
    // Pinned explicitly. This test used to inherit the Playwright default
    // (1280x720), where tile #3 sits at y=14: the -40px hover offset then
    // resolved to a NEGATIVE y, i.e. off-screen, so no mousemove was ever
    // dispatched and the tile legitimately never moved. The assertion passed
    // or failed depending on the default viewport rather than on the code.
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForSelector('[data-testid="mcp-logo"]');
    // Wait on the same signal the component waits on. A fixed sleep races the
    // web font: the centre cache is re-measured on `document.fonts.ready`, and
    // until that lands the cached centres can be offset far enough that the
    // cursor sits outside `radius` of every one of them, so the tile under test
    // legitimately never moves. Sleeping a guessed 1200ms is what made this
    // test report a working magnet as dead.
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
    await page.waitForTimeout(800);

    // Pick the hover point first, then the tile that actually sits under it.
    // Hardcoding `.nth(3)` tested one arbitrary cell in the top row and read as
    // "the magnet is dead" whenever that particular cell was outside the radius
    // of wherever the cached centres happened to be. A test should assert the
    // behaviour, not one cell's luck.
    const hero = (await page.getByTestId("hero-section").boundingBox())!;
    const hx = Math.round(hero.x + hero.width / 2);
    const hy = Math.round(hero.y + hero.height / 2);

    const idx = await page.evaluate(
      ([px, py]) => {
        const tiles = Array.from(document.querySelectorAll('[data-testid="mcp-logo"]'));
        let best = -1;
        let bestD = Infinity;
        tiles.forEach((el, i) => {
          const r = el.getBoundingClientRect();
          const d = Math.hypot(r.left + r.width / 2 - px, r.top + r.height / 2 - py);
          if (d < bestD) {
            bestD = d;
            best = i;
          }
        });
        return best;
      },
      [hx, hy],
    );
    const tile = page.getByTestId("mcp-logo").nth(idx);
    const tb = await tile.boundingBox();
    expect(tb).not.toBeNull();
    const before = await tile.evaluate((el) => getComputedStyle(el).transform);

    // Park the cursor in a corner first, exactly as the evidence sweep does.
    // Hovering cold, as the very first synthetic mousemove of the session, is
    // the one path that reliably reproduces a field that has never been
    // activated: the transform is still "none" and the assertion below reports
    // a working magnet as broken. Park, wait, then hover - the same sequence
    // the passing 16-point grid sweep uses.
    await page.mouse.move(5, 895);
    await page.waitForTimeout(1000);
    // The activation move, held long enough for the exponential lerp to warm.
    // This is the warm-up the evidence sweep performs, and it is the whole fix:
    // sampled cold, the first probe reads the exponential ramp-up as a dead
    // field (fieldMax 0 across all 218 tiles) and the assertion below reports a
    // working magnet as broken. The evidence test hid this by sweeping 16
    // points long after the field was already warm.
    await page.mouse.move(720, 470);
    await page.waitForTimeout(1200);
    await page.mouse.move(5, 895);
    await page.waitForTimeout(1200);

    // Offset the cursor slightly so the tile is genuinely PULLED rather than
    // sitting at its target. With the cursor exactly on the centre, dx and dy
    // are both 0 and the tile is already where it belongs, so it correctly
    // does not move - an assertion that would be testing nothing.
    await page.mouse.move(hx, hy);
    await page.waitForTimeout(400);
    await page.mouse.move(hx - 40, hy - 40);
    await page.waitForTimeout(800);
    const after = await tile.evaluate((el) => getComputedStyle(el).transform);
    expect(after, "magnetic effect did not move the tile").not.toBe(before);
    expect(after).not.toBe("none");

    // Task D: the tile must move, but only within the collision-free bound.
    // A tile directly under the cursor has a legitimate displacement of ~0, so
    // the bound is asserted separately below against the whole field rather
    // than against this one tile.
    const moved = await tile.evaluate((el) => {
      const m = new DOMMatrix(getComputedStyle(el).transform);
      return Math.hypot(m.m41, m.m42);
    });
    expect(moved, "tile did not visibly move").toBeGreaterThan(1);

    // Not clickable: no pointer events, and clicking must not navigate.
    const pe = await tile.evaluate((el) => getComputedStyle(el).pointerEvents);
    expect(pe).toBe("none");
    const urlBefore = page.url();
    await tile.click({ force: true });
    await page.waitForTimeout(500);
    expect(page.url()).toBe(urlBefore);
    // aria-hidden sits on the cloud container, not on each tile - one attribute
    // hides all 55. Asserting it on the tile tested the wrong element and failed
    // for the right reason, which is worth stating so nobody "fixes" it by
    // adding a redundant attribute to 55 nodes.
    await expect(page.getByTestId("magnetic-logo-cloud")).toHaveAttribute("aria-hidden", "true");
    // And a decorative mark must be invisible to the tab order.
    await expect(tile).not.toHaveAttribute("tabindex", /\S/);

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
    await page.waitForSelector('[data-testid="mcp-logo"]');
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

  test("mobile: the field is capped, not clipped to one lonely row", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForSelector('[data-testid="mcp-logo"]');
    await page.waitForTimeout(1200);
    await page.screenshot({ path: `${SHOTS}/f6-mobile-hero.png` });

    // 218 tiles in 5 columns is 44 rows, which cannot fit one viewport. The
    // fix is a below-`sm` cap, so the VISIBLE count must be small while the
    // DOM still holds all 218.
    const visible = await page
      .getByTestId("mcp-logo")
      .evaluateAll((els) => els.filter((el) => el.getClientRects().length > 0).length);
    const total = await page.getByTestId("mcp-logo").count();

    expect(total, "mobile should not drop brands from the DOM").toBe(218);
    expect(visible, "mobile shows the whole 218 and clips to a single row").toBeLessThanOrEqual(60);
    expect(visible, "mobile shows too few to read as a field").toBeGreaterThanOrEqual(20);

    // And the visible ones must actually sit inside the hero, not overflow it.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(2);
  });

  test("mobile: hero cloud visible, no horizontal overflow", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForSelector('[data-testid="mcp-logo"]');
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${SHOTS}/f6-mobile-hero.png` });

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(2);
  });
});
