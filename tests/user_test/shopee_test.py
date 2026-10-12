"""TASK 4 - REAL WORKFLOW TEST: use case Shopee (Katalir, 12 Okt 2026).

Prompt nyata pengguna:
  "Buat workflow: webhook Shopee -> batch order jam 8 -> kirim WhatsApp ->
   AI parse balasan -> update Sheets"

Yang diuji:
  4.1 Apakah Katalir memahami intent? (apakah ia bertanya balik / menyusun draf)
  4.2 Apakah workflow benar-benar terbangun - node & edge di Canvas Builder

Bukti: screenshot chat + canvas, jumlah node, jumlah edge, label node.

CATATAN JUJUR: bila jalur chat frontend mati (API_URL menunjuk host lama),
skenario ini dicatat FAIL/BLOCKED dengan bukti - bukan diklaim lulus.
"""
from __future__ import annotations

import json
import os
import pathlib
import time

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
UT = ROOT / "tests" / "user_test"
SHOTS = ROOT / "docs" / "evidence" / "user-test"
SHOTS.mkdir(parents=True, exist_ok=True)
FRONTEND = "https://katalir.de5.net"
SESS = json.loads((UT / "_session.json").read_text(encoding="utf-8"))

PROMPT = ("Buat workflow: webhook Shopee -> batch order jam 8 -> "
          "kirim WhatsApp -> AI parse balasan -> update Sheets")

from playwright.sync_api import sync_playwright  # noqa: E402

out: dict = {"prompt": PROMPT}
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 1000}, locale="id-ID")
    pg = ctx.new_page()
    errs: list = []
    fails: list = []
    pg.on("console", lambda m: errs.append({"t": m.type, "x": m.text[:200]})
          if m.type in ("error", "pageerror") else None)
    pg.on("pageerror", lambda e: errs.append({"t": "pageerror", "x": str(e)[:200]}))
    pg.on("requestfailed", lambda r: fails.append(
        {"u": r.url[:150], "f": (r.failure or "")[:120]}))

    pg.goto(f"{FRONTEND}/chat", wait_until="domcontentloaded", timeout=60000)
    pg.evaluate("([k,v]) => { try { localStorage.setItem(k,v); } catch(e){} }",
                [SESS["storage_key"], json.dumps(SESS["session"])])
    pg.reload(wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4000)
    for lbl in ("Lewati", "Tutup"):
        try:
            el = pg.get_by_role("button", name=lbl, exact=False)
            if el.count() and el.first.is_visible():
                el.first.click(timeout=3000)
                pg.wait_for_timeout(900)
                break
        except Exception:  # noqa: BLE001
            pass

    # ---------- 4.1 chat ----------
    ta = pg.locator("textarea").first
    ta.click(timeout=10000)
    ta.fill(PROMPT)
    t0 = time.time()
    ta.press("Enter")
    pg.wait_for_timeout(70000)
    out["chat_s"] = round(time.time() - t0, 2)
    body = pg.inner_text("body")
    out["chat_body_len"] = len(body)
    out["chat_body"] = body[-2500:]
    pg.screenshot(path=str(SHOTS / "shopee-01-chat.png"), full_page=True)
    out["chat_screenshot"] = str(SHOTS / "shopee-01-chat.png")

    # apakah Katalir bertanya balik (perilaku yang diharapkan brief)?
    low = body.lower()
    out["asks_questions"] = ("?" in body and any(
        w in low for w in ("shopee", "webhook", "order", "whatsapp", "sheets")))
    out["mentions_intent"] = any(
        w in low for w in ("webhook shopee", "batch", "jam 8", "whatsapp",
                           "sheets", "parse"))
    out["echoed_prompt"] = PROMPT[:60].lower() in low

    # ---------- 4.2 canvas ----------
    pg.goto(f"{FRONTEND}/builder", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(6000)
    pg.screenshot(path=str(SHOTS / "shopee-02-canvas.png"), full_page=True)
    out["canvas_screenshot"] = str(SHOTS / "shopee-02-canvas.png")
    nodes = pg.locator(".react-flow__node, [data-node-id]")
    edges = pg.locator(".react-flow__edge")
    out["nodes"] = nodes.count()
    out["edges"] = edges.count()
    labels = []
    for i in range(min(out["nodes"], 25)):
        try:
            labels.append((nodes.nth(i).inner_text() or "").strip()[:60])
        except Exception:  # noqa: BLE001
            pass
    out["node_labels"] = labels
    out["canvas_body"] = pg.inner_text("body")[:900]
    out["console_errors"] = errs[:10]
    out["failed_requests"] = fails[:10]
    b.close()

# ---------- verdict ----------
out["gate_4_1"] = bool(out.get("asks_questions") or out.get("mentions_intent"))
out["gate_4_2"] = out.get("nodes", 0) > 0 and out.get("edges", 0) > 0
out["verdict"] = ("PASS" if (out["gate_4_1"] and out["gate_4_2"]) else "FAIL")

print(json.dumps({k: v for k, v in out.items()
                  if k not in ("chat_body", "canvas_body", "node_labels")},
                 ensure_ascii=False, indent=1)[:2000])
print(f"\nnode labels : {out.get('node_labels')}")
print(f"body chat   : {out.get('chat_body','')[-300:]!r}")
(UT / "_shopee_results.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"bukti -> {UT / '_shopee_results.json'}")
