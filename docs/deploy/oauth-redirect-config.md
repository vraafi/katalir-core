# OAuth Redirect Configuration

_Last verified: 2026-09-25_

## Production frontend

- Site: `https://katalir.de5.net`
- Legacy Cloudflare URL retained only as a backward-compatible CORS origin: `https://proyek-agent.pages.dev`
- Frontend client: `src/lib/supabase.ts`
- Login implementation: `src/context/auth.tsx`

`signInWithGoogle()` explicitly passes:

```ts
options: { redirectTo: window.location.origin }
```

This makes the redirect use the current browser origin (`https://katalir.de5.net` in production and `http://localhost:3000` in local development) instead of hardcoding a Cloudflare domain.

## Supabase Auth configuration

In Supabase Dashboard → Authentication → URL Configuration:

- Site URL: `https://katalir.de5.net`
- Redirect URL allow-list must include:
  - `https://katalir.de5.net`
  - `https://katalir.de5.net/**`
  - `http://localhost:3000/**` (local development only)

The production redirect sent to Supabase is generated at runtime by the browser. No Supabase secret is stored in this document or committed to the repository.

## Google Cloud Console

For the Google OAuth client used by Supabase:

- Authorized JavaScript origins:
  - `https://katalir.de5.net`
  - `http://localhost:3000` (local development only)
- Authorized redirect URIs: use the callback URL configured for the Supabase OAuth client, not the Katalir API OAuth callback.
- Application home page: `https://katalir.de5.net`
- Privacy policy: `https://katalir.de5.net/privacy`
- Terms of service: `https://katalir.de5.net/terms`
- Support email: `support@katalir.de5.net`

## Railway API OAuth callbacks

Katalir's Google Sheets and Slack OAuth callbacks remain on the backend. They must not move to Cloudflare Pages:

```text
https://web-production-dc90b.up.railway.app/oauth/google/callback
https://web-production-dc90b.up.railway.app/oauth/slack/callback
```

The backend CORS allow-list contains `https://katalir.de5.net`.

## Debugging a redirect to the legacy domain

1. Open DevTools → Application → Local Storage and remove stale Supabase auth state if necessary.
2. Clear the old Site URL/redirect entry in Supabase Dashboard.
3. Confirm the deployed frontend contains `redirectTo: window.location.origin`; a stale Cloudflare deployment can hide the change.
4. Confirm the Cloudflare Pages deployment is serving the current `main` commit.
5. Start a fresh private/incognito login and inspect the Supabase authorize URL's `redirect_to` parameter. It should contain `https://katalir.de5.net`, never the legacy `pages.dev` domain.
6. If Google itself redirects, verify the Google OAuth client's Authorized JavaScript origins and the Supabase Google provider callback configuration.

## Verification boundary

The code and deployment configuration can be verified in CI and in the browser DOM, but a real Google consent round trip requires a user login and is not claimed automatically.
