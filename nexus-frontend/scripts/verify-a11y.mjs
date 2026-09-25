import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
const routes = ["/", "/pricing", "/docs", "/chat", "/builder"];
const b = await chromium.launch(); let critical = 0, serious = 0;
for (const route of routes) { const ctx = await b.newContext({ viewport: { width: 390, height: 844 } }); const p = await ctx.newPage(); await p.goto(`https://katalir.de5.net${route}`, { waitUntil: "networkidle", timeout: 30000 }); await p.waitForTimeout(1500); const r = await new AxeBuilder({ page: p }).analyze(); critical += r.violations.filter(v => v.impact === "critical").length; serious += r.violations.filter(v => v.impact === "serious").length; console.log(`${route}: VIOLATIONS=${r.violations.length}`); r.violations.forEach(v => console.log(`  [${v.impact}] ${v.id}: ${v.description}`)); await p.close(); }
await b.close(); console.log(`A11Y_CRITICAL=${critical} A11Y_SERIOUS=${serious}`); if (critical || serious) process.exit(1);
