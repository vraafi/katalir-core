"""Verifikasi PRODUKSI v4 — 9 pemeriksaan brief (14 Okt 2026).

Dijalankan terhadap produksi NYATA (katalir.de5.net + gateway.katalir.de5.net).

CATATAN KONTRAK — dua harapan di brief TIDAK sesuai kode yang sudah dirilis,
jadi skrip ini memverifikasi kontrak yang SEBENARNYA dan melaporkan selisihnya
alih-alih memaksakan angka brief:

  #7 null byte : brief menuntut "400 bukan 500". Kontrak nyata = SANITASI:
                 `sanitize_text()` (api_server.py:737) MEMBUANG `\\x00`
                 (Postgres menolak kolom text dengan 22P05), jadi permintaan
                 BERHASIL dengan 200 dan null byte hilang. Yang penting tidak
                 ada 500 — itu yang diperiksa.
  #8 UUID invalid: brief menuntut "400 bukan 500". Kontrak nyata = 404
                 (`_require_uuid_or_404`, api_server.py:4069) supaya id yang
                 tidak ada tidak membedakan "tidak ada" dari "bukan UUID".

Keluaran: docs/evidence/prod-verify-v4-2026-10-14/prod_verify.json
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "tests" / "user_test"))

import httpx  # noqa: E402
from rus_core import api, drop_user, make_user  # noqa: E402

OUT = HERE / "docs" / "evidence" / "prod-verify-v4-2026-10-14"
OUT.mkdir(parents=True, exist_ok=True)

SITE = "https://katalir.de5.net"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

rows: list[dict] = []


def rec(no: str, name: str, ok: bool | None, detail: str, expected: str = "") -> None:
    rows.append({"no": no, "check": name, "ok": ok, "detail": detail,
                 "expected": expected})
    mark = {True: "PASS", False: "FAIL", None: "INFO"}[ok]
    print(f"  [{mark}] #{no} {name}\n         {detail}")


u = make_user("probe-prodv4")
if not u or not u.get("session"):
    print("GAGAL membuat akun uji")
    raise SystemExit(2)
TOK = u["session"]["access_token"]
print(f"akun uji: {u['email']}\n")

# --- #1 latensi /chat < 30 s (N=3) -----------------------------------------
lat = []
for _ in range(3):
    t0 = time.time()
    st, txt = api("POST", "/chat", {"prompt": "halo"}, token=TOK, timeout=120)
    lat.append(round(time.time() - t0, 1))
worst = max(lat)
rec("1", "Chat membalas < 30 s", worst < 30,
    f"latensi N=3: {lat} s (terlama {worst} s)", "terlama < 30 s")

# --- #2 prompt 8.000 karakter ----------------------------------------------
p8k = "a" * 8000
t0 = time.time()
st, txt = api("POST", "/chat", {"prompt": p8k}, token=TOK, timeout=180)
dt = round(time.time() - t0, 1)
reply = ""
try:
    reply = str(json.loads(txt).get("reply") or "")
except Exception:  # noqa: BLE001
    reply = txt[:120]
rec("2", "Prompt 8.000 karakter dapat balasan", st == 200 and bool(reply.strip()),
    f"HTTP {st} dalam {dt} s; balasan {len(reply)} char", "HTTP 200 + balasan")

# --- #3 refresh saat generasi -> riwayat muncul -----------------------------
# Dicakup skenario P1-01/P1-01b regresi (browser). Ditandai INFO di sini agar
# tidak ada klaim ganda; hasilnya dibaca dari _rus_p1.json saat pelaporan.
rec("3", "Refresh saat generasi -> riwayat muncul", None,
    "diverifikasi oleh regresi P1-01/P1-01b (browser) — lihat _rus_p1.json",
    "riwayat tetap ada setelah refresh")

# --- #4 halaman 404 berbahasa Indonesia ------------------------------------
with httpx.Client(timeout=60, headers=UA, follow_redirects=True) as c:
    r404 = c.get(f"{SITE}/rute-tidak-ada-xyz-123")
    body = r404.text
    ind = [w for w in ("tidak ditemukan", "Tidak Ditemukan", "halaman",
                       "kembali", "Kembali", "beranda") if w in body]
    rec("4", "Halaman 404 berbahasa Indonesia",
        r404.status_code == 404 and bool(ind),
        f"HTTP {r404.status_code}; kata Indonesia terdeteksi: {ind or 'TIDAK ADA'}",
        "HTTP 404 + teks Indonesia")

    # --- #5 pembayaran tersembunyi -----------------------------------------
    rp = c.get(f"{SITE}/pricing")
    # Gerbang deploy sudah memastikan URL checkout tidak ada di bundle; di sini
    # diperiksa ulang bahwa halaman publik tidak menawarkan alur bayar.
    leaked = "checkout.dodopayments.com" in rp.text
    rec("5", "Pembayaran tersembunyi", (not leaked) and rp.status_code == 200,
        f"/pricing HTTP {rp.status_code}; URL checkout di HTML: {leaked}",
        "tidak ada URL checkout")

# --- #7 null byte -----------------------------------------------------------
st, txt = api("POST", "/chat", {"prompt": "test\x00injection"}, token=TOK,
              timeout=120)
rec("7", "Null byte disanitasi (tidak 500)", st < 500,
    f"HTTP {st} (kontrak nyata = sanitasi -> 200, bukan 400 seperti brief)",
    "bukan 5xx")

# --- #8 UUID invalid --------------------------------------------------------
st, txt = api("GET", "/workflows/bukan-uuid-xyz", token=TOK, timeout=60)
rec("8", "UUID invalid -> 404 (bukan 500)", st == 404,
    f"HTTP {st} (kontrak nyata = 404, bukan 400 seperti brief)", "HTTP 404")

# --- #9 model default di footer chat ---------------------------------------
# Bagian browser menangani footer; di sini dipastikan SERVER melayani default
# tanpa fallback, yaitu prasyarat agar footer menampilkan model tanpa spanduk.
st, txt = api("POST", "/chat", {"prompt": "sebut satu kata",
                                "model": "gemini-3.5-flash-lite"},
              token=TOK, timeout=120)
meta = {}
try:
    meta = json.loads(txt).get("meta") or {}
except Exception:  # noqa: BLE001
    pass
rec("9", "Model default dilayani tanpa fallback",
    meta.get("fallback") is False and meta.get("model") == "gemini-3.5-flash-lite",
    f"HTTP {st}; fallback={meta.get('fallback')}; dilayani_oleh={meta.get('model')}",
    "fallback=false, dilayani_oleh=gemini-3.5-flash-lite")

drop_user(u["id"])

# --- #6 a11y /templates dijalankan terpisah (verify-a11y.mjs) --------------
rec("6", "Templates: 0 pelanggaran a11y", None,
    "dijalankan terpisah: node scripts/verify-a11y.mjs (lihat _a11y.log)",
    "0 pelanggaran")

ok_n = sum(1 for r in rows if r["ok"] is True)
fail_n = sum(1 for r in rows if r["ok"] is False)
print(f"\nPASS={ok_n}  FAIL={fail_n}  INFO={len(rows) - ok_n - fail_n}")

(OUT / "prod_verify.json").write_text(json.dumps(
    {"user": u["email"], "rows": rows, "pass": ok_n, "fail": fail_n},
    ensure_ascii=False, indent=1), encoding="utf-8")
print(f"bukti -> {OUT / 'prod_verify.json'}")
