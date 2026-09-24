import { chromium } from 'playwright';

const routes = ['/', '/chat', '/builder', '/settings', '/billing', '/help'];
const b = await chromium.launch();
try {
  for (const route of routes) {
    const p = await b.newPage({ viewport: { width: 1280, height: 800 } });
    await p.goto(`http://localhost:3000${route}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await p.waitForTimeout(1500);
    const body = await p.locator('body').innerText();
    if (body.trim().length < 20) throw new Error(`${route} rendered blank`);
    const name = route === '/' ? 'home' : route.slice(1);
    await p.screenshot({ path: `test-results/routes/${name}-desktop.png`, fullPage: true });
    await p.setViewportSize({ width: 390, height: 844 });
    await p.waitForTimeout(250);
    await p.screenshot({ path: `test-results/routes/${name}-mobile.png`, fullPage: true });
    console.log(`${route}: desktop+mobile OK body=${body.length}`);
    await p.close();
  }
  console.log(`ROUTES_SCREENSHOTS=${routes.length * 2}`);
} finally {
  await b.close();
}
