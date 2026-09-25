import { chromium } from "playwright";
import { readFileSync, mkdirSync } from "node:fs";
const session = JSON.parse(readFileSync("../.agent-test-session.json", "utf8"));
const ref = new URL(session.url || "https://placeholder.supabase.co").hostname.split(".")[0];
const key = `sb-${ref}-auth-token`;
const jwt = session.access_token;
mkdirSync("test-results/p25", { recursive: true });
const b = await chromium.launch();
const ctx = await b.newContext({ acceptDownloads: true });
await ctx.addInitScript(({ key, token }) => localStorage.setItem(key, JSON.stringify({ access_token: token, token_type: "bearer", expires_in: 3600 })), { key, token: jwt });
const p = await ctx.newPage();
async function visit(route, name, selectors) { await p.goto(`https://katalir.de5.net${route}`, { waitUntil: "networkidle", timeout: 30000 }); await p.waitForTimeout(2500); const count = await p.locator(selectors.join(", ")).count(); await p.screenshot({ path: `test-results/p25/${name}.png`, fullPage: true }); return count; }
const chat = await visit("/chat", "chat", ['[data-testid="chat-export-actions"]', 'button:has-text("Export JSON")', 'button:has-text("Ekspor JSON")']);
const analytics = await visit("/billing", "analytics", ['[data-testid="card-usage"]', '[data-testid="card-analytics"]', '[data-testid="analytics"]']);
const templates = await visit("/builder", "templates", ['[data-testid="workflow-templates"]']);
console.log(`P2.5_CHAT_EXPORT=${chat ? "ok" : "fail"} P2.5_ANALYTICS=${analytics ? "ok" : "fail"} P2.5_TEMPLATES=${templates ? "ok" : "fail"}`);
await b.close(); if (!chat || !analytics || !templates) process.exit(1);
