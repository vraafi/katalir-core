"""Tarik build/deploy log Railway untuk diagnosis. Diagnostik saja.

Pakai:
    python scripts/security/railway_logs.py            # deployment terbaru
    python scripts/security/railway_logs.py <deploymentId>

Bentuk API (hasil introspeksi 2026-09-30):
    buildLogs(deploymentId, limit)      -> { logs }
    deploymentLogs(deploymentId, limit) -> { logs }
    deploymentEvents(id)                -> [ ... ]
Log dibungkus JSON {"logs": "..."} atau teks polos; keduanya ditangani.
Nilai credential tidak pernah dicetak.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from scripts.security.railway_deploy_status import (  # noqa: E402
    _q, describe, gql, load_env,
)


def unwrap(raw):
    """Railwaysometimes membalut log dalam JSON; dua-duanya ditangani."""
    if isinstance(raw, str) and raw.lstrip().startswith("{"):
        try:
            return json.loads(raw).get("logs", raw)
        except json.JSONDecodeError:
            return raw
    return raw or ""


def latest_deployment(tok: str) -> tuple[str, str]:
    _, pj = gql(tok, "query { projects { edges { node { id name } } } }")
    if pj.get("errors"):
        raise SystemExit(f"projects -> {describe(0, pj)}")
    pid = pj["data"]["projects"]["edges"][0]["node"]["id"]
    q = _q(
        f'project(id: "{pid}")',
        "{ environments { edges { node { id name",
        "deployments(last: 8) { edges { node { id status } } } } } } }",
    )
    _, tr = gql(tok, q)
    if tr.get("errors"):
        raise SystemExit(f"tree -> {describe(0, tr)}")
    node = tr["data"]["project"]["environments"]["edges"][0]["node"]
    # `last: 8` mengembalikan 8 deployment TERBARU; `edges[0]` = paling baru.
    newest = node["deployments"]["edges"][0]["node"]
    print(f"8 deployment terbaru (status): "
          f"{', '.join(x['node']['status'] for x in node['deployments']['edges'])}")
    return newest["id"], newest["status"]


def main() -> int:
    env, _ = load_env()
    tok = env.get("RAILWAY_API_TOKEN") or env.get("RAILWAY_TOKEN")

    if "--plan" in sys.argv:
        _, pj = gql(tok, "query { projects { edges { node { id name } } } }")
        if pj.get("errors"):
            print("projects ->", describe(0, pj))
            return 2
        pid = pj["data"]["projects"]["edges"][0]["node"]["id"]
        q = _q(f'project(id: "{pid}")',
               "{ id name subscriptionType subscriptionPlanLimit",
               "workspace { id name plan subscriptionPlanLimit }",
               "primaryEnvironmentId",
               "services { edges { node { id name } } }")
        st, body = gql(tok, q)
        print(f"project HTTP {st}")
        if body.get("errors"):
            print("  ", describe(st, body))
            return 1
        p = body["data"]["project"]
        ws = p.get("workspace") or {}
        print(f"  nama         : {p['name']}")
        print(f"  plan project : {p.get('subscriptionType')} "
              f"limit={p.get('subscriptionPlanLimit')}")
        print(f"  workspace    : {ws.get('name')} plan={ws.get('plan')} "
              f"limit={ws.get('subscriptionPlanLimit')}")
        print(f"  services     : "
              f"{[s['node']['name'] for s in p['services']['edges']]}")
        return 0

    if len(sys.argv) > 1:
        dep_id = sys.argv[1]
    else:
        dep_id, status = latest_deployment(tok)
        print(f"deployment terbaru: {dep_id} ({status})")
    print()

    st, body = gql(tok, _q(
        f'deployment(id: "{dep_id}")',
        "{ id status statusUpdatedAt meta createdAt",
        "service { name } staticUrl diagnosis",
    ))
    print(f"deployment HTTP {st}")
    if body.get("errors"):
        print("  ", describe(st, body))
    else:
        d = body["data"]["deployment"]
        print(f"  status={d['status']}  service={d['service']['name']}")
        print(f"  url={d['staticUrl']}  created={d['createdAt']}  "
              f"updated={d['statusUpdatedAt']}")
        if d.get("diagnosis"):
            print("  diagnosis:", json.dumps(d["diagnosis"])[:800])
        if d.get("meta"):
            print("  meta:", json.dumps(d["meta"])[:800])

    for field in ("buildLogs", "deploymentLogs"):
        st, body = gql(tok, _q(
            f'{field}(deploymentId: "{dep_id}", limit: 400)',
            "{ message timestamp severity }"))
        print(f"\n===== {field}  HTTP {st} =====")
        rows = (body.get("data") or {}).get(field) or []
        if body.get("errors"):
            print("  ", describe(st, body))
            continue
        if not rows:
            print("   (kosong)")
            continue
        for r in rows[-60:]:
            ts = (r.get("timestamp") or "")[11:19]
            print(f"  {ts} {r.get('severity', '?'):8s} "
                  f"{(r.get('message') or '')[:280]}")

    st, body = gql(tok, _q(f'deploymentEvents(id: "{dep_id}")',
                           "{ edges { node { createdAt type message } } }"))
    print(f"\n===== deploymentEvents  HTTP {st} =====")
    conn = (body.get("data") or {}).get("deploymentEvents") or {}
    for e in conn.get("edges") or []:
        n = e.get("node") or {}
        print(f"  {n.get('createdAt')}  {n.get('type')}  {n.get('message')}")
    if body.get("errors"):
        print("  ", describe(st, body))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())