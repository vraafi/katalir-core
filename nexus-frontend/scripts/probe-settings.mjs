import { chromium } from 'playwright';

const b = await chromium.launch();
try {
  const p = await b.newPage({ viewport: { width: 1280, height: 800 } });
  await p.goto('http://localhost:3000/settings');
  await p.waitForSelector('[data-testid="oauth-cards"]', { timeout: 10000 });
  await p.screenshot({ path: 'test-results/settings-desktop.png', fullPage: true });
  const m = await b.newPage({ viewport: { width: 390, height: 844 } });
  await m.goto('http://localhost:3000/settings');
  await m.waitForSelector('[data-testid="oauth-cards"]', { timeout: 10000 });
  await m.screenshot({ path: 'test-results/settings-mobile.png', fullPage: true });
  console.log('SCREENSHOT_SETTINGS=desktop,desktop+mobile');
} finally {
  await b.close();
}
