# tests/test_csp_headers.py — CSP `_headers` (fix analitik Cloudflare, 8 Okt 2026)
# =====================================================================
# MENGAPA TES INI ADA
#   CSP situs memblokir beacon `static.cloudflareinsights.com`, sehingga
#   Cloudflare Web Analytics TIDAK PERNAH berjalan di produksi. Setiap
#   pemuatan halaman mencatat satu pelanggaran CSP di Console, dan dashboard
#   analitik tetap kosong.
#
#   Memperbaiki satu baris di `_headers` itu mudah; yang sulit adalah
#   memastikan perbaikannya (a) tidak dihapus orang lain, dan (b) tidak
#   "diperbaiki" dengan cara yang menghancurkan CSP — mis. menambahkan `https:`
#   atau `*` ke `script-src`, yang praktis mematikan perlindungan XSS.
#
#   Tes ini membaca berkas NYATA `nexus-frontend/public/_headers`, bukan
#   salinan nilai di dalam tes. Kalau produksi memakai nilai lain dari yang
#   ada di berkas ini, tes tidak akan menangkapnya — itu sebabnya
#   `tests/test_csp_production.py` membandingkan header PRODUKSI dengan
#   berkas ini.
#
# CATATAN: `output: "export"` membuat `headers()` di next.config.ts DIABAIKAN
# Next.js untuk aset statis (dibuktikan dengan peringatan
# `export-no-custom-routes`). Sumber kebenaran header produksi = berkas ini,
# yang disalin `public/` -> `out/` lalu dibaca Cloudflare Pages.
# =====================================================================
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HEADERS = ROOT / "nexus-frontend" / "public" / "_headers"

#: Host yang WAJIB ada supaya beacon Cloudflare bisa jalan.
#: Diambil dari Cloudflare docs ("Web Analytics":
#: `script-src static.cloudflareinsights.com; connect-src cloudflareinsights.com`)
#: DAN diverifikasi terhadap artefak nyata di produksi:
#:   - src skrip beacon : https://static.cloudflareinsights.com/beacon.min.js/v...
#:   - endpoint POST    : https://cloudflareinsights.com/cdn-cgi/rum
BEACON_SCRIPT_HOST = "https://static.cloudflareinsights.com"
BEACON_CONNECT_HOST = "https://cloudflareinsights.com"

#: Token yang sah sebagai sumber CSP. Selain ini -> sintaks salah.
_KEYWORD = re.compile(r"^'(self|none|unsafe-inline|unsafe-eval|strict-dynamic|"
                      r"unsafe-hashes|report-sample|inline-speculation-rules|"
                      r"wasm-unsafe-eval)'$")
_SCHEME_SOURCE = re.compile(r"^[a-z][a-z0-9+.\-]*:$", re.I)
_HOST_SOURCE = re.compile(
    r"^[a-z][a-z0-9+.\-]*://"                     # skema eksplisit
    r"(\*\.)?[a-z0-9]([a-z0-9\-]*[a-z0-9])?"
    r"(\.[a-z0-9]([a-z0-9\-]*[a-z0-9])?)*"        # host
    r"(:\d+)?$", re.I)
_SCHEMELESS_HOST = re.compile(
    r"^(\*\.)?[a-z0-9]([a-z0-9\-]*[a-z0-9])?"
    r"(\.[a-z0-9]([a-z0-9\-]*[a-z0-9])?)*$", re.I)
_DATA_BLOB = re.compile(r"^(data|blob|mediastream|filesystem):$", re.I)
_HASH = re.compile(r"^'(sha256|sha384|sha512)-[A-Za-z0-9+/=]+'$")
_NONCE = re.compile(r"^'nonce-[A-Za-z0-9+/=]+'$")


def _read_headers() -> str:
    assert HEADERS.is_file(), f"berkas CSP tidak ada: {HEADERS}"
    return HEADERS.read_text(encoding="utf-8")


def _parse_csp() -> dict[str, list[str]]:
    """Kembalikan {direktif: [sumber, ...]} dari baris CSP di `_headers`."""
    teks = _read_headers()
    m = re.search(r"^\s*Content-Security-Policy:\s*(.+?)\s*$", teks, re.M)
    assert m, "tidak ada direktif Content-Security-Policy di _headers"
    out: dict[str, list[str]] = {}
    for bagian in m.group(1).split(";"):
        bagian = bagian.strip()
        if not bagian:
            continue
        nama, _, sisa = bagian.partition(" ")
        out[nama.strip().lower()] = sisa.split()
    return out


@pytest.fixture(scope="module")
def csp() -> dict[str, list[str]]:
    return _parse_csp()


# ---------------------------------------------------------------------------
# 1. Header-nya ENFORCING, bukan Report-Only
# ---------------------------------------------------------------------------
def _direktif_aktif(teks: str) -> list[str]:
    """Baris direktif yang BENAR-BENAR dibaca Cloudflare (bukan komentar).

    Menyaring komentar itu wajib, bukan kerapian: berkas ini memuat riwayat
    yang MENYEBUT `Content-Security-Policy-Report-Only` sebagai penjelasan.
    Pencocokan teks mentah akan menganggap riwayat itu sebagai kebijakan aktif.
    """
    return [
        l.strip() for l in teks.splitlines()
        if l[:1].isspace() and not l.strip().startswith("#")
        and re.match(r"^[A-Za-z-]+:", l.strip())
    ]


def test_csp_enforcing_bukan_report_only():
    teks = _read_headers()
    aktif = _direktif_aktif(teks)
    print("[1] direktif aktif:", [d.split(":", 1)[0] for d in aktif])
    assert not [d for d in aktif
                if d.lower().startswith("content-security-policy-report-only")], (
        "CSP turun kembali ke Report-Only: pelanggaran TIDAK lagi diblokir, "
        "jadi analitik 'jalan' tapi tidak ada yang ditegakkan.")
    assert [d for d in aktif
            if d.lower().startswith("content-security-policy:")], \
        "tidak ada Content-Security-Policy enforcing"
    # Riwayat boleh menyebut Report-Only, tapi hanya di dalam komentar.
    for l in teks.splitlines():
        if "Report-Only" in l and not l.strip().startswith("#"):
            raise AssertionError(
                f"Report-Only muncul di baris non-komentar: {l!r}")


# ---------------------------------------------------------------------------
# 2. INTI PERBAIKAN: dua host beacon ada di direktif yang BENAR
# ---------------------------------------------------------------------------
def test_beacon_script_diizinkan_di_script_src(csp):
    src = csp.get("script-src", [])
    print(f"[2] script-src = {src}")
    assert BEACON_SCRIPT_HOST in src, (
        f"{BEACON_SCRIPT_HOST} harus ada di script-src; kalau tidak, "
        f"beacon Cloudflare diblokir dan analitik mati.")
    # Kalau host salah taruh (mis. di connect-src saja), beacon tetap gagal.
    assert BEACON_SCRIPT_HOST not in csp.get("connect-src", []), (
        "host skrip beacon tidak perlu ada di connect-src")


def test_beacon_post_diizinkan_di_connect_src(csp):
    con = csp.get("connect-src", [])
    print(f"[2] connect-src = {con}")
    assert BEACON_CONNECT_HOST in con, (
        f"{BEACON_CONNECT_HOST} harus ada di connect-src; beacon POST ke "
        f"{BEACON_CONNECT_HOST}/cdn-cgi/rum, jadi tanpa ini skrip termuat "
        f"tetapi datanya tidak pernah terkirim.")


def test_host_analitik_ditulis_eksplisit_bukan_wildcard(csp):
    for direk in ("script-src", "connect-src"):
        for sumber in csp.get(direk, []):
            assert not sumber.startswith("*"), \
                f"wildcard '{sumber}' di {direk} terlalu luas"
            assert "*.cloudflareinsights.com" != sumber, (
                "pakai host eksplisit; wildcard subdomain memperluas "
                "permukaan tanpa manfaat")


# ---------------------------------------------------------------------------
# 3. CSP TIDAK boleh dilonggarkan demi memperbaiki ini
# ---------------------------------------------------------------------------
def test_tidak_ada_unsafe_eval(csp):
    semua = [s for v in csp.values() for s in v]
    print("[3] unsafe-eval hadir?", "any" if any("unsafe-eval" in s for s in semua)
          else "tidak")
    assert not any("unsafe-eval" in s for s in semua), (
        "unsafe-eval tidak dibutuhkan beacon Cloudflare maupun Next.js "
        "produksi; menambahkannya membuka jalan XSS.")


def test_script_src_tidak_pakai_skema_luas(csp):
    """`https:` atau `*` di script-src = CSP praktis mati terhadap XSS."""
    for sumber in csp.get("script-src", []):
        assert sumber not in ("*", "https:", "http:", "data:", "blob:"), (
            f"'{sumber}' di script-src mengizinkan skrip dari host mana pun")
        assert not sumber.startswith("*."), (
            f"'{sumber}' wildcard di script-src terlalu luas")


def test_default_src_tidak_dilonggarkan(csp):
    assert csp.get("default-src") == ["'self'"], (
        "default-src harus tetap 'self' — ia pagar terakhir untuk direktif "
        "yang tidak ditulis eksplisit")
    assert csp.get("object-src") == ["'none'"]
    assert csp.get("base-uri") == ["'self'"]
    assert csp.get("frame-ancestors") == ["'none'"]
    assert csp.get("form-action") == ["'self'"]


def test_host_lama_tidak_hilang(csp):
    """Perbaikan tidak boleh menghapus host yang sudah bekerja."""
    con = csp.get("connect-src", [])
    img = csp.get("img-src", [])
    assert "https://web-production-dc90b.up.railway.app" in con, \
        "backend Railway hilang dari connect-src -> /chat tidak bisa memanggil API"
    assert "https://qmukkphwaajzbqjrcvaz.supabase.co" in con, \
        "Supabase hilang dari connect-src -> login mati"
    assert "wss://qmukkphwaajzbqjrcvaz.supabase.co" in con, \
        "WebSocket Supabase hilang -> realtime mati"
    assert "https://lh3.googleusercontent.com" in img, \
        "avatar Google hilang -> regresi 2026-10-02 kembali"
    assert "https://avatars.githubusercontent.com" in img, \
        "avatar GitHub hilang -> regresi 2026-10-02 kembali"


# ---------------------------------------------------------------------------
# 4. Validasi SINTAKS setiap token sumber
# ---------------------------------------------------------------------------
def test_semua_token_sumber_sintaksnya_sah(csp):
    """Token yang tidak dikenali browser diabaikan DIAM-DIAM.

    Ini bahaya nyata: salah tulis `https://static.cloudflareinsights.com/`
    (dengan garis miring di akhir) atau menambah koma membuat browser
    mengabaikan token itu tanpa error — CSP terlihat "sudah diperbaiki"
    padahal beacon tetap diblokir.
    """
    buruk: list[str] = []
    for direk, sumber_list in csp.items():
        for s in sumber_list:
            if (_KEYWORD.match(s) or _SCHEME_SOURCE.match(s)
                    or _HOST_SOURCE.match(s) or _SCHEMELESS_HOST.match(s)
                    or _DATA_BLOB.match(s) or _HASH.match(s)
                    or _NONCE.match(s) or s == "'unsafe-inline'"):
                continue
            buruk.append(f"{direk}: {s!r}")
    print(f"[4] token diperiksa = {sum(len(v) for v in csp.values())}, "
          f"tidak sah = {len(buruk)}")
    assert not buruk, f"token sumber tidak sah (diabaikan browser): {buruk}"


def test_tidak_ada_karakter_terlarang(csp):
    teks = _read_headers()
    m = re.search(r"^\s*Content-Security-Policy:\s*(.+?)\s*$", teks, re.M)
    nilai = m.group(1)
    for ch, nama in ((",", "koma (pemisah harus titik-koma)"),
                     ("\t", "tab")):
        assert ch not in nilai, f"nilai CSP memuat {nama}"
    # Garis miring di akhir host membuat token diabaikan browser.
    for sumber in nilai.split():
        assert not sumber.endswith("/"), \
            f"sumber '{sumber}' berakhir '/' -> diabaikan browser"


# ---------------------------------------------------------------------------
# 5. Berkas `_headers` masih berbentuk sah untuk Cloudflare Pages
# ---------------------------------------------------------------------------
def test_format_headers_sah():
    teks = _read_headers()
    baris = teks.splitlines()
    blok = [i for i, l in enumerate(baris) if l.strip() and not l.startswith("#")]
    print(f"[5] baris non-komentar = {len(blok)}; baris /* = "
          f"{sum(1 for l in baris if l.strip() == '/*')}")
    assert sum(1 for l in baris if l.strip() == "/*") >= 1, "tidak ada blok /*"
    # Setiap baris header HARUS menjorok (Cloudflare membaca indentasi sebagai
    # penanda 'ini header dari aturan di atasnya').
    for i, l in enumerate(baris):
        if not l.strip() or l.startswith("#") or l.strip() == "/*":
            continue
        if re.match(r"^\s*\S+:", l) and not l[0].isspace() and \
                not l.startswith("/"):
            # Baris `/*` atau pola path boleh di kolom 0; header tidak.
            raise AssertionError(f"baris {i+1} tidak menjorok: {l!r}")
    # Header di dalam blok harus punya indentasi dua spasi.
    for l in baris:
        if re.match(r"^\s+[A-Za-z-]+:", l):
            assert l.startswith("  "), f"indentasi header aneh: {l!r}"


def test_komentar_yatim_tidak_kembali():
    """Regresi higiene: potongan komentar lama pernah terselip di blok header."""
    teks = _read_headers()
    m = re.search(r"^/\*\n(.*?)\n\s*$", teks, re.M | re.S)
    if not m:
        pytest.skip("struktur blok /* tidak terdeteksi")
    for l in m.group(1).splitlines():
        assert not l.strip().startswith("#"), \
            f"komentar terselip di dalam blok header: {l!r}"
