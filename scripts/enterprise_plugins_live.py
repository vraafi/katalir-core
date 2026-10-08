# CATATAN: jalankan dari ROOT repo (butuh .autonomous_jwt + .env):
#   python scripts/enterprise_plugins_live.py
# Prasyarat: server uvicorn lokal di port 8123 + token dari
#   python scripts/autonomous_login.py  (atau mk_session.py)
"""Hard test LIVE untuk FITUR #11 (Plugin/Extension System).

Menguji endpoint nyata di server yang berjalan (bukan in-process), dengan
token Supabase asli. Semua klaim = kode status + isi respons mentah.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

BASE = os.getenv("BASE", "http://localhost:8123")
TOK = open(".autonomous_jwt", encoding="utf-8").read().strip()

# WAJIB: lingkungan ini menyetel HTTP_PROXY (proxy sandbox). Tanpa bypass,
# permintaan ke 127.0.0.1 ikut dibelokkan ke proxy -> 502 "upstream connect
# failed". Opener tanpa ProxyHandler memaksa koneksi langsung ke localhost.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

HASIL: list[tuple[str, bool, str]] = []


def call(method: str, path: str, body: dict | None = None, auth: bool = True):
    data = json.dumps(body).encode() if body is not None else None
    hdr = {"Content-Type": "application/json"}
    if auth:
        hdr["Authorization"] = f"Bearer {TOK}"
    req = urllib.request.Request(BASE + path, data=data, headers=hdr, method=method)
    try:
        r = _OPENER.open(req, timeout=60)
        return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, {"raw": raw[:300].decode("utf-8", "replace")}


def check(nama: str, ok: bool, detail: str) -> None:
    HASIL.append((nama, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} | {nama} | {detail}")


def man(name, caps=None, ver="1.0.0", minv="", deps=None):
    return {"manifest": {"name": name, "version": ver, "entry": "main:run",
                         "capabilities": caps or [], "dependencies": deps or {},
                         "min_katalir_version": minv, "author": "Acme",
                         "description": "plugin uji"}}


print("=" * 78)
print("HARD TEST LIVE — FITUR #11 PLUGIN SYSTEM")
print("=" * 78)

# 1. Auth wajib
st, _ = call("GET", "/plugins", auth=False)
check("01 auth wajib (tanpa token)", st == 401, f"HTTP {st}")

# 2. Daftar plugin (ada contoh bawaan)
st, d = call("GET", "/plugins")
names = [p["name"] for p in d.get("plugins", [])]
check("02 daftar plugin + contoh bawaan", st == 200 and "katalir.sample" in names,
      f"HTTP {st} plugins={names}")

# 3. Capability aman vs terlarang
st, d = call("GET", "/plugins/capabilities")
check("03 capability policy",
      st == 200 and "http" in d.get("safe", []) and "secrets" in d.get("forbidden", []),
      f"HTTP {st} safe={len(d.get('safe', []))} forbidden={len(d.get('forbidden', []))}")

# 4. Install valid
st, d = call("POST", "/plugins/install", man("acme.http", ["http"]))
check("04 install plugin valid", st == 200 and d.get("enabled") is True,
      f"HTTP {st} {json.dumps(d)[:120]}")

# 5. Capability TERLARANG -> 403 (fail-closed)
st, d = call("POST", "/plugins/install", man("evil.secrets", ["secrets"]))
check("05 capability terlarang diblokir 403", st == 403,
      f"HTTP {st} {json.dumps(d)[:120]}")

# 6. Capability tak dikenal -> 400
st, d = call("POST", "/plugins/install", man("acme.weird", ["teleport"]))
check("06 capability tak dikenal ditolak 400", st == 400,
      f"HTTP {st} {json.dumps(d)[:120]}")

# 7. Nama plugin invalid -> 400
st, d = call("POST", "/plugins/install", man("x", ["http"]))
check("07 nama invalid ditolak 400", st == 400, f"HTTP {st} {json.dumps(d)[:100]}")

# 8. Call capability yang dideklarasikan -> 200
st, d = call("POST", "/plugins/acme.http/call", {"capability": "http", "args": {"url": "https://x.test"}})
check("08 call capability diizinkan", st == 200 and d.get("result", {}).get("dry_run") is True,
      f"HTTP {st} {json.dumps(d.get('result'))[:120]}")

# 9. Call capability TIDAK dideklarasikan -> 403 (sandbox)
st, d = call("POST", "/plugins/acme.http/call", {"capability": "kv", "args": {"key": "a"}})
check("09 call capability tak dideklarasikan 403", st == 403,
      f"HTTP {st} {json.dumps(d)[:120]}")

# 10. Call capability TERLARANG dari sandbox -> 403
st, d = call("POST", "/plugins/acme.http/call", {"capability": "secrets", "args": {}})
check("10 call capability terlarang 403", st == 403,
      f"HTTP {st} {json.dumps(d)[:120]}")

# 11. Enable/disable berpengaruh ke pemanggilan
st, _ = call("POST", "/plugins/acme.http/enable", {"enabled": False})
st2, d2 = call("POST", "/plugins/acme.http/call", {"capability": "http", "args": {}})
check("11 disable -> call ditolak", st == 200 and st2 == 400,
      f"enable HTTP {st}; call HTTP {st2} {json.dumps(d2)[:100]}")
call("POST", "/plugins/acme.http/enable", {"enabled": True})

# 12. Marketplace search
st, d = call("GET", "/plugins/search?q=sample")
check("12 search marketplace", st == 200 and any(r["name"] == "katalir.sample" for r in d.get("results", [])),
      f"HTTP {st} results={[r['name'] for r in d.get('results', [])]}")

# 13. Manifest
st, d = call("GET", "/plugins/acme.http/manifest")
check("13 ambil manifest", st == 200 and d.get("manifest", {}).get("name") == "acme.http",
      f"HTTP {st} {json.dumps(d.get('manifest'))[:120]}")

# 14. Inkompatibel versi platform -> 409
st, d = call("POST", "/plugins/install", man("acme.future", ["http"], minv="99.0.0"))
check("14 versi platform tak kompatibel 409", st == 409, f"HTTP {st} {json.dumps(d)[:100]}")

# 15. Dependensi hilang -> 409
st, d = call("POST", "/plugins/install", man("acme.dep", ["http"], deps={"ghost": "^1.0.0"}))
check("15 dependensi hilang 409", st == 409, f"HTTP {st} {json.dumps(d)[:110]}")

# 16. Review: submit -> approve
st, d = call("POST", "/plugins/reviews", {"manifest": {"name": "acme.rev", "version": "1.0.0",
                                                       "entry": "m:r", "capabilities": ["log"],
                                                       "author": "Acme", "description": "ok"}})
rid = d.get("review", {}).get("request_id")
st2, d2 = call("POST", f"/plugins/reviews/{rid}/approve", {"reviewer": "qa@katalir"})
check("16 review submit + approve", st == 200 and st2 == 200 and d2.get("review", {}).get("status") == "approved",
      f"HTTP {st}/{st2} rid={rid} status={d2.get('review', {}).get('status')}")

# 17. Review dengan pelanggaran -> approve diblokir 403
st, d = call("POST", "/plugins/reviews", {"manifest": {"name": "evil.rev", "version": "1.0.0",
                                                       "entry": "m:r", "capabilities": ["db"]}})
rid2 = d.get("review", {}).get("request_id")
st2, d2 = call("POST", f"/plugins/reviews/{rid2}/approve", {"reviewer": "qa@katalir"})
check("17 approve plugin berpelanggaran 403", st == 200 and st2 == 403,
      f"submit HTTP {st} approve HTTP {st2} {json.dumps(d2)[:100]}")

# 18. Reject
st, d = call("POST", "/plugins/reviews", {"manifest": {"name": "acme.rev2", "version": "1.0.0",
                                                       "entry": "m:r", "capabilities": []}})
rid3 = d.get("review", {}).get("request_id")
st2, d2 = call("POST", f"/plugins/reviews/{rid3}/reject", {"reviewer": "qa@katalir", "reason": "kebijakan"})
check("18 review reject", st2 == 200 and d2.get("review", {}).get("status") == "rejected",
      f"HTTP {st2} status={d2.get('review', {}).get('status')}")

# 19. Stats + audit
st, d = call("GET", "/plugins/stats")
st2, d2 = call("GET", "/plugins/audit")
aksi = {a["action"] for a in d2.get("audit", [])}
check("19 stats + audit terisi", st == 200 and st2 == 200 and "install_blocked" in aksi,
      f"stats={json.dumps(d.get('stats'))} aksi={sorted(aksi)}")

# 20. Uninstall -> 200 lalu 404 saat manifest
st, _ = call("DELETE", "/plugins/acme.http")
st2, _ = call("GET", "/plugins/acme.http/manifest")
check("20 uninstall lalu 404", st == 200 and st2 == 404, f"delete HTTP {st}; manifest HTTP {st2}")

# 21. Uninstall plugin tak ada -> 404
st, _ = call("DELETE", "/plugins/ghost.plugin")
check("21 uninstall tak ada 404", st == 404, f"HTTP {st}")

# 22. REGRESI /version -> 27/27 fitur
st, d = call("GET", "/version")
check("22 /version 27/27 fitur", st == 200 and d.get("features_present") == 27 == d.get("features_total"),
      f"HTTP {st} present={d.get('features_present')}/{d.get('features_total')}")

# 23. REGRESI /metrics (fitur #3)
req = urllib.request.Request(BASE + "/metrics", headers={"Authorization": f"Bearer {TOK}"})
try:
    r = _OPENER.open(req, timeout=30)
    body = r.read().decode()
    ok = r.status == 200 and "# TYPE" in body
    check("23 regresi /metrics prometheus", ok, f"HTTP {r.status} bytes={len(body)}")
except urllib.error.HTTPError as e:
    check("23 regresi /metrics prometheus", False, f"HTTP {e.code}")

print("=" * 78)
lolos = sum(1 for _, ok, _ in HASIL if ok)
print(f"RINGKASAN: {lolos}/{len(HASIL)} skenario LIVE lolos")
print("=" * 78)
if lolos != len(HASIL):
    raise SystemExit(1)
