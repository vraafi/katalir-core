import { test, expect } from "@playwright/test";
import { mkdirSync, copyFileSync } from "node:fs";
import { basename } from "node:path";

/**
 * Video evidence: the dramatic magnetic bounce, recorded.
 *
 * The numbers in landing-magnet-evidence.spec.ts prove the physics is correct.
 * They cannot show whether it LOOKS like a shoal of tiles bouncing, which is
 * what the brief actually asked for. A transform matrix moving 43px says
 * nothing about whether the result reads as dramatic or as a jitter.
 *
 * So this records 15 seconds of the cursor sweeping the hero, which is the
 * artefact a human can actually judge. The assertion is deliberately weak -
 * the video is the point, not the gate. The hard invariants live in the
 * evidence spec.
 */
// `video` is a worker-level fixture, so it must be set at file scope. Declaring
// it inside `test.describe` is rejected outright: "Cannot use({ video }) in a
// describe group, because it forces a new worker."
test.use({
  video: { mode: "on", size: { width: 1440, height: 900 } },
});

test.describe("magnetic drama video", () => {
  test.setTimeout(180_000);

  test("record the magnetic bounce", async ({ page }, testInfo) => {
    mkdirSync("f6-shots/magnet-video", { recursive: true });

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForSelector('[data-testid="mcp-logo"]');
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
    await page.waitForTimeout(1500);

    const hero = (await page.getByTestId("hero-section").boundingBox())!;
    const cx = hero.x + hero.width / 2;
    const cy = hero.y + hero.height / 2;

    // Park and warm, so the recording opens on a settled field rather than
    // mid-ramp: the first frames of a cold spring read as a glitch, not a
    // bounce, and that would misrepresent the effect.
    await page.mouse.move(5, 895);
    await page.waitForTimeout(1000);
    await page.mouse.move(cx, cy);
    await page.waitForTimeout(1200);

    // ~14s of sweeping. A slow arc through the densest part of the field, then
    // a faster pass, because the collision is most visible when the cursor
    // changes direction and the tiles have to re-settle around it.
    const t0 = Date.now();
    let i = 0;
    while (Date.now() - t0 < 14_000) {
      const phase = (Date.now() - t0) / 1000;
      const r = 180 + Math.sin(phase * 0.7) * 120;
      const x = cx + Math.cos(phase * 1.6) * r;
      const y = cy + Math.sin(phase * 2.1) * (r * 0.55);
      await page.mouse.move(Math.round(x), Math.round(y), { steps: 6 });
      i++;
      await page.waitForTimeout(60);
    }

    const video = page.video();
    expect(video, "no video was recorded").not.toBeNull();
    const path = await video!.path();
    // Playwright writes video into a per-run temp directory that is deleted on
    // teardown, so copy it somewhere durable. Without this the artefact is gone
    // the moment the test ends and there is nothing to review.
    const dest = `f6-shots/magnet-video/magnetic-bounce.webm`;
    copyFileSync(path, dest);
    console.log("VIDEO", dest, "from", basename(path), "moves", i);

    // A moving field at the end proves the recording captured a live magnet.
    const moving = await page.evaluate(() => {
      let n = 0;
      document.querySelectorAll('[data-testid="mcp-logo"]').forEach((e) => {
        const m = new DOMMatrix(getComputedStyle(e).transform);
        if (Math.hypot(m.m41, m.m42) > 1) n++;
      });
      return n;
    });
    expect(moving, "field was at rest at the end of the recording").toBeGreaterThan(5);
    console.log("TILES_MOVING_AT_END", moving, "video", testInfo.title);
  });
});
