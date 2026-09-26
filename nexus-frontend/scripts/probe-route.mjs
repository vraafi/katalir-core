import { chromium } from "playwright";
const route = process.argv[2];
if (!route) throw new Error("route required");
const b = await chromium.launch();
try {
  const p = await b.newPage({ viewport: { width: 1280, height: 800 } });
  const errors = [];
  p.on("pageerror", (e) => errors.push(`PAGEERROR: ${e.message}`));
  p.on("console", (m) => { if (m.type() === "error") errors.push(`CONSOLE: ${m.text()}`); });
  p.on("response", (r) => { if (r.status() >= 500) errors.push(`HTTP${r.status()}: ${r.url()}`); });
  await p.goto(`https://katalir.de5.net${route}`, { waitUntil: "networkidle", timeout: 20000 });
  await p.waitForTimeout(1500);
  const body = await p.locator("body").innerText();
  const file = `test-results/domain${route.replace(/\//g, "_")}.png`;
  await p.screenshot({ path: file, fullPage: true });
  console.log(JSON.stringify({ route, body: body.length, errors, screenshot: file }));
  await p.close();
  if (body.length <= 300 || errors.length) process.exitCode = 1;
} finally { await b.close(); }
