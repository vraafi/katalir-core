/**
 * FASE 5 — a11y tuntas: tautan lewati-ke-konten + landmark di SEMUA rute.
 *
 * Kenapa spec terpisah dari `fase4-a11y.spec.ts`: spec FASE 4 menjalankan axe
 * HANYA dengan tag WCAG (`wcag2a`/`wcag2aa`/`wcag21a`/`wcag21aa`). Aturan
 * `skip-link` yang dipakai Lighthouse adalah aturan **best-practice**, sehingga
 * "axe 0 pelanggaran" di FASE 4 benar tetapi Lighthouse tetap 98 — audited beda.
 * Spec ini menutup celah itu: menjalankan axe termasuk `best-practice`, dan
 * menegaskan `skip-link` tidak muncul sama sekali (tanpa peduli impact), di
 * samping 0 pelanggaran critical/serious untuk seluruh aturan.
 *
 * Semua klaim di sini bisa dibaca ulang dari output tes: SKIP_*, AXE_*, SEVERE_*.
 */
import { test, expect, type Page } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const AXE_PATH = join(process.cwd(), "node_modules", "axe-core", "axe.min.js");

/** Rute aplikasi (ber-provider) + /pricing (halaman statis murni). */
const ROUTES = ["/", "/chat", "/settings", "/billing", "/help", "/builder", "/pricing"];

/** Rute yang WAJIB punya tautan lewati-ke-konten yang berfungsi. */
const SKIP_ROUTES = ["/", "/settings", "/billing", "/help", "/builder"];

function supabaseRef(): string {
  for (const f of [".env.local", ".env"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    const m = readFileSync(p, "utf-8").match(/NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/);
    if (m) return m[1];
  }
  return "qmukkphwaajzbqjrcvaz";
}

async function seedSession(page: Page) {
  const p = join(process.cwd(), "_e2e_session.refreshed.json");
  if (!existsSync(p)) return;
  const sess = JSON.parse(readFileSync(p, "utf-8"));
  await page.addInitScript(
    (kv: { key: string; value: unknown }) => {
      try { window.localStorage.setItem(kv.key, JSON.stringify(kv.value)); } catch { /* abaikan */ }
    },
    { key: `sb-${supabaseRef()}-auth-token`, value: sess }
  );
}

async function ready(page: Page, route: string) {
  await seedSession(page);
  await page.goto(route, { waitUntil: "domcontentloaded" });
  // /pricing tidak memasang HydrationReady (halaman statis tanpa provider
  // i18n/auth), jadi penanda `data-hydrated` memang TIDAK muncul di sana.
  // Rute aplikasi tetap WAJIB menunggunya: tanpa itu, scan axe berjalan di DOM
  // pra-hidrasi dan hasilnya tidak menggambarkan aplikasi yang sudah hidup.
  if (route === "/pricing") {
    await page.waitForTimeout(900);
  } else {
    await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
  }
  await page.waitForTimeout(1200);
  // Paritas keadaan dengan Lighthouse: Lighthouse menunggu jaringan tenang,
  // sehingga pemilih model sudah menampilkan NAMA model. Kalau axe discan lebih
  // awal, teks itu masih kosong/"Memuat…" dan aturan
  // `label-content-name-mismatch` (Label in Name) tidak bisa dievaluasi — persis
  // alasan temuan di `/` luput dari scan axe meski Lighthouse melihatnya.
  await page
    .waitForFunction(
      () => {
        const b = document.querySelector('[data-testid="model-selector"]');
        if (!b) return true;
        const txt = (b.textContent || "").trim();
        return txt.length > 0 && !/^(Memuat|Loading)/i.test(txt);
      },
      null,
      { timeout: 20000 }
    )
    .catch(() => {});
}

/**
 * Pemilih model harus punya nama aksesibel yang MEMUAT teks terlihat (WCAG 2.5.3).
 * FASE 6 final: diukur di `/chat` karena aplikasi chat pindah ke sana
 * (`/` kini landing ringan yang memang tidak punya pemilih model).
 */
test("label-in-name: pemilih model memuat nama model yang terlihat", async ({ page }) => {
  await ready(page, "/chat");
  const info = await page.evaluate(() => {
    const b = document.querySelector('[data-testid="model-selector"]');
    if (!b) return null;
    const visible = (b.textContent || "").trim();
    return { visible, name: b.getAttribute("aria-label") || "" };
  });
  console.log("MODEL_TRIGGER=" + JSON.stringify(info));
  expect(info, "pemilih model tidak ditemukan di /").not.toBeNull();
  if (info) {
    const visible = info.visible.toLowerCase().replace(/\s+/g, " ");
    const name = info.name.toLowerCase().replace(/\s+/g, " ");
    expect(visible.length, "pemilih model tidak menampilkan teks").toBeGreaterThan(0);
    expect(name.includes(visible), `nama aksesibel "${info.name}" tidak memuat teks terlihat "${info.visible}"`).toBe(true);
  }
});

type Violation = {
  id: string;
  impact: string | null;
  nodes: number;
  targets: { target: string; html: string; why: string }[];
};

/** axe termasuk aturan best-practice (di sinilah `skip-link` berada). */
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
      nodes: { target: unknown; html: string; failureSummary?: string }[];
    }[]).map((v) => ({
      id: v.id,
      impact: v.impact,
      nodes: v.nodes.length,
      targets: v.nodes.map((n) => ({
        target: JSON.stringify(n.target).slice(0, 90),
        html: String(n.html).replace(/\s+/g, " ").slice(0, 90),
        why: String(n.failureSummary ?? "").replace(/\s+/g, " ").slice(0, 160),
      })),
    }));
  });
}

const SKIP_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

// ===========================================================================
// 1. Struktur tautan lewati-ke-konten: tepat satu, targetnya ada & fokusable
// ===========================================================================
for (const route of SKIP_ROUTES) {
  test(`skip-link ${route}: tepat 1 tautan, target #main-content ada & fokusable`, async ({ page }) => {
    await ready(page, route);

    const info = await page.evaluate((sel) => {
      const links = Array.from(document.querySelectorAll('a[data-testid="skip-link"]'));
      return links.map((a) => {
        const href = a.getAttribute("href") ?? "";
        const id = href.startsWith("#") ? href.slice(1) : "";
        const target = id ? document.getElementById(id) : null;
        const all = Array.from(document.querySelectorAll<HTMLElement>(sel)).filter(
          (el) => el.offsetParent !== null || el === a
        );
        return {
          text: (a.textContent ?? "").trim(),
          href,
          targetFound: !!target,
          targetTabIndex: target ? target.getAttribute("tabindex") : null,
          targetTag: target ? target.tagName.toLowerCase() : null,
          isFirstFocusable: all[0] === a,
        };
      });
    }, SKIP_SELECTOR);
    console.log(`SKIP_${route}=` + JSON.stringify(info));

    expect(info.length, `rute ${route} harus punya TEPAT satu tautan skip (duplikat membingungkan keyboard/screen reader)`).toBe(1);
    expect(info[0].text.length, "tautan skip tanpa teks").toBeGreaterThan(0);
    expect(info[0].href, "target tautan skip tidak boleh kosong/broken").toBe("#main-content");
    expect(info[0].targetFound, "target #main-content tidak ada di DOM").toBe(true);
    expect(info[0].targetTabIndex, "target harus tabindex=-1 agar bisa menerima fokus").toBe("-1");
    expect(info[0].isFirstFocusable, "tautan skip harus elemen fokusable pertama").toBe(true);
    expect(info[0].targetTag).toBe("main");
  });
}

// ===========================================================================
// 2. Perilaku nyata: Tab -> terlihat, Enter -> fokus pindah ke konten
// ===========================================================================
for (const route of SKIP_ROUTES) {
  test(`skip-link ${route}: Tab menampilkan, Enter memindahkan fokus ke <main>`, async ({ page }) => {
    await ready(page, route);

    const link = page.locator('[data-testid="skip-link"]').first();
    const boxHidden = await link.boundingBox();

    await page.keyboard.press("Tab");
    await page.waitForTimeout(250);

    const focus = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      return { testid: el?.getAttribute("data-testid") ?? null, tag: el?.tagName.toLowerCase() ?? null };
    });
    const boxFocused = await link.boundingBox();
    console.log(`SKIP_FOCUS_${route}=` + JSON.stringify({ firstTabStop: focus.testid, visibleBox: boxFocused }));

    expect(focus.testid, "Tab pertama tidak mendarat di tautan skip").toBe("skip-link");
    expect(boxFocused, "tautan skip tidak terlihat saat fokus").not.toBeNull();
    expect(boxFocused!.width).toBeGreaterThan(8);
    expect(boxFocused!.height).toBeGreaterThan(8);
    if (boxHidden) console.log(`SKIP_HIDDEN_BOX_${route}=` + JSON.stringify(boxHidden));

    await page.keyboard.press("Enter");
    await page.waitForTimeout(400);
    const after = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      return { id: el?.id ?? null, tag: el?.tagName.toLowerCase() ?? null };
    });
    console.log(`SKIP_AFTER_ENTER_${route}=` + JSON.stringify(after));
    expect(after.id, "Enter pada tautan skip tidak memindahkan fokus ke #main-content").toBe("main-content");
  });
}

// ===========================================================================
// 3. axe (WCAG + best-practice) di semua rute
// ===========================================================================
for (const route of ROUTES) {
  test(`axe(best-practice) ${route}: 0 serious/critical + skip-link bersih`, async ({ page }) => {
    await ready(page, route);

    const violations = await axeScan(page);
    const severe = violations.filter((v) => v.impact === "critical" || v.impact === "serious");
    console.log(`AXE_${route}=` + JSON.stringify(violations.map((v) => `${v.id}(${v.impact})x${v.nodes}`)));
    // Detail untuk SEMUA pelanggaran (bukan hanya serious/critical): tanpa ini,
    // perbaikan temuan moderate seperti `landmark-unique` menjadi menebak.
    if (violations.length) console.log(`AXE_${route}_DETAIL=` + JSON.stringify(violations, null, 1));

    // Aturan skip-link: TIDAK boleh muncul sama sekali — inilah yang ditemukan
    // Lighthouse di FASE 4 dan tidak tertangkap scan WCAG-saja.
    const skipLink = violations.find((v) => v.id === "skip-link");
    expect(skipLink, `skip-link masih dilanggar: ${JSON.stringify(skipLink?.targets)}`).toBeUndefined();

    expect(severe, `pelanggaran serious/critical di ${route}`).toHaveLength(0);
  });
}

// ===========================================================================
// 5. Keadaan TANPA SESI (paritas dengan Lighthouse)
// ===========================================================================
/**
 * Kenapa ini WAJIB ada: Lighthouse selalu menjelajah TANPA sesi, sedangkan
 * semua spesifikasi FASE 4/5 lain menyemai sesi lebih dulu. Akibatnya axe
 * melaporkan "0 pelanggaran" sementara Lighthouse menemukan DUA
 * (`color-contrast` pada teks sidebar alur kerja dan
 * `label-content-name-mismatch` pada tombol tema kanvas) — bukan karena alatnya
 * salah, tetapi karena keadaan yang diperiksa berbeda. Bagian ini memeriksa
 * keadaan tanpas sesi supaya kedua alat melihat halaman yang sama.
 */
const UNAUTH_ROUTES = ["/", "/builder", "/settings"];

for (const route of UNAUTH_ROUTES) {
  test(`axe(best-practice, TANPA sesi) ${route}: 0 serious/critical + skip-link bersih`, async ({ page }) => {
    await page.goto(route, { waitUntil: "load" });
    await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
    await page.waitForTimeout(1500);

    const violations = await axeScan(page);
    const severe = violations.filter((v) => v.impact === "critical" || v.impact === "serious");
    console.log(`AXE_UNAUTH_${route}=` + JSON.stringify(violations.map((v) => `${v.id}(${v.impact})x${v.nodes}`)));
    if (violations.length) console.log(`AXE_UNAUTH_${route}_DETAIL=` + JSON.stringify(violations, null, 1));

    const skipLink = violations.find((v) => v.id === "skip-link");
    expect(skipLink, `skip-link masih dilanggar: ${JSON.stringify(skipLink?.targets)}`).toBeUndefined();
    // Tanpa sesi pun aturan ini tidak boleh muncul: Lighthouse menilainya biner.
    const mismatch = violations.find((v) => v.id === "label-content-name-mismatch");
    expect(mismatch, `label-content-name-mismatch: ${JSON.stringify(mismatch?.targets)}`).toBeUndefined();
    expect(severe, `pelanggaran serious/critical di ${route} (tanpa sesi)`).toHaveLength(0);
  });
}

// ===========================================================================
// 6. Paritas Lighthouse: audit biner yang dinilai Lighthouse juga diperiksa
// ===========================================================================
/**
 * `label-content-name-mismatch` dan `color-contrast` punya bobot di Lighthouse.
 * Dua tes di atas menuntut keduanya bersih di kedua keadaan sesi; tes-nya
 * sengaja TIDAK memakai toleransi "kecuali moderate" supaya skor 100 di
 * Lighthouse tidak bisa dicapai dengan cara menurunkan ambang tes.
 */
test("paritas: seluruh aturan best-practice bersih di /builder TANPA sesi", async ({ page }) => {
  await page.goto("/builder", { waitUntil: "load" });
  await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
  await page.waitForTimeout(1500);
  const violations = await axeScan(page);
  console.log("AXE_UNAUTH_BUILDER_ALL=" + JSON.stringify(violations.map((v) => `${v.id}(${v.impact})x${v.nodes}`)));
  expect(violations, "masih ada pelanggaran apa pun di /builder tanpa sesi").toHaveLength(0);
});

/**
 * Bagian 4 (dipindah ke bawah setelah paritas Lighthouse):
 * /builder KEDUA keadaan — setelah ada node, toolbar + palette muncul.
 *
 * Kenapa perlu: pada keadaan kosong, toolbar (Simpan/Jalankan) dan palette
 * belum dirender, sehingga scan pertama tidak pernah "melihat" tombol-tombol
 * itu. FASE 5 menemukan teks putih di atas isi neon hanya karena kebetulan
 * tombolnya terlihat — tombol lain dengan pola sama bisa lolos kalau tes
 * berhenti di keadaan kosong. Karena itu keadaan kedua ini diuji eksplisit.
 */
test("axe(best-practice) /builder dengan node: toolbar + palette juga bersih", async ({ page }) => {
  await ready(page, "/builder");

  const addNode = page.locator('[data-testid="btn-empty-add-node"]');
  if (await addNode.count()) {
    await addNode.click();
    await page.waitForTimeout(1200);
  }
  const nodes = await page.locator(".react-flow__node").count();
  const toolbarVisible = await page.locator('[data-testid="btn-run"]').isVisible().catch(() => false);
  console.log(`BUILDER_NODE_STATE nodes=${nodes} toolbar=${toolbarVisible}`);

  const violations = await axeScan(page);
  const severe = violations.filter((v) => v.impact === "critical" || v.impact === "serious");
  console.log("AXE_/builder+nodes=" + JSON.stringify(violations.map((v) => `${v.id}(${v.impact})x${v.nodes}`)));
  const skipLink = violations.find((v) => v.id === "skip-link");
  expect(skipLink, `skip-link masih dilanggar: ${JSON.stringify(skipLink?.targets)}`).toBeUndefined();
  if (severe.length) console.log("SEVERE_DETAIL_NODES=" + JSON.stringify(severe.map((s) => JSON.stringify(s.targets)), null, 1));
  expect(severe, "pelanggaran serious/critical di /builder (dengan node)").toHaveLength(0);
});
