/**
 * F5.3 — demo recorder, deliberately NOT part of the regression suite.
 *
 * `launch-demo.spec.ts` records a webm of the real product for the Product Hunt
 * listing. It is excluded from playwright.dev.config.ts on purpose: running a
 * camera on every test run would slow the suite for no benefit, and a recording
 * step that can fail would then look like a product regression.
 *
 * Run:  npx playwright test -c playwright.demo.config.ts
 * Out:  the webm under test-results/
 */
import { defineConfig } from "@playwright/test";
import base from "./playwright.dev.config";

export default defineConfig({
  ...base,
  testMatch: ["launch-demo.spec.ts"],
  testIgnore: [] as string[],
  // Recordings are the entire point of this config, so they are always kept -
  // the base config only retains them on failure. `videoSize` is deliberately
  // not set here: it is a context option rather than a `use` option in this
  // Playwright version, and setting it here is a type error. The viewport
  // already fixes the frame size at 1440x900.
  use: { ...base.use, video: "on" },
  timeout: 180_000,
  retries: 0,
});
