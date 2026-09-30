"""Status deployment Railway via Backboard GraphQL API (tanpa print token)."""
import json
import pathlib
import re
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
UA = "Katalir-DeployCheck/1.0"
API = "https://backboard.railway.app/graphql/v2"


def token() -> str:
    """Cari RAILWAY_API_TOKEN di .env, atau fallback ke .env.bak-* .

    `.env` bisa tidak ada (mis. sedang dipindah / dirotasi user), jadi
    query read-only ini harus tetap jalan dari backup.
    """
    for cand in [ROOT / ".env"] + sorted(ROOT.glob(".env.bak-*")):
        if not cand.is_file():
            continue
        m = re.search(
            r"^RAILWAY_API_TOKEN\s*=\s*(\S+)",
            cand.read_text(encoding="utf-8", errors="replace"),
            re.M,
        )
        if m:
            print(f"(sumber token: {cand.name})")
            return m.group(1).strip().strip("\"'")
    raise SystemExit("RAILWAY_API_TOKEN tidak ditemukan di .env / .env.bak-*")


def call(tok: str, query: str, variables: dict | None = None,
         header_style: str = "bearer") -> tuple[int, dict]:
    """Kirim query GraphQL Railway. Kembalikan (http_status, body).

    Dua perbaikan yang WAJIB (lihat docs/security/api-2026-investigation.md):

    1. **User-Agent eksplisit.** Tanpa ini Cloudflare memblokir dengan
       `HTTP 403 / "error code: 1010"` — itu blokir signature bot, BUKAN
       penolakan token. `urllib` bawaan Python Identifying dirinya sebagai bot.

    2. **Periksa `errors`, bukan cuma status code.** Dokumentasi Railway:
       "A query that runs but is denied returns 200; the failure is in
       `errors`." Jadi HTTP 200 pun bisa berarti GAGAL.

    `header_style`:
      - "bearer"  -> `Authorization: Bearer <token>`  (account/workspace token)
      - "project" -> `Project-Access-Token: <token>`   (project-scoped token)
    """
    if header_style == "project":
        auth = {"Project-Access-Token": tok}
    else:
        auth = {"Authorization": "Bearer " + tok}
    req = urllib.request.Request(
        API, data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={**auth, "Content-Type": "application/json", "User-Agent": UA},
    )
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"_raw": raw[:200]}


def describe(status: int, body: dict) -> str:
    """Ringkas respons Railway dengan benar."""
    if body.get("_raw"):
        return f"HTTP {status}  non-JSON body={body['_raw']!r}"
    errs = body.get("errors")
    if errs:
        first = errs[0]
        code = (first.get("extensions") or {}).get("code", "?")
        return f"HTTP {status}  GraphQL error: {first.get('message')}  (code={code})"
    if body.get("data") is None and "data" in body:
        return f"HTTP {status}  data=null tanpa errors"
    return f"HTTP {status}  OK (data ada)"


def main() -> int:
    tok = token()
    print(f"token: prefix={tok[:8]}... len={len(tok)} "
          f"(UUID format = project token)")

    # Diagnosa header: coba Bearer lalu Project-Access-Token. Railway membalas
    # "Not Authorized" (HTTP 200) kalau scope-nya tidak cocok, jadi kita
    # membandingkan keduanya alih-alih menebak.
    q_me = "query { me { id } }"
    print("\n=== diagnosa gaya header ===")
    winner = None
    for style in ("bearer", "project"):
        status, body = call(tok, q_me, header_style=style)
        print(f"  {style:8s} -> {describe(status, body)}")
        if winner is None and not body.get("errors") and body.get("data"):
            winner = style
    if winner is None:
        print("\n  -> kedua gaya header ditolak. Token tidak sah / expired,")
        print("     atau scope-nya tidak mencukupi. Perlu token baru.")
        return 2
    print(f"\n  -> gaya header yang bekerja: {winner}")

    status, body = call(tok, "query { me { id account { id name } } }", header_style=winner)
    if body.get("errors"):
        print("  query `me.account` ditolak:", body["errors"][0].get("message"))
        print("  (token kemungkinan project-scoped; query level-account tidak diizinkan)")
        return 2
    acct = body["data"]["me"]["account"]
    print(f"\naccount: {acct['name']} ({acct['id']})")

    q = """
    query($id: String!) {
      account(id: $id) {
        projects { edges { node {
          id name
          environments { edges { node {
            id name
            deployments(first: 2) { edges { node { id status createdAt } } }
          } } }
        } } }
      }
    }
    """
    _, data = call(tok, q, {"id": acct["id"]}, header_style=winner)
    if data.get("errors"):
        print("query error:", data["errors"])
        return 2

    found = False
    for pe in data["data"]["account"]["projects"]["edges"]:
        proj = pe["node"]
        for ee in proj["environments"]["edges"]:
            env = ee["node"]
            deps = env["deployments"]["edges"]
            if not deps:
                continue
            found = True
            print(f"\nproject={proj['name']} env={env['name']}")
            for de in deps:
                d = de["node"]
                print(f"   deployment {d['status']:10s} {d['createdAt']}")
    if not found:
        print("tidak ada deployment record yang dikembalikan API")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
