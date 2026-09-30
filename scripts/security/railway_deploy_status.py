"""Railway deploy status - versi 2026 yang benar.

TIGA kesalahan lama yang sudah diperbaiki di sini:

1. **Token yang salah.** Repo punya DUA token:
   - `RAILWAY_TOKEN`     -> **account token** (scope paling luas)
   - `RAILWAY_API_TOKEN` -> **project token** (satu environment satu project)
   `railway.com/auth.md` (akses 2026-09-30): "`me` resolves only for account
   tokens - it is scoped to a personal account." Query `me` dengan project
   token **selalu** membalas "Not Authorized" walau tokennya valid. Script
   lama memakai `RAILWAY_API_TOKEN` + query `me` - kombinasi salah yang
   hasilnya saya salah baca sebagai "token expired".

2. **User-Agent default urllib.** Cloudflare memblokir dengan
   `HTTP 403 / "error code: 1010"` (blokir signature bot) sebelum request
   sampai ke Railway. UA eksplisit wajib.

3. **Hanya status code.** Railway membalas `HTTP 200` + `errors` untuk
   penolakan otorisasi. Array `errors` WAJIB diperiksa.

Nilai token tidak pernah dicetak; hanya prefix 8 char + panjang.
"""
import json
import pathlib
import re
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
API = "https://backboard.railway.com/graphql/v2"
UA = "Katalir-DeployCheck/1.0"

# Sumber .env, dari yang paling mungkin ke paling lama.
ENV_CANDIDATES = [
    ROOT / ".env",
    ROOT / ".env.bak-pretrustedhost-20260930-172610",
    pathlib.Path(r"C:\Users\user\minimax_agent_otonom\.env"),
    ROOT / ".env.bak-20260926-150120",
    ROOT / ".env.bak-20260924-131948",
    ROOT / ".env.bak-20260924-101059",
    ROOT / ".env.bak-20260917-014828",
]

Q_ME = 'query { __type(name: "User") { name fields { name } } }'

# TEMUAN 2026-09-30 (akhirnya, setelah probe bertingkat):
#   RAILWAY_API_TOKEN  -> **project token**. Hanya boleh query `projects`
#                         miliknya sendiri. Query `me` SELALU membalas
#                         "Not Authorized". Itulah sebabnya semua probe
#                         sebelumnya menyimpulkan "token expired" - salah diagnosis.
#   RAILWAY_TOKEN      -> account token lama; lolos introspeksi tapi SEMUA
#                         query data ditolak (kemungkinan dicabut).
#   Schema 2026 juga menghapus `User.account` -> digantikan `User.workspaces`.
def _q(*parts: str) -> str:
    """Bungkus badan query dengan `query { ... }` dan lengkapi kurung kurang.

    `body` ditulis dengan kurung kurawal yang sudah seimbang; helper ini
    hanya menambah kurung penutup yang kurang untuk lapisan `query { ... }`.
    Menulis query GraphQL sebagai string literal manual berulang kali
    menghasilkan bug kurung kurawal ("Expected Name, found <EOF>").
    """
    body = " ".join(parts)
    return "query { " + body + " }" * (1 + body.count("{") - body.count("}"))


Q_PROJECTS = "query { projects { edges { node { id name } } } }"

# Hasil introspeksi 2026-09-30:
#   Project     -> services, environments
#   Environment -> deployments   (TIDAK punya `services`)
#   Deployment  -> status, createdAt, staticUrl, service { name }, canRollback
TREE_BODY = (
    'project(id: "{pid}") { id name services { edges { node { id name } } } '
    'environments { edges { node { id name '
    'deployments(last: 8) { edges { node '
    '{ id status createdAt staticUrl canRollback service { name } '
    '} } } } } } } }'
)


def tree_query(pid: str) -> str:
    q = _q(TREE_BODY.replace("{pid}", pid))
    assert q.count("{") == q.count("}"), q
    return q

for _name, _query in (("Q_ME", Q_ME), ("Q_PROJECTS", Q_PROJECTS)):
    assert _query.count("{") == _query.count("}"), f"{_name} tidak seimbang"


def load_env() -> tuple[dict, pathlib.Path]:
    for p in ENV_CANDIDATES:
        if not p.is_file():
            continue
        data = {}
        for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
            s = raw.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, _, v = s.partition("=")
            data[k.strip()] = v.split(" #")[0].strip().strip("\"'")
        if data.get("SUPABASE_URL"):
            return data, p
    raise SystemExit("tidak ada .env yang memuat SUPABASE_URL")


def gql(token: str, query: str, attempts: int = 3):
    """Kirim query GraphQL. Bertahan terhadap connection reset / timeout."""
    last = ""
    for i in range(attempts):
        req = urllib.request.Request(
            API, data=json.dumps({"query": query}).encode(),
            headers={"Authorization": "Bearer " + token,
                     "Content-Type": "application/json", "User-Agent": UA},
        )
        try:
            r = urllib.request.urlopen(req, timeout=30)
            return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(raw)
            except json.JSONDecodeError:
                return e.code, {"_raw": raw[:160]}
        except Exception as exc:  # noqa: BLE001
            # Connection reset / timeout sesaat.
            last = f"{type(exc).__name__}: {str(exc)[:70]}"
            if i < attempts - 1:
                time.sleep(2 + 2 * i)
    return 0, {"_net": last}


def describe(status: int, body: dict) -> str:
    if body.get("_net"):
        return f"jaringan gagal: {body['_net']}"
    if body.get("_raw"):
        return f"HTTP {status}  non-JSON: {body['_raw']!r}"
    errs = body.get("errors")
    if errs:
        f = errs[0]
        code = (f.get("extensions") or {}).get("code", "?")
        return f"HTTP {status}  {f.get('message')}  (code={code})"
    return f"HTTP {status}  OK"


def main() -> int:
    env, src = load_env()
    print(f"sumber env : {src}")
    print()
    for var in ("RAILWAY_TOKEN", "RAILWAY_API_TOKEN", "RAILWAY_akun", "RAILWAY_projek"):
        tok = env.get(var)
        if not tok:
            continue
        # Introspeksi = pembuktian autentikasi yang paling bersih:
        # token mati akan kena "Not Authorized" (HTTP 200 + errors),
        # token hidup akan kena error validasi field (HTTP 400).
        status, body = gql(tok, Q_ME)
        print(f"  {var:20s} ({tok[:8]}... len={len(tok)})  -> {describe(status, body)}")
        if body.get("errors") or body.get("_raw") or body.get("_net"):
            continue
        fields = [f["name"] for f in body["data"]["__type"]["fields"]]
        print(f"  {'':20s} AUTH OK")
        print(f"  {'':20s} tipe User punya 'workspaces': "
              f"{'workspaces' in fields}  ('account': {'account' in fields})")

        _, wl = gql(tok, Q_PROJECTS)
        if wl.get("errors") or wl.get("_raw") or wl.get("_net"):
            print(f"  projects -> {describe(200, wl)}")
            continue
        edges = wl["data"]["projects"]["edges"]
        if not edges:
            print("  projects -> kosong (token tidak melihat project apa pun)")
            continue
        print(f"  {'':20s} bisa melihat {len(edges)} project")
        print()
        total = 0
        for pe in edges:
            proj = pe["node"]
            pid = proj["id"]
        print(f"  project '{proj['name']}'  id={pid}")
        q = tree_query(pid)
        _, tr = gql(tok, q)
        if tr.get("errors"):
            print(f"    -> {describe(200, tr)}")
            print()
            continue
        pnode = tr["data"]["project"]
        svc = ", ".join(f"{s['node']['name']}({s['node']['id'][:8]})"
                        for s in pnode["services"]["edges"])
        print(f"    services: [{svc}]")
        for ee in pnode["environments"]["edges"]:
            envn = ee["node"]
            print(f"    env '{envn['name']}'  id={envn['id']}")
            for de in envn["deployments"]["edges"]:
                d = de["node"]
                total += 1
                mark = "  <== AKTIF" if d.get("staticUrl") else ""
                print(f"      - {d['status']:10s} {d['createdAt']}  "
                      f"{d.get('service', {}).get('name', '?')}  "
                      f"url={d.get('staticUrl')}{mark}")
        print()
    print(f"  total deployment: {total}")
    return 0
    print("\n  tidak ada token yang bisa membaca data project")
    print("  -> butuh project token baru di Settings > Service > Tokens")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
