/**
 * FASE 4 — HARD TEST composer chat: viewport mobile, keyboard, auto-resize.
 *
 * MENGAPA SPEC INI ADA
 * Dua masalah yang dilaporkan dari screenshot user:
 *   (1) di MOBILE kolom input tidak terlihat di bawah;
 *   (2) di DESKTOP input terlihat tapi bukan gaya DeepSeek.
 * Keduanya tidak bisa dibuktikan dengan membaca kode — harus diukur di
 * browser pada viewport nyata. Spec ini mengukur, bukan mengasumsikan.
 *
 * MASALAH TERSulit: SIMULASI KEYBOARD
 * Chromium desktop TIDAK punya keyboard OS, jadi `visualViewport.height`
 * tidak pernah mengecil dengan sendirinya. Karena itu spec ini memasang
 * `visualViewport` PALSU lewat `addInitScript` (sebelum hidrasi) dan
 * menggerakkannya persis seperti browser:
 *
 *   • mode "resizes-visual" (DEFAULT, dipakai Safari iOS & Chromium tanpa
 *     `interactive-widget`): layout viewport TIDAK mengecil →
 *     `documentElement.clientHeight` tetap penuh. INI tes yang paling
 *     penting, karena di sini SELURUH pekerjaan ada di sisi kita.
 *   • mode "resizes-content" (Chromium yang menghormati
 *     `interactive-widget=resizes-content`): layout viewport IKUT mengecil →
 *     `100dvh` juga mengecil. Ini diemulasi dengan mengecilkan
 *     `clientHeight` DAN tinggi `.k-chat-shell` (karena di Chromium asli
 *     `dvh` = tinggi visual viewport). Tujuannya satu: membuktikan rumus
 *     `layoutH − vv.height − vv.offsetTop` TIDAK menghitung ganda.
 *
 * Yang diemulasi adalah PERILAKU BROWSER, bukan logika aplikasi. Logika
 * aplikasi (hook `useKeyboardInset` + CSS) berjalan apa adanya.
 *
 * CATATAN JUJUR: ini emulasi, bukan keyboard sungguhan. Verifikasi
 * perangkat-nyata tetap diperlukan dan dicatat sebagai risiko terbuka di
 * `docs/chat-ui-mobile-fix.md`.
 *
 * BUKTI: setiap tes menulis JSON `getComputedStyle` ke
 * `docs/marketing/screenshots/chat-ui/evidence/<label>.json` dan PNG ke
 * direktori induknya.
 */
import { test, expect, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

/** Direktori bukti. Di luar repo-app supaya ikut terkomit bersama dokumen. */
const SHOT_DIR =
  process.env.CHATUI_SHOT_DIR ||
  resolve(process.cwd(), "..", "docs", "marketing", "screenshots", "chat-ui");
const EVIDENCE_DIR = join(SHOT_DIR, "evidence");
mkdirSync(EVIDENCE_DIR, { recursive: true });

const THEME_KEY = "katalir.theme";
const CHAT = "/chat";
const SEL = {
  composer: '[data-testid="chat-composer"]',
  input: '[data-testid="composer-input"]',
  send: '[data-testid="composer-send"]',
  model: '[data-testid="composer-model"]',
  brand: '[data-testid="header-logo"]',
  theme: '[data-testid="theme-toggle"]',
  shell: ".k-chat-shell",
  scroll: ".chat-scroll",
  footer: ".k-chat-footer",
};

/** Dua kotak berbagi baris bila rentang vertikalnya beririsan. */
function sameRow(a: { y: number; bottom: number } | null, b: { y: number; bottom: number } | null): boolean {
  if (!a || !b) return false;
  return Math.max(a.y, b.y) < Math.min(a.bottom, b.bottom);
}

type Theme = "light" | "dark";

interface Viewport {
  name: string;
  width: number;
  height: number;
  mobile: boolean;
  note: string;
}

const VIEWPORTS: Viewport[] = [
  { name: "320x568", width: 320, height: 568, mobile: true, note: "iPhone SE 1st gen / Android kecil" },
  { name: "375x667", width: 375, height: 667, mobile: true, note: "iPhone SE 2/3 — viewport acuan brief" },
  { name: "390x844", width: 390, height: 844, mobile: true, note: "iPhone 14/15" },
  { name: "768x1024", width: 768, height: 1024, mobile: false, note: "iPad potret — ambang md" },
  { name: "1440x900", width: 1440, height: 900, mobile: false, note: "desktop" },
];

/** Ukuran keyboard yang disimulasikan (px). 300px ≈ keyboard iOS tengah. */
const KB = 300;

// ---------------------------------------------------------------------------
// Stub visualViewport — dijalankan SEBELUM skrip halaman mana pun.
// ---------------------------------------------------------------------------
function viewportStub() {
  const L: Record<string, Array<(e: Event) => void>> = { resize: [], scroll: [] };
  let openPx = 0;
  let openTop = 0;
  let sc = 1;

  const vv = {
    get width() {
      return window.innerWidth;
    },
    get height() {
      return Math.max(0, window.innerHeight - openPx);
    },
    get offsetTop() {
      return openTop;
    },
    get offsetLeft() {
      return 0;
    },
    get pageTop() {
      return 0;
    },
    get pageLeft() {
      return 0;
    },
    get scale() {
      return sc;
    },
    addEventListener(t: string, fn: (e: Event) => void) {
      (L[t] = L[t] || []).push(fn);
    },
    removeEventListener(t: string, fn: (e: Event) => void) {
      const a = L[t] || [];
      const i = a.indexOf(fn);
      if (i >= 0) a.splice(i, 1);
    },
    dispatchEvent() {
      return true;
    },
  };

  Object.defineProperty(window, "visualViewport", { value: vv, configurable: true, writable: true });

  const w = window as unknown as Record<string, unknown>;
  w.__vv = vv;

  const fire = () => (L.resize || []).slice().forEach((fn) => fn(new Event("resize")));
  const shell = () => document.querySelector(".k-chat-shell") as HTMLElement | null;
  const docEl = () => document.documentElement as unknown as Record<string, unknown>;

  w.__kb = (px: number, opts?: { offsetTop?: number; scale?: number; shrinkLayout?: boolean }) => {
    const o = opts || {};
    openPx = px;
    openTop = o.offsetTop || 0;
    sc = o.scale || 1;
    if (o.shrinkLayout) {
      Object.defineProperty(document.documentElement, "clientHeight", {
        get() {
          return Math.max(0, window.innerHeight - openPx);
        },
        configurable: true,
      });
      const s = shell();
      if (s) s.style.height = `${Math.max(0, window.innerHeight - openPx)}px`;
    } else {
      delete docEl().clientHeight;
      const s = shell();
      if (s) s.style.height = "";
    }
    fire();
  };

  w.__kbClose = () => {
    openPx = 0;
    openTop = 0;
    sc = 1;
    delete docEl().clientHeight;
    const s = shell();
    if (s) s.style.height = "";
    fire();
  };
}

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

/** Buka /chat, tunggu composer DAN tema benar-benar terpasang. */
async function openChat(page: Page, theme: Theme = "light") {
  await page.addInitScript(
    (t: string) => {
      try {
        window.localStorage.setItem("katalir.theme", t);
      } catch {
        /* localStorage bisa dilarang di beberapa konteks; tema lalu jatuh ke
           prefers-color-scheme yang sudah di-set lewat `colorScheme`. */
      }
    },
    theme,
  );
  await page.goto(CHAT, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(SEL.composer, { state: "visible", timeout: 30000 });
  // ThemeToggle menandai `data-theme-ready="true"` setelah kelas tema dipasang.
  // Tanpa menunggu ini, screenshot bisa menangkap mode yang salah.
  await page
    .waitForFunction(
      () => {
        const b = document.querySelector('[data-testid="theme-toggle"]');
        return !!b && b.getAttribute("data-theme-ready") === "true";
      },
      undefined,
      { timeout: 20000 },
    )
    .catch(() => {
      throw new Error("tema tidak pernah siap (data-theme-ready) — screenshot akan menyesatkan");
    });
}

/** Semua angka yang dipakai untuk klaim. Satu sumber, tidak ada tebakan. */
async function metrics(page: Page) {
  return page.evaluate((sel) => {
    const q = (s: string) => document.querySelector(s) as HTMLElement | null;
    const rect = (s: string) => {
      const el = q(s);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return {
        x: Math.round(r.x),
        y: Math.round(r.y),
        w: Math.round(r.width),
        h: Math.round(r.height),
        bottom: Math.round(r.bottom),
      };
    };
    const css = (s: string, prop: string) => {
      const el = q(s);
      return el ? getComputedStyle(el).getPropertyValue(prop).trim() : null;
    };

    const chain: string[] = [];
    let n: HTMLElement | null = q(sel.composer);
    while (n && n !== document.body) {
      const cls = String(n.className || "").split(" ").filter(Boolean)[0] || "";
      chain.push(`${n.tagName.toLowerCase()}${cls ? "." + cls : ""}=${getComputedStyle(n).position}`);
      n = n.parentElement;
    }

    const ta = q(sel.input) as HTMLTextAreaElement | null;
    const vv = window.visualViewport;

    return {
      innerW: window.innerWidth,
      innerH: window.innerHeight,
      docClientW: document.documentElement.clientWidth,
      docClientH: document.documentElement.clientHeight,
      docScrollW: document.documentElement.scrollWidth,
      docScrollH: document.documentElement.scrollHeight,
      visualH: vv ? Math.round(vv.height) : null,
      visualTop: vv ? Math.round(vv.offsetTop) : null,
      visualScale: vv ? Number(vv.scale.toFixed(2)) : null,
      keyboardInset: getComputedStyle(document.documentElement).getPropertyValue("--keyboard-inset").trim(),
      shellCssHeight: css(sel.shell, "height"),
      shellRect: rect(sel.shell),
      headerRect: rect("header"),
      footerRect: rect(sel.footer),
      footerPadBottom: css(sel.footer, "padding-bottom"),
      composerRect: rect(sel.composer),
      composerPosition: css(sel.composer, "position"),
      composerRadius: css(sel.composer, "border-radius"),
      composerBg: css(sel.composer, "background-color"),
      composerBorder: css(sel.composer, "border-top-color"),
      composerShadow: css(sel.composer, "box-shadow"),
      composerChain: chain,
      inputRect: rect(sel.input),
      inputFontSize: css(sel.input, "font-size"),
      inputLineHeight: css(sel.input, "line-height"),
      inputMinHeight: css(sel.input, "min-height"),
      inputMaxHeight: css(sel.input, "max-height"),
      inputOverflowY: css(sel.input, "overflow-y"),
      inputInlineHeight: ta ? ta.style.height : null,
      inputScrollH: ta ? ta.scrollHeight : null,
      inputClientH: ta ? ta.clientHeight : null,
      inputRows: ta ? ta.rows : null,
      inputEnterKeyHint: ta ? ta.getAttribute("enterkeyhint") : null,
      inputAriaLabel: ta ? ta.getAttribute("aria-label") : null,
      sendRect: rect(sel.send),
      sendDisabled: (q(sel.send) as HTMLButtonElement | null)?.disabled ?? null,
      modelRect: rect(sel.model),
      brandRect: rect(sel.brand),
      menuRect: rect('header button[aria-label="Buka menu"]'),
      themeRect: rect(sel.theme),
      /** Jumlah tautan header yang benar-benar terlihat (lebar > 0).
       *  Di <sm harus 0: tautan sekunder pindah ke drawer karena 320px tidak
       *  cukup untuk lima target 44px + logo + tombol menu. */
      headerLinksVisible: Array.from(document.querySelectorAll("header a[href]")).filter(
        (el) => (el as HTMLElement).getBoundingClientRect().width > 0,
      ).length,
      wordmarkVisible: (() => {
        const el = q(sel.brand);
        const span = el ? Array.from(el.querySelectorAll("span")).find((s) => s.textContent === "Katalir") : null;
        if (!span) return null;
        return getComputedStyle(span).display !== "none";
      })(),
      scrollTouchAction: css(sel.scroll, "touch-action"),
      scrollOverscroll: css(sel.scroll, "overscroll-behavior-y"),
      scrollOverflowY: css(sel.scroll, "overflow-y"),
      scrollRect: rect(sel.scroll),
      theme: document.documentElement.classList.contains("dark") ? "dark" : "light",
      colorScheme: getComputedStyle(document.documentElement).colorScheme,
    };
  }, SEL);
}

/** Tulis bukti mentah ke disk + cetak ke log Playwright. */
function record(label: string, data: unknown) {
  writeFileSync(join(EVIDENCE_DIR, `${label}.json`), JSON.stringify(data, null, 2));
  console.log(`EVIDENCE ${label} ${JSON.stringify(data)}`);
}

/** Pasang kolektor galat runtime; mengembalikan fungsi assertion. */
function watchErrors(page: Page) {
  const pageErrors: string[] = [];
  const consoleErrors: string[] = [];
  page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 300)));
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text().slice(0, 300));
  });
  return () => {
    expect(pageErrors, `galat runtime di halaman: ${JSON.stringify(pageErrors)}`).toHaveLength(0);
    expect(consoleErrors, `galat konsol: ${JSON.stringify(consoleErrors)}`).toHaveLength(0);
  };
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: join(SHOT_DIR, `${name}.png`) });
}

/** Tunggu transisi tinggi (120ms) selesai, lalu kembalikan tinggi terukur. */
async function settleHeight(page: Page, expected: number, tol = 2) {
  await page
    .waitForFunction(
      (a) => {
        const el = document.querySelector(a.sel) as HTMLElement | null;
        if (!el) return false;
        return Math.abs(el.getBoundingClientRect().height - a.want) <= a.tol;
      },
      { sel: SEL.input, want: expected, tol },
      { timeout: 5000 },
    )
    .catch(() => {
      /* biarkan assertion di bawah yang melaporkan angka sebenarnya */
    });
  return Math.round((await metrics(page)).inputRect!.h);
}

// ===========================================================================
// 1. MATRIKS VIEWPORT × TEMA — 5 ukuran × 2 mode = 10 tes / 10 screenshot
// ===========================================================================
for (const vp of VIEWPORTS) {
  for (const theme of ["light", "dark"] as const) {
    test.describe(`${vp.name} / ${theme}`, () => {
      test.use({
        viewport: { width: vp.width, height: vp.height },
        isMobile: vp.mobile,
        hasTouch: vp.mobile,
        deviceScaleFactor: vp.mobile ? 2 : 1,
        colorScheme: theme,
      });

      test(`composer terlihat penuh, tanpa overflow horizontal (${vp.note})`, async ({ page }) => {
        const assertClean = watchErrors(page);
        await openChat(page, theme);
        const m = await metrics(page);
        record(`matrix-${vp.name}-${theme}`, m);

        // --- Klaim 1: tidak ada gulir horizontal (penyebab "input tidak terlihat").
        expect(m.docScrollW, "scrollWidth dokumen tidak boleh melebihi lebar viewport").toBeLessThanOrEqual(
          m.innerW,
        );

        // --- Klaim 2: composer & textarea berada DI DALAM area terlihat.
        expect(m.composerRect, "composer harus ada").not.toBeNull();
        expect(m.inputRect, "textarea harus ada").not.toBeNull();
        expect(m.composerRect!.bottom, "dasar composer harus di atas tepi bawah viewport").toBeLessThanOrEqual(
          m.innerH,
        );
        expect(m.inputRect!.bottom, "textarea harus terlihat penuh").toBeLessThanOrEqual(m.innerH);
        expect(m.inputRect!.y, "textarea tidak boleh di atas viewport").toBeGreaterThanOrEqual(0);

        // --- Klaim 3: tinggi shell = tinggi viewport dinamis, bukan 100vh beku.
        expect(m.shellCssHeight, "shell memakai 100dvh").toBe(`${vp.height}px`);

        // --- Klaim 4: header tidak menimpa area pesan.
        expect(m.headerRect!.bottom, "header harus di atas textarea").toBeLessThanOrEqual(m.inputRect!.y);

        // --- Klaim 5: composer TIDAK `position: fixed` (elemen fixed menempel di
        // layout viewport dan tenggelam di bawah keyboard — akar masalah aslinya).
        expect(m.composerPosition, "composer harus di aliran dokumen, bukan fixed").not.toBe("fixed");
        expect(
          m.composerChain.filter((c) => c.endsWith("=fixed")),
          `tidak boleh ada leluhur fixed: ${JSON.stringify(m.composerChain)}`,
        ).toHaveLength(0);

        // --- Klaim 6: tema benar-benar terpasang.
        expect(m.theme).toBe(theme);

        // --- Klaim 7: gulir pesan mengunci gulir halaman (tidak "menularkan").
        expect(m.scrollTouchAction).toContain("pan-y");
        expect(m.scrollOverscroll).toBe("contain");

        // --- Klaim 8: font 16px mencegah iOS memperbesar halaman saat fokus.
        expect(m.inputFontSize).toBe("16px");

        // --- Klaim 9: dua mode tata letak (brief: mobile 1 baris, desktop 3 baris).
        if (vp.width >= 768) {
          expect(m.inputMinHeight, "desktop = min 72px (3 baris)").toBe("72px");
          // Satu baris: model | textarea | kirim harus berbagi baris yang sama.
          expect(
            sameRow(m.modelRect, m.inputRect),
            `desktop harus SATU baris (model=${JSON.stringify(m.modelRect)}, input=${JSON.stringify(m.inputRect)})`,
          ).toBe(true);
          expect(
            sameRow(m.inputRect, m.sendRect),
            `desktop harus SATU baris (input=${JSON.stringify(m.inputRect)}, kirim=${JSON.stringify(m.sendRect)})`,
          ).toBe(true);
          // Regresi terukur: dengan flex-wrap dulu, composer jadi 174px (3 baris).
          expect(m.composerRect!.h, `desktop satu baris harus ~96px, dapat ${m.composerRect!.h}px`).toBeLessThan(
            120,
          );
        } else {
          expect(m.inputMinHeight, "mobile = min 24px (1 baris)").toBe("24px");
          // Dua baris: textarea DI ATAS baris model+kirim.
          expect(
            m.inputRect!.bottom,
            `mobile: textarea harus di atas baris tombol (input.bottom=${m.inputRect!.bottom}, kirim.y=${m.sendRect!.y})`,
          ).toBeLessThanOrEqual(m.sendRect!.y);
          expect(sameRow(m.modelRect, m.sendRect), "mobile: model & kirim sebaris").toBe(true);
        }

        // --- Klaim 10: header rapat tidak boleh saling menimpa.
        // Regresi terukur: wordmark "Katalir" menimpa tombol tema di 320-390px.
        // Tombol menu hanya ada di <md; di ≥md `display:none` sehingga rect-nya
        // nol (bukan null) — jadi batas kiri grup kanan dipakai langsung.
        const menuTampil = !!m.menuRect && m.menuRect.w > 0;
        const batasKananKiri = menuTampil ? m.menuRect!.x : m.themeRect!.x;
        expect(
          m.brandRect!.x + m.brandRect!.w,
          `brand (kanan=${m.brandRect!.x + m.brandRect!.w}) menimpa kontrol berikutnya (x=${batasKananKiri})`,
        ).toBeLessThanOrEqual(batasKananKiri);
        if (menuTampil) {
          expect(
            m.menuRect!.x + m.menuRect!.w,
            `grup kiri menimpa grup kanan (tema di ${m.themeRect!.x})`,
          ).toBeLessThanOrEqual(m.themeRect!.x);
        }
        expect(m.themeRect!.x + m.themeRect!.w, "grup kanan harus di dalam viewport").toBeLessThanOrEqual(m.innerW);
        // Wordmark hanya tampil bila ruangnya ada (sm = 640px).
        expect(
          m.wordmarkVisible,
          `wordmark harus ${vp.width >= 640 ? "tampil" : "disembunyikan"} di ${vp.width}px`,
        ).toBe(vp.width >= 640);
        // Logo WAJIB punya lebar nyata. Sebelum diperbaiki, di 320px grup kiri
        // terkompresi dan `getBoundingClientRect().width` logo = 0 → logo tidak
        // terlihat sama sekali, sementara assertion "tidak menimpa" tetap HIJAU
        // (0 <= apa pun). Karena itu lebarnya diperiksa langsung di sini.
        expect(
          m.brandRect!.w,
          `logo harus terlihat di ${vp.width}px (lebar=${m.brandRect!.w})`,
        ).toBeGreaterThanOrEqual(32);
        // Tautan sekunder hanya ada di header bila ruangnya cukup (sm = 640px).
        expect(
          m.headerLinksVisible,
          `tautan header harus ${vp.width >= 640 ? "tampil" : "pindah ke drawer"} di ${vp.width}px`,
        ).toBe(vp.width >= 640 ? 3 : 0);

        await shot(page, `matrix-${vp.name}-${theme}`);
        assertClean();
      });
    });
  }
}

// ===========================================================================
// 2. KEYBOARD — inti masalah yang dilaporkan
// ===========================================================================
test.describe("keyboard mobile", () => {
  test.use({
    viewport: { width: 375, height: 667 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 2,
    colorScheme: "light",
  });

  test("375x667 resizes-visual (iOS): keyboard TIDAK mengecilkan layout — composer didorong naik", async ({
    page,
  }) => {
    const assertClean = watchErrors(page);
    await page.addInitScript(viewportStub);
    await openChat(page);

    const tertutup = await metrics(page);
    record("kb-375-tertutup", tertutup);
    expect(tertutup.keyboardInset, "sebelum keyboard: inset = 0").toBe("0px");

    await page.evaluate((px) => (window as never as { __kb: (p: number) => void }).__kb(px), KB);
    await expect
      .poll(async () => (await metrics(page)).keyboardInset, {
        message: "--keyboard-inset harus menjadi tinggi keyboard",
        timeout: 5000,
      })
      .toBe(`${KB}px`);

    const terbuka = await metrics(page);
    record("kb-375-terbuka", terbuka);
    await shot(page, "keyboard-open-375x667");

    // INI klaim utamanya: dasar textarea ada DI ATAS tepi bawah visual viewport.
    expect(
      terbuka.inputRect!.bottom,
      `textarea harus di atas keyboard: bottom=${terbuka.inputRect!.bottom} > visualH=${terbuka.visualH}`,
    ).toBeLessThanOrEqual(terbuka.visualH!);
    // Dan memang benar-benar bergeser (bukan kebetulan sudah di atas).
    expect(terbuka.inputRect!.bottom, "textarea harus NAIK saat keyboard terbuka").toBeLessThan(
      tertutup.inputRect!.bottom,
    );
    // Padding footer menyerap inset supaya composer tidak tertutup.
    expect(parseFloat(terbuka.footerPadBottom!)).toBeGreaterThanOrEqual(KB);
    // Area pesan menyusut, tidak mendorong composer keluar layar.
    expect(terbuka.scrollRect!.h).toBeLessThan(tertutup.scrollRect!.h);

    assertClean();
  });

  test("375x667: menutup keyboard mengembalikan inset ke 0 dan posisi semula", async ({ page }) => {
    const assertClean = watchErrors(page);
    await page.addInitScript(viewportStub);
    await openChat(page);
    const awal = await metrics(page);

    await page.evaluate((px) => (window as never as { __kb: (p: number) => void }).__kb(px), KB);
    await expect.poll(async () => (await metrics(page)).keyboardInset, { timeout: 5000 }).toBe(`${KB}px`);

    await page.evaluate(() => (window as never as { __kbClose: () => void }).__kbClose());
    await expect.poll(async () => (await metrics(page)).keyboardInset, { timeout: 5000 }).toBe("0px");

    const akhir = await metrics(page);
    record("kb-375-buka-tutup", { awal, akhir });
    expect(akhir.inputRect!.bottom, "posisi harus kembali persis").toBe(awal.inputRect!.bottom);
    expect(akhir.footerPadBottom).toBe(awal.footerPadBottom);
    assertClean();
  });

  test("Android resizes-content: layout ikut mengecil — inset 0, TIDAK hitung ganda", async ({ page }) => {
    const assertClean = watchErrors(page);
    await page.addInitScript(viewportStub);
    await openChat(page);

    await page.evaluate(
      (px) =>
        (window as never as { __kb: (p: number, o: { shrinkLayout: boolean }) => void }).__kb(px, {
          shrinkLayout: true,
        }),
      KB,
    );
    await page.waitForTimeout(300);
    const m = await metrics(page);
    record("kb-android-resizes-content", m);

    // Browser sudah mengecilkan layout viewport => rumus harus menghasilkan 0.
    // Kalau hook ikut menambah inset, composer akan terdorong 300px terlalu jauh.
    expect(m.docClientH, "layout viewport mengecil (emulasi resizes-content)").toBe(m.innerH - KB);
    expect(m.keyboardInset, "inset harus 0 agar tidak dihitung dua kali").toBe("0px");
    expect(m.inputRect!.bottom, "textarea tetap di dalam area terlihat").toBeLessThanOrEqual(m.visualH!);
    await shot(page, "keyboard-open-android-resizes-content");
    assertClean();
  });

  test("pinch-zoom (scale > 1) TIDAK dianggap keyboard", async ({ page }) => {
    const assertClean = watchErrors(page);
    await page.addInitScript(viewportStub);
    await openChat(page);

    await page.evaluate(
      (px) =>
        (window as never as { __kb: (p: number, o: { scale: number }) => void }).__kb(px, { scale: 2 }),
      KB,
    );
    await page.waitForTimeout(300);
    const m = await metrics(page);
    record("kb-pinch-zoom", m);
    expect(m.visualScale, "stub melaporkan scale 2").toBe(2);
    expect(m.keyboardInset, "zoom bukan keyboard → inset 0").toBe("0px");
    assertClean();
  });

  test("offsetTop visual viewport diperhitungkan (Safari menggeser tampilan saat fokus)", async ({ page }) => {
    const assertClean = watchErrors(page);
    await page.addInitScript(viewportStub);
    await openChat(page);

    // Safari menggeser visual viewport turun 120px saat menggulir field ke dalam
    // pandangan. Kalau offsetTop diabaikan, inset jadi kebesaran 120px.
    await page.evaluate(
      (px) =>
        (window as never as { __kb: (p: number, o: { offsetTop: number }) => void }).__kb(px, {
          offsetTop: 120,
        }),
      KB,
    );
    await expect.poll(async () => (await metrics(page)).keyboardInset, { timeout: 5000 }).toBe(`${KB - 120}px`);
    const m = await metrics(page);
    record("kb-offset-top", m);
    expect(m.inputRect!.bottom).toBeLessThanOrEqual(m.visualH! + m.visualTop!);
    assertClean();
  });
});

test.describe("keyboard 320x568 (layar tersempit)", () => {
  test.use({
    viewport: { width: 320, height: 568 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 2,
    colorScheme: "light",
  });

  test("nav sekunder tetap terjangkau lewat drawer (tidak hilang dari 320px)", async ({ page }) => {
    const assertClean = watchErrors(page);
    await openChat(page);
    const sebelum = await metrics(page);
    expect(sebelum.headerLinksVisible, "di 320px tautan header disembunyikan").toBe(0);

    await page.locator('header button[aria-label="Buka menu"]').click();
    const drawer = page.locator('[role="dialog"][aria-label="Menu navigasi"]');
    await expect(drawer).toBeVisible();

    // Ketiga tujuan tetap ada dan bisa diklik di dalam drawer.
    const nav = drawer.locator('nav[aria-label="Navigasi utama"]');
    await expect(nav.locator("a[href]"), "Chat/Builder/Templates harus ada di drawer").toHaveCount(3);
    for (const href of ["/chat", "/builder", "/templates"]) {
      const link = nav.locator(`a[href="${href}"]`);
      await expect(link, `${href} harus terlihat di drawer`).toBeVisible();
      const box = await link.boundingBox();
      expect(box!.height, `${href} harus >= 44px (target sentuh)`).toBeGreaterThanOrEqual(44);
    }

    // Semua target di drawer juga memenuhi 44px.
    const kecil = await drawer.evaluate((el) =>
      Array.from(el.querySelectorAll("a[href], button"))
        .map((n) => ({ n: (n.textContent || n.getAttribute("aria-label") || "?").trim().slice(0, 24), h: Math.round(n.getBoundingClientRect().height) }))
        .filter((o) => o.h < 44),
    );
    expect(kecil, `target sentuh < 44px di drawer: ${JSON.stringify(kecil)}`).toHaveLength(0);

    await shot(page, "drawer-nav-320x568");
    assertClean();
  });

  test("keyboard terbuka: textarea tetap di atas keyboard, tanpa overflow horizontal", async ({ page }) => {
    const assertClean = watchErrors(page);
    await page.addInitScript(viewportStub);
    await openChat(page);
    await page.evaluate((px) => (window as never as { __kb: (p: number) => void }).__kb(px), KB);
    await expect.poll(async () => (await metrics(page)).keyboardInset, { timeout: 5000 }).toBe(`${KB}px`);
    const m = await metrics(page);
    record("kb-320-terbuka", m);
    await shot(page, "keyboard-open-320x568");
    expect(m.inputRect!.bottom, "textarea di atas keyboard").toBeLessThanOrEqual(m.visualH!);
    expect(m.docScrollW, "tanpa gulir horizontal").toBeLessThanOrEqual(m.innerW);
    assertClean();
  });
});

test.describe("keyboard 390x844", () => {
  test.use({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 3,
    colorScheme: "dark",
  });

  test("keyboard terbuka (mode gelap): textarea tetap di atas keyboard", async ({ page }) => {
    const assertClean = watchErrors(page);
    await page.addInitScript(viewportStub);
    await openChat(page, "dark");
    await page.evaluate((px) => (window as never as { __kb: (p: number) => void }).__kb(px), KB);
    await expect.poll(async () => (await metrics(page)).keyboardInset, { timeout: 5000 }).toBe(`${KB}px`);
    const m = await metrics(page);
    record("kb-390-terbuka-dark", m);
    await shot(page, "keyboard-open-390x844-dark");
    expect(m.inputRect!.bottom).toBeLessThanOrEqual(m.visualH!);
    expect(m.theme).toBe("dark");
    assertClean();
  });
});

// ===========================================================================
// 3. AUTO-RESIZE
// ===========================================================================
test.describe("auto-resize textarea", () => {
  test.use({
    viewport: { width: 375, height: 667 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 2,
    colorScheme: "light",
  });

  test("1 baris: tinggi = 24px (line-height 1.5 x 16px)", async ({ page }) => {
    const assertClean = watchErrors(page);
    await openChat(page);
    await page.locator(SEL.input).fill("Halo");
    const h = await settleHeight(page, 24);
    const m = await metrics(page);
    record("resize-1-baris", m);
    await shot(page, "resize-1-baris");
    expect(h, `1 baris harus 24px, dapat ${h}px`).toBeGreaterThanOrEqual(22);
    expect(h, `1 baris harus 24px, dapat ${h}px`).toBeLessThanOrEqual(26);
    expect(m.inputOverflowY, "tidak perlu gulir internal").toBe("hidden");
    assertClean();
  });

  test("5 baris: tinggi = 120px", async ({ page }) => {
    const assertClean = watchErrors(page);
    await openChat(page);
    await page.locator(SEL.input).fill("baris 1\nbaris 2\nbaris 3\nbaris 4\nbaris 5");
    const h = await settleHeight(page, 120);
    const m = await metrics(page);
    record("resize-5-baris", m);
    await shot(page, "resize-5-baris");
    expect(h, `5 baris harus ~120px, dapat ${h}px`).toBeGreaterThanOrEqual(118);
    expect(h, `5 baris harus ~120px, dapat ${h}px`).toBeLessThanOrEqual(122);
    assertClean();
  });

  test("20 baris: DIBATASI tepat 200px dan menggulir sendiri", async ({ page }) => {
    const assertClean = watchErrors(page);
    await openChat(page);
    const duaPuluh = Array.from({ length: 20 }, (_, i) => `baris ${i + 1}`).join("\n");
    await page.locator(SEL.input).fill(duaPuluh);
    const h = await settleHeight(page, 200);
    const m = await metrics(page);
    record("resize-20-baris", m);
    await shot(page, "resize-20-baris");
    expect(h, `20 baris harus dibatasi tepat 200px, dapat ${h}px`).toBe(200);
    expect(m.inputScrollH!, "isi sebenarnya lebih tinggi dari kotak").toBeGreaterThan(200);
    expect(m.inputOverflowY, "di atas batas → gulir internal").toBe("auto");
    // Yang penting untuk mobile: composer tetap di dalam layar walau 20 baris.
    expect(m.composerRect!.bottom, "composer tetap terlihat").toBeLessThanOrEqual(m.innerH);
    assertClean();
  });

  test("tempel 1000 karakter: tetap dibatasi 200px, tanpa overflow horizontal", async ({ page }) => {
    const assertClean = watchErrors(page);
    await openChat(page);
    const input = page.locator(SEL.input);
    await input.click();
    // insertText = jalur yang sama dengan paste (input event, tanpa keydown).
    await page.keyboard.insertText("A".repeat(1000));
    const h = await settleHeight(page, 200);
    const m = await metrics(page);
    record("resize-tempel-1000", m);
    await shot(page, "resize-tempel-1000");
    expect(h, `tempel 1000 karakter harus 200px, dapat ${h}px`).toBe(200);
    expect(m.docScrollW, "tanpa gulir horizontal").toBeLessThanOrEqual(m.innerW);
    expect(await input.inputValue()).toHaveLength(1000);
    assertClean();
  });

  test("menghapus isi menyusutkan kembali ke 24px (bukan hanya bisa tumbuh)", async ({ page }) => {
    const assertClean = watchErrors(page);
    await openChat(page);
    const input = page.locator(SEL.input);
    await input.fill("baris 1\nbaris 2\nbaris 3\nbaris 4\nbaris 5");
    await settleHeight(page, 120);
    await input.fill("x");
    const h = await settleHeight(page, 24);
    const m = await metrics(page);
    record("resize-susut", m);
    expect(h, `harus menyusut kembali ke 24px, dapat ${h}px`).toBeLessThanOrEqual(26);
    assertClean();
  });
});

// ===========================================================================
// 3b. DESKTOP — satu baris + terpusat (regresi flex-wrap)
// ===========================================================================
test.describe("desktop: composer satu baris dan terpusat", () => {
  test.use({
    viewport: { width: 1440, height: 900 },
    isMobile: false,
    hasTouch: false,
    deviceScaleFactor: 1,
    colorScheme: "light",
  });

  test("model | textarea | kirim sebaris dalam satu baris, max-width 768 terpusat", async ({ page }) => {
    const assertClean = watchErrors(page);
    await openChat(page);
    const m = await metrics(page);
    record("desktop-satu-baris", m);
    await shot(page, "desktop-composer-satu-baris");

    expect(m.composerRect!.w, "lebar maksimum 768px (48rem)").toBe(768);
    // Terpusat terhadap area konten (sidebar desktop 256px = w-64).
    const areaKiri = 256;
    const pusatKonten = areaKiri + (m.innerW - areaKiri) / 2;
    const pusatComposer = m.composerRect!.x + m.composerRect!.w / 2;
    expect(
      Math.abs(pusatComposer - pusatKonten),
      `composer harus terpusat (pusat composer=${pusatComposer}, pusat konten=${pusatKonten})`,
    ).toBeLessThanOrEqual(2);

    expect(sameRow(m.modelRect, m.inputRect), "model sebaris dengan textarea").toBe(true);
    expect(sameRow(m.inputRect, m.sendRect), "kirim sebaris dengan textarea").toBe(true);
    expect(
      m.composerRect!.h,
      `satu baris harus ~96px; 174px berarti textarea pindah baris sendiri (regresi flex-wrap)`,
    ).toBeLessThan(120);
    assertClean();
  });
});

// ===========================================================================
// 4. INTERAKSI + KONTRAK SELECTOR
// ===========================================================================
test.describe("interaksi composer", () => {
  test.use({
    viewport: { width: 375, height: 667 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 2,
    colorScheme: "light",
  });

  test("Shift+Enter menyisipkan baris baru dan textarea ikut tumbuh", async ({ page }) => {
    const assertClean = watchErrors(page);
    await openChat(page);
    const input = page.locator(SEL.input);
    await input.click();
    await page.keyboard.insertText("baris satu");
    await page.keyboard.press("Shift+Enter");
    await page.keyboard.insertText("baris dua");
    await expect(input).toHaveValue("baris satu\nbaris dua");
    const h = await settleHeight(page, 48);
    expect(h, `dua baris harus ~48px, dapat ${h}px`).toBeGreaterThanOrEqual(46);
    expect(h).toBeLessThanOrEqual(50);
    assertClean();
  });

  test("tombol kirim nonaktif saat kosong, aktif saat ada teks", async ({ page }) => {
    const assertClean = watchErrors(page);
    await openChat(page);
    const send = page.locator(SEL.send);
    await expect(send).toBeDisabled();
    await page.locator(SEL.input).fill("halo");
    await expect(send).toBeEnabled();
    // Spasi saja bukan isi yang sah.
    await page.locator(SEL.input).fill("   ");
    await expect(send, "spasi saja harus tetap nonaktif").toBeDisabled();
    assertClean();
  });

  test("REGRESI: Enter saat belum login tidak mengunci antrean selamanya", async ({ page }) => {
    const assertClean = watchErrors(page);
    const dialogs: string[] = [];
    page.on("dialog", async (d) => {
      dialogs.push(d.message());
      await d.dismiss();
    });
    await openChat(page);
    const input = page.locator(SEL.input);
    await input.fill("pesan uji");

    // Tekan 1: dialog "belum login" muncul, teks TIDAK hilang.
    await input.press("Enter");
    await expect.poll(() => dialogs.length, { timeout: 5000 }).toBeGreaterThanOrEqual(1);
    await expect(input, "teks user harus dipertahankan").toHaveValue("pesan uji");

    // Tekan 2: SEBELUM perbaikan, `busyRef` sudah terkunci sehingga cabang ini
    // justru mengosongkan input dan memasukkan pesan ke antrean tanpa dialog.
    // Sesudah perbaikan, dialog muncul lagi dan input tetap utuh.
    await input.press("Enter");
    await expect
      .poll(() => dialogs.length, {
        message: "dialog harus muncul lagi — kalau tidak, antrean terkunci",
        timeout: 5000,
      })
      .toBeGreaterThanOrEqual(2);
    await expect(input).toHaveValue("pesan uji");
    await expect(
      page.locator('[data-testid="queue-area"]'),
      "pesan tidak boleh diam-diam masuk antrean",
    ).toHaveCount(0);
    expect(dialogs[0]).toContain("login");
    assertClean();
  });

  test("kontrak selector lama tetap utuh untuk 7 spec lain", async ({ page }) => {
    const assertClean = watchErrors(page);
    await openChat(page);
    await expect(page.locator(SEL.composer)).toHaveCount(1);
    await expect(page.locator(SEL.input)).toHaveCount(1);
    await expect(page.locator(SEL.send)).toHaveCount(1);
    const m = await metrics(page);
    record("kontrak-selector", m);
    expect(m.inputRows, "rows=1 supaya tingginya murni dari auto-resize").toBe(1);
    expect(m.inputEnterKeyHint, "papan ketik ponsel menampilkan tombol Kirim").toBe("send");
    expect(m.inputAriaLabel, "textarea wajib punya nama aksesibel").toBeTruthy();
    expect(m.composerRect!.w, "composer melebar mengikuti kolom").toBeGreaterThan(0);
    assertClean();
  });
});
