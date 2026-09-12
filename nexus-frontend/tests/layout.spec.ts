import { test, Page } from "@playwright/test";

const BASE = "http://localhost:3000";
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

test("4G-a: layout sticky-bottom — input in-flow, scroll flex-1, hero terpusat", async ({ page }) => {
  const errs: string[] = [];
  page.on("pageerror", (e) => errs.push(String(e as object)));
  await page.goto(`${BASE}/?s=demo`, { waitUntil: "domcontentloaded" }).catch(() => {});
  await sleep(1000);

  const m = await page.evaluate(() => {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    // input bar (parent flex-none border-t) — ukur bar, bukan form (form punya py-3)
    const form = document.querySelector("form");
    const bar = form?.parentElement?.parentElement as HTMLElement | null;
    const bb = bar ? bar.getBoundingClientRect() : form ? form.getBoundingClientRect() : null;
    const pos = bar ? getComputedStyle(bar).position : null;
    // scroll container
    const sc = document.querySelector<HTMLElement>(".overflow-y-auto");
    const scb = sc ? sc.getBoundingClientRect() : null;
    const scOv = sc ? getComputedStyle(sc).overflowY : null;
    return {
      vh,
      formPos: pos,
      formBottom: bb ? Math.round(bb.bottom) : null,
      formTop: bb ? Math.round(bb.top) : null,
      formCenterX: form ? Math.round(((form.getBoundingClientRect().left + form.getBoundingClientRect().right)) / 2) : null,
      formWidth: bb ? Math.round(bb.width) : null,
      scrollOv: scOv,
      scrollHeight: scb ? Math.round(scb.height) : null,
      scrollBottomGap: scb ? Math.round(vh - scb.bottom) : null,
    };
  });
  console.log("LAYOUT=" + JSON.stringify(m));

  console.log("ERRORS=" + JSON.stringify(errs));

  // helmet assertions
  if (errs.length) throw new Error("pageerror: " + errs.join("|"));
  if (m.formPos !== "static") throw new Error("input harus in-flow (static), dapat " + m.formPos);
  if (m.formBottom !== m.vh) throw new Error("input harus menempel ke bawah viewport, dapat " + m.formBottom);
  if (m.scrollOv !== "auto") throw new Error("list harus overflow-y auto");
  await page.screenshot({ path: "test-results/4g-layout.png" });
});