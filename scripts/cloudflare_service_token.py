"""Bagian 3: verify Cloudflare token scope BEFORE acting, then create service token.

Never claims "insufficient scope" without printing the raw API evidence.
Never prints the client_secret.
"""
from __future__ import annotations

import json
import os
import sys

import httpx

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
from dotenv_loader import load_repo_env  # noqa: E402

load_repo_env()

TOKEN = os.getenv("CLOUDFLARE_API_TOKEN") or ""
ACCOUNT = os.getenv("CLOUDFLARE_ACCOUNT_ID") or ""
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def verify_token():
    """0.2 — check BOTH endpoints.

    `/user/tokens/verify` is user-scoped and returns "Invalid API Token" for a
    valid account-scoped token, so it must never be the sole verdict.
    """
    acct = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/tokens/verify"
    print("=== 0.2a USER-SCOPED verify (NOT authoritative for account tokens) ===")
    r = httpx.get("https://api.cloudflare.com/client/v4/user/tokens/verify", headers=H, timeout=30)
    print(f"HTTP {r.status_code} body={r.text[:300]}")

    print("\n=== 0.2a ACCOUNT-SCOPED verify (authoritative) ===")
    r2 = httpx.get(acct, headers=H, timeout=30)
    print(f"HTTP {r2.status_code} body={r2.text[:400]}")

    ok_account = r2.status_code == 200 and r2.json().get("success")
    ok_user = r.status_code == 200 and r.json().get("success")
    print(f"\nUSER_SCOPED_OK={ok_user} ACCOUNT_SCOPED_OK={ok_account}")
    return ok_account or ok_user


def permission_groups():
    """Enumerate scopes. NOTE: these are USER-level endpoints; an account-scoped
    token gets 403 "Valid user-level authentication not found" here even when
    perfectly valid. A 403 here is therefore NOT proof of missing scope — the
    authoritative test is attempting the real operation (create_service_token).
    """
    print("\n=== permission groups (user-level endpoint; 403 != missing scope) ===")
    r = httpx.get("https://api.cloudflare.com/client/v4/user/tokens/permission_groups", headers=H, timeout=30)
    print(f"HTTP {r.status_code} body={r.text[:250]}")
    return [], r.status_code


def token_scopes():
    """What the token can actually do (scopes on the token itself)."""
    print("\n=== 3.1c token own scopes ===")
    r = httpx.get("https://api.cloudflare.com/client/v4/user/tokens/permission_groups", headers=H, timeout=30)
    if r.status_code == 200:
        ids = [g.get("id") for g in (r.json().get("result") or [])]
        print(f"catalog_ids_sample={json.dumps(ids[:10])}")
    r2 = httpx.get("https://api.cloudflare.com/client/v4/user/tokens", headers=H, timeout=30)
    print(f"list_tokens HTTP {r2.status_code}")
    if r2.status_code == 200:
        for t in (r2.json().get("result") or [])[:10]:
            print(f"  token id={t.get('id')} name={t.get('name')} status={t.get('status')}")


def create_service_token():
    print("\n=== 3.2 create Access service token ===")
    r = httpx.post(
        f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/access/service_tokens",
        headers=H,
        json={"name": "katalir-gateway-token", "duration": "8760h"},
        timeout=30,
    )
    print(f"HTTP {r.status_code}")
    if r.status_code not in (200, 201):
        print(f"RAW={r.text[:800]}")
        return None
    data = r.json()
    if not data.get("success"):
        print(f"RAW={r.text[:800]}")
        return None
    res = data["result"]
    print(f"  client_id={res.get('client_id')}")
    print(f"  client_secret={'***REDACTED*** present=' + str(bool(res.get('client_secret')))}")
    print(f"  token_id={res.get('id')} expires_at={res.get('expires_at')}")
    return res


def main() -> int:
    print(f"account_id_present={bool(ACCOUNT)} token_present={bool(TOKEN)}")
    if not TOKEN:
        print("NO TOKEN")
        return 1
    if not verify_token():
        print("TOKEN INVALID ON BOTH ENDPOINTS -> stop")
        return 1
    hits, status = permission_groups()
    # Authoritative test: just try the real operation.
    print("\nSCOPE_EVIDENCE: permission_groups endpoint is user-level; proceeding to direct create attempt")
    res = create_service_token()
    if res:
        with open(os.path.join(REPO_ROOT, ".cf_service_token_id"), "w", encoding="utf-8") as fh:
            fh.write(res.get("client_id") or "")
        print(f"SERVICE_TOKEN_CLIENT_ID={res.get('client_id')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())