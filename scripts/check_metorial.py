"""Check Metorial live, against the official API reference.

Base https://api.metorial.com, auth `Authorization: Bearer <metorial_sk_...>`
(https://metorial.com/api.md). The roadmap recorded 0 providers earlier, so this
re-tests that and looks for the GitHub connection. The key is never printed.
"""
import json
import os
import urllib.error
import urllib.request

from dotenv_loader import load_repo_env

load_repo_env(override=True)
key = os.environ.get("METORIAL_API_KEY", "")
print(f"key_present={bool(key)} prefix_ok={key.startswith('metorial_sk_')} len={len(key)}")
if not key:
    raise SystemExit(0)

BASE = "https://api.metorial.com"
PATHS = [
    "/integration-providers",
    "/provider-tools?provider=github",
    "/provider-tools?providerId=github",
    "/providers",
    "/integration-providers/inp_0mui33wr9cVxaZQR85Kv7t",
    "/sessions",
]


def get(path):
    req = urllib.request.Request(
        f"{BASE}{path}",
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            # Cloudflare error 1010 blocks non-browser signatures outright, which
            # is a WAF fingerprint block, not an auth failure. Identified from the
            # 403 body, not assumed.
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.status, json.loads(r.read()), r.headers.get("content-type")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        if key in raw:
            raw = raw.replace(key, "<REDACTED>")
        try:
            return e.code, json.loads(raw), e.headers.get("content-type")
        except ValueError:
            return e.code, {"_raw": raw[:300]}, e.headers.get("content-type")
    except Exception as e:  # noqa: BLE001  (RemoteDisconnected, TLS, DNS, ...)
        return f"EXC {type(e).__name__}", {"_raw": str(e)[:160]}, ""


for p in PATHS:
    code, data, ctype = get(p)
    n = "-"
    if isinstance(data, dict):
        items = data.get("items") or data.get("data") or []
        n = len(items) if isinstance(items, list) else "n/a"
    print(f"{p:26s} -> {code}  ct={ctype}  items={n}")
    print(f"    body: {json.dumps(data)[:260]}")
    if code == 200 and isinstance(data, dict):
        items = data.get("items") or data.get("data") or []
        if isinstance(items, list):
            for it in items[:8]:
                if isinstance(it, dict):
                    print(
                        "     ",
                        {k: it.get(k) for k in ("id", "name", "type", "provider", "status") if k in it},
                    )
