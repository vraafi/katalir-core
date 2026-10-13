/**
 * BUG-10 — Regresi aksesibilitas `/templates` (dan kelas cacat yang sama di
 * `/integrations`).
 *
 * TEMUAN ASLI (hard test 13 Okt, skenario B-12): `/templates` punya 2 pelanggaran
 *   · `color-contrast` **serious** ×9 — chip kategori `bg-<c>-500/15 text-<c>-600`
 *   · `heading-order` **moderate** ×1 — judul kartu `<h3>` setelah `<h1>`
 * `/chat`, `/builder`, `/settings` bersih.
 *
 * AKAR MASALAH: bukan "satu chip yang salah", melainkan **pola warna** yang
 * dipakai berulang. Karena itu spec ini menguji dua hal:
 *   1. Nilai kontrasnya (axe `color-contrast`) — bukan daftar kelas tertentu.
 *      Chip dibuat dari data, jadi kelasnya bisa berubah; yang tidak boleh
 *      berubah adalah rasio kontrasnya.
 *   2. Struktur heading (`heading-order` + urutan nyata h1 → h2), supaya
 *      perubahan level heading tidak lolos tanpa jejak.
 *
 * KENAPA DATA DI-FIXTURE, BUKAN DARI BACKEND: jumlah pelanggaran bergantung pada
 * template yang kebetulan ada di database (kategori mana yang muncul). Fixture
 * membuat tes deterministik dan menjangkau SEMUA enam kategori — termasuk yang
 * kebetulan tidak ada di DB — sehingga regresi warna ketahuan sebelum user
 * melihatnya. Backend tetap diuji di `templates-live.spec.ts`.
 */
import { test, expect, type Page } from "@playwright/test";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const SHOTS = join(process.cwd(), "f6-shots", "bug-10");
const AXE_PATH = join(process.cwd(), "node_modules", "axe-core", "axe.min.js");

const CATS = ["notification", "marketing", "data", "ops", "ai", "integration"];
const NAMES: [string, string][] = [
  ["Kirim email selamat datang", "mail"],
  ["Siarkan RSS ke Telegram", "rss"],
  ["Posting promo ke sosial media", "send"],
  ["Webhook ke Slack saat error", "webhook"],
  ["Ringkas dokumen dengan AI", "sparkles"],
  ["Sinkron tabel ke Google Sheets", "table"],
  ["Ingatkan jadwal rapat harian", "calendar"],
  ["Pantau uptime situs", "activity"],
  ["Balas komentar otomatis", "message-circle"],
];

/** Sembilan template menutupi keenam kategori (2 kustom agar badge "Kustom" ikut). */
const TEMPLATES = NAMES.map((n, i) => ({
  id: `tpl-${i + 1}`,
  name: n[0],
  description: "Alur siap pakai: hubungkan pemicu, proses, dan aksi tanpa menulis kode.",
  category: CATS[i % CATS.length],
  tags: ["otomatis", "contoh"],
  icon: n[1],
  source: i === 4 || i === 8 ? "custom" : "builtin",
  node_count: 3 + (i % 4),
  flow_data: { nodes: [], edges: [] },
  created_at: "2026-10-01T00:00:00Z",
}));

/** Layani `GET /templates*` dari fixture, tetapi JANGAN sentuh origin aplikasi. */
async function stubTemplates(page: Page) {
  const base = new URL(test.info().project.use.baseURL || "http://localhost:3000").origin;
  await page.route(
    // `includes`, bukan `startsWith`: build produksi membakar URL backend dengan
    // prefix path (`/katalir-api/templates`), sedangkan build E2E memakai
    // `/templates` polos. Keduanya harus tertangkap agar fixture tidak bergantung
    // pada cara app di-build.
    (url) => url.pathname.includes("/templates") && url.origin !== base,
    async (route) => {
      const u = route.request().url();
      const body = u.includes("/templates/info")
        ? {
            status: "success",
            builtin_count: 7,
            categories: CATS,
            builtin_ids: TEMPLATES.map((t) => t.id),
            max_nodes: 200,
            max_edges: 400,
          }
        : { status: "success", count: TEMPLATES.length, templates: TEMPLATES };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    },
  );
}

type Violation = {
  id: string;
  impact: string | null;
  nodes: number;
  targets: { target: string; html: string; why: string; data: unknown }[];
};

async function axeScan(page: Page): Promise<Violation[]> {
  if (!existsSync(AXE_PATH)) throw new Error("axe-core tidak ada di node_modules");
  await page.addScriptTag({ path: AXE_PATH });
  return page.evaluate(async () => {
    // @ts-expect-error axe disuntik runtime
    const axe = window.axe;
    const res = await axe.run(document, {
      resultTypes: ["violations"],
      runOnly: {
        type: "tag",
        values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"],
      },
    });
    return (res.violations as {
      id: string;
      impact: string | null;
      nodes: {
        target: unknown;
        html: string;
        failureSummary?: string;
        any?: { data?: unknown }[];
        all?: { data?: unknown }[];
      }[];
    }[]).map((v) => ({
      id: v.id,
      impact: v.impact,
      nodes: v.nodes.length,
      targets: v.nodes.map((n) => ({
        target: JSON.stringify(n.target).slice(0, 120),
        html: String(n.html).replace(/\s+/g, " ").slice(0, 160),
        why: String(n.failureSummary ?? "").replace(/\s+/g, " ").slice(0, 200),
        data: n.any?.[0]?.data ?? n.all?.[0]?.data ?? null,
      })),
    }));
  });
}

function saveShot(page: Page, name: string) {
  if (!existsSync(SHOTS)) mkdirSync(SHOTS, { recursive: true });
  return page.screenshot({ path: join(SHOTS, name), fullPage: true });
}

/**
 * Layani registry MCP dari fixture supaya KEEMPAT badge tier benar-benar
 * dirender. Tanpa ini, registry gagal dimuat (tidak ada backend saat audit
 * aksesibilitas) dan satu-satunya hal yang terukur adalah keadaan galat —
 * yaitu "0 pelanggaran" yang tidak membuktikan apa pun tentang badge.
 */
async function stubRegistry(page: Page) {
  const base = new URL(test.info().project.use.baseURL || "http://localhost:3000").origin;
  const mk = (i: number, tier: string) => ({
    id: `reg-${i}`,
    name: `Server ${tier}`,
    category: "tools",
    description: "Integrasi contoh untuk audit kontras badge tier.",
    source: "glama",
    source_url: "https://glama.ai/mcp/servers",
    tools: [],
    tools_count: 3,
    no_auth: tier === "call_verified",
    runtime_tier: tier,
  });
  const items = [
    mk(1, "call_verified"),
    mk(2, "auth_required"),
    mk(3, "tools_listed"),
    mk(4, "discovered"),
  ];
  await page.route(
    (url) => url.pathname.includes("/mcp/") && url.origin !== base,
    async (route) => {
      const p = new URL(route.request().url()).pathname;
      let body: unknown = {};
      if (p.endsWith("/registry")) body = { items, total: items.length };
      else if (p.endsWith("/registry/sources")) body = { sources: { glama: 4 }, sources_unique: { glama: 4 } };
      else if (p.endsWith("/registry/capabilities")) body = { unique_view: true };
      else if (p.endsWith("/registry/categories"))
        // Bentuk NYATA: array objek {category, count}. Mengirim array string di
        // sini membuat halaman melempar `undefined.toLocaleString()` → Next
        // merender halaman galat, dan auditnya mengukur halaman galat itu.
        body = { categories: [{ category: "tools", count: items.length }] };
      else if (p.endsWith("/mcp/native")) body = { items: [], total: 0 };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    },
  );
}

// ===========================================================================
// 1. /templates — 0 pelanggaran serious/critical, dan heading-order bersih
// ===========================================================================
test("BUG-10 /templates: chip kategori AA + heading-order bersih", async ({ page }) => {
  await stubTemplates(page);
  await page.goto("/templates", { waitUntil: "load", timeout: 90_000 });
  await page.waitForSelector('[data-testid="template-card"]', { timeout: 45_000 });
  await page.waitForTimeout(1200);

  const cards = await page.locator('[data-testid="template-card"]').count();
  expect(cards, "fixture tidak ter-render — asersi kontras tidak valid").toBe(TEMPLATES.length);

  const violations = await axeScan(page);
  const severe = violations.filter((v) => v.impact === "critical" || v.impact === "serious");
  console.log("BUG10_AXE_templates=" + JSON.stringify(violations.map((v) => `${v.id}(${v.impact})x${v.nodes}`)));
  if (violations.length) console.log("BUG10_AXE_templates_DETAIL=" + JSON.stringify(violations, null, 1));

  // Kontras diukur pada elemen chip yang sesungguhnya; data axe memuat rasio.
  const contrast = violations.find((v) => v.id === "color-contrast");
  if (contrast) {
    const worst = contrast.targets
      .map((t) => (t.data as { contrastRatio?: number })?.contrastRatio ?? 0)
      .sort((a, b) => a - b)[0];
    console.log(`BUG10_WORST_CONTRAST=${worst}`);
  }

  const headingOrder = violations.find((v) => v.id === "heading-order");
  expect(headingOrder, `heading-order masih dilanggar: ${JSON.stringify(headingOrder?.targets)}`).toBeUndefined();
  expect(severe, "masih ada pelanggaran serious/critical di /templates").toHaveLength(0);

  await saveShot(page, "templates-after.png");
});

// ===========================================================================
// 2. Urutan heading nyata: h1 tunggal, level berikutnya h2 (bukan lompatan)
// ===========================================================================
test("BUG-10 /templates: hierarki heading h1 → h2 tanpa lompatan", async ({ page }) => {
  await stubTemplates(page);
  await page.goto("/templates", { waitUntil: "load", timeout: 90_000 });
  await page.waitForSelector('[data-testid="template-card"]', { timeout: 45_000 });
  await page.waitForTimeout(800);

  const outline = await page.$$eval("h1,h2,h3,h4,h5,h6", (els) =>
    els.map((e) => Number(e.tagName.slice(1))),
  );
  console.log("BUG10_HEADING_OUTLINE=" + JSON.stringify(outline));
  expect(outline.length, "tidak ada heading sama sekali").toBeGreaterThan(1);
  expect(outline[0], "heading pertama harus h1").toBe(1);
  expect(outline.filter((l) => l === 1).length, "h1 harus tunggal").toBe(1);
  // Setiap heading setelah h1 tidak boleh melompat lebih dari satu level.
  for (let i = 1; i < outline.length; i++) {
    expect(
      outline[i] - outline[i - 1],
      `lompatan heading pada indeks ${i}: ${outline[i - 1]} → ${outline[i]}`,
    ).toBeLessThanOrEqual(1);
  }
});

// ===========================================================================
// 3. Kelas cacat yang sama di /integrations (badge tier)
// ===========================================================================
test("BUG-10 /integrations: badge tier juga bebas pelanggaran kontras", async ({ page }) => {
  await stubRegistry(page);
  const res = await page.goto("/integrations", { waitUntil: "load", timeout: 90_000 });
  // Gerbang status: pernah terjadi (2026-10-13) `/integrations` dijawab 404 oleh
  // server statis lokal karena `out/integrations/` (rute anak) menutupi
  // `out/integrations.html`. Auditnya lalu mengukur HALAMAN 404 dan melaporkan
  // `document-title`/`html-has-lang` sebagai pelanggaran produk — temuan palsu.
  // Assert status membuat kegagalan harness terlihat sebagai kegagalan harness.
  expect(res?.status(), "harness menyajikan bukan halaman /integrations").toBe(200);
  await page.waitForSelector("#main-content", { timeout: 45_000 });
  await page.waitForSelector('[data-testid="integration-card"]', { timeout: 45_000 });
  await page.waitForTimeout(1500);

  // Keempat badge harus ada — kalau tidak, "0 pelanggaran" tidak bermakna.
  for (const id of ["badge-ready", "badge-auth", "badge-listed", "badge-catalog"]) {
    await expect(page.locator(`[data-testid="${id}"]`).first(), `badge ${id} tidak dirender`).toBeVisible();
  }
  const badgeColors = await page.$$eval('[data-testid^="badge-"]', (els) =>
    els.map((e) => ({ t: e.getAttribute("data-testid"), c: getComputedStyle(e).color })),
  );
  console.log("BUG10_BADGE_COLORS=" + JSON.stringify(badgeColors));

  const violations = await axeScan(page);
  const severe = violations.filter((v) => v.impact === "critical" || v.impact === "serious");
  console.log("BUG10_AXE_integrations=" + JSON.stringify(violations.map((v) => `${v.id}(${v.impact})x${v.nodes}`)));
  if (violations.length) console.log("BUG10_AXE_integrations_DETAIL=" + JSON.stringify(violations, null, 1));

  await saveShot(page, "integrations-after.png");
  expect(severe, "masih ada pelanggaran serious/critical di /integrations").toHaveLength(0);
});

// Tulis ringkasan mesin-terbaca untuk laporan (dibaca FASE 8).
test.afterAll(() => {
  if (!existsSync(SHOTS)) mkdirSync(SHOTS, { recursive: true });
  writeFileSync(
    join(SHOTS, "summary.json"),
    JSON.stringify({ bug: "BUG-10", spec: "tests/bug10-a11y.spec.ts", shots: SHOTS }, null, 2),
  );
});
