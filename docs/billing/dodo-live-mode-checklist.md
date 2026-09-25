# Dodo Live Mode Checklist

Accessed 25 September 2026. Official source: https://docs.dodopayments.com/

## Agent-verified

- Checkout URL is a Dodo hosted checkout URL, not a webhook URL.
- Dodo API key and webhook secret are configured in backend environment (values not printed).
- Webhook endpoint uses Standard Webhooks signature verification and fails closed without a valid signature.
- Dodo webhook tests pass 14/14, including spoof rejection, idempotency, tier upgrade, refund, and DB-failure retry.
- `/billing` Plus CTA now points to the billing flow and pricing displays `$299/year`.

- Dodo official docs (accessed 2026-09-25) confirm product setup, account verification, dashboard checkout links, and environment setup are dashboard/account operations. No documented API was found that safely enables merchant verification or switches live mode; application code must not do this automatically.

1. Log in to the Dodo dashboard.
2. Complete merchant identity/business verification.
3. Create/verify the Plus subscription product and price.
4. Confirm the production checkout URL matches `DODO_CHECKOUT_URL`.
5. Switch the environment to live mode only after the product is verified.
6. Send a real low-value subscription and verify the webhook, tier, balance, and invoice in production.

## Expected result

A successful checkout increases Plus entitlement exactly once; duplicate webhook delivery is idempotent; invalid signatures return 401.

Never enable live mode or submit a payment from application code.
