# Google OAuth Publish Checklist

Accessed 25 September 2026. Official source: https://support.google.com/cloud/answer/15549257

## Agent-verified

- Production callback: `https://web-production-dc90b.up.railway.app/oauth/google/callback`
- Frontend origin: `https://katalir.de5.net`
- Google credentials are present in backend environment (values not printed).
- Supabase Site URL and redirect allow-list are the production domain per prior configuration.
- Backend uses PKCE/state validation and stores tokens in Fernet Vault.

## User action

1. Open Google Auth Platform → Branding.
2. Set application home page, privacy policy (`https://katalir.de5.net/privacy`), terms (`https://katalir.de5.net/terms`), authorized domain `katalir.de5.net`, support email `support@katalir.de5.net`, and upload the 120×120 logo.
3. Open Audience → Test users → add production users if still in Testing.
4. Click **Publish app**.
5. Run a fresh incognito login and a Google Sheets consent test.
6. Record the result and review time; Google verification can take several business days.

## Expected result

Google no longer shows the unverified-app warning for approved users; redirect returns to the production app and Vault status is Connected.

There is no supported API for clicking Publish. Do not log client secrets or paste them into this file.
