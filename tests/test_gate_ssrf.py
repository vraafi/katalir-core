"""SSRF harus ditolak DI GERBANG, bukan menunggu error di lapisan alat.

TEMUAN CHAOS TEST (2026-10-06)
`validate_call("http_request", {"url": "...169.254.169.254/latest/meta-data/"})`
mengembalikan **ALLOW**. `tools.http_request` memang menolaknya, jadi tidak ada
permintaan yang keluar — tetapi gerbang seharusnya gagal-tertutup lebih dulu.
Penolakan di lapisan alat muncul sebagai error runtime, bukan keputusan
kebijakan, sehingga tidak terlihat di audit dan tidak seragam.

YANG DIKUNCI
1. Host internal/loopback/metadata DENY di gerbang.
2. Skema non-http(s) DENY di gerbang.
3. Host publik TETAP ALLOW (tidak ada DENY palsu).
4. Alat data-only TIDAK ikut kena pola SSRF — spec workflow yang menyebut
   "localhost" sebagai dokumentasi tidak boleh ditolak.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tool_policy_gate as gate  # noqa: E402

CTX = {"email": "u@katalir.test"}


def _action(tool: str, args: dict) -> str:
    disp, _ = gate.validate_call(tool, args, CTX)
    return str(getattr(disp, "name", disp))


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/admin",
    "http://localhost:8000/admin",
    "http://0.0.0.0:8000/",
    "http://[::1]:8000/",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/internal",
    "http://192.168.1.1/router",
    "http://172.16.0.1/",
    "http://172.31.255.254/",
])
def test_host_internal_ditolak_gerbang(url):
    assert _action("http_request", {"url": url, "method": "GET"}) == "DENY", url


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "gopher://127.0.0.1:70/",
    "ftp://example.com/x",
])
def test_skema_bukan_http_ditolak(url):
    assert _action("http_request", {"url": url, "method": "GET"}) == "DENY", url


@pytest.mark.parametrize("url", [
    "https://api.github.com/repos",
    "https://web-production-dc90b.up.railway.app/health",
    "http://93.184.216.34/",          # IP publik
    "https://example.com/172.16.0.1",  # mirip privat tapi di PATH, bukan host
])
def test_host_publik_tetap_allow(url):
    assert _action("http_request", {"url": url, "method": "GET"}) == "ALLOW", url


def test_tool_data_only_tidak_kena_pola_ssrf():
    """`generate_workflow_json` hanya menyimpan data, bukan memanggil URL."""
    spec = ('{"name":"Alur","nodes":[{"id":"n1","data":{"kind":"mcp",'
            '"config":{"provider":"http","url":"http://localhost:3000/dok"}}}]}')
    assert _action("generate_workflow_json", {"spec": spec}) == "ALLOW"


def test_path_traversal_tetap_ditolak():
    assert _action("baca_google_sheets",
                   {"spreadsheet_id": "../../etc/passwd"}) == "DENY"
