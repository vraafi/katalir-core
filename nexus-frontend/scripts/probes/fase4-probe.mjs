/**
 * Probe FASE 4: (1) detail node pelanggaran axe color-contrast,
 * (2) struktur DOM command palette setelah Ctrl+K, (3) timeline data-auth
 * setelah sesi dihapus. Pakai: node scripts/probes/fase4-probe.mjs
 */
import { chromium } from "@playwright/test";
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const AXE = join(process.cwd(), "node_modules", "axe-core", "axe.min.js");
const ref = (readFileSync(join(process.cwd(), ".env.local"), "utf-8").match(
  /NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/
) || [])[1];
const sess = JSON.parse(readFileSync(join(process.cwd(), "_e2e_session.refreshed.json"), "utf-8"));

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const seed = async (page) => {
  await page.addInitScript((kv) => { try { window.localStorage.setItem(kv.key, JSON.stringify(kv.value)); } catch {} }, { key: `sb-${ref}-auth-token`, value: sess });
};

// ---------- 1. axe color-contrast details (/settings) ----------
{
  const page = await ctx.newPage();
  await seed(page);
  await page.goto("http://localhost:3000/settings", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
  await page.waitForTimeout(2500);
  await page.addScriptTag({ path: AXE });
  const details = await page.evaluate(async () => {
    const axe = window.axe;
    const res = await axe.run(document, {
      resultTypes: ["violations"],
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
    });
    const out = [];
    for (const v of res.violations) {
      for (const n of v.nodes) {
        out.push({
          rule: v.id,
          impact: v.impact,
          target: JSON.stringify(n.target).slice(0, 120),
          html: String(n.html).replace(/\s+/g, " ").slice(0, 140),
          summary: String(n.failureSummary ?? "").replace(/\s+/g, " ").slice(0, 220),
        });
      }
    }
    return out;
  });
  console.log("AXE_DETAILS_SETTINGS=" + JSON.stringify(details, null, 1));
  await page.close();
}

// ---------- 2. command palette DOM setelah Ctrl+K ----------
{
  const page = await ctx.newPage();
  await seed(page);
  await page.goto("http://localhost:3000/help", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
  await page.waitForTimeout(1200);
  await page.keyboard.press("Control+k");
  await page.waitForTimeout(1200);
  const dom = await page.evaluate(() => {
    const dialog = document.querySelector('[role="dialog"]');
    const all = [...document.querySelectorAll("*")].filter((e) =>
      [...e.attributes].some((a) => a.name.startsWith("cmdk"))
    );
    return {
      hasDialog: !!dialog,
      dialogAttrs: dialog ? [...dialog.attributes].map((a) => `${a.name}=${String(a.value).slice(0, 30)}`) : [],
      cmdkElements: all.slice(0, 8).map((e) => e.tagName + " [" + [...e.attributes].filter((a) => a.name.startsWith("cmdk")).map((a) => a.name).join(",") + "]"),
      bodyText: document.body.innerText.replace(/\s+/g, " ").slice(0, 200),
    };
  });
  console.log("PALETTE_DOM=" + JSON.stringify(dom, null, 1));
  await page.close();
}

// ---------- 3. timeline data-auth setelah sesi dihapus ----------
{
  const page = await ctx.newPage();
  await seed(page);
  await page.goto("http://localhost:3000/settings", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
  await page.waitForTimeout(800);
  const removed = await page.evaluate(() => {
    const keys = Object.keys(localStorage).filter((k) => k.includes("auth-token") || k.startsWith("sb-"));
    keys.forEach((k) => localStorage.removeItem(k));
    return keys;
  });
  console.log("LOGOUT_removedKeys=" + JSON.stringify(removed));
  await page.reload({ waitUntil: "domcontentloaded" });
  const timeline = [];
  for (let i = 0; i < 12; i++) {
    await page.waitForTimeout(1000);
    timeline.push(await page.evaluate(() => ({
      auth: document.documentElement.dataset.auth ?? null,
      hydrated: document.documentElement.dataset.hydrated ?? null,
      lsKeys: Object.keys(localStorage).filter((k) => k.startsWith("sb-")).length,
    })));
    if (timeline[timeline.length - 1].auth === "out") break;
  }
  console.log("LOGOUT_timeline=" + JSON.stringify(timeline));
  await page.close();
}

await browser.close();
