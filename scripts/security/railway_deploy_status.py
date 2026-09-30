"""Status deployment Railway via Backboard GraphQL API (tanpa print token)."""
import json
import pathlib
import re
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
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


def call(tok: str, query: str, variables: dict | None = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        API, data=body,
        headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())


def main() -> int:
    tok = token()
    me = call(tok, "query { me { id account { id name } } }")
    if me.get("errors"):
        print("Railway API error:", me["errors"])
        return 2
    acct = me["data"]["me"]["account"]
    print(f"account: {acct['name']} ({acct['id']})")

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
    data = call(tok, q, {"id": acct["id"]})
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
