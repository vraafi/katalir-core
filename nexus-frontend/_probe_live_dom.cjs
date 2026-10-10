// Direct live-DOM probe: no Playwright webServer, talks straight to the
// deployed production site. Answers the only question that matters here:
// does /connectors/health actually render its dashboard after hydration?
const { chromium } = require("playwright");
const fs = require("node:fs");

const LIVE = process.env.LIVE_URL || "https://katalir.de5.net";
const ROUTES = [
  { path: "/connectors/health", needles: ["Connector Health", "Status nyata konektor"] },
  { path: "/agents", needles: ["Agent"] },
  { path: "/", needles: ["Katalir"] },
];

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const out = [];

  for (const r of ROUTES) {
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e).slice(0, 300)));
    const failed = [];
    page.on("response", (res) => {
      if (res.status() >= 400) failed.push(`${res.status()} ${res.url().slice(0, 140)}`);
    });

    let status = "n/a";
    try {
      const resp = await page.goto(LIVE + r.path, { waitUntil: "networkidle", timeout: 60000 });
      status = resp ? resp.status() : "n/a";
    } catch (e) {
      status = "GOTO-FAIL: " + String(e).slice(0, 160);
    }
    await page.waitForTimeout(5000);

    let text = "";
    let h1 = [];
    let h2 = [];
    let title = "";
    try {
      text = await page.innerText("body");
      h1 = await page.locator("h1").allInnerTexts();
      h2 = await page.locator("h2").allInnerTexts();
      title = await page.title();
    } catch (e) {
      text = "READ-FAIL " + String(e).slice(0, 200);
    }

    const rec = {
      url: LIVE + r.path,
      http: status,
      title,
      h1,
      h2,
      bodyLen: text.length,
      head: text.slice(0, 500),
      needles: Object.fromEntries(r.needles.map((n) => [n, text.includes(n)])),
      pageerrors: errors,
      failedResponses: failed.slice(0, 12),
    };
    out.push(rec);

    console.log(`\n========= ${rec.url} =========`);
    console.log(`HTTP            : ${rec.http}`);
    console.log(`title           : ${rec.title}`);
    console.log(`h1              : ${JSON.stringify(rec.h1)}`);
    console.log(`h2              : ${JSON.stringify(rec.h2)}`);
    console.log(`body length     : ${rec.bodyLen}`);
    console.log(`body head       : ${JSON.stringify(rec.head)}`);
    console.log(`needles         : ${JSON.stringify(rec.needles)}`);
    console.log(`pageerrors      : ${JSON.stringify(rec.pageerrors)}`);
    console.log(`failedResponses : ${JSON.stringify(rec.failedResponses)}`);

    await page.close();
  }

  fs.writeFileSync("_probe_live_dom.json", JSON.stringify(out, null, 2));
  await browser.close();
  console.log("\nWROTE _probe_live_dom.json");
})().catch((e) => {
  console.error("FATAL", e);
  process.exit(1);
});
