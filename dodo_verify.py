# dodo_verify.py — Dodo Payments webhook verification (Standard Webhooks spec)
# Officiële bron: https://docs.dodopayments.com/developer-resources/fastapi-boilerplate
#   "Pass all three webhook-id, webhook-timestamp, and webhook-signature headers
#    to webhook.verify() — the Standard Webhooks signature covers id.timestamp.body"

import os
from dotenv import load_dotenv
load_dotenv()


def _sdk_client():
    """DodoPayments SDK client configurationerd volgens boilerplate."""
    from dodopayments import DodoPayments

    api_key = (os.getenv("DODO_PAYMENTS_API_KEY") or os.getenv("DODO_API_KEY") or "").strip()
    webhook_key = (os.getenv("DODO_PAYMENTS_WEBHOOK_KEY")
                   or os.getenv("DODO_WEBHOOK_SECRET") or "").strip()
    env = (os.getenv("DODO_PAYMENTS_ENVIRONMENT") or "test_mode").strip()
    return DodoPayments(
        bearer_token=api_key or None,
        webhook_key=webhook_key or None,
        environment=("live_mode" if env == "live_mode" else "test_mode"),
    )


def verify_dodo_webhook(body: bytes, headers: dict) -> bool:
    """Verifieert Standard Webhooks signature via dodopayments SDK unwrap.

    Gebruikt webhook-id / webhook-timestamp / webhook-signature headers
    (Standard Webhooks). Geeft False bij: ontbrekende key, SDK-fout, of
    ongeldige signature (anti-spoof — NOOIT iets accepteren zonder key OF sig).
    """
    webhook_key = (os.getenv("DODO_PAYMENTS_WEBHOOK_KEY")
                   or os.getenv("DODO_WEBHOOK_SECRET") or "").strip()
    if not webhook_key:
        # Geen key geconfigureerd → kan niet verifiëren → REJECT (geen spoof-leak).
        return False
    try:
        client = _sdk_client()
        unwrapped = client.webhooks.unwrap(
            body,
            headers={
                "webhook-id": headers.get("webhook-id", ""),
                "webhook-signature": headers.get("webhook-signature", ""),
                "webhook-timestamp": headers.get("webhook-timestamp", ""),
            },
        )
        return bool(unwrapped)
    except Exception:
        return False