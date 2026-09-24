/**
 * fase6-contrast-probe.mjs — repro detail `color-contrast` di /builder (mobile).
 *
 * KENAPA PROBE, BUKAN SPEC: spec final-mobile hanya memberi TAHU bahwa ada 9
 * pelanggaran; untuk memutuskan "bug vs timing" saya butuh elemen mana, rasio
 * berapa, dan apakah jumlahnya sama antar run. Probe ini mencetak ketiganya.
 *
 * Pakai: node scripts/probes/fase6-contrast-probe.mjs [runs=3] [route=/builder]
 */
import { chromium, devices } from "playwright";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const RUNS = Number(process.argv[2] || 3);
const ROUTE = process.argv[3] || "/builder";
const BASE = process.env.BASE_URL || "http://localhost:3000";
const AXE = join(process.cwd(), "node_modules", "axe-core", "axe.min.js");
const SHOTS = join(process.cwd(), "test-results", "fase6-contrast");
if (!existsSync(SHOTS)) mkdirSync(SHOTS, { recursive: true });

function supabaseRef() {
  for (const f of [".env.local", ".env"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    const m = readFileSync(p, "utf-8").match(/NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/);
    if (m) return m[1];
  }
  return "qmukkphwaajzbqjrcvaz";
}

const sessPath = join(process.cwd(), "_e2e_session.refreshed.json");
const NO_SESSION = process.env.NO_SESSION === "1";
const sess = !NO_SESSION && existsSync(sessPath) ? readFileSync(sessPath, "utf-8") : null;
console.log(
  `MODE=${NO_SESSION ? "TANPA_SESI (parity Lighthouse/spec)" : "BERSESI"} theme_dari_preferensi=${NO_SESSION ? "-" : "tersimpan"}`
);

const browser = await chromium.launch();
const iphone = devices["iPhone 14"];
const counts = [];

for (let i = 1; i <= RUNS; i++) {
  const ctx = await browser.newContext({ ...iphone });
  const page = await ctx.newPage();
  if (sess) {
    const key = `sb-${supabaseRef()}-auth-token`;
    await page.addInitScript(
      (kv) => {
        try {
          window.localStorage.setItem(kv.k, kv.v);
          window.localStorage.setItem("katalir.onboarding.v1", "done");
          window.localStorage.setItem("katalir.locale.v1", "id");
        } catch {}
      },
      { k: key, v: sess }
    );
  }
  await page.goto(BASE + ROUTE, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 }).catch(() => {});
  await page.waitForTimeout(1500);
  await page.addScriptTag({ path: AXE });
  const res = await page.evaluate(async () => {
    const r = await window.axe.run(document, { runOnly: { type: "rule", values: ["color-contrast"] } });
    const theme = document.documentElement.getAttribute("data-canvas-theme");
    const canvas = document.querySelector(".react-flow");
    const token = canvas ? getComputedStyle(canvas).getPropertyValue("--canvas-bg") : "";
    return {
      theme,
      token: String(token).trim().slice(0, 24),
      nodes: r.violations.flatMap((v) =>
        v.nodes.slice(0, 12).map((n) => ({
          target: Array.isArray(n.target) ? n.target.join(" ") : String(n.target),
          html: String(n.html).slice(0, 90),
          why: (n.failureSummary || "").replace(/\s+/g, " ").slice(0, 150),
        }))
      ),
    };
  });
  counts.push(res.nodes.length);
  console.log(`RUN_${i} theme=${res.theme} canvasToken=${res.token} violations=${res.nodes.length}`);
  for (const n of res.nodes) console.log(`   ${n.target} | ${n.html} | ${n.why}`);
  await page.screenshot({ path: join(SHOTS, `builder_mobile_run${i}.png`) });
  await ctx.close();
}

console.log(`COUNTS=${JSON.stringify(counts)}`);
const same = counts.every((c) => c === counts[0]);
console.log(same ? `KONSISTEN=${counts[0]}` : "INTERMITTENT");
await browser.close();
