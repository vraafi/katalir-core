import { test, expect } from "@playwright/test";

// Fix 3 stress (gptme #1254): 3 submit cepat SEKALIGUS -> hanya 1 yang
// in-flight (busyRef sinkron), sisanya masuk antrean FIFO — tidak pernah
// 2 mutateAsync paralel ke key yang sama (race window 1-tick).
const TARGET = process.env.E2E_TARGET || "http://localhost:3000";
const E2E_SESSION = "./_e2e_storage.json";

test.describe("UX queue burst", () => {
  test.use({ storageState: E2E_SESSION });

  test("3 submit cepat: 1 tampil + 2 queued, FIFO berurutan", async ({ page }) => {
    await page.goto(TARGET, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2500);
    const input = page.getByLabel("Pesan");
    await expect(input).toBeEnabled();
    // Tembak 3 pesan sekaligus tanpa menunggu render di antaranya.
    await input.fill("burst A");
    await page.getByRole("button", { name: "Kirim", exact: true }).click();
    await input.fill("burst B");
    // Tombol berubah Send<->Stop tergantung state; pakai Enter agar deterministik.
    await input.press("Enter");
    await input.fill("burst C");
    await input.press("Enter");
    await page.waitForTimeout(1500);
    // Queue default collapsed: baca label + preview dulu (Geta.Team pattern).
    await expect(page.getByTestId("queue-area")).toContainText("Antrean (2)", { timeout: 5000 });
    await expect(page.getByTestId("queue-preview")).toContainText("burst B", { timeout: 5000 });
    // Expand lalu cek isi queued + urutan FIFO.
    await page.getByTestId("queue-toggle").click();
    const nQueued = await page.getByTestId("queued-msg").count();
    const body = (await page.textContent("body")) ?? "";
    const countA = (body.match(/burst A/g) || []).length;
    const countB = (body.match(/burst B/g) || []).length;
    const countC = (body.match(/burst C/g) || []).length;
    console.log(`BURST A=${countA} B=${countB} C=${countC} QUEUED_SLOTS=${nQueued}`);
    // Semua 3 teks harus tampil tepat 1x (1 in-flight + 2 queued), tidak ada yang hilang/duplikat.
    expect(countA).toBe(1);
    expect(countB).toBe(1);
    expect(countC).toBe(1);
    expect(nQueued).toBe(2);
    await expect(page.getByTestId("queued-msg").first()).toContainText("burst B");
    await expect(page.getByTestId("queued-msg").nth(1)).toContainText("burst C");
  });
});
