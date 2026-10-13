/**
 * FASE 7 — pembayaran TERTUTUP ("coming soon").
 *
 * Aturan yang diuji: selama `NEXT_PUBLIC_PAYMENT_ENABLED` bukan "true", tidak
 * boleh ada SATU pun jalan menuju pembayaran di UI — dan URL checkout tidak
 * boleh ikut terkirim ke browser sama sekali.
 *
 * KENAPA TERMASUK CEK BUNDLE: menyembunyikan tombol lewat CSS/logika render
 * masih meninggalkan URL di dalam bundle. Siapa pun bisa membacanya dan membuka
 * checkout langsung. Karena `NEXT_PUBLIC_*` di-INLINE saat build, satu-satunya
 * bukti yang berarti adalah "string-nya tidak ada di berkas yang dikirim ke
 * browser" — bukan "komponennya tidak merender".
 */
import { test, expect } from "@playwright/test";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const SHOTS = join(process.cwd(), "f6-shots", "payment");

/** Kumpulkan semua berkas di `out/` yang benar-benar dikirim ke browser. */
function walk(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, acc);
    else if (/\.(js|html|txt|json)$/.test(name)) acc.push(p);
  }
  return acc;
}

// ===========================================================================
// 1. Tidak ada URL checkout di bundle produksi
// ===========================================================================
test("pembayaran tertutup: URL checkout tidak ada di bundle", async () => {
  const out = join(process.cwd(), "out");
  expect(existsSync(out), "out/ belum di-build").toBe(true);
  const files = walk(out);
  expect(files.length, "out/ kosong").toBeGreaterThan(10);

  const hits: string[] = [];
  for (const f of files) {
    const s = readFileSync(f, "utf-8");
    if (s.includes("dodopayments.com") || s.includes("pdt_0NnsVLn7IzpG8Sokr3pZh")) {
      hits.push(f.replace(out, "out"));
    }
  }
  console.log(`PAYMENT_BUNDLE_FILES=${files.length} hits=${JSON.stringify(hits)}`);
  expect(hits, "URL checkout masih ter-inline ke bundle produksi").toEqual([]);
});

// ===========================================================================
// 2. /pricing — CTA diganti lencana "segera hadir"
// ===========================================================================
test("pembayaran tertutup: /pricing menampilkan lencana, bukan CTA", async ({ page }) => {
  await page.goto("/pricing", { waitUntil: "load", timeout: 90_000 });
  await page.waitForTimeout(1200);

  await expect(page.locator('[data-testid="pricing-coming-soon"]')).toBeVisible();
  // Tidak ada tautan apa pun ke checkout, dan tidak ada tautan "Upgrade" yang
  // mengarah ke /billing sebagai jalan pembayaran.
  const checkoutLinks = await page.locator('a[href*="dodopayments"], a[href*="checkout"]').count();
  expect(checkoutLinks, "masih ada tautan checkout di /pricing").toBe(0);
  const upgradeLinks = await page.locator('a:has-text("Upgrade")').count();
  console.log(`PAYMENT_PRICING upgrade_links=${upgradeLinks}`);
  expect(upgradeLinks, "CTA 'Upgrade' masih tampil di /pricing").toBe(0);
});

// ===========================================================================
// 3. /billing — lencana "segera hadir", tanpa tautan bayar
// ===========================================================================
test("pembayaran tertutup: /billing menampilkan lencana, tanpa tautan bayar", async ({ page }) => {
  await page.goto("/billing", { waitUntil: "load", timeout: 90_000 });
  await page.waitForSelector("#main-content", { timeout: 45_000 });
  await page.waitForTimeout(1500);

  await expect(page.locator('[data-testid="payment-coming-soon"]').first()).toBeVisible();
  await expect(page.locator('[data-testid="plan-coming-soon"]')).toBeVisible();
  const payLinks = await page.locator('a[href*="dodopayments"], a[href*="checkout"]').count();
  console.log(`PAYMENT_BILLING pay_links=${payLinks}`);
  expect(payLinks, "masih ada tautan pembayaran di /billing").toBe(0);
});

// ===========================================================================
// 4. /chat — spanduk "pembayaran belum dibuka" + bisa ditutup
// ===========================================================================
test("pembayaran tertutup: /chat menampilkan spanduk yang bisa ditutup", async ({ page }) => {
  await page.goto("/chat", { waitUntil: "load", timeout: 90_000 });
  await page.waitForSelector("#main-content, [data-testid='payment-banner']", { timeout: 45_000 });

  const banner = page.locator('[data-testid="payment-banner"]');
  await expect(banner, "spanduk pembayaran tidak muncul di /chat").toBeVisible({ timeout: 20_000 });
  const text = (await banner.innerText()).toLowerCase();
  console.log("PAYMENT_BANNER_TEXT=" + text.replace(/\s+/g, " ").slice(0, 160));
  // Lokal-agnostik: locale default adalah EN, jadi jangan mengikat ke satu bahasa.
  expect(/payment|pembayaran/.test(text), `teks spanduk tidak menyebut pembayaran: ${text}`).toBe(true);

  await page.locator('[data-testid="payment-banner-close"]').click();
  await expect(banner, "spanduk tidak hilang setelah ditutup").toHaveCount(0);

  // Penutupan harus bertahan setelah muat ulang (disimpan di localStorage).
  await page.reload({ waitUntil: "load" });
  await page.waitForTimeout(2500);
  await expect(page.locator('[data-testid="payment-banner"]'), "spanduk muncul lagi setelah reload").toHaveCount(0);
});
