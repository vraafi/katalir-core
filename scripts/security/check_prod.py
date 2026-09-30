"""Probe endpoint produksi Railway. Diagnostik saja, tanpa menebak.

Pakai:
    python scripts/security/check_prod.py
    python scripts/security/check_prod.py /workflows /health
"""


import json
import pathlib
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from scripts.security.railway_deploy_status import load_env  # noqa: E402

UA = "Katalir-ProdCheck/1.0"
DEFAULT_PATHS = ["/health", "/", "/docs", "/openapi.json", "/workflows"]


def probe(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        r = urllib.request.urlopen(req, timeout=25)
        return r.status, r.read(600).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(600).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {str(exc)[:90]}"


def main() -> int:
    env, _ = load_env()
    base = (env.get("RAILWAY_STATIC_URL")
            or "https://web-production-dc90b.up.railway.app").rstrip("/")
    paths = sys.argv[1:] or DEFAULT_PATHS
    print(f"base: {base}")
    worst = 0
    for p in paths:
        url = base + p
        st, body = probe(url)
        worst = max(worst, st if st else 599)
        head = " ".join(body.split())[:180]
        print(f"  {p:16s} HTTP {st}  {head}")
    return 0 if worst < 500 else 1


if __name__ == "__main__":
    raise SystemExit(main())