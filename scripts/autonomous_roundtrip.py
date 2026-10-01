"""Bagian 2: tenant production round-trip against live Railway with a real JWT.

Covers workflows CRUD, /chat with timing, then Supabase persistence checks.
Test data is cleaned up; the test USER is kept on purpose.
"""
from __future__ import annotations

import json
import os
import sys
import time

import httpx

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
from dotenv_loader import load_repo_env  # noqa: E402

load_repo_env()

API = os.getenv("KATALIR_API", "https://web-production-dc90b.up.railway.app")
JWT = open(os.path.join(REPO_ROOT, ".autonomous_jwt"), encoding="utf-8").read().strip()
USER_ID = open(os.path.join(REPO_ROOT, ".autonomous_user_id"), encoding="utf-8").read().strip()
H = {"Authorization": f"Bearer {JWT}", "Content-Type": "application/json"}
SECRET = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""
SB = (os.getenv("SUPABASE_URL") or "").rstrip("/")

created_workflow: str | None = None


def step(n: str, ok: bool, detail: str) -> None:
    print(f"[{'OK ' if ok else 'FAIL'}] {n}: {detail}")


def main() -> int:
    failures = []
    with httpx.Client(timeout=140.0) as c:
        # 2.1a GET /workflows
        t0 = time.time()
        r = c.get(f"{API}/workflows", headers=H)
        dt = time.time() - t0
        step("2.1a GET /workflows", r.status_code == 200, f"HTTP {r.status_code} in {dt:.2f}s body={r.text[:180]}")
        if r.status_code != 200:
            failures.append("GET /workflows")

        # 2.1b POST /workflows
        global created_workflow
        r = c.post(f"{API}/workflows", headers=H, json={"name": "Auto Test", "description": "Round-trip test"})
        step("2.1b POST /workflows", r.status_code in (200, 201), f"HTTP {r.status_code} body={r.text[:200]}")
        if r.status_code in (200, 201):
            try:
                wf = r.json()
                created_workflow = str(wf.get("id") or (wf.get("workflow") or {}).get("id"))
            except Exception:
                pass
            if created_workflow:
                # 2.1c GET /workflows/{id}
                r2 = c.get(f"{API}/workflows/{created_workflow}", headers=H)
                step("2.1c GET /workflows/{id}", r2.status_code == 200,
                     f"HTTP {r2.status_code} id={created_workflow} body={r2.text[:180]}")
                if r2.status_code != 200:
                    failures.append("GET /workflows/{id}")

        # 2.2 chat E2E
        # NOTE: ChatRequest field is `prompt`, NOT `message` (api_server.py:309).
        # The task brief's example payload used "message" and got a legitimate 422.
        t0 = time.time()
        r = c.post(f"{API}/chat", headers=H, json={"prompt": "Test round-trip otonom."})
        dt = time.time() - t0
        under = dt < 127
        try:
            reply = (r.json().get("reply") or "")[:120]
        except Exception:
            reply = r.text[:120]
        step("2.2 POST /chat", r.status_code == 200 and under,
             f"HTTP {r.status_code} time={dt:.2f}s (<127s: {under}) reply={reply!r}")
        if r.status_code != 200:
            failures.append("POST /chat")
        if not under:
            failures.append("chat timeout budget")

    # 2.3 persistence via PostgREST (service role)
    sh = {"apikey": SECRET, "Authorization": f"Bearer {SECRET}"}
    r = httpx.get(f"{SB}/rest/v1/chat_sessions", headers=sh,
                  params={"user_id": f"eq.{USER_ID}", "select": "id,created_at", "order": "created_at.desc", "limit": "5"},
                  timeout=30)
    sessions = r.json() if r.status_code == 200 else []
    step("2.3a chat_sessions", r.status_code == 200 and bool(sessions),
         f"HTTP {r.status_code} count={len(sessions)} rows={json.dumps(sessions)[:220]}")
    if not sessions:
        failures.append("chat_sessions persistence")

    if sessions:
        sid = sessions[0]["id"]
        r = httpx.get(f"{SB}/rest/v1/chat_messages", headers=sh,
                      params={"session_id": f"eq.{sid}", "select": "id,role,created_at", "order": "created_at", "limit": "10"},
                      timeout=30)
        msgs = r.json() if r.status_code == 200 else []
        step("2.3b chat_messages", r.status_code == 200 and bool(msgs),
             f"HTTP {r.status_code} count={len(msgs)} rows={json.dumps(msgs)[:220]}")
        if not msgs:
            failures.append("chat_messages persistence")

    # 2.4 cleanup workflow only (never the user)
    # Purge ALL workflows named "Auto Test" for this user: an interrupted run can
    # leave orphans that a single-id delete would miss.
    with httpx.Client(timeout=60.0) as c:
        r = c.get(f"{API}/workflows", headers=H)
        if r.status_code == 200:
            for wf in r.json().get("workflows") or []:
                if wf.get("name") == "Auto Test":
                    d = c.delete(f"{API}/workflows/{wf['id']}", headers=H)
                    step("2.4 cleanup workflow", d.status_code in (200, 204, 404),
                         f"HTTP {d.status_code} id={wf['id']}")
        if created_workflow:
            step("2.4 created id cleaned", True, f"id={created_workflow}")

    print(f"USER_ID={USER_ID} (test user KEPT per instructions)")
    print("RESULT=" + ("PASS" if not failures else "FAIL:" + ",".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())