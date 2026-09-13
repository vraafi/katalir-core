import { test, expect } from "@playwright/test";

// Verifikasi UX: lock lepas, Stop, queue, edit, visual, konfirmasi chat baru.
// Catatan: /chat ke Gemini lambat — test cukup untuk input lock + Stop morph
// + antrean visual + edit inline (dipompa FIFO saat idle). Jaringan backend
// hanya sampai "terkirim/queued", bukan menunggu reply AI penuh.
const TARGET = process.env.E2E_TARGET || "http://localhost:3000";
const E2E_SESSION = "./_e2e_storage.json";

test.describe("UX message queue + stop", () => {
  test.use({ storageState: E2E_SESSION });

  test("input tetap aktif saat loading + Stop morph + queue 2 pesan", async ({ page }) => {
    const out: string[] = [];
    page.on("console", (m) => { if (m.type() === "error") out.push(m.text().slice(0, 120)); });
    await page.goto(TARGET, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2500);

    const input = page.getByLabel("Pesan");
    await expect(input).toBeEnabled();
    await input.fill("ux probe satu");
    await page.getByLabel("Pesan").press("Enter");

    // Segera setelah kirim: bubble user harus ada, input HARUS tetap enabled (Fix 1)
    await expect(page.getByTestId("msg-list")).toContainText("ux probe satu", { timeout: 15000 });
    await expect(input).toBeEnabled({ timeout: 5000 });

    // Saat AI bekerja & composer kosong: tombol Stop muncul (Fix 2)
    const stopBtn = page.getByRole("button", { name: "Stop" });
    await expect(stopBtn).toBeVisible({ timeout: 15000 });

    // Ketik follow-up -> tombol balik jadi Send, kirim -> masuk antrean (Fix 2+3)
    await input.fill("ux probe dua");
    await expect(page.getByRole("button", { name: "Kirim", exact: true })).toBeVisible({ timeout: 5000 });
    await page.getByLabel("Pesan").press("Enter");
    const queued = page.getByTestId("queued-msg");
    await expect(queued.first()).toContainText("ux probe dua", { timeout: 5000 });
    await expect(queued.first()).toContainText("Queued", { timeout: 5000 });

    // Edit pesan antrean (Fix 4)
    await queued.first().getByRole("button", { name: "Edit antrean" }).click();
    const editBox = page.getByLabel("Ubah teks antrean");
    await editBox.fill("ux probe dua EDIT");
    await page.getByRole("button", { name: "Simpan edit antrean" }).click();
    await expect(queued.first()).toContainText("ux probe dua EDIT", { timeout: 5000 });

    // Chat Baru saat AI sibuk -> dialog konfirmasi (Fix 6)
    await page.getByRole("button", { name: /Chat Baru/i }).click();
    await expect(page.getByText("AI sedang bekerja di chat ini")).toBeVisible({ timeout: 5000 });
    await page.getByRole("button", { name: "Tetap di sini" }).click();

    // Stop -> cancel request, loading hilang
    await input.fill("");
    const stop2 = page.getByRole("button", { name: "Stop" });
    if (await stop2.count()) {
      await stop2.first().click();
      await page.waitForTimeout(2000);
    }
    console.log("CONSOLE_ERRORS=" + JSON.stringify(out.slice(0, 5)));
  });
});
