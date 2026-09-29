"""Fetch popularity + freshness signals for MCP registry entries.

Writes `mcp_signals.json` at repo root. Idempotent and resumable:
entries already recorded are skipped, so the script can be re-run to
accumulate coverage against a rate limit.

NO FABRICATION. A signal that cannot be fetched is written absent
(`null`), never estimated.

  * install_count - only from npm/PyPI downloads, which need an
    `install_config.package`. ZERO entries in the current catalogue
    have one, so this stays null until packages are actually recorded.
    GitHub stars are deliberately NOT substituted: stars are a
    different metric, and reporting them as installs would make the
    0.35 weight look fed when it is not.
  * updated_at    - GitHub `pushed_at`, for entries that link a repo.

GitHub allows 60 req/h unauthenticated (5.000/h with a token). The
script reads the remaining budget from response headers and stops
cleanly when it runs out, instead of hammering into a 403 and
retrying.

Usage:
    python scripts/fetch-install-counts.py --limit 500
    GITHUB_TOKEN=... python scripts/fetch-install-counts.py --limit 5000
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "mcp_signals.json"
UA = "katalir-signal-fetch/1.0 (+https://katalir.de5.net)"
GH_REPO_RE = re.compile(r"github\.com/([^/\s]+)/([^/\s#?]+)", re.I)


def load_existing() -> dict:
    if OUT.exists():
        try:
            return json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save(data: dict) -> None:
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")


def parse_pkg(install_config: dict):
    p = (install_config.get("package") or "").strip()
    if not p or install_config.get("transport") not in ("stdio", "http", "sse"):
        return None
    if p.startswith("npx"):
        m = re.search(r"(@?[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)?)\s*$", p.split()[-1])
        return m.group(1) if m else None
    if re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", p):
        return p
    return None


def npm_downloads(client, pkg: str) -> int:
    try:
        r = client.get(f"https://api.npmjs.org/downloads/point/last-month/{pkg}", timeout=10)
        if r.status_code == 200:
            return int(r.json().get("downloads") or 0)
    except Exception:
        pass
    return 0


def pypi_downloads(client, pkg: str) -> int:
    try:
        r = client.get(f"https://pypistats.org/api/packages/{pkg}/recent", timeout=10)
        if r.status_code == 200:
            return int((r.json().get("data") or {}).get("last_month") or 0)
    except Exception:
        pass
    return 0


def github_pushed_at(client, repo_url: str, token):
    m = GH_REPO_RE.search(repo_url or "")
    if not m:
        return None, None
    owner, repo = m.group(1), m.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = client.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers, timeout=10)
    except Exception:
        return None, None
    if r.status_code == 200:
        return r.json().get("pushed_at"), None
    if r.status_code in (403, 429):
        # Out of budget. Caller must stop, not retry.
        return None, int(r.headers.get("x-ratelimit-remaining", "0") or 0)
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--sleep", type=float, default=1.0, help="seconds between GitHub calls")
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT))
    import mcp_registry as catalog

    entries = list(catalog.load_cached().values())
    data = load_existing()
    token = os.environ.get("GITHUB_TOKEN") or None

    # Priority: verified first (they actually move the ranking), then
    # curator picks, then the rest. The 500 fetched should be the 500
    # whose signals can change the outcome.
    def rank(e):
        verified = e.get("runtime_verified") or (e.get("verification") or {}).get("call_verified")
        return (
            0 if verified else 1,
            0 if catalog.is_curator_pick(e) else 1,
            int(e.get("tools_count") or 0),
        )

    entries.sort(key=rank)
    todo = [e for e in entries if str(e.get("id")) not in data][: args.limit]
    print(f"entries={len(entries)} already={len(data)} todo={len(todo)} token={'yes' if token else 'no'}")

    got_updated = got_install = 0
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True) as client:
        for n, e in enumerate(todo, 1):
            eid = str(e.get("id"))
            rec = data.get(eid) or {}
            pkg = parse_pkg(e.get("install_config") or {})

            installs = 0
            if pkg:
                installs = npm_downloads(client, pkg)
                if installs == 0 and "." not in pkg:
                    installs = pypi_downloads(client, pkg)
                if installs:
                    got_install += 1
            rec["install_count"] = installs or None
            rec["has_package"] = bool(pkg)

            if not rec.get("updated_at"):
                pushed, remaining = github_pushed_at(client, e.get("repo_url") or "", token)
                if remaining is not None and remaining <= 1:
                    rec["updated_at"] = None
                    rec["skipped"] = "github rate limit exhausted"
                    data[eid] = rec
                    save(data)
                    print(f"STOP at {n}/{len(todo)}: GitHub rate limit exhausted")
                    break
                if pushed:
                    rec["updated_at"] = pushed
                    got_updated += 1
                time.sleep(args.sleep)

            data[eid] = rec
            if n % 25 == 0:
                save(data)
                print(f"  {n}/{len(todo)} updated={got_updated} install={got_install}")

    save(data)
    print(f"DONE covered={len(data)} updated_at={got_updated} install_count={got_install}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
