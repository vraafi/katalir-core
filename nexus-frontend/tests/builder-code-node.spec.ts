/**
 * HARD TEST UI — node "code" di Canvas Builder (fitur #6, sandbox).
 *
 * TARGET: BUNDLE PRODUKSI (`out/` via `scripts/serve-out.mjs`, port 3110).
 * Alasan tidak memakai `next dev` ada di kepala `playwright.codenode.config.ts`.
 *
 * SETIAP tes punya assertion KUANTITATIF (jumlah node, nilai input, teks
 * terukur, token CSS ter-resolve). Tidak ada "kelihatan benar".
 *
 * Jalankan:
 *   node ./node_modules/@playwright/test/cli.js test -c playwright.codenode.config.ts --reporter=list
 */
import { test, expect, type Page } from "@playwright/test";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const SHOT_DIR = join(process.cwd(), "..", "docs", "marketing", "screenshots", "code-node");

function supabaseRef(): string {
  const fromEnv = (process.env.NEXT_PUBLIC_SUPABASE_URL || "").trim();
  const m0 = fromEnv.match(/https?:\/\/([a-z0-9]+)\.supabase/);
  if (m0) return m0[1];
  for (const f of [".env.local", ".env"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    const m = readFileSync(p, "utf-8").match(
      /NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/);
    if (m) return m[1];
  }
  return "qmukkphwaajzbqjrcvaz";
}

const LS_KEY = `sb-${supabaseRef()}-auth-token`;

/** Semai sesi uji (file yang sama dipakai harness fase 3). */
async function seedSession(page: Page) {
  const p = join(process.cwd(), "_e2e_session.refreshed.json");
  if (!existsSync(p)) return;
  const sess = JSON.parse(readFileSync(p, "utf-8"));
  await page.addInitScript(
    (kv: { key: string; value: unknown }) => {
      try {
        window.localStorage.setItem(kv.key, JSON.stringify(kv.value));
      } catch {
        /* localStorage bisa diblokir; tes tetap lanjut */
      }
    },
    { key: LS_KEY, value: sess }
  );
}

/** Tunggu hidrasi React (marker `data-hydrated` ditulis ke <html>). */
async function waitHydrated(page: Page) {
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
}

/** Buka /builder dengan contoh workflow (4 node) — dasar semua tes di sini. */
async function openDemo(page: Page, extraQuery = "") {
  await seedSession(page);
  await page.goto(`/builder?demo=1${extraQuery}`, { waitUntil: "domcontentloaded" });
  await waitHydrated(page);
  await page.waitForSelector('[data-testid="node-card"]', { timeout: 45000 });
  await page.waitForTimeout(1500);
}

/** Tambah satu node `code` lewat palette (klik = onAddNode, sama seperti drag). */
async function addCodeNode(page: Page) {
  await page.waitForSelector('[data-testid="palette"]', { timeout: 30000 });
  await page.click('[data-testid="palette-item-code"]');
  await page.waitForSelector('[data-testid="node-card"][data-kind="code"]', {
    timeout: 15000,
  });
  await page.waitForTimeout(600);
}

/**
 * Panel konfigurasi desktop.
 *
 * KENAPA HARUS DI-SCOPE: saat sebuah node dipilih, `ConfigPanel` dirender DUA
 * kali — sekali di `<aside data-testid="config-aside">` (desktop, `hidden
 * lg:flex`) dan sekali lagi di dalam `<Sheet>` mobile (`lg:hidden`, tapi TETAP
 * ada di DOM karena `open={!!selectedNode}`). `[data-testid="code-language"]`
 * tanpa scope karena itu cocok ke 2 elemen dan Playwright melempar strict-mode
 * violation — bukan bug aplikasi, tapi locator yang salah. Terbukti: C1 gagal
 * dalam 7,1 s (instan, bukan timeout) padahal node benar-benar terseleksi.
 */
const ASIDE = '[data-testid="config-aside"]';

const langSel = (page: Page) => page.locator(`${ASIDE} [data-testid="code-language"]`);
const timeoutInput = (page: Page) => page.locator(`${ASIDE} [data-testid="code-timeout"]`);
const editor = (page: Page) => page.locator(`${ASIDE} .cm-content`).first();

/** Pilih node code pertama -> panel konfigurasi desktop muncul. */
async function selectCodeNode(page: Page) {
  const card = page.locator('[data-testid="node-card"][data-kind="code"]').first();
  await card.click();
  await page.waitForSelector(ASIDE, { timeout: 15000 });
  await page.waitForSelector(`${ASIDE} [data-testid="code-language"]`, { timeout: 15000 });
  // `ExpressionEditor` dimuat lewat `next/dynamic({ ssr: false })`, jadi saat
  // panel pertama muncul yang ada di DOM adalah placeholder "Memuat editor...".
  // Tanpa menunggu `.cm-editor`, pengukuran memakai `.count()`/`querySelectorAll`
  // (yang TIDAK menunggu) akan membaca placeholder itu dan melaporkan
  // "0 gutter" seolah CodeMirror tidak pernah ter-mount. Terbukti di probe:
  // `cmEditor=false, asideHTMLlen=4061` + `<p class="mt-1 text-xs">Memuat editor…`.
  await page.waitForSelector(`${ASIDE} .cm-editor`, { timeout: 30000 });
  await page.waitForTimeout(400);
}

/**
 * Kumpulkan pageerror + console error agar tes bisa membuktikan "tidak ada".
 *
 * KENAPA ADA FILTER: harness ini menyajikan bundle dari `127.0.0.1:3111`,
 * sementara backend produksi hanya mengizinkan origin `katalir.de5.net`/Pages.
 * Akibatnya setiap request `/workflows` dan `/preferences` diblokir CORS dan
 * menghasilkan console error — itu keadaan LINGKUNGAN, bukan cacat aplikasi,
 * dan mencampurnya ke dalam assertion membuat tes gagal-acak tergantung
 * kapan request yang gagal itu selesai. Yang disaring hanya pola jaringan/CORS;
 * error aplikasi (TypeError, React warning, CSP) tetap lolos.
 */
const LINGKUNGAN = [
  /CORS policy/i,
  /Failed to load resource/i,
  /ERR_FAILED|ERR_CONNECTION|ERR_NAME_NOT_RESOLVED|net::/i,
  /preferences|workflows/i,
];

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const t = m.text();
    if (LINGKUNGAN.some((re) => re.test(t))) return;
    errors.push(`console: ${t}`);
  });
  return errors;
}

// ---------------------------------------------------------------------------
// A. Palette
// ---------------------------------------------------------------------------

test("A1 palette menampilkan node 'Kode' dengan token warna tema yang benar", async ({ page }) => {
  const errors = collectErrors(page);
  await openDemo(page);

  const item = page.locator('[data-testid="palette-item-code"]');
  await expect(item).toBeVisible();

  const info = await item.evaluate((el) => {
    const icon = el.querySelector("span[aria-hidden='true']") as HTMLElement | null;
    return {
      label: el.textContent ?? "",
      bg: icon ? getComputedStyle(icon).backgroundColor : "",
      token: getComputedStyle(document.documentElement)
        .getPropertyValue("--node-code-color")
        .trim(),
    };
  });

  console.log(`[A1] label="${info.label.trim()}" bg=${info.bg} token=${info.token}`);
  expect(info.label).toContain("Kode");
  // Token tema midnight = #34d399 -> rgb(52, 211, 153).
  expect(info.token).toBe("#34d399");
  expect(info.bg).toBe("rgb(52, 211, 153)");
  expect(errors, `error di halaman: ${errors.join(" | ")}`).toHaveLength(0);
});

// ---------------------------------------------------------------------------
// B. Node masuk ke kanvas
// ---------------------------------------------------------------------------

test("B1 klik palette menambah TEPAT satu node code ke kanvas", async ({ page }) => {
  await openDemo(page);
  const before = await page.locator('[data-testid="node-card"]').count();
  await addCodeNode(page);
  const after = await page.locator('[data-testid="node-card"]').count();
  const codes = await page.locator('[data-testid="node-card"][data-kind="code"]').count();
  console.log(`[B1] node sebelum=${before} sesudah=${after} code=${codes}`);
  expect(after).toBe(before + 1);
  expect(codes).toBe(1);
});

test("B2 node code baru langsung punya subtitle sandbox + preview kode default", async ({ page }) => {
  await openDemo(page);
  await addCodeNode(page);
  const txt = (await page
    .locator('[data-testid="node-card"][data-kind="code"]')
    .first()
    .innerText()).replace(/\s+/g, " ");
  console.log(`[B2] teks kartu="${txt}"`);
  expect(txt).toContain("Python");
  expect(txt).toContain("sandbox");
  // Default dari canvas-store: `result = 1 + 1` -> tampil di preview.
  expect(txt).toContain("result = 1 + 1");
});

test("E2 node code memakai kartu Katalir, BUKAN node bawaan React Flow", async ({ page }) => {
  // Bug nyata: `NODE_TYPES` tidak punya kunci `code`, sehingga React Flow
  // memakai node bawaannya — node ADA di store tetapi tanpa `data-testid=
  // "node-card"` dan tanpa Handle. Gejalanya "node tidak muncul", tanpa error.
  await openDemo(page);
  await addCodeNode(page);

  const card = page.locator('[data-testid="node-card"][data-kind="code"]').first();
  await expect(card).toBeVisible();

  // 1) Node React Flow yang membungkus kartu harus bertipe `code`, bukan default.
  const rfClass = await page
    .locator('.react-flow__node[data-id]')
    .evaluateAll((els) =>
      els.map((e) => ({
        id: e.getAttribute("data-id") ?? "",
        cls: e.className,
        hasCard: !!e.querySelector('[data-testid="node-card"]'),
      }))
    );
  const codeNode = rfClass.find((n) => n.id.startsWith("code-"));
  console.log(`[E2] node code RF: ${JSON.stringify(codeNode)}`);
  expect(codeNode, "node code tidak dirender oleh React Flow").toBeTruthy();
  // React Flow menambahkan kelas `react-flow__node-<type>`; kalau type-nya tidak
  // terdaftar, kelasnya menjadi `react-flow__node-default`.
  expect(codeNode!.cls).toContain("react-flow__node-code");
  expect(codeNode!.cls).not.toContain("react-flow__node-default");
  expect(codeNode!.hasCard).toBe(true);

  // 2) Kartu Katalir punya Handle koneksi (node bawaan tidak punya).
  const handles = await card.locator(".react-flow__handle").count();
  console.log(`[E2] handle pada kartu code = ${handles}`);
  expect(handles).toBeGreaterThan(0);

  // 3) Tidak ada node bawaan yang tersisa di kanvas.
  const defaults = await page.locator(".react-flow__node-default").count();
  console.log(`[E2] node bawaan React Flow = ${defaults}`);
  expect(defaults).toBe(0);
});

// ---------------------------------------------------------------------------
// C. Panel konfigurasi (UI update 1.3.3)
// ---------------------------------------------------------------------------

test("C1 panel config: bahasa=python, timeout=30, editor terisi kode default", async ({ page }) => {
  await openDemo(page);
  await addCodeNode(page);
  await selectCodeNode(page);

  const lang = await langSel(page).inputValue();
  const timeout = await timeoutInput(page).inputValue();
  const minMax = await timeoutInput(page).evaluate((el) => ({
    min: (el as HTMLInputElement).min,
    max: (el as HTMLInputElement).max,
    type: (el as HTMLInputElement).type,
  }));
  const editorText = await editor(page).innerText();

  console.log(
    `[C1] language=${lang} timeout=${timeout} min=${minMax.min} max=${minMax.max} editor="${editorText}"`
  );
  expect(lang).toBe("python");
  expect(timeout).toBe("30");
  expect(minMax.type).toBe("number");
  expect(minMax.min).toBe("1");
  // Batas keras sandbox = 30s; atribut max mencegah user mengetik 300.
  expect(minMax.max).toBe("30");
  expect(editorText).toContain("result = 1 + 1");
});

test("C2 ganti bahasa ke JavaScript -> subtitle kartu ikut berubah", async ({ page }) => {
  await openDemo(page);
  await addCodeNode(page);
  await selectCodeNode(page);

  await langSel(page).selectOption("javascript");
  await page.waitForTimeout(600);

  const txt = (await page
    .locator('[data-testid="node-card"][data-kind="code"]')
    .first()
    .innerText()).replace(/\s+/g, " ");
  const lang = await langSel(page).inputValue();
  console.log(`[C2] language=${lang} teks kartu="${txt}"`);
  expect(lang).toBe("javascript");
  expect(txt).toContain("JavaScript");
  expect(txt).toContain("sandbox");
});

test("C3 timeout bisa diubah dan nilainya tersimpan di node", async ({ page }) => {
  await openDemo(page);
  await addCodeNode(page);
  await selectCodeNode(page);

  await timeoutInput(page).fill("12");
  await page.waitForTimeout(600);
  const val = await timeoutInput(page).inputValue();
  // Preview kartu menampilkan timeout -> membuktikan nilai masuk ke STORE,
  // bukan hanya ke DOM input.
  const txt = (await page
    .locator('[data-testid="node-card"][data-kind="code"]')
    .first()
    .innerText()).replace(/\s+/g, " ");
  console.log(`[C3] timeout input=${val} teks kartu="${txt}"`);
  expect(val).toBe("12");
  expect(txt).toContain("12s");
});

test("C4 mengetik kode -> preview kartu node mengikuti (store benar-benar ter-update)", async ({ page }) => {
  await openDemo(page);
  await addCodeNode(page);
  await selectCodeNode(page);

  const cm = editor(page);
  await cm.click();
  // Pilih semua lalu timpa supaya hasilnya deterministik.
  await page.keyboard.press("Control+A");
  await page.keyboard.type('print("halo katalir")');
  await page.waitForTimeout(900);

  const editorText = await cm.innerText();
  const txt = (await page
    .locator('[data-testid="node-card"][data-kind="code"]')
    .first()
    .innerText()).replace(/\s+/g, " ");
  console.log(`[C4] editor="${editorText}" kartu="${txt}"`);
  expect(editorText).toContain('print("halo katalir")');
  expect(txt).toContain('print("halo katalir")');
});

test("C5 editor kode punya nomor baris (kode multi-baris butuh ini)", async ({ page }) => {
  await openDemo(page);
  await addCodeNode(page);
  await selectCodeNode(page);
  const gutter = await page.locator('[data-testid="config-aside"] .cm-gutters').count();
  const lineNumbers = await page
    .locator('[data-testid="config-aside"] .cm-lineNumbers')
    .count();
  console.log(`[C5] .cm-gutters=${gutter} .cm-lineNumbers=${lineNumbers}`);
  expect(gutter).toBeGreaterThan(0);
  expect(lineNumbers).toBeGreaterThan(0);
});

// ---------------------------------------------------------------------------
// F. Bug nyata: Sheet mobile menutup panel konfigurasi DESKTOP
// ---------------------------------------------------------------------------

test("F1 panel konfigurasi desktop TETAP terbuka setelah kolom diedit", async ({ page }) => {
  // Bug nyata: `<Sheet modal={false} open={!!selectedNode}>` juga terbuka di
  // desktop (hanya disembunyikan `lg:hidden`). Radix tetap menganggapnya
  // terbuka dan menutup diri pada pointerdown/focus di luar Content → memanggil
  // `onOpenChange(false)` → `setSelectedId(null)`. Akibatnya panel desktop
  // hilang begitu pengguna mengisi kolom APA PUN. Bukti probe sebelum fix:
  //   `Q1 FILL: aside before=1 after=0 | dialog before=1 after=0 | ?n=null`
  await openDemo(page);
  await addCodeNode(page);
  await selectCodeNode(page);

  await timeoutInput(page).fill("12");
  await page.waitForTimeout(700);

  const masihAda = await page.locator(ASIDE).count();
  console.log(`[F1] aside setelah fill = ${masihAda}`);
  expect(masihAda, "panel konfigurasi tertutup sendiri setelah diedit").toBe(1);
  expect(await timeoutInput(page).inputValue()).toBe("12");

  // Ketik di editor juga tidak boleh menutup panel.
  await editor(page).click();
  await page.waitForTimeout(700);
  const masihAda2 = await page.locator(ASIDE).count();
  console.log(`[F1] aside setelah klik editor = ${masihAda2}`);
  expect(masihAda2).toBe(1);
});

test("F2 di desktop tidak ada dialog mobile yang terbuka (sheet benar-benar mobile-only)", async ({ page }) => {
  await openDemo(page);
  await addCodeNode(page);
  await selectCodeNode(page);
  // Panel desktop ada, dan TIDAK ada `role="dialog"` yang tersembunyi — dialog
  // tak terlihat itu sumber bug F1 sekaligus cacat a11y (modal tak terlihat).
  expect(await page.locator(ASIDE).count()).toBe(1);
  const dialogs = await page.locator('[role="dialog"]').count();
  console.log(`[F2] role=dialog di desktop = ${dialogs}`);
  expect(dialogs).toBe(0);
});

test("F3 di ponsel (390px) sheet konfigurasi tetap terbuka saat node dipilih", async ({ page }) => {
  // Membuktikan perbaikan F1/F2 TIDAK mematikan perilaku mobile.
  await page.setViewportSize({ width: 390, height: 844 });
  await openDemo(page);
  // Di 390px sidebar `palette` desktop (`md:flex`) TERSEMBUNYI; yang tersedia
  // adalah bottom-sheet `palette-sheet`. Karena `palette-item-code` juga ada di
  // sidebar tersembunyi, locator WAJIB di-scope ke sheet (kalau tidak:
  // strict-mode violation karena 2 elemen cocok).
  await page.click('[data-testid="palette-sheet-trigger"]');
  await page.waitForSelector('[data-testid="palette-sheet"]', { timeout: 15000 });
  await page.click('[data-testid="palette-sheet"] [data-testid="palette-item-code"]');
  await page.waitForSelector('[data-testid="node-card"][data-kind="code"]', { timeout: 15000 });
  await page.waitForTimeout(600);

  await page.locator('[data-testid="node-card"][data-kind="code"]').first().click();
  await page.waitForSelector('[role="dialog"]', { timeout: 15000 });
  const visible = await page.locator('[role="dialog"]').first().isVisible();
  const lang = await page
    .locator('[role="dialog"] [data-testid="code-language"]')
    .count();
  console.log(`[F3] dialog visible=${visible} code-language di dialog=${lang}`);
  expect(visible).toBe(true);
  expect(lang).toBe(1);
});

// ---------------------------------------------------------------------------
// D. Token tema untuk node code ada di SEMUA tema
// ---------------------------------------------------------------------------

const THEME_TOKEN: Record<string, string> = {
  midnight: "#34d399",
  daylight: "#059669",
  cyberpunk: "#00ff9d",
  minimal: "#71717a",
};

for (const [theme, expected] of Object.entries(THEME_TOKEN)) {
  test(`D tema ${theme}: --node-code-color terdefinisi (${expected})`, async ({ page }) => {
    await openDemo(page, `&canvasTheme=${theme}`);
    const got = await page.evaluate(() =>
      getComputedStyle(document.documentElement)
        .getPropertyValue("--node-code-color")
        .trim()
    );
    console.log(`[D] tema=${theme} --node-code-color=${got}`);
    expect(got).toBe(expected);
  });
}

// ---------------------------------------------------------------------------
// E. Bukti visual (screenshot wajib dari brief)
// ---------------------------------------------------------------------------

test("E1 screenshot UI node code di Canvas Builder", async ({ page }) => {
  mkdirSync(SHOT_DIR, { recursive: true });
  await openDemo(page);
  await addCodeNode(page);
  await selectCodeNode(page);

  const cm = page.locator('[data-testid="config-aside"] .cm-content').first();
  await cm.click();
  await page.keyboard.press("Control+A");
  await page.keyboard.type('total = sum(input_data["input"]["values"])\nprint(total)');
  await page.waitForTimeout(1000);

  const target = join(SHOT_DIR, "canvas-code-node.png");
  await page.screenshot({ path: target, fullPage: false });
  console.log(`[E1] screenshot -> ${target}`);

  // Bukti pendamping: hanya node code yang tersorot + panel berisi 3 kontrol.
  const aside = page.locator('[data-testid="config-aside"]');
  await expect(aside.locator('[data-testid="code-language"]')).toBeVisible();
  await expect(aside.locator('[data-testid="code-timeout"]')).toBeVisible();
  const txt = (await aside.innerText()).replace(/\s+/g, " ");
  // `innerText` mengembalikan teks SETELAH text-transform CSS, dan judul kotak
  // batas memakai kelas `uppercase` → yang terbaca "BATAS SANDBOX", bukan
  // "Batas sandbox". Perbandingan karena itu case-insensitive (dan angka tetap
  // dibandingkan apa adanya).
  const lower = txt.toLowerCase();
  console.log(`[E1] panel memuat batas sandbox = ${lower.includes("batas sandbox")}`);
  expect(lower).toContain("batas sandbox");
  expect(txt).toContain("128 MB");
  expect(txt).toContain("64 KB");
  // Judul bahasa + timeout harus ikut terbaca di panel (bukti UI 1.3.3 lengkap).
  expect(lower).toContain("bahasa");
  expect(lower).toContain("batas waktu (detik)");
  expect(txt).toContain("Python 3");
  expect(txt).toContain("JavaScript (Node)");
  expect(txt).toContain("input_data");
});
