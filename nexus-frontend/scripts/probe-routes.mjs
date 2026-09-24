import { chromium } from 'playwright';

const routes = ['/', '/chat', '/builder', '/settings', '/billing', '/help'];
const b = await chromium.launch();
const report = [];
try {
  for (const route of routes) {
    const name = route === '/' ? 'home' : route.slice(1);
    const desktopErrors = [];
    const p = await b.newPage({ viewport: { width: 1280, height: 800 } });
    p.on('console', (m) => { if (m.type() === 'error') desktopErrors.push(`CONSOLE: ${m.text()}`); });
    p.on('pageerror', (e) => desktopErrors.push(`PAGEERROR: ${e.message}`));
    p.on('requestfailed', (r) => desktopErrors.push(`REQFAIL: ${r.url()} ${r.failure()?.errorText ?? ''}`));
    p.on('response', (r) => { if (r.status() >= 400) desktopErrors.push(`HTTP${r.status()}: ${r.url()}`); });
    try {
      await p.goto(`http://localhost:3000${route}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await p.waitForTimeout(3000);
      const body = await p.locator('body').innerText();
      await p.screenshot({ path: `test-results/routes/${name}-desktop.png`, fullPage: true });
      const mobileErrors = [];
      await p.setViewportSize({ width: 390, height: 844 });
      await p.reload({ waitUntil: 'domcontentloaded', timeout: 30000 });
      await p.waitForTimeout(2000);
      const mobileBody = await p.locator('body').innerText();
      await p.screenshot({ path: `test-results/routes/${name}-mobile.png`, fullPage: true });
      report.push({ route, bodyLen: body.length, mobileBodyLen: mobileBody.length, errors: desktopErrors.length + mobileErrors.length, detail: desktopErrors.slice(0, 5) });
    } catch (error) {
      report.push({ route, bodyLen: 0, mobileBodyLen: 0, errors: 1, detail: [String(error)] });
    }
    await p.close();
  }
  console.log(JSON.stringify(report, null, 2));
  console.log(`ROUTES_SCREENSHOTS=${routes.length * 2}`);
} finally {
  await b.close();
}
