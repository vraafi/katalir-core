/**
 * Probe FASE 5: daftar landmark di /builder + nama aksesibelnya.
 *
 * Kenapa perlu: axe melaporkan `landmark-unique` (dua landmark dengan peran &
 * nama sama) tapi hanya menyebut selector kelas (`.bg-bg-subtle`) — bukan
 * pasangan elemennya. Menebak dari kelas pernah menyesatkan, jadi probe ini
 * membaca DOM langsung dan mencetak setiap landmark beserta tag/kelas/nama.
 */
import { chromium } from "playwright";

const BASE = process.env.BASE_URL || "http://localhost:3000";
const ROUTE = process.env.PROBE_ROUTE || "/builder";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto(BASE + ROUTE, { waitUntil: "load" });
try {
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 30000 });
} catch {
  console.log("WARN: penanda hidrasi tidak muncul");
}
await page.waitForTimeout(2000);

const landmarks = await page.evaluate(() => {
  const implicit = { ASIDE: "complementary", NAV: "navigation", MAIN: "main", FORM: "form" };
  const nodes = Array.from(document.querySelectorAll("aside, nav, main, section[aria-label], form[role='search'], form[aria-label]"));
  return nodes.map((el) => {
    const cs = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    const visible = cs.display !== "none" && cs.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    const labelled = el.getAttribute("aria-label") || (el.getAttribute("aria-labelledby") ? "(labelledby)" : "");
    return {
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute("role") || implicit[el.tagName] || "",
      name: labelled,
      visible,
      size: `${Math.round(rect.width)}x${Math.round(rect.height)}`,
      cls: (el.className || "").toString().slice(0, 60),
    };
  });
});

console.log("LANDMARKS=" + JSON.stringify(landmarks, null, 1));
const visible = landmarks.filter((l) => l.visible && l.role);
const byRole = {};
for (const l of visible) {
  byRole[l.role] = byRole[l.role] || [];
  byRole[l.role].push(l.name || "(tanpa nama)");
}
console.log("VISIBLE_BY_ROLE=" + JSON.stringify(byRole));
for (const [role, names] of Object.entries(byRole)) {
  const dupes = names.filter((n, i) => names.indexOf(n) !== i);
  if (dupes.length) console.log(`DUPLICATE role=${role} names=${JSON.stringify([...new Set(dupes)])}`);
}

await browser.close();
