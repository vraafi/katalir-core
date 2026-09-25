import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
const routes = ["/pricing", "/docs", "/about", "/changelog"];
const out = "test-results/p23-bilingual"; mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
const failures = [];
for (const route of routes) for (const locale of ["id", "en"]) {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const errors = []; page.on("pageerror", e => errors.push(String(e))); page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
  await page.addInitScript((l) => localStorage.setItem("katalir.locale.v1", l), locale);
  await page.goto(`https://katalir.de5.net${route}`, { waitUntil: "networkidle", timeout: 30000 });
  await page.waitForTimeout(500);
  const heading = await page.locator("h1").first().innerText();
  if (errors.length) failures.push({ route, locale, errors });
  await page.screenshot({ path: `${out}/${route.slice(1)}-${locale}.png`, fullPage: true });
  console.log(JSON.stringify({ route, locale, heading, errors }));
  await page.close();
}
await browser.close(); if (failures.length) { console.error(JSON.stringify(failures)); process.exit(1); }
