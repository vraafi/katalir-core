"""Baca & ubah environment variable Railway.

Kenapa perlu: `api_server.py` sengaja gagal start kalau `ALLOWED_HOSTS` kosong
(mitigasi CVE-2026-48710 menolak fallback ke '*'). Variabel itu belum pernah
di-set di Railway, jadi container crash-loop dan produksi balas HTTP 502.

Pakai:
    python scripts/security/railway_vars.py --list
    python scripts/security/railway_vars.py --set ALLOWED_HOSTS "a.com,b.com"

Nilai variabel yang sudah ada TIDAK pernah dicetak - hanya nama + panjang.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from scripts.security.railway_deploy import ids  # noqa: E402
from scripts.security.railway_deploy_status import (  # noqa: E402
    _q, describe, gql, load_env,
)


def list_vars(tok: str, info: dict) -> int:
    q = _q(f'variables(projectId: "{info["project"]}", '
           f'environmentId: "{info["env"]}", serviceId: "{info["service"]}")')
    st, body = gql(tok, q)
    print(f"variables HTTP {st}")
    if body.get("errors"):
        print("  ", describe(st, body))
        return 1
    # Bentuk balasan `variables` berubah-ubah; cetak nama variabel saja.
    # Nilai tidak pernah dicetak.
    data = (body.get("data") or {}).get("variables")
    seen: set[str] = set()
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            print("  (respons bukan JSON)")
            return 0
    if isinstance(data, dict):
        for k, v in data.items():
            seen.add(k)
            print(f"  {k:34s} len={len(str(v))}")
    else:
        print(f"  tipe={type(data).__name__} {str(data)[:120]}")
    print(f"  total: {len(seen)}")
    return 0


def gql_input(d: dict) -> str:
    """Render object input GraphQL.

    `json.dumps` TIDAK bisa dipakai: GraphQL butuh kunci tanpa tanda kutip
    (`{projectId: "x"}`), sedangkan JSON menghasilkan `{"projectId": "x"}`
    -> "Syntax Error: Expected Name, found String".
    """
    parts = []
    for k, v in d.items():
        if isinstance(v, bool):
            parts.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            parts.append(f"{k}: {v}")
        elif v is None:
            parts.append(f"{k}: null")
        else:
            parts.append(f"{k}: {json.dumps(str(v))}")
    return "{" + ", ".join(parts) + "}"


def set_var(tok: str, info: dict, name: str, value: str) -> int:
    payload = {
        "projectId": info["project"],
        "environmentId": info["env"],
        "serviceId": info["service"],
        "name": name,
        "value": value,
        "skipDeploys": False,
    }
    m = f"mutation {{ variableUpsert(input: {gql_input(payload)}) }}"
    st, body = gql(tok, m)
    print(f"variableUpsert({name}) HTTP {st}: {describe(st, body)[:300]}")
    return 0 if not body.get("errors") else 1


def domains(tok: str, info: dict) -> list[str]:
    q = _q(f'domains(projectId: "{info["project"]}", '
           f'environmentId: "{info["env"]}", serviceId: "{info["service"]}")',
           "{ domain }")
    st, body = gql(tok, q)
    if body.get("errors"):
        return []
    return [d["domain"] for d in (body.get("data") or {}).get("domains") or []]


# Nama variabel yang tidak boleh pernah dicetaknya nilainya.
SECRET_HINTS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "JWT", "CREDENTIAL")


def get_var(tok: str, info: dict, name: str) -> int:
    """Cetak nilai satu variabel - hanya untuk yang jelas bukan rahasia."""
    if any(h in name.upper() for h in SECRET_HINTS):
        print(f"  {name} ditolak: nama menandakan rahasia")
        return 1
    q = _q(f'variables(projectId: "{info["project"]}", '
           f'environmentId: "{info["env"]}", serviceId: "{info["service"]}")')
    _, body = gql(tok, q)
    data = (body.get("data") or {}).get("variables") or {}
    if isinstance(data, str):
        data = json.loads(data)
    print(f"  {name} = {data.get(name, '(tidak ada)')}")
    return 0


def main() -> int:
    env, _ = load_env()
    tok = env.get("RAILWAY_API_TOKEN") or env.get("RAILWAY_TOKEN")
    info = ids(tok)

    if "--list" in sys.argv:
        return list_vars(tok, info)

    if "--get" in sys.argv:
        return get_var(tok, info, sys.argv[sys.argv.index("--get") + 1])

    if "--domains" in sys.argv:
        print(json.dumps(domains(tok, info), indent=2))
        return 0

    if "--set" in sys.argv:
        i = sys.argv.index("--set")
        return set_var(tok, info, sys.argv[i + 1], sys.argv[i + 2])

    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())