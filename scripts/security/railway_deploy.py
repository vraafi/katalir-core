"""Trigger deploy Railway lalu polling statusnya.

Kenapa perlu: sejak 2026-09-25 tidak ada deployment baru sama sekali meski
commit sudah di-push, jadi perbaikan `requirements.txt` (pydantic conflict)
tidak pernah ikut ter-build. Skrip ini membuat deployment baru secara eksplisit
dari commit terbaru repo yang terhubung.

Pakai:
    python scripts/security/railway_deploy.py            # trigger + poll
    python scripts/security/railway_deploy.py --status   # status saja

Nilai credential tidak pernah dicetak.
"""
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from scripts.security.railway_deploy_status import (  # noqa: E402
    _q, describe, gql, load_env,
)


def ids(tok: str) -> dict:
    _, pj = gql(tok, "query { projects { edges { node { id name } } } }")
    if pj.get("errors"):
        raise SystemExit(f"projects -> {describe(0, pj)}")
    pid = pj["data"]["projects"]["edges"][0]["node"]["id"]
    q = _q(f'project(id: "{pid}")', "{ id name",
           "services { edges { node { id name } } }",
           "environments { edges { node { id name } } }")
    _, tr = gql(tok, q)
    if tr.get("errors"):
        raise SystemExit(f"tree -> {describe(0, tr)}")
    p = tr["data"]["project"]
    return {
        "project": pid,
        "project_name": p["name"],
        "service": p["services"]["edges"][0]["node"]["id"],
        "service_name": p["services"]["edges"][0]["node"]["name"],
        "env": p["environments"]["edges"][0]["node"]["id"],
        "env_name": p["environments"]["edges"][0]["node"]["name"],
    }


def latest(tok: str, pid: str):
    """`first:` = deployment TERBARU (descending). `last:` justru yang tertua."""
    q = _q(
        f'project(id: "{pid}")',
        "{ environments { edges { node { id name",
        "deployments(first: 3) { edges { node { id status createdAt } } } } } } }",
    )
    _, tr = gql(tok, q)
    if tr.get("errors"):
        raise SystemExit(f"tree -> {describe(0, tr)}")
    return tr["data"]["project"]["environments"]["edges"][0]["node"][
        "deployments"]["edges"]


def main() -> int:
    env, _ = load_env()
    tok = env.get("RAILWAY_API_TOKEN") or env.get("RAILWAY_TOKEN")
    info = ids(tok)
    print(f"project '{info['project_name']}'  service '{info['service_name']}'  "
          f"env '{info['env_name']}'")

    before = latest(tok, info["project"])
    newest_before = before[0]["node"]
    print(f"sebelum: {newest_before['status']:10s} {newest_before['createdAt']}  "
          f"{newest_before['id']}")
    for e in before[1:]:
        print(f"          {e['node']['status']:10s} {e['node']['createdAt']}")

    if "--status" in sys.argv:
        return 0

    print("\nmemicet deployment dari commit terbaru ...")
    m = ("mutation { serviceInstanceDeploy(environmentId: \"%s\", serviceId: \"%s\", "
         "latestCommit: true) }" % (info["env"], info["service"]))
    st, body = gql(tok, m)
    print(f"mutation HTTP {st}: {describe(st, body)[:300]}")
    if body.get("errors"):
        return 2
    new_id = None
    data = body.get("data") or {}
    for v in data.values():
        if isinstance(v, dict) and v.get("id"):
            new_id = v["id"]
    print(f"deployment baru: {new_id or '(tidak ada id, akan dicari lewat polling)'}")

    for i in range(1, 31):
        time.sleep(20)
        rows = latest(tok, info["project"])
        top = rows[0]["node"]
        if top["id"] != newest_before["id"] or top["status"] in (
                "SUCCESS", "FAILED", "CRASHED", "REMOVED"):
            print(f"\n[{i*20:>4}s] {top['status']:10s} {top['createdAt']}  {top['id']}")
            if top["status"] in ("SUCCESS", "FAILED", "CRASHED"):
                return 0 if top["status"] == "SUCCESS" else 1
        else:
            print(f"[{i*20:>4}s] masih {top['status']:10s} {top['createdAt']}")
    print("\ntimeout menunggu status")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())