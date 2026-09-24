import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
const base = "https://proyek-agent.pages.dev";
const routes = ["/", "/chat", "/builder", "/settings", "/billing", "/help"];
const out = join(process.cwd(), "test-results", "production-verify");
mkdirSync(out, { recursive: true });
const b = await chromium.launch(); let failures = 0;
for (const route of routes) {
  const p = await b.newPage({ viewport: { width: 1280, height: 800 } }); const errors = []; const api = new Set();
  p.on("pageerror", e => errors.push(`PAGEERROR:${e.message}`));
  p.on("console", m => { if (m.type() === "error") errors.push(`CONSOLE:${m.text()}`); });
  p.on("response", r => { if (r.status() >= 500) errors.push(`HTTP${r.status()}:${r.url()}`); if (r.url().includes("/oauth/") || r.url().includes("/health")) api.add(r.url()); });
  try { await p.goto(base + route, { waitUntil: "networkidle", timeout: 30000 }); await p.waitForTimeout(1500); const body = await p.locator("body").innerText(); const crash = /__webpack_modules__|Runtime TypeError/i.test(body); if (body.length <= 150 || errors.length || crash) failures++; console.log(`${route} BODY=${body.length} ERRORS=${errors.length} CRASH=${crash} API=${JSON.stringify([...api])}`); errors.slice(0,2).forEach(e=>console.log(` ${e.slice(0,180)}`)); } catch (e) { failures++; console.log(`${route} BODY=0 ERRORS=1 PROBE=${String(e).slice(0,180)}`); }
  await p.screenshot({ path: join(out, `${route === "/" ? "root" : route.slice(1)}.png`), fullPage: true }); await p.close();
}
console.log(`PROD_ROUTES=${routes.length} PROD_FAILURES=${failures}`); await b.close(); process.exitCode = failures ? 1 : 0;
