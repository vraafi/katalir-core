import { chromium } from "playwright";
import { existsSync, readFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const out = join(root, "test-results", "brand-profile");
mkdirSync(out, { recursive: true });
const storagePath = join(root, "_e2e_storage.json");
const storage = existsSync(storagePath) ? JSON.parse(readFileSync(storagePath, "utf8")) : undefined;
const browser = await chromium.launch();

async function pageWithSession(viewport) {
  const context = await browser.newContext({ viewport, ...(storage ? { storageState: storage } : {}) });
  const page = await context.newPage();
  await page.goto("http://localhost:3000/chat", { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForTimeout(3500);
  return { page, context };
}
const landing = await browser.newPage({ viewport: { width: 1280, height: 800 } });
await landing.goto("http://localhost:3000/", { waitUntil: "domcontentloaded", timeout: 30000 });
await landing.waitForTimeout(1000);
await landing.screenshot({ path: join(out, "landing-logo.png"), fullPage: true });
console.log("LANDING_LOGO=", await landing.locator('[data-testid="landing-logo"]').count());

const { page, context } = await pageWithSession({ width: 1280, height: 800 });
const avatar = page.locator('[data-testid="profile-avatar"]').last();
console.log("AVATAR=", await avatar.count());
await page.screenshot({ path: join(out, "header-avatar.png"), fullPage: true });
await avatar.click();
await page.waitForTimeout(300);
const menu = page.getByRole("menu");
console.log("MENU=", await menu.count());
console.log("MENU_TEXT=", (await menu.innerText()).replace(/\s+/g, " ").trim());
await page.screenshot({ path: join(out, "profile-dropdown.png"), fullPage: true });
await context.close();

const mobile = await pageWithSession({ width: 390, height: 844 });
await mobile.page.locator('[data-testid="profile-avatar"]').last().click();
await mobile.page.waitForTimeout(300);
await mobile.page.screenshot({ path: join(out, "profile-dropdown-mobile.png"), fullPage: true });
console.log("MOBILE_MENU=", await mobile.page.getByRole("menu").count());
await mobile.context.close();
await browser.close();
