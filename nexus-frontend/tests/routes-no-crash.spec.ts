// Regression: 6 route tidak boleh crash (no pageerror).
// Dibuat setelah /builder crash "useAuth must be used within AuthProvider"
// yang lolos karena verifikasi hanya menyentuh chat. Pola: goto tiap route,
// kumpulkan pageerror, assert kosong. Tanpa login (halaman publik harus
// render untuk anon) — route terproteksi cukup menampilkan empty/login state.
import { test, expect } from "@playwright/test";

const ROUTES = ["/", "/chat", "/settings", "/billing", "/help", "/builder", "/templates", "/agents"];

for (const route of ROUTES) {
  test(`no-crash ${route}`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));
    await page.goto(route, { waitUntil: "networkidle", timeout: 60000 });
    await page.waitForTimeout(2500);
    expect(errors, `pageerror di ${route}: ${JSON.stringify(errors)}`).toHaveLength(0);
  });
}
