import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * Template Gallery (/templates) — 12 tes.
 *
 * Strategi (mengikuti pola `playwright.mcp.config.ts` yang sudah dipakai di repo):
 * seluruh endpoint backend di-stub lewat `page.route`, sehingga tes
 * DETERMINISTIK dan tidak bergantung pada sesi/kredensial. Yang diuji adalah
 * bundle produksi yang benar-benar di-deploy (`E2E_BASE_URL`), bukan dev server.
 *
 * PENTING soal pola URL: halaman /templates SENDIRI beralamat
 * `https://<domain>/templates`, jadi glob `**​/templates*` akan ikut mencegat
 * navigasi dokumen. Karena itu pencegat di-scope ke ORIGIN BACKEND lewat regex,
 * bukan glob.
 */
const BASE = (process.env.E2E_BASE || "https://katalir.de5.net").replace(/\/$/, "");
const API_ORIGIN = (
  process.env.E2E_API_ORIGIN || "https://web-production-dc90b.up.railway.app"
).replace(/\/$/, "");
const SHOTS = "../docs/marketing/screenshots/templates-gallery";

/** Regex pencegat khusus endpoint backend /templates*. */
const TPL_RE = new RegExp(
  `^${API_ORIGIN.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/templates`,
);

type Tpl = {
  id: string;
  name: string;
  description: string;
  category: string;
  tags: string[];
  icon: string;
  source: "builtin" | "custom";
  node_count: number;
  flow_data: { nodes: unknown[]; edges: unknown[] };
};

function node(id: string, kind: string, label: string) {
  return { id, type: kind === "trigger" ? "trigger" : "mcp-tool", position: { x: 0, y: 0 }, data: { kind, label, config: {} } };
}

/** Katalog fixture: 4 bawaan + 1 kustom. */
const FIXTURES: Tpl[] = [
  {
    id: "tpl-email-ke-sheets",
    name: "Email masuk → Google Sheets",
    description: "Setiap email baru dirangkum lalu ditambahkan ke Google Sheets.",
    category: "data",
    tags: ["gmail", "sheets"],
    icon: "mail",
    source: "builtin",
    node_count: 3,
    flow_data: {
      nodes: [node("t1", "trigger", "Email Masuk"), node("a1", "agent", "Rangkum Email"), node("m1", "mcp", "Tambah ke Sheets")],
      edges: [{ id: "e1", source: "t1", target: "a1" }, { id: "e2", source: "a1", target: "m1" }],
    },
  },
  {
    id: "tpl-rss-ke-slack",
    name: "RSS → Slack",
    description: "Cek feed RSS lalu kirim ringkasan item terbaru ke Slack.",
    category: "notification",
    tags: ["http", "slack"],
    icon: "rss",
    source: "builtin",
    node_count: 4,
    flow_data: {
      nodes: [node("t1", "trigger", "Jadwal Harian"), node("m1", "mcp", "Ambil RSS"), node("a1", "agent", "Pilih 5 Teratas"), node("m2", "mcp", "Kirim ke Slack")],
      edges: [{ id: "e1", source: "t1", target: "m1" }, { id: "e2", source: "m1", target: "a1" }, { id: "e3", source: "a1", target: "m2" }],
    },
  },
  {
    id: "tpl-telegram-digest-harian",
    name: "Digest Harian → Telegram",
    description: "Setiap pagi Agent menyusun digest lalu mengirimkannya ke Telegram.",
    category: "notification",
    tags: ["telegram", "cron"],
    icon: "send",
    source: "builtin",
    node_count: 3,
    flow_data: {
      nodes: [node("t1", "trigger", "Setiap Pagi 07:00"), node("a1", "agent", "Susun Digest"), node("m1", "mcp", "Kirim Telegram")],
      edges: [{ id: "e1", source: "t1", target: "a1" }, { id: "e2", source: "a1", target: "m1" }],
    },
  },
  {
    id: "tpl-tanya-jawab-ai",
    name: "Tanya Jawab AI",
    description: "Agent menjawab pertanyaan dari webhook memakai konteks Anda.",
    category: "ai",
    tags: ["agent", "webhook"],
    icon: "sparkles",
    source: "builtin",
    node_count: 2,
    flow_data: {
      nodes: [node("t1", "trigger", "Webhook Pertanyaan"), node("a1", "agent", "Jawab")],
      edges: [{ id: "e1", source: "t1", target: "a1" }],
    },
  },
  {
    id: "11111111-2222-3333-4444-555555555555",
    name: "Template Kustom Saya",
    description: "Dibuat dari workflow saya sendiri.",
    category: "ops",
    tags: ["kustom"],
    icon: "activity",
    source: "custom",
    node_count: 1,
    flow_data: { nodes: [node("t1", "trigger", "Manual")], edges: [] },
  },
];

/** Pasang stub untuk seluruh endpoint /templates* pada halaman. */
async function stubBackend(page: Page, opts?: { failList?: boolean; onUse?: (r: Route) => void; onDelete?: (r: Route) => void }) {
  await page.route(TPL_RE, async (route: Route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    const path = url.pathname;

    if (opts?.failList && path === "/templates" && method === "GET") {
      await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Gagal memuat template: server sibuk" }) });
      return;
    }

    // GET /templates/info
    if (path === "/templates/info") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "success", builtin_count: 4, categories: ["notification", "marketing", "data", "ops", "ai", "integration"], builtin_ids: [], max_nodes: 100, max_edges: 200 }) });
      return;
    }

    // POST /templates/{id}/use
    if (method === "POST" && /\/use$/.test(path)) {
      if (opts?.onUse) opts.onUse(route);
      const id = decodeURIComponent(path.split("/").slice(-2)[0]);
      const tpl = FIXTURES.find((t) => t.id === id);
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ status: "success", template: { id, name: tpl?.name, category: tpl?.category, source: tpl?.source, node_count: tpl?.node_count }, workflow: { id: "wf-baru-123", name: tpl?.name ?? "Workflow baru" } }) });
      return;
    }

    // DELETE /templates/{id}
    if (method === "DELETE") {
      if (opts?.onDelete) opts.onDelete(route);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "success", deleted: true }) });
      return;
    }

    // GET /templates (+ query)
    if (method === "GET" && path === "/templates") {
      const category = url.searchParams.get("category");
      const q = (url.searchParams.get("q") || "").toLowerCase();
      let items = FIXTURES.slice();
      if (category) items = items.filter((t) => t.category === category);
      if (q) items = items.filter((t) => t.name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q) || t.tags.some((tag) => tag.toLowerCase().includes(q)));
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "success", count: items.length, templates: items }) });
      return;
    }

    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "not stubbed" }) });
  });
}

test.describe("Template Gallery (/templates)", () => {
  test("1. halaman render tanpa crash + judul & landmark utama ada", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));
    await stubBackend(page);
    await page.goto(`${BASE}/templates`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector("#main-content", { timeout: 45_000 });
    await page.waitForSelector('[data-testid="template-gallery"]', { timeout: 45_000 });
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Template");
    expect(errors, `pageerror: ${JSON.stringify(errors)}`).toHaveLength(0);
    await page.screenshot({ path: `${SHOTS}/01-page.png` });
  });

  test("2. tautan Template ada di navigasi shell dan menuju /templates", async ({ page }) => {
    await stubBackend(page);
    await page.goto(`${BASE}/chat`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForTimeout(2500);
    const link = page.locator('[data-testid="shell-templates-link"]');
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "/templates");
    await link.click();
    await page.waitForURL("**/templates", { timeout: 45_000 });
    await expect(page.locator('[data-testid="template-gallery"]')).toBeVisible({ timeout: 45_000 });
    await page.screenshot({ path: `${SHOTS}/02-nav.png` });
  });

  test("3. kisi menampilkan seluruh template (bawaan + kustom)", async ({ page }) => {
    await stubBackend(page);
    await page.goto(`${BASE}/templates`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector('[data-testid="template-grid"]', { timeout: 45_000 });
    const cards = page.locator('[data-testid="template-card"]');
    await expect(cards).toHaveCount(FIXTURES.length);
    // Badge "Kustom" hanya untuk template non-bawaan.
    await expect(page.locator('[data-testid="template-badge-custom"]')).toHaveCount(1);
    await page.screenshot({ path: `${SHOTS}/03-grid.png`, fullPage: true });
  });

  test("4. chip filter kategori lengkap + tombol Semua", async ({ page }) => {
    await stubBackend(page);
    await page.goto(`${BASE}/templates`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector('[data-testid="template-filters"]', { timeout: 45_000 });
    await expect(page.locator('[data-testid="filter-all"]')).toBeVisible();
    for (const c of ["notification", "data", "ops", "ai"]) {
      await expect(page.locator(`[data-testid="filter-${c}"]`)).toBeVisible();
    }
    // "Semua" aktif (aria-pressed) secara default.
    await expect(page.locator('[data-testid="filter-all"]')).toHaveAttribute("aria-pressed", "true");
    await page.screenshot({ path: `${SHOTS}/04-filters.png` });
  });

  test("5. pencarian memfilter daftar (server-side q)", async ({ page }) => {
    await stubBackend(page);
    await page.goto(`${BASE}/templates`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector('[data-testid="template-grid"]', { timeout: 45_000 });
    const input = page.getByLabel("Cari template").or(page.getByPlaceholder("Cari template…"));
    await input.first().fill("slack");
    await expect(page.locator('[data-testid="template-card"]')).toHaveCount(1, { timeout: 15_000 });
    await expect(page.locator('[data-testid="template-card"]')).toContainText("RSS → Slack");
    await page.screenshot({ path: `${SHOTS}/05-search.png` });
  });

  test("6. filter kategori mempersempit daftar ke satu kategori", async ({ page }) => {
    await stubBackend(page);
    await page.goto(`${BASE}/templates`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector('[data-testid="template-grid"]', { timeout: 45_000 });
    await page.locator('[data-testid="filter-notification"]').click();
    await expect(page.locator('[data-testid="template-card"]')).toHaveCount(2, { timeout: 15_000 });
    const cats = await page.locator('[data-testid="template-card"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-template-category")));
    expect(new Set(cats)).toEqual(new Set(["notification"]));
    await expect(page.locator('[data-testid="filter-notification"]')).toHaveAttribute("aria-pressed", "true");
    await page.screenshot({ path: `${SHOTS}/06-category.png` });
  });

  test("7. pratinjau membuka modal dan menampilkan rantai node", async ({ page }) => {
    await stubBackend(page);
    await page.goto(`${BASE}/templates`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector('[data-testid="template-grid"]', { timeout: 45_000 });
    const card = page.locator('[data-template-id="tpl-rss-ke-slack"]');
    await card.locator('[data-testid="template-preview-btn"]').click();
    const preview = page.locator('[data-testid="template-preview"]');
    await expect(preview).toBeVisible({ timeout: 15_000 });
    await expect(page.locator('[data-testid="preview-node"]')).toHaveCount(4);
    await expect(page.locator('[data-testid="preview-flow"]')).toContainText("Ambil RSS");
    await page.screenshot({ path: `${SHOTS}/07-preview.png` });
    // Tutup via tombol Tutup.
    await page.locator('[data-testid="preview-close-btn"]').click();
    await expect(preview).toBeHidden({ timeout: 10_000 });
  });

  test("8. tombol Pakai pada kartu memanggil POST /use dan menampilkan notifikasi sukses", async ({ page }) => {
    let useCalled = 0;
    let usedPath = "";
    await stubBackend(page, { onUse: (r) => { useCalled++; usedPath = new URL(r.request().url()).pathname; } });
    await page.goto(`${BASE}/templates`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector('[data-testid="template-grid"]', { timeout: 45_000 });
    await page.locator('[data-template-id="tpl-email-ke-sheets"]').locator('[data-testid="template-use-btn"]').click();
    const notice = page.locator('[data-testid="template-notice"]');
    await expect(notice).toBeVisible({ timeout: 20_000 });
    await expect(notice).toContainText("dibuat dari template");
    expect(useCalled, "POST /templates/{id}/use tidak terpanggil").toBe(1);
    expect(usedPath).toBe("/templates/tpl-email-ke-sheets/use");
    await page.screenshot({ path: `${SHOTS}/08-use-card.png` });
  });

  test("9. tombol Pakai dari dalam pratinjau juga membuat workflow", async ({ page }) => {
    let useCalled = 0;
    await stubBackend(page, { onUse: () => { useCalled++; } });
    await page.goto(`${BASE}/templates`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector('[data-testid="template-grid"]', { timeout: 45_000 });
    await page.locator('[data-template-id="tpl-tanya-jawab-ai"]').locator('[data-testid="template-preview-btn"]').click();
    await page.waitForSelector('[data-testid="template-preview"]', { timeout: 15_000 });
    await page.locator('[data-testid="preview-use-btn"]').click();
    await expect(page.locator('[data-testid="template-notice"]')).toBeVisible({ timeout: 20_000 });
    expect(useCalled).toBe(1);
    // Modal pratinjau harus tertutup setelah "Pakai".
    await expect(page.locator('[data-testid="template-preview"]')).toBeHidden({ timeout: 10_000 });
    await page.screenshot({ path: `${SHOTS}/09-use-preview.png` });
  });

  test("10. tombol hapus hanya ada pada template kustom dan memanggil DELETE", async ({ page }) => {
    let delCalled = 0;
    await stubBackend(page, { onDelete: () => { delCalled++; } });
    await page.goto(`${BASE}/templates`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector('[data-testid="template-grid"]', { timeout: 45_000 });
    // Bawaan tidak punya tombol hapus.
    await expect(page.locator('[data-template-id="tpl-rss-ke-slack"] [data-testid="template-delete-btn"]')).toHaveCount(0);
    const custom = page.locator('[data-template-source="custom"]');
    await expect(custom.locator('[data-testid="template-delete-btn"]')).toHaveCount(1);
    await custom.locator('[data-testid="template-delete-btn"]').click();
    await expect(page.locator('[data-testid="template-notice"]')).toContainText("dihapus", { timeout: 20_000 });
    expect(delCalled).toBe(1);
    await page.screenshot({ path: `${SHOTS}/10-delete.png` });
  });

  test("11. keadaan kosong tampil saat pencarian tidak menemukan apa pun", async ({ page }) => {
    await stubBackend(page);
    await page.goto(`${BASE}/templates`, { waitUntil: "load", timeout: 90_000 });
    await page.waitForSelector('[data-testid="template-grid"]', { timeout: 45_000 });
    const input = page.getByLabel("Cari template").or(page.getByPlaceholder("Cari template…"));
    await input.first().fill("zzz-tidak-ada-xyz");
    await expect(page.locator('[data-testid="template-empty"]')).toBeVisible({ timeout: 15_000 });
    await expect(page.locator('[data-testid="template-empty"]')).toContainText("Tidak ada template cocok");
    await page.screenshot({ path: `${SHOTS}/11-empty.png` });
  });

  test("12. keadaan galat + tombol Coba lagi saat backend 500", async ({ page }) => {
    await stubBackend(page, { failList: true });
    await page.goto(`${BASE}/templates`, { waitUntil: "load", timeout: 90_000 });
    const err = page.locator('[data-testid="template-error"]');
    await expect(err).toBeVisible({ timeout: 45_000 });
    await expect(err).toContainText("Gagal memuat template");
    await expect(page.locator('[data-testid="template-retry-btn"]')).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/12-error.png` });
  });
});
