import { test, Page } from "@playwright/test";

const BASE = "http://localhost:3000";
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

// Rekam trail opacity/transform pada selector elemen sejak awal load
async function trailOf(page: Page, find: string, label: string, wait = 1600) {
  await page.addInitScript((sel) => {
    (window as any).__tr = [];
    const go = () => {
      const t = Array.from(document.querySelectorAll("*")).find((e) => {
        const s = (e.textContent || "").trim();
        return (sel as any) === "__palette" ? e.className && String(e.className).includes("cursor-grab") : s === (sel as any);
      });
      if (t) {
        // palette: parent .cursor-grab = StaggerItem motion.div; chat: parent teks/h2 = FadeIn motion.div
        const el = t.parentElement as HTMLElement;
        const cs = getComputedStyle(el);
        (window as any).__tr.push({ o: cs.opacity, tr: cs.transform });
      }
      requestAnimationFrame(go);
    };
    requestAnimationFrame(go);
  }, find);

  await page.goto(`${BASE}${label === "BUILDER" ? "/builder" : "/"}`, { waitUntil: "domcontentloaded" }).catch(() => {});
  await sleep(wait);

  const tr = await page.evaluate(() => (window as any).__tr as { o: string; tr: string }[]);
  const ops = (tr || []).map((s) => parseFloat(s.o));
  const moved = ops.length > 1 && Math.max(...ops) - Math.min(...ops) > 0.2;
  const hadTransform = (tr || []).some((s) => s.tr && s.tr !== "none");
  const f0 = tr?.[0], fLast = tr?.[tr.length - 1];
  console.log(`${label}[${find}] frames=${ops.length} moved=${moved} hadTransform=${hadTransform} f0=${f0?.o ?? "?"}/${f0?.tr ?? "?"} fEnd=${fLast?.o ?? "?"}`);
  return { moved, hadTransform };
}

test("FIX-4A: animasi lebih tebal + area baru (palette, halo) + reduce-motion", async ({ page }) => {
  // 1) Chat hero ("Silakan masuk ...") — FadeIn y16, durasi 0.5s
  const chat = await trailOf(page, "Silakan masuk dulu", "CHAT");

  // 2) Builder palette item (stagger) — apakah stagger animates
  const pal = await trailOf(page, "__palette", "BUILDER");

  // 3) Reduce-motion ON: fade tetap jalan, transform disabled
  const page2 = await page.context().newPage();
  await page2.emulateMedia({ reducedMotion: "reduce" });
  const reduce = await trailOf(page2, "Silakan masuk dulu", "REDUCE");
  await page2.context().close();

  console.log("RESULT chat=" + JSON.stringify(chat) + " palette=" + JSON.stringify(pal) + " reduce=" + JSON.stringify(reduce));

  // KotakLog: pengujian visual (test lulus bila chat & palette moved, reduce fade-retained)
  if (!chat.moved) throw new Error("chat hero tidak bergerak");
  if (!pal.moved) throw new Error("palette stagger tidak bergerak");
  if (!reduce.moved) throw new Error("reduce-motion jadi fade harusnya tetap bergerak (opacity)");
});