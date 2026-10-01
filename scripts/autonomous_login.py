"""Bagian 1: autonomous Supabase test user + JWT.

Rules honoured here:
  * full JWT / password / secret is NEVER printed (prefix + length only)
  * test user is created once and reused if it already exists
"""
from __future__ import annotations

import os
import sys

import httpx

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
from dotenv_loader import load_repo_env  # noqa: E402

load_repo_env()

URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SECRET = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""
PUBLISHABLE = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_KEY") or ""

EMAIL = "otonom-test@katalir-internal.dev"
PASSWORD = "AutoTestKatalir2026!"


def mask(tok: str) -> str:
    return f"prefix={tok[:10]}... len={len(tok)}"


def find_existing_test_user() -> dict | None:
    """1.1a — look for an existing test user we can reuse."""
    r = httpx.get(
        f"{URL}/auth/v1/admin/users",
        headers={"apikey": SECRET, "Authorization": f"Bearer {SECRET}"},
        params={"per_page": 200},
        timeout=30,
    )
    r.raise_for_status()
    for u in r.json().get("users") or []:
        if (u.get("email") or "").lower() == EMAIL:
            return u
    return None


def create_user() -> dict:
    """1.2a — create + confirm the dedicated test account."""
    r = httpx.post(
        f"{URL}/auth/v1/admin/users",
        headers={"apikey": SECRET, "Authorization": f"Bearer {SECRET}", "Content-Type": "application/json"},
        json={"email": EMAIL, "password": PASSWORD, "email_confirm": True},
        timeout=30,
    )
    if r.status_code not in (200, 201):
        raise SystemExit(f"create_user failed: HTTP {r.status_code} {r.text[:300]}")
    return r.json()


def login() -> str:
    """1.3 — password grant against the public token endpoint."""
    r = httpx.post(
        f"{URL}/auth/v1/token?grant_type=password",
        headers={"apikey": PUBLISHABLE, "Content-Type": "application/json"},
        json={"email": EMAIL, "password": PASSWORD},
        timeout=30,
    )
    if r.status_code != 200:
        raise SystemExit(f"login failed: HTTP {r.status_code} {r.text[:300]}")
    return r.json()["access_token"]


def main() -> int:
    print(f"SUPABASE_URL={URL}")
    print(f"secret_key_present={bool(SECRET)} publishable_key_present={bool(PUBLISHABLE)}")

    existing = find_existing_test_user()
    if existing:
        print(f"STEP 1.1 REUSED user id={existing['id']} email={existing['email']} "
              f"confirmed_at={existing.get('email_confirmed_at')}")
        user_id = existing["id"]
    else:
        created = create_user()
        user_id = created["id"]
        print(f"STEP 1.2 CREATED user id={user_id} email={created.get('email')} "
              f"confirmed_at={created.get('email_confirmed_at')} (password NOT printed)")

    token = login()
    print(f"STEP 1.3 LOGIN OK {mask(token)}")

    # Persist for the next steps; file is gitignored territory, never committed.
    with open(".autonomous_jwt", "w", encoding="utf-8") as fh:
        fh.write(token)
    with open(".autonomous_user_id", "w", encoding="utf-8") as fh:
        fh.write(user_id)
    print(f"USER_ID={user_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())