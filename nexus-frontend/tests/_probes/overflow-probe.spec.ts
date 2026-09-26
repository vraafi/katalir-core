import { test, expect } from "@playwright/test";

/** Diagnostic: which logo tiles render nothing, and why. */
test("find blank logo tiles", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/", { waitUntil: "domcontentloaded", timeout: 90_000 });
  await page.waitForSelector('[data-testid="mcp-logo"]');
  await page.waitForTimeout(2500);

  const info = await page.getByTestId("mcp-logo").evaluateAll((tiles) =>
    tiles.map((t) => {
      const svg = t.querySelector("svg");
      const inner = t.querySelector("span:last-of-type");
      const cs = inner ? getComputedStyle(inner) : null;
      return {
        hasSvg: !!svg,
        title: svg?.querySelector("title")?.textContent ?? null,
        fill: svg?.getAttribute("fill") ?? null,
        pathLen: svg?.querySelector("path")?.getAttribute("d")?.length ?? 0,
        color: cs?.color ?? null,
        opacity: cs?.opacity ?? null,
      };
    }),
  );
  const blank = info.filter((i) => !i.hasSvg || i.pathLen === 0);
  console.log("TOTAL", info.length, "BLANK", blank.length);
  for (const b of blank) console.log("  BLANK:", JSON.stringify(b));
  const hex2rgb = (h: string) => {
    const m = h.replace("#", "");
    return [0, 2, 4].map((i) => parseInt(m.substr(i, 2), 16));
  };
  const lum = (c: number[]) => {
    const [r, g, b] = c.map((v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const faint = info.filter((i) => {
    const f = i.fill || "";
    if (!f.startsWith("#") || f.length < 7) return false;
    return lum(hex2rgb(f)) > 0.75;
  });
  console.log("FAINT_ON_WHITE", faint.length);
  for (const f of faint) console.log("  FAINT:", f.title, f.fill);

  // Resolve the colour the browser ACTUALLY paints, covering the lobehub tier
  // which paints with currentColor rather than a fill attribute.
  const resolved = await page.getByTestId("mcp-logo").evaluateAll((tiles) =>
    tiles.map((t) => {
      const svg = t.querySelector("svg");
      const path = svg?.querySelector("path");
      if (!svg || !path) return null;
      const cs = getComputedStyle(path);
      return { title: svg.querySelector("title")?.textContent ?? "?", paint: cs.fill, color: cs.color };
    }),
  );
  const whiteish = resolved.filter(
    (r) => r && (r.paint === "rgb(255, 255, 255)" || r.paint === "#fff" || r.paint === "none" || r.color === "rgb(255, 255, 255)"),
  );
  console.log("WHITEISH", whiteish.length);
  for (const w of whiteish) console.log("  WHITEISH:", JSON.stringify(w));
  const noneFill = resolved.filter((r) => r && r.paint === "none");
  console.log("PAINT_NONE", noneFill.length);
  for (const n of noneFill.slice(0, 10)) console.log("  NONE:", JSON.stringify(n));

  const noColor = info.filter((i) => i.hasSvg && i.pathLen > 0 && (!i.color || i.color === "rgba(0, 0, 0, 0)"));
  console.log("NO_COLOR", noColor.length);
  for (const n of noColor.slice(0, 12)) console.log("  NOCOLOR:", JSON.stringify(n));
  expect(blank.length).toBe(0);
});

test("find mobile overflow culprit", async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/integrations", { waitUntil: "load" });
  await page.waitForSelector('[data-testid^="source-tab-"]');
  await page.waitForTimeout(2500);

  const culprits = await page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const out: Array<{ tag: string; cls: string; testid: string; w: number; right: number }> = [];
    for (const el of Array.from(document.querySelectorAll("*"))) {
      const r = el.getBoundingClientRect();
      if (r.width > vw + 1 || r.right > vw + 1) {
        out.push({
          tag: el.tagName.toLowerCase(),
          cls: (el.getAttribute("class") || "").slice(0, 70),
          testid: el.getAttribute("data-testid") || "",
          w: Math.round(r.width),
          right: Math.round(r.right),
        });
      }
    }
    return { vw, scrollWidth: document.documentElement.scrollWidth, out: out.slice(0, 12) };
  });
  console.log("VIEWPORT", culprits.vw, "SCROLLWIDTH", culprits.scrollWidth);
  for (const c of culprits.out) console.log(`  ${c.tag} w=${c.w} right=${c.right} testid=${c.testid} cls=${c.cls}`);
});
