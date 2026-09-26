/**
 * One-off diagnostic harness. Not part of the regression suite: it exists so a
 * mobile overflow can be attributed to a specific element instead of guessed
 * at from a screenshot. `testIgnore` is cleared here because the dev config
 * deliberately excludes _probes/.
 */
import { defineConfig } from "@playwright/test";
import base from "./playwright.dev.config";

export default defineConfig({
  ...base,
  testMatch: ["_probes/overflow-probe.spec.ts"],
  testIgnore: [] as string[],
});
