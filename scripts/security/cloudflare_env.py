"""Baca NAMA environment variable Cloudflare Pages (tanpa nilai).

Kenapa perlu: `NEXT_PUBLIC_SUPABASE_*` TIDAK dibaca Railway sama sekali - itu
dibaca browser dari Cloudflare Pages (`src/lib/supabase.ts`). Railway list
tidak akan pernah menunjukkannya, jadi kita harus cek ke Pages.

Pakai:
    python scripts/security/cloudflare_env.py            # daftar semua project
    python scripts/security/cloudflare_env.py <project> # env var project itu

Nilai variable tidak pernah dicetak - hanya nama + panjang.
"""
import json
import pathlib
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from scripts.security.railway_deploy_status import load_env  # noqa: E402

API = "https://api.cloudflare.com/client/v4"
UA = "Katalir-EnvCheck/1.0"
SECRET_HINTS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "JWT", "WEBHOOK")


def cf(env, path: str):
    tok = env.get("CLOUDFLARE_API_TOKEN") or ""
    acct = env.get("CLOUDFLARE_ACCOUNT_ID") or ""
    if not tok or not acct:
        raise SystemExit("CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID kosong")
    req = urllib.request.Request(
        f"{API}{path}",
        headers={"Authorization": f"Bearer {tok}", "User-Agent": UA})
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"errors": [{"code": e.code,
                            "message": e.read().decode("utf-8", "replace")[:200]}]}
    except Exception as exc:  # noqa: BLE001
        return {"errors": [{"code": 0, "message": str(exc)[:120]}]}


def main() -> int:
    env, _ = load_env()
    acct = env["CLOUDFLARE_ACCOUNT_ID"]

    if len(sys.argv) < 2:
        data = cf(env, f"/accounts/{acct}/pages/projects")
        if data.get("errors"):
            print("errors:", json.dumps(data["errors"])[:300])
            return 1
        for p in data.get("result") or []:
            print(f"  {p.get('name'):28s} domain={p.get('subdomain')} "
                  f"prod={p.get('production_branch')}")
        return 0

    name = sys.argv[1]
    # Bentuk endpoint berubah beberapa kali. Coba semua, laporkan yang
    # memang mengembalikan daftar env var (bukan metadata project).
    PATHS = [
        ("env", f"/accounts/{acct}/pages/projects/{name}/env/"),
        ("envs", f"/accounts/{acct}/pages/projects/{name}/envs"),
        ("env-production", f"/accounts/{acct}/pages/projects/{name}/env/production"),
    ]
    for label, path in PATHS:
        data = cf(env, path)
        if data.get("errors"):
            print(f"  [{label}] errors: {json.dumps(data['errors'])[:120]}")
            continue
        result = data.get("result")
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                result = []
        if isinstance(result, dict):
            print(f"  [{label}] objek metadata, bukan env var. kunci={sorted(result)[:6]}")
            continue
        rows = result if isinstance(result, list) else []
        print(f"  [{label}] {len(rows)} entri")
        for v in rows:
            if isinstance(v, dict) and v.get("name"):
                name_v = str(v["name"])
                shown = "len=? (disembunyikan)" if any(
                    h in name_v.upper() for h in SECRET_HINTS) else \
                    f"len={len(str(v.get('value') or ''))}"
                print(f"    {name_v:36s} {shown}")
        if rows:
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())