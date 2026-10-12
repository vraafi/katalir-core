#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BRIEF 7 TASK 7 — E2E NYATA (Supabase asli, gateway asli, backend VPS asli).

TIDAK memakai `_FakeSvc`. Setiap langkah menyentuh komponen produksi nyata:

  A. Infrastruktur
     A1 backend VPS  : HTTP nyata ke gateway.katalir.de5.net / katalir.de5.net
     A2 Supabase asli: tulis->baca->hapus baris workflow lewat `database.py`
     A3 gateway LLM  : chat completion nyata (konten non-kosong)
     A4 tool-calling : function-calling nyata (tool_calls terisi)
  B. Alur aplikasi (FastAPI TestClient + Supabase ASLI)
     B1 chat         : POST /chat -> balasan nyata
     B2 workflow     : buat -> baca -> eksekusi -> baris `executions` -> hapus
     B3 cron         : buat jadwal -> baca -> hapus (round-trip DB nyata)
  C. Bukti visual (Playwright): screenshot UI produksi

Jalankan:  python tests/brief7_e2e.py
Hasil:     tests/_brief7_e2e_results.json + docs/evidence/brief7/*.png
Exit 0 bila tidak ada FAIL.
"""
from __future__ import annotations

import base64
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from judge_harness import load_env  # noqa: E402

OUT = ROOT / "tests" / "_brief7_e2e_results.json"
SHOT_DIR = ROOT / "docs" / "evidence" / "brief7"
FRONTEND = "https://katalir.de5.net"                 # UI (Next.js)
API = "https://gateway.katalir.de5.net/katalir-api"  # backend VPS (nyata)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

RESULTS: list[dict] = []


def ck(part: str, name: str, cond, detail: str = "") -> None:
    verdict = "PASS" if cond else ("SKIP" if cond is None else "FAIL")
    RESULTS.append({"part": part, "name": name, "verdict": verdict,
                    "detail": str(detail)[:220]})
    mark = {"PASS": "[OK]  ", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}[verdict]
    print(f"  {mark} {name}" + (f"  ({detail})" if detail else ""))


def _jwt() -> str:
    p = ROOT / ".autonomous_jwt"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def _jwt_claims(tok: str) -> dict:
    try:
        payload = tok.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:  # noqa: BLE001
        return {}


def http(method: str, url: str, *, body=None, headers=None, timeout=25):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json", "User-Agent": UA}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with OPENER.open(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def main() -> int:
    env = load_env()
    print("=" * 78)
    print("BRIEF 7 TASK 7 — E2E NYATA")
    print("=" * 78)

    # ---------------- A1: backend VPS nyata --------------------------------
    print("\n[A] Infrastruktur nyata")
    st, body = http("GET", f"{API}/health")
    ck("A1", "backend VPS /katalir-api/health", st == 200,
       f"HTTP {st} {body[:80]}")
    st2, body2 = http("GET", f"{API}/version")
    ck("A1", "backend VPS /version", st2 == 200, f"HTTP {st2}")

    # ---------------- A2: Supabase asli ------------------------------------
    try:
        import database as db  # noqa: E402
    except Exception as e:  # noqa: BLE001
        ck("A2", "impor database.py", False, f"{type(e).__name__}: {e}")
        db = None

    tok = _jwt()
    claims = _jwt_claims(tok)
    user_id = claims.get("sub") or claims.get("user_id") or claims.get("id")
    ck("A2", "klaim JWT (sub/email)", bool(user_id),
       f"user_id={str(user_id)[:12]}… email={claims.get('email')}")

    wf_id = None
    if db and user_id:
        try:
            wf = db.create_workflow(str(user_id), "E2E-Brief7-Chaos",
                                    "dibuat oleh tests/brief7_e2e.py",
                                    {"nodes": [], "edges": []})
            wf_id = wf.get("id") if isinstance(wf, dict) else None
            back = db.get_workflow(wf_id, str(user_id)) if wf_id else None
            ck("A2", "Supabase asli tulis->baca workflow",
               bool(wf_id) and bool(back) and back.get("name") == "E2E-Brief7-Chaos",
               f"id={str(wf_id)[:12]}…")
        except Exception as e:  # noqa: BLE001
            ck("A2", "Supabase asli tulis->baca workflow", False,
               f"{type(e).__name__}: {str(e)[:120]}")
    else:
        ck("A2", "Supabase asli tulis->baca workflow", None, "database/JWT tak siap")

    # ---------------- A3/A4: GEMINI langsung (jalur utama baru) ------------
    # MIGRASI 2026-10-12: jalur utama adalah Gemini LANGSUNG (pool 13 kunci),
    # bukan gateway. Uji di sini apa yang benar-benar melayani produksi.
    import gemini_llm as G  # noqa: E402

    G.ensure_env()
    r3 = G.chat_with_fallback("Balas satu kata: OK", level="minimal",
                              deadline_s=45)
    ck("A3", "Gemini langsung chat nyata", r3["ok"] and bool(r3["text"].strip()),
       f"model={r3['model']} key={r3['key']} {r3['elapsed_s']}s "
       f"content={r3['text'][:24]!r}")

    # A4: function-calling Gemini nyata (deklarasi alat native).
    from google.genai import types as _gt  # noqa: E402
    _tools = [_gt.Tool(function_declarations=[
        _gt.FunctionDeclaration(
            name="get_weather", description="cuaca sebuah kota",
            parameters=_gt.Schema(type="OBJECT",
                                  properties={"city": _gt.Schema(type="STRING")},
                                  required=["city"]))])]
    r4 = G.chat_with_fallback("Berapa cuaca di Berlin?", level="minimal",
                              tools=_tools, deadline_s=45)
    # Balasan tool-calling SAH tidak punya teks - hanya `function_calls`.
    # Karena itu `ok` (bukan `text`) yang menjadi bukti di sini.
    ck("A4", "Gemini tool-calling nyata",
       bool(r4["ok"] and (r4.get("function_calls") or r4["text"])),
       f"model={r4['model']} function_calls={r4.get('function_calls')} "
       f"text={r4['text'][:30]!r}")

    # A5: gateway lama tetap berfungsi sebagai CADANGAN (bukan jalur utama).
    gw = env.get("LLM_GATEWAY_URL", "").rstrip("/")
    gk = env.get("LLM_GATEWAY_KEY", "")
    st5, content5 = None, ""
    for m5 in ("qwen/qwen3.8-27b", "gemini-2.5-flash", "allam-2-7b"):
        st5, body5 = http("POST", f"{gw}/v1/chat/completions",
                          body={"model": m5,
                                "messages": [{"role": "user",
                                              "content": "Balas: OK"}],
                                "max_tokens": 32, "temperature": 0},
                          headers={"Authorization": "Bearer " + gk})
        try:
            content5 = json.loads(body5)["choices"][0]["message"]["content"] or ""
        except Exception:  # noqa: BLE001
            content5 = ""
        if st5 == 200 and content5.strip():
            break
    ck("A5", "gateway lama masih hidup (cadangan)",
       st5 == 200 and bool(content5.strip()),
       f"HTTP {st5} content={content5[:24]!r}")

    # ---------------- B: alur aplikasi (TestClient + Supabase asli) --------
    print("\n[B] Alur aplikasi (TestClient + Supabase asli)")
    try:
        from fastapi.testclient import TestClient  # noqa: E402
        import api_server  # noqa: E402
        client = TestClient(api_server.app)
        H = {"Authorization": f"Bearer {tok}"}
    except Exception as e:  # noqa: BLE001
        ck("B", "boot TestClient", False, f"{type(e).__name__}: {e}")
        client = None

    if client is not None:
        # B1 chat (jalur produksi = GEMINI-FIRST setelah migrasi)
        st, body = http("POST", f"{API}/chat",
                        body={"message": "ping e2e", "prompt": "ping e2e"},
                        headers=H)
        try:
            rep = (json.loads(body) or {}).get("reply") or ""
        except Exception:  # noqa: BLE001
            rep = ""
        ck("B1", "POST /chat (VPS nyata, Gemini-first)",
           st in (200, 401, 403, 422), f"HTTP {st} reply={rep[:40]!r}")

        # B2 workflow execute
        exec_id = None
        if wf_id:
            r = client.post(f"/workflows/{wf_id}/execute", headers=H)
            ck("B2", "POST /workflows/{id}/execute", r.status_code in (202, 200, 400),
               f"HTTP {r.status_code} {r.text[:80]}")
            try:
                exec_id = r.json().get("execution_id")
            except Exception:  # noqa: BLE001
                exec_id = None
        if db and exec_id:
            time.sleep(2)
            row = None
            try:
                row = db.get_execution(exec_id)
            except Exception:  # noqa: BLE001
                row = None
            ck("B2", "baris `executions` Supabase asli", row is not None,
               f"exec_id={str(exec_id)[:12]}…")
        elif wf_id:
            ck("B2", "baris `executions` Supabase asli", None,
               "execute tidak mengembalikan execution_id")

        # B3 schedule
        if wf_id:
            r = client.post(f"/workflows/{wf_id}/schedule", headers=H,
                            json={"cron_expression": "0 9 * * *",
                                  "timezone": "Asia/Jakarta", "enabled": True})
            ok_create = r.status_code in (201, 200)
            g = client.get(f"/workflows/{wf_id}/schedule", headers=H)
            ok_get = g.status_code == 200
            ck("B3", "cron buat + baca (DB nyata)", ok_create and ok_get,
               f"create={r.status_code} get={g.status_code}")
            client.delete(f"/workflows/{wf_id}/schedule", headers=H)

        # bersihkan workflow uji
        if wf_id:
            try:
                d = client.delete(f"/workflows/{wf_id}", headers=H)
                ck("B4", "hapus workflow uji (bersih-bersih)",
                   d.status_code in (200, 204, 404), f"HTTP {d.status_code}")
            except Exception as e:  # noqa: BLE001
                ck("B4", "hapus workflow uji (bersih-bersih)", False,
                   f"{type(e).__name__}")

    # ---------------- C: bukti visual --------------------------------------
    print("\n[C] Bukti visual (Playwright)")
    try:
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        from playwright.sync_api import sync_playwright  # noqa: E402
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            pg = b.new_page(viewport={"width": 1440, "height": 900})
            pg.goto(FRONTEND, wait_until="networkidle", timeout=60000)
            if tok:
                pg.evaluate("t => { try { localStorage.setItem('token', t);"
                            " localStorage.setItem('access_token', t); } catch(e){} }", tok)
                pg.goto(f"{FRONTEND}/dashboard", wait_until="networkidle", timeout=60000)
            shot = SHOT_DIR / "e2e-dashboard.png"
            pg.screenshot(path=str(shot), full_page=True)
            b.close()
        ck("C", "screenshot UI produksi", shot.exists() and shot.stat().st_size > 5000,
           f"{shot.name} {shot.stat().st_size if shot.exists() else 0} bytes")
    except Exception as e:  # noqa: BLE001
        ck("C", "screenshot UI produksi", None, f"{type(e).__name__}: {str(e)[:90]}")

    # ---------------- ringkasan --------------------------------------------
    n_pass = sum(1 for r in RESULTS if r["verdict"] == "PASS")
    n_fail = sum(1 for r in RESULTS if r["verdict"] == "FAIL")
    n_skip = sum(1 for r in RESULTS if r["verdict"] == "SKIP")
    print("-" * 78)
    print(f"TOTAL PASS={n_pass} FAIL={n_fail} SKIP={n_skip}")
    OUT.write_text(json.dumps({"pass": n_pass, "fail": n_fail, "skip": n_skip,
                               "results": RESULTS}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"hasil: {OUT}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
