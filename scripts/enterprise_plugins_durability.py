# CATATAN: jalankan dari ROOT repo (butuh .autonomous_jwt + .env):
#   python scripts/enterprise_plugins_live.py
# Prasyarat: server uvicorn lokal di port 8123 + token dari
#   python scripts/autonomous_login.py  (atau mk_session.py)
"""Bukti DURABILITY fitur #11 — plugin bertahan lintas RESTART proses.

Dua fase (dijalankan terpisah, dengan restart server di antaranya):

  fase 1 (install)  : pasang plugin lewat API, lalu buktikan BARISNYA ADA di
                      tabel `plugin_registry` Supabase (bukan cuma di memori).
  fase 2 (verify)   : setelah server di-restart, buktikan plugin MASIH ada dan
                      status enabled-nya ikut pulih.

Pakai: python _plugins_durability.py 1   -> pasang
       <restart server>
       python _plugins_durability.py 2   -> verifikasi
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:8123"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TOK = open(".autonomous_jwt", encoding="utf-8").read().strip()
OWNER = "otonom-test@katalir-internal.dev"
NAMA = "acme.durable"
fase = sys.argv[1] if len(sys.argv) > 1 else "1"


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {TOK}"})
    try:
        r = OPENER.open(req, timeout=30)
        return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def db_rows():
    """Baca tabel plugin_registry LANGSUNG dari Supabase (service_role)."""
    from dotenv import load_dotenv
    load_dotenv()
    url = os.getenv("SUPABASE_URL").rstrip("/")
    key = (os.getenv("SUPABASE_SECRET_KEY")
           or os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
    q = (f"{url}/rest/v1/plugin_registry?owner=eq.{OWNER}"
         f"&select=name,version,enabled,manifest&order=name")
    req = urllib.request.Request(
        q, headers={"apikey": key, "Authorization": f"Bearer {key}"})
    return json.loads(OPENER.open(req, timeout=30).read())


if fase == "1":
    print("== FASE 1: install + bukti baris DB ==")
    st, d = api("POST", "/plugins/install", {"manifest": {
        "name": NAMA, "version": "3.3.3", "entry": "main:run",
        "capabilities": ["kv", "log"], "author": "DurabilityTest",
        "description": "plugin uji durability lintas restart"}})
    print("install HTTP", st, json.dumps(d)[:160])
    assert st == 200, "install gagal"

    rows = db_rows()
    print("baris DB plugin_registry:", json.dumps(rows, indent=1)[:400])
    hit = [r for r in rows if r["name"] == NAMA]
    assert hit, f"{NAMA} TIDAK ada di DB -> tidak durable"
    assert hit[0]["version"] == "3.3.3"
    assert hit[0]["manifest"]["capabilities"] == ["kv", "log"]
    print(f"BUKTI: {NAMA} v{hit[0]['version']} tersimpan di DB "
          f"(enabled={hit[0]['enabled']})")
    print("LANGKAH BERIKUT: restart server, lalu jalankan fase 2.")
else:
    print("== FASE 2: verifikasi setelah restart ==")
    st, d = api("GET", "/plugins")
    names = [p["name"] for p in d.get("plugins", [])]
    print("HTTP", st, "plugins:", names)
    assert NAMA in names, f"{NAMA} HILANG setelah restart -> TIDAK durable"
    pl = [p for p in d["plugins"] if p["name"] == NAMA][0]
    assert pl["version"] == "3.3.3", pl
    assert pl["enabled"] is True
    assert sorted(pl["capabilities"]) == ["kv", "log"]
    print(f"BUKTI: {NAMA} v{pl['version']} PULIH setelah restart "
          f"(enabled={pl['enabled']}, caps={pl['capabilities']})")

    # bersihkan supaya tidak mengotori run berikutnya
    st2, _ = api("DELETE", f"/plugins/{NAMA}")
    print("cleanup delete HTTP", st2)
print("OK")
