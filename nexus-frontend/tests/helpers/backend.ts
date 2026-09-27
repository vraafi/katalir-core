import { test, type APIRequestContext } from "@playwright/test";

/**
 * Skip a test when the API is not running.
 *
 * A large block of this suite talks to the Python backend on :8000. When that
 * process is not up, every one of those specs fails - not because the frontend
 * regressed, but because there is nothing to talk to. That is a false signal:
 * a red suite trains you to ignore red, which is how a real regression gets
 * shipped.
 *
 * So the specs that genuinely need the backend ask for it explicitly and skip
 * cleanly when it is absent. Specs that are pure frontend (layout, colour,
 * geometry) are left alone on purpose - they must keep running, because they
 * are the ones that can catch a frontend regression while the backend is down.
 *
 * Takes Playwright's `request` fixture (an APIRequestContext) so it works for
 * both request-only tests and page-scoped ones. The health check is a plain
 * GET with a short timeout: the point is to fail fast, not to wait out a long
 * connect timeout on a closed port.
 */
export async function skipIfBackendDown(request: APIRequestContext): Promise<void> {
  const url = process.env.E2E_API_URL ?? "http://127.0.0.1:8000/health";
  const up = await request
    .get(url, { timeout: 3000, failOnStatusCode: false })
    .then((r) => r.ok())
    .catch(() => false);
  if (!up) {
    // eslint-disable-next-line no-console
    console.warn(`[skip] backend not reachable at ${url} - skipping backend-dependent test`);
    test.skip(true, `backend not reachable at ${url}`);
  }
}
