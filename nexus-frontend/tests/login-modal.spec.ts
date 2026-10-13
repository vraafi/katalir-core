import { test, expect } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";

/**
 * Login modal — GitHub, Google (+ email/password when enabled).
 *
 * Scope note: these assert that the UI is wired correctly and that clicking
 * GitHub actually sends the browser to GitHub's authorize endpoint. They
 * deliberately do NOT claim a completed OAuth sign-in: finishing the flow
 * requires a human to log in at github.com and grant consent, which cannot be
 * automated here without a real account. Asserting "login works" on the basis
 * of a redirect would be exactly the unearned claim this suite exists to avoid.
 *
 * EMAIL AUTH HIDDEN (13 Okt 2026, BUG-06): Supabase free tier allows only
 * 2 emails/hour from the built-in sender, so email signup frequently 429s and
 * wrecks the first impression at launch. `login-modal.tsx` gates the email
 * form behind `EMAIL_AUTH_HIDDEN = true`. This suite was updated in lockstep —
 * it used to assert `login-email-form` VISIBLE, which is now the opposite of
 * correct. Tests below assert the email form is ABSENT and a "coming soon"
 * notice is shown instead, while OAuth (Google/GitHub) stays fully exercised.
 *
 * WHEN RE-ENABLING email auth: flip `EMAIL_AUTH_HIDDEN` to false AND restore
 * the email-form assertions; otherwise this suite keeps passing while the form
 * is live and the notice assertions fail noisily (which is the intended tripwire).
 */

const OAUTH_TIMEOUT = 15000;

test.describe("login modal", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("trigger opens a centred modal with OAuth options only", async ({ page }) => {
    await page.getByTestId("landing-signin-trigger").click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // OAuth providers always present.
    await expect(page.getByTestId("login-github")).toBeVisible();
    await expect(page.getByTestId("login-google")).toBeVisible();

    // Email auth hidden while BUG-06 is outstanding: the form AND the
    // toggle live inside the same gate, so neither may render. The notice
    // that replaces them must be visible so the omission is intentional to
    // the user rather than looking like a broken half-modal.
    await expect(page.getByTestId("login-email-form")).toHaveCount(0);
    await expect(page.getByTestId("login-submit")).toHaveCount(0);
    await expect(page.getByTestId("login-email")).toHaveCount(0);
    await expect(page.getByTestId("login-toggle-mode")).toHaveCount(0);
    await expect(page.getByTestId("login-email-hidden")).toBeVisible();

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

    // Every control that IS rendered must be reachable: an unclamped dialog
    // pushes the lower ones below the fold and they silently become unclickable.
    for (const id of ["login-github", "login-google"]) {
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

    // Reopening must not resurrect stale state. With email auth hidden the
    // observable signal is the notice (there is no field to check), so assert
    // the modal comes back clean and still hides the form.
    await page.getByTestId("landing-signin-trigger").click();
    await expect(dialog).toBeVisible();
    await expect(page.getByTestId("login-email-hidden")).toBeVisible();
    await expect(page.getByTestId("login-email-form")).toHaveCount(0);
  });

  test("email signup is not exposed anywhere in the modal", async ({ page }) => {
    await page.getByTestId("landing-signin-trigger").click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // BUG-06 evidence: no email entry point, no sign-up toggle, no submit.
    // This is the core assertion for the "hide email signup" change — a
    // regression that re-renders any of these fails here by name.
    await expect(page.getByTestId("login-email-form")).toHaveCount(0);
    await expect(page.getByTestId("login-email")).toHaveCount(0);
    await expect(page.getByTestId("login-password")).toHaveCount(0);
    await expect(page.getByTestId("login-submit")).toHaveCount(0);
    await expect(page.getByTestId("login-toggle-mode")).toHaveCount(0);

    // No loose "Sign up" affordance anywhere inside the dialog either — the
    // toggle was the only one, but assert by role+name so a re-introduced
    // link with a different testid still trips this.
    await expect(dialog.getByRole("button", { name: /daftar|sign up/i })).toHaveCount(0);

    // The replacement notice must be present, so the absence reads as
    // deliberate rather than broken.
    await expect(page.getByTestId("login-email-hidden")).toBeVisible();
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

  test("signup via Google works end to end up to the consent screen", async ({ page }) => {
    // BUG-06 requirement: with the email path hidden, Google must remain a
    // complete sign-up route. This walks the full client-side chain the modal
    // owns and proves it terminates at a real Google authorize URL carrying a
    // client_id — i.e. Supabase's provider config is intact, not just that a
    // button exists. It stops at the consent screen on purpose: completing it
    // needs a human Google account, and pretending otherwise would be the
    // unearned claim this suite exists to avoid.
    await page.getByTestId("landing-signin-trigger").click();
    await expect(page.getByRole("dialog")).toBeVisible();

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
    // redirect_uri points at SUPABASE, not this app — Supabase brokers the
    // OAuth exchange and only then bounces to our /auth/callback. Asserting
    // `/auth/callback$` here would be wrong: Google never sees our route.
    const redirectUri = url.searchParams.get("redirect_uri");
    expect(redirectUri, "redirect_uri present").toBeTruthy();
    expect(redirectUri!, "Google returns to the Supabase broker").toMatch(
      /supabase\.co\/auth\/v1\/callback$/
    );
    // scope must request an identity, not a bare token.
    expect(url.searchParams.get("scope"), "scope requested").toContain("email");
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
 *
 * BUG-06 (13 Okt 2026): the dated shots under `f6-shots/bug-06/` are the
 * screenshots the task asked for — (1) modal with NO email button/sign-up, and
 * (2) the Google sign-up path reached. The `f6-shots/login/` shots are the
 * original milestone evidence and are refreshed here so the record stays current.
 */
const BUG06_DIR = "f6-shots/bug-06";

test.describe("login modal evidence", () => {
  test.use({ viewport: { width: 1440, height: 900 } });
  test("desktop modal", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("landing-signin-trigger").click();
    await expect(page.getByRole("dialog")).toBeVisible();
    // Let the rise animation settle so the shot is not captured mid-transform.
    await page.waitForTimeout(600);
    await page.screenshot({ path: "f6-shots/login/login-modal-desktop.png" });
    // BUG-06 evidence #1: modal without the email form.
    await page.screenshot({ path: `${BUG06_DIR}/01-modal-no-email-signup.png` });
  });

  test("mobile modal", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await page.getByTestId("landing-signin-trigger").click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.waitForTimeout(600);
    await page.screenshot({ path: "f6-shots/login/login-modal-mobile.png" });
    await page.screenshot({ path: `${BUG06_DIR}/01-modal-no-email-signup-mobile.png` });
  });

  test("google signup path reached", async ({ page }) => {
    // BUG-06 evidence #2: Google sign-up is a working route while email is
    // hidden. Capture the modal (both OAuth buttons live) and the authorize
    // request that follows the click.
    await page.goto("/");
    await page.getByTestId("landing-signin-trigger").click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${BUG06_DIR}/02-modal-google-available.png` });

    const [request] = await Promise.all([
      page.waitForRequest(
        (r) => r.url().includes("accounts.google.com") && r.url().includes("oauth"),
        { timeout: OAUTH_TIMEOUT }
      ),
      page.getByTestId("login-google").click(),
    ]);
    // Persist the exact authorize URL as proof (screenshot of a cross-origin
    // redirect is not capturable here; the URL is the durable evidence).
    const url = request.url();
    expect(url).toContain("accounts.google.com");
    mkdirSync(BUG06_DIR, { recursive: true });
    writeFileSync(`${BUG06_DIR}/02-google-authorize-url.txt`, url + "\n");
  });
});
