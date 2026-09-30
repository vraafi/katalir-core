"""Introspeksi skema Railway GraphQL. Diagnostik saja.

Pakai:
    python scripts/security/railway_introspect.py Environment Project
    python scripts/security/railway_introspect.py --fields buildLogs deploymentLogs

Query dibangun lewat helper `_q` dari railway_deploy_status supaya kurung
kurawalnya pasti seimbang. Menulis literal GraphQL manual sempat salah dua kali
dan menghasilkan "GRAPHQL_PARSE_FAILED: Expected Name, found <EOF>".
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from scripts.security.railway_deploy_status import (  # noqa: E402
    _q, describe, gql, load_env,
)


def main() -> int:
    env, _ = load_env()
    tok = env.get("RAILWAY_API_TOKEN") or env.get("RAILWAY_TOKEN")

    if "--github" in sys.argv:
        st, body = gql(tok, _q("githubRepos",
                               "{ id name fullName defaultBranch isPrivate }"))
        print(f"githubRepos HTTP {st}")
        if body.get("errors"):
            print("  ", describe(st, body))
            return 1
        rows = (body.get("data") or {}).get("githubRepos") or []
        for r in rows:
            print(f"  {r.get('fullName'):38s} branch={r.get('defaultBranch')} "
                  f"private={r.get('isPrivate')}")
        return 0

    if "--autodeploy" in sys.argv:
        _, pj = gql(tok, "query { projects { edges { node { id name } } } }")
        if pj.get("errors"):
            print("projects ->", describe(0, pj))
            return 2
        pid = pj["data"]["projects"]["edges"][0]["node"]["id"]
        q = _q(f'project(id: "{pid}")',
               "{ environments { edges { node { id name } } } }")
        _, tr = gql(tok, q)
        for ee in tr["data"]["project"]["environments"]["edges"]:
            eid = ee["node"]["id"]
            st2, b2 = gql(tok, _q(
                f'serviceInstanceAutoDeployStatus(projectId: "{pid}", '
                f'environmentId: "{eid}", service: "web")',
                "{ enabled branch }"))
            summary = json.dumps(b2.get("data"))[:200] if not b2.get("errors") \
                else describe(st2, b2)
            print(f"  env {ee['node']['name']}: {summary}")
        return 0

    if len(sys.argv) > 2 and sys.argv[1] == "--inputtypes":
        want = set(sys.argv[2:])
        for tname in sorted(want):
            q = _q(f'__type(name: "{tname}") '
                   '{ kind name inputFields '
                   '{ name type { name kind ofType { name } } } }')
            st, body = gql(tok, q)
            t = (body.get("data") or {}).get("__type")
            print(f"=== {tname}  HTTP {st}")
            if not t:
                continue
            for f in t.get("inputFields") or []:
                print(f"   {f['name']}: "
                      f"{(f['type'].get('ofType') or f['type']).get('name')}")
        return 0

    if len(sys.argv) > 2 and sys.argv[1] in ("--fields", "--mutations"):
        root = "Mutation" if sys.argv[1] == "--mutations" else "Query"
        q = _q(f'__type(name: "{root}") {{ fields {{ name args '
               '{ name type { name kind ofType { name } } } } } }')
        st, body = gql(tok, q)
        print(f"{root} HTTP {st}")
        want = set(sys.argv[2:])
        for f in (body.get("data") or {}).get("__type", {}).get("fields") or []:
            if f["name"] not in want:
                continue
            args = ", ".join(
                f"{a['name']}:{(a['type'].get('ofType') or a['type']).get('name')}"
                for a in f["args"])
            print(f"  {f['name']}({args})")
        return 0

    for tname in sys.argv[1:] or ["Environment"]:
        q = _q("__type(name: %s) { name fields { name } }" % json.dumps(tname))
        st, body = gql(tok, q)
        print(f"=== {tname}  HTTP {st}")
        if body.get("errors"):
            print("   ", body["errors"][0]["message"])
            continue
        for f in body["data"]["__type"]["fields"]:
            print(f"   {f['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())