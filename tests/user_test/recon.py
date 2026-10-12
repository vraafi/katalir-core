"""Reconnaissance frontend Katalir: rute nyata, elemen, error konsol.

Tujuan: JANGAN mengarang rute. Brief menyebut /templates, /insights, /chat,
/builder - skrip ini membuktikan mana yang benar-benar ada sebelum diuji.

Keluaran: tests/user_test/_recon.json + screenshot.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "tests" / "user_test"
SHOTS = ROOT / "docs" / "evidence" / "user-test"
OUT.mkdir(parents=True, exist_ok=True)
SHOTS.mkdir(parents=True, exist_ok=True)

FRONTEND = "https://katalir.de5.net"

from playwright.sync_api import sync_playwright  # noqa: E402

CANDIDATE_ROUTES = [
    "/", "/chat", "/dashboard", "/templates", "/insights", "/builder",
    "/workflows", "/agents", "/settings", "/login", "/signup", "/sign-up",
    "/pricing", "/integrations", "/runs", "/analytics",
]

report: dict = {"frontend": FRONTEND, "landing": {}, "routes": {},
                "links_found": [], "console": []}


def attach(pg, sink):
    pg.on("console", lambda m: sink.append(
        {"type": m.type, "text": m.text[:200]}))
    pg.on("pageerror", lambda e: sink.append(
        {"type": "pageerror", "text": str(e)[:200]}))


with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 900},
                        locale="id-ID")
    pg = ctx.new_page()
    attach(pg, report["console"])

    print(f"[recon] buka {FRONTEND}")
    pg.goto(FRONTEND, wait_until="networkidle", timeout=60000)
    pg.screenshot(path=str(SHOTS / "recon-landing.png"), full_page=True)
    report["landing"] = {
        "url": pg.url,
        "title": pg.title(),
        "h1": (pg.locator("h1").first.inner_text()[:200]
               if pg.locator("h1").count() else None),
        "body_text_head": pg.inner_text("body")[:600],
        "nav_links": [],
    }
    for a in pg.locator("a[href]").all()[:60]:
        try:
            href = a.get_attribute("href")
            txt = (a.inner_text() or "").strip()[:40]
            if href:
                report["landing"]["nav_links"].append({"href": href, "text": txt})
        except Exception:  # noqa: BLE001
            pass
    report["links_found"] = sorted({d["href"] for d in report["landing"]["nav_links"]})

    print(f"  title   : {report['landing']['title']}")
    print(f"  h1      : {report['landing']['h1']}")
    print(f"  links   : {len(report['links_found'])}")

    for r in CANDIDATE_ROUTES:
        url = FRONTEND + r
        entry = {"route": r}
        try:
            resp = pg.goto(url, wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(1500)
            entry["http"] = resp.status if resp else None
            entry["final_url"] = pg.url
            entry["redirected"] = pg.url.rstrip("/") != url.rstrip("/")
            entry["title"] = pg.title()
            body = pg.inner_text("body")
            entry["text_len"] = len(body)
            entry["text_head"] = body[:220]
            entry["has_404"] = ("404" in body[:400]
                                or "not found" in body[:400].lower())
            entry["inputs"] = pg.locator("input, textarea").count()
            entry["buttons"] = pg.locator("button").count()
            entry["canvas"] = pg.locator("canvas").count()
            entry["svg"] = pg.locator("svg").count()
            tag = "OK " if (entry["http"] == 200 and not entry["has_404"]) else "?? "
            print(f"  {tag}{r:<14} http={entry['http']} "
                  f"redirect={entry['redirected']} in={entry['inputs']} "
                  f"btn={entry['buttons']} canvas={entry['canvas']}")
        except Exception as exc:  # noqa: BLE001
            entry["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
            print(f"  ERR {r:<14} {entry['error']}")
        report["routes"][r] = entry

    b.close()

(OUT / "_recon.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n[recon] bukti -> {OUT / '_recon.json'}")
print(f"[recon] screenshot -> {SHOTS / 'recon-landing.png'}")
