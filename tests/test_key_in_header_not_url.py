"""test_key_in_header_not_url.py - Kunci API tidak boleh ikut di query string URL.

Kelas bug yang dijaga (temuan keamanan 2026-09-18): kunci Gemini dikirim sebagai
`?key=<API_KEY>` di URL, sehingga kunci tercetak ke log siapa pun yang mencatat
URL (terbukti: 1651 baris `?key=` di log container gateway, 2026-09-14..17).
Cara yang didokumentasikan Google adalah header `x-goog-api-key`.

Kontrak yang dikunci di sini (murni statis, tanpa jaringan):
  1. tidak ada kode Python terlacak yang MEMBANGUN URL ber-kunci;
  2. klien Gemini di repo ini memakai SDK dengan `api_key=` (SDK kirim header);
  3. jalur gateway di `api_server.py` mengautentikasi lewat HEADER.

KENAPA AST, BUKAN GREP: percobaan pertama memakai regex atas teks dan langsung
memberi false positive pada DOCSTRING yang mengutip bukti lama
(`test_gemini_key_pool.py`: "`x-goog-api-key` 200 dan `?key=` 200 ..."). Yang
berbahaya secara nyata hanyalah kunci yang benar-benar DIRAKIT ke URL, yaitu:
  * f-string yang memuat query ber-key,
  * konkatenasi string yang memuat query ber-key,
  * literal kunci panjang yang ditempel langsung ke URL.
Docstring/prosa tidak pernah cocok karena tidak menginterpolasi nilai kunci.

CATATAN CAKUPAN: 4 situs `?key=` yang dipindahkan ke header berada di gateway VPS
(`/opt/free-llm-gateway/providers.py`, `health.py`, `config.py`) yang BUKAN bagian
repo ini, jadi tidak bisa diperiksa unit test lokal. Verifikasinya lewat SSH +
grep container (bukti ada di laporan task): 0 situs `?key=` tersisa.
"""

import ast
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP_PREFIX = "_"  # skrip scratch (gitignored) tidak ikut dinilai
KEY_QUERY = re.compile(r"[?&][^\"'\s]*key=")
LITERAL_KEY_IN_URL = re.compile(r"[?&][^\"'\s]*key=(AIza|AQ\.)")


def _tracked_py():
    out = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True
    )
    assert out.returncode == 0, "gagal menjalankan git ls-files: %s" % out.stderr
    files = []
    for line in out.stdout.splitlines():
        p = pathlib.Path(line.strip())
        if not line.strip() or p.name.startswith(SKIP_PREFIX):
            continue
        files.append(p)
    return files


def _urls_with_key_in_code(src):
    """Cari URL ber-kunci yang benar-benar DIRAKIT kode (bukan dokumentasi)."""
    hits = []
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):  # f-string
            text = "".join(
                v.value for v in node.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)
            )
            if KEY_QUERY.search(text):
                hits.append("f-string: %s" % text.strip()[:80])
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            parts = [n for n in ast.walk(node)
                     if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            text = "".join(p.value for p in parts)
            if KEY_QUERY.search(text):
                hits.append("konkatenasi: %s" % text.strip()[:80])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if LITERAL_KEY_IN_URL.search(node.value):
                hits.append("literal: %s" % node.value.strip()[:80])
    return hits


def test_tidak_ada_kode_membangun_url_ber_kunci():
    offenders = []
    for rel in _tracked_py():
        # `utf-8-sig`, bukan `utf-8`: beberapa file .py di repo ini punya BOM
        # UTF-8 (mis. tests/test_self_healing.py, sudah committed). Dengan
        # `utf-8` + errors="replace", BOM-nya jadi karakter U+FEFF di awal
        # sumber dan `ast.parse` di bawah melempar SyntaxError. Akibatnya guard
        # ini CRASH, bukan menolak - jadi file yang melanggar aturan tidak pernah
        # benar-benar diperiksa. `utf-8-sig` membuang BOM bila ada dan tetap
        # aman untuk file tanpa BOM.
        src = (ROOT / rel).read_text(encoding="utf-8-sig", errors="replace")
        for hit in _urls_with_key_in_code(src):
            offenders.append("%s: %s" % (rel.as_posix(), hit))
    assert not offenders, (
        "kode membangun URL dengan kunci di query string (harus pindah ke header "
        "`x-goog-api-key`): %s" % offenders
    )


def test_klien_gemini_pakai_api_key_lewat_sdk():
    """SDK `genai.Client(api_key=...)` mengirim header, bukan URL."""
    src = (ROOT / "gemini_key_pool.py").read_text(encoding="utf-8")
    assert "genai.Client(" in src, "pembuatan klien Gemini tidak ditemukan"
    assert "api_key=key" in src, (
        "klien Gemini tidak menerima `api_key=`; jalur header tidak terpakai"
    )
    assert not _urls_with_key_in_code(src), (
        "gemini_key_pool.py membangun URL ber-kunci (bocor ke log)"
    )


def test_jalur_gateway_di_api_server_pakai_header_authorization():
    """Autentikasi ke gateway = header `Authorization: Bearer`, bukan URL."""
    src = (ROOT / "api_server.py").read_text(encoding="utf-8")
    assert "Authorization" in src, "api_server tidak mengirim Authorization ke gateway"
    assert not _urls_with_key_in_code(src), (
        "api_server.py membangun URL ber-kunci (bocor ke log)"
    )
