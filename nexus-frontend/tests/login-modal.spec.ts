import { test, expect } from "@playwright/test";

/**
 * Login modal — GitHub, Google, email/password.
 *
 * Scope note: these assert that the UI is wired correctly and that clicking
 * GitHub actually sends the browser to GitHub's authorize endpoint. They
 * deliberately do NOT claim a completed OAuth sign-in: finishing the flow
 * requires a human to log in at github.com and grant consent, which cannot be
 * automated here without a real account. Asserting "login works" on the basis
 * of a redirect would be exactly the unearned claim this suite exists to avoid.
 */

const OAUTH_TIMEOUT = 15000;

test.describe("login modal", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("trigger opens a centred modal with all three sign-in options", async ({ page }) => {
    await page.getByTestId("landing-signin-trigger").click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // All three providers, not just the one this milestone added.
    await expect(page.getByTestId("login-github")).toBeVisible();
    await expect(page.getByTestId("login-google")).toBeVisible();
    await expect(page.getByTestId("login-email-form")).toBeVisible();
    await expect(page.getByTestId("login-submit")).toBeVisible();

    // Centred: the dialog's box must be roughly centred in the viewport.
    const box = (await dialog.boundingBox())!;
    const viewport = page.viewportSize()!;
    const centreDX = Math.abs(box.x + box.width / 2 - viewport.width / 2);
    const centreDY = Math.abs(box.y + box.height / 2 - viewport.height / 2);
    // The geometry is in the message so a regression reports what moved rather
    // than just two bare numbers.
    expect(
      centreDX,
      `horizontally centred (box=${JSON.stringify(box)}, viewport=${JSON.stringify(viewport)})`
    ).toBeLessThan(24);
    expect(
      centreDY,
      `vertically centred (box=${JSON.stringify(box)}, viewport=${JSON.stringify(viewport)})`
    ).toBeLessThan(24);

    // Every control must be reachable: an unclamped dialog pushes the lower
    // ones below the fold and they silently become unclickable.
    for (const id of ["login-submit", "login-toggle-mode"]) {
      const control = page.getByTestId(id);
      await expect(control, `${id} is visible`).toBeVisible();
      const inView = await control.evaluate((el) => {
        const r = el.getBoundingClientRect();
        return r.top >= 0 && r.bottom <= window.innerHeight;
      });
      expect(inView, `${id} within the viewport`).toBe(true);
    }
  });

  test("modal is dismissible and clears state", async ({ page }) => {
    await page.getByTestId("landing-signin-trigger").click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    await page.getByRole("button", { name: /tutup|close/i }).click();
    await expect(dialog).toBeHidden();

    // Reopening must not resurrect the previous form state.
    await page.getByTestId("landing-signin-trigger").click();
    await expect(page.getByTestId("login-email")).toHaveValue("");
    await expect(page.getByTestId("login-error")).toHaveCount(0);
  });

  test("sign-up mode is reachable and toggles back", async ({ page }) => {
    await page.getByTestId("landing-signin-trigger").click();

    await page.getByTestId("login-toggle-mode").click();
    // new-password is the signal that the form is in sign-up mode; autocomplete
    // is what changes, not the visible labels.
    await expect(page.getByTestId("login-password")).toHaveAttribute(
      "autocomplete",
      "new-password"
    );

    await page.getByTestId("login-toggle-mode").click();
    await expect(page.getByTestId("login-password")).toHaveAttribute(
      "autocomplete",
      "current-password"
    );
  });

  test("bad credentials surface an inline error and keep the modal open", async ({ page }) => {
    await page.getByTestId("landing-signin-trigger").click();

    await page.getByTestId("login-email").fill("nobody@example.invalid");
    await page.getByTestId("login-password").fill("wrong-password-123");
    await page.getByTestId("login-submit").click();

    // Supabase rejects this, so the failure must be visible and recoverable —
    // the dialog closing here would look like a successful sign-in.
    const error = page.getByTestId("login-error");
    await expect(error).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole("dialog")).toBeVisible();
  });

  test("GitHub button redirects to GitHub authorize", async ({ page }) => {
    await page.getByTestId("landing-signin-trigger").click();

    // The redirect target is the provider, so intercept the navigation rather
    // than waiting for a page that will only load after a human signs in.
    const [request] = await Promise.all([
      page.waitForRequest(
        (r) => r.url().includes("github.com/login/oauth/authorize"),
        { timeout: OAUTH_TIMEOUT }
      ),
      page.getByTestId("login-github").click(),
    ]);

    const url = new URL(request.url());
    expect(url.hostname).toBe("github.com");
    // Supabase proxies the exchange; client_id is what identifies the GitHub
    // OAuth App and proves the provider is genuinely configured.
    expect(url.searchParams.get("client_id"), "GitHub client_id present").toBeTruthy();
    expect(url.searchParams.get("scope"), "scope requested").toBeTruthy();
  });

  test("Google button redirects to Google authorize", async ({ page }) => {
    await page.getByTestId("landing-signin-trigger").click();

    const [request] = await Promise.all([
      page.waitForRequest(
        (r) => r.url().includes("accounts.google.com") && r.url().includes("oauth"),
        { timeout: OAUTH_TIMEOUT }
      ),
      page.getByTestId("login-google").click(),
    ]);

    const url = new URL(request.url());
    expect(url.hostname).toBe("accounts.google.com");
    expect(url.searchParams.get("client_id"), "Google client_id present").toBeTruthy();
  });

  test("OAuth callback route renders", async ({ page }) => {
    const res = await page.goto("/auth/callback");
    expect(res?.status()).toBeLessThan(500);
    await expect(page.getByTestId("auth-callback")).toBeVisible();
  });
});

/**
 * Evidence capture. Kept out of the main describe so the assertions above stay
 * the pass/fail signal and these never affect the run outcome.
 */
test.describe("login modal evidence", () => {
  test.use({ viewport: { width: 1440, height: 900 } });
  test("desktop modal", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("landing-signin-trigger").click();
    await expect(page.getByRole("dialog")).toBeVisible();
    // Let the rise animation settle so the shot is not captured mid-transform.
    await page.waitForTimeout(600);
    await page.screenshot({ path: "f6-shots/login/login-modal-desktop.png" });
  });

  test("mobile modal", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await page.getByTestId("landing-signin-trigger").click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.waitForTimeout(600);
    await page.screenshot({ path: "f6-shots/login/login-modal-mobile.png" });
  });
});
