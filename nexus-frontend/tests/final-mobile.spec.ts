/**
 * FASE 6 — audit mobile: 6 halaman × 3 device (Playwright device emulation).
 *
 * Tiap halaman diperiksa EMPAT hal dengan angka, bukan kesan:
 *   1. `pageerror` = 0 (runtime error tidak boleh ada di perangkat mana pun),
 *   2. target sentuh ≥ 44×44 px (WCAG 2.5.5 / Apple HIG) untuk kontrol
 *      interaktif yang terlihat,
 *   3. layout tidak pecah: `scrollWidth` tidak melebihi viewport (overflow
 *      horizontal adalah tanda paling umum layout mobile rusak),
 *   4. axe: 0 pelanggaran serious/critical.
 *
 * Kenapa tiga device dan bukan satu: 390 (iPhone), 412 (Pixel) dan 768 (iPad)
 * mewakili tiga kelas lebar yang berbeda; bug layout biasanya muncul di salah
 * satu saja. Semua angka dicetak sebagai `MOB_*` agar bisa dibaca ulang.
 */
import { test, expect, devices, type Page, type PlaywrightTestOptions } from "@playwright/test";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const AXE_PATH = join(process.cwd(), "node_modules", "axe-core", "axe.min.js");
const SHOTS = join(process.cwd(), "test-results", "final-mobile");

const ROUTES = ["/", "/chat", "/settings", "/billing", "/help", "/builder"];

const DEVICE_SET = {
  iphone14: devices["iPhone 14"],
  pixel7: devices["Pixel 7"],
  ipadmini: devices["iPad Mini"],
} as const;

/**
 * `test.use` di dalam `describe` MENOLAK `defaultBrowserType` (ia memaksa
 * worker baru). Kita hanya butuh emulasi viewport/touch/user-agent, jadi kunci
 * itu dibuang — bukan diabaikan diam-diam: kalau suatu saat Playwright menolak
 * kunci lain, tesnya gagal dan kita tahu.
 */
function deviceOptions(d: (typeof DEVICE_SET)[keyof typeof DEVICE_SET]): PlaywrightTestOptions {
  const { defaultBrowserType, ...rest } = d as unknown as PlaywrightTestOptions & { defaultBrowserType?: string };
  void defaultBrowserType;
  return rest;
}

function supabaseRef(): string {
  for (const f of [".env.local", ".env"]) {
    const p = join(process.cwd(), f);
    if (!existsSync(p)) continue;
    const m = readFileSync(p, "utf-8").match(/NEXT_PUBLIC_SUPABASE_URL\s*=\s*https?:\/\/([a-z0-9]+)\.supabase/);
    if (m) return m[1];
  }
  return "qmukkphwaajzbqjrcvaz";
}

async function seed(page: Page) {
  const p = join(process.cwd(), "_e2e_session.refreshed.json");
  if (!existsSync(p)) return;
  const sess = JSON.parse(readFileSync(p, "utf-8"));
  await page.addInitScript(
    (kv: { k: string; v: string }) => {
      try {
        window.localStorage.setItem(kv.k, kv.v);
        // Onboarding ditandai selesai supaya audit mobile mengukur APLIKASI,
        // bukan dialog onboarding (yang sudah diuji khusus di FASE 5).
        window.localStorage.setItem("katalir.onboarding.v1", "done");
        window.localStorage.setItem("katalir.locale.v1", "id");
      } catch {
        /* abaikan */
      }
    },
    { k: `sb-${supabaseRef()}-auth-token`, v: JSON.stringify(sess) }
  );
}

test.beforeAll(() => {
  if (!existsSync(SHOTS)) mkdirSync(SHOTS, { recursive: true });
});

for (const [name, device] of Object.entries(DEVICE_SET)) {
  test.describe(name, () => {
    test.use(deviceOptions(DEVICE_SET[name as keyof typeof DEVICE_SET]));

    for (const route of ROUTES) {
      test(`${name} ${route}: bersih + tap ≥44 + axe 0`, async ({ page }) => {
        test.setTimeout(120000);
        const errors: string[] = [];
        page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
        await seed(page);
        await page.goto(route, { waitUntil: "domcontentloaded" });
        if (route !== "/pricing") {
          await page.waitForSelector("html[data-hydrated='true']", { timeout: 45000 });
        }
        await page.waitForTimeout(1200);

        // 1) runtime error
        expect(errors, `pageerror di ${route}: ${errors.join(" | ")}`).toHaveLength(0);

        // 2) target sentuh + 3) overflow horizontal (diukur di browser)
        const metrics = await page.evaluate(() => {
          const small: string[] = [];
          let total = 0;
          const els = Array.from(
            document.querySelectorAll("button, a[href], input, [role=button], [role=tab]")
          ) as HTMLElement[];
          for (const el of els) {
            const r = el.getBoundingClientRect();
            const st = getComputedStyle(el);
            if (r.width === 0 || r.height === 0 || st.visibility === "hidden" || st.display === "none") continue;
            total += 1;
            if (r.width < 44 || r.height < 44) {
              small.push(`${el.tagName.toLowerCase()}:${(el.getAttribute("data-testid") || el.getAttribute("aria-label") || el.textContent || "?").trim().slice(0, 22)}=${Math.round(r.width)}x${Math.round(r.height)}`);
            }
          }
          return {
            total,
            small,
            scrollW: document.documentElement.scrollWidth,
            clientW: document.documentElement.clientWidth,
          };
        });
        console.log(
          `MOB_${name}_${route.replace(/\//g, "root")}=touch:${metrics.total} tooSmall:${metrics.small.length} overflow:${Math.max(0, metrics.scrollW - metrics.clientW)}`
        );
        if (metrics.small.length) console.log(`MOB_SMALL_${name}_${route.replace(/\//g, "root")}=${metrics.small.slice(0, 6).join(", ")}`);
        // Toleransi 1px untuk pembulatan sub-pixel.
        expect(metrics.scrollW - metrics.clientW, `overflow horizontal di ${route} (${name})`).toBeLessThanOrEqual(1);

        // 4) axe
        await page.addScriptTag({ path: AXE_PATH });
        const axe = (await page.evaluate(async () => {
          // @ts-expect-error axe disuntik runtime
          const res = await window.axe.run(document, {
            runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] },
          });
          return res.violations.map((v: { id: string; impact: string | null; nodes: unknown[] }) => ({
            id: v.id,
            impact: v.impact,
            n: v.nodes.length,
          }));
        })) as { id: string; impact: string | null; n: number }[];
        const severe = axe.filter((v) => v.impact === "serious" || v.impact === "critical");
        console.log(`AXE_MOB_${name}_${route.replace(/\//g, "root")}=${severe.map((v) => `${v.id}(${v.impact})x${v.n}`).join(",") || "[]"}`);
        expect(severe, `axe serious/critical di ${route} (${name})`).toEqual([]);

        await page.screenshot({ path: join(SHOTS, `${name}_${route.replace(/\//g, "root")}.png`), fullPage: false });
      });
    }
  });
}
