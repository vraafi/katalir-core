# tests/test_code_sandbox.py — Fitur #6 (8 Okt 2026)
# =====================================================================
# Hard test Code Node (Sandbox). 13 skenario (brief minta min 12).
#
# Yang diuji (BUKTI raw output, bukan asumsi):
#   1   kode Python valid berjalan & hasil terbaca
#   2   output print tertangkap
#   3   AST: `import os` DITOLAK
#   4   AST: `import subprocess` DITOLAK
#   5   AST: `open()` (akses filesystem) DITOLAK
#   6   AST: `eval()` DITOLAK
#   7   AST: `exec()` DITOLAK
#   8   AST: `__import__()` DITOLAK
#   9   AST: escape lewat atribut (`__subclasses__`/`__globals__`) DITOLAK
#   10  AST: `os.system()`/`subprocess` lewat atribut DITOLAK
#   11  TIMEOUT: infinite loop DIBUNUH (hard kill), bukan menggantung
#   12  Batas & validasi: kode kosong, bahasa ngawur, kode → error runtime
#   13  Isolasi: proses sandbox tidak bisa mengubah variabel proses induk;
#       batas 30s/128MB dilaporkan apa adanya (capabilities)
# =====================================================================
import os
import time

import pytest

import code_sandbox as cs


# ---------------------------------------------------------------------------
# 1. Kode valid berjalan
# ---------------------------------------------------------------------------
def test_01_kode_valid_berjalan():
    r = cs.execute("result = sum([x * x for x in range(10)])")
    print(f"[1] ok={r['ok']} result={r['result']} durasi={r['duration_s']}s "
          f"os_limits={r['os_limits']}")
    assert r["ok"] is True, r["error"]
    assert r["result"] == 285            # 0+1+4+...+81
    assert r["duration_s"] > 0
    assert r["language"] == "python"


# ---------------------------------------------------------------------------
# 2. Output print tertangkap
# ---------------------------------------------------------------------------
def test_02_output_print_tertangkap():
    r = cs.execute("print('halo dari sandbox')\nresult = 42")
    print(f"[2] stdout={r['stdout'].strip()!r} result={r['result']}")
    assert r["ok"] is True, r["error"]
    assert "halo dari sandbox" in r["stdout"]
    assert r["result"] == 42


# ---------------------------------------------------------------------------
# 3-10. AST menolak operasi berbahaya (satu tes per kelas serangan)
# ---------------------------------------------------------------------------
def test_03_import_os_ditolak():
    r = cs.execute("import os\nresult = os.getcwd()")
    print(f"[3] ok={r['ok']} error={r['error']}")
    assert r["ok"] is False
    assert "import" in r["error"]


def test_04_import_subprocess_ditolak():
    r = cs.execute("import subprocess\nresult = subprocess.run(['ls'])")
    print(f"[4] ok={r['ok']} error={r['error']}")
    assert r["ok"] is False
    assert "import" in r["error"]


def test_05_akses_filesystem_ditolak():
    r = cs.execute("result = open('/etc/passwd').read()")
    print(f"[5] ok={r['ok']} error={r['error']}")
    assert r["ok"] is False
    assert "open" in r["error"]


def test_06_eval_ditolak():
    r = cs.execute("result = eval('1+1')")
    print(f"[6] ok={r['ok']} error={r['error']}")
    assert r["ok"] is False
    assert "eval" in r["error"]


def test_07_exec_ditolak():
    r = cs.execute("exec('x = 1')\nresult = 1")
    print(f"[7] ok={r['ok']} error={r['error']}")
    assert r["ok"] is False
    assert "exec" in r["error"]


def test_08_dunder_import_ditolak():
    r = cs.execute("mod = __import__('os')\nresult = mod.getcwd()")
    print(f"[8] ok={r['ok']} error={r['error']}")
    assert r["ok"] is False
    assert "__import__" in r["error"]


def test_09_escape_atribut_ditolak():
    serangan = [
        "result = (1).__class__.__subclasses__()",
        "result = (lambda: 0).__globals__",
        "result = ''.__class__.__mro__",
        "result = {}.__class__.__bases__",
    ]
    for kode in serangan:
        r = cs.execute(kode)
        print(f"[9] {kode[:45]!r:48} -> ok={r['ok']} err={str(r['error'])[:55]}")
        assert r["ok"] is False, f"TIDAK DIBLOKIR: {kode}"
        assert "atribut" in r["error"] or "RestrictedPython" in r["error"]


def test_10_pemanggilan_os_system_ditolak():
    serangan = [
        "import os; os.system('echo pwned')",
        "result = __import__('subprocess').check_output(['whoami'])",
        "result = getattr(__import__('os'), 'system')('echo x')",
    ]
    for kode in serangan:
        r = cs.execute(kode)
        print(f"[10] {kode[:45]!r:48} -> ok={r['ok']} err={str(r['error'])[:55]}")
        assert r["ok"] is False, f"TIDAK DIBLOKIR: {kode}"


# ---------------------------------------------------------------------------
# 11. Timeout: infinite loop dibunuh
# ---------------------------------------------------------------------------
def test_11_infinite_loop_dibunuh():
    t0 = time.monotonic()
    r = cs.execute("while True:\n    pass", timeout_s=3)
    durasi = time.monotonic() - t0
    print(f"[11] ok={r['ok']} killed={r['killed']} error={r['error']} "
          f"durasi_nyata={durasi:.1f}s")
    assert r["ok"] is False
    assert r["killed"] is True, "infinite loop tidak dibunuh!"
    assert "timeout" in r["error"].lower()
    # dibunuh dekat batas, bukan menggantung selamanya
    assert durasi < 15, f"terlalu lama: {durasi:.1f}s"


# ---------------------------------------------------------------------------
# 12. Validasi batas & penanganan error runtime
# ---------------------------------------------------------------------------
def test_12_validasi_dan_error_runtime():
    # kode kosong
    r = cs.execute("")
    print(f"[12] kosong -> ok={r['ok']} err={r['error']}")
    assert r["ok"] is False and "kosong" in r["error"]
    # sintaks rusak
    r = cs.execute("def rusak(:\n  pass")
    print(f"[12] sintaks rusak -> ok={r['ok']} err={str(r['error'])[:60]}")
    assert r["ok"] is False
    # bahasa tidak dikenal
    r = cs.execute("result = 1", language="brainfuck")
    print(f"[12] bahasa ngawur -> ok={r['ok']} err={r['error']}")
    assert r["ok"] is False and "tidak didukung" in r["error"]
    # error runtime (ZeroDivisionError) -> dilaporkan, bukan crash
    r = cs.execute("result = 1 / 0")
    print(f"[12] 1/0 -> ok={r['ok']} err={str(r['error'])[:60]}")
    assert r["ok"] is False
    assert "ZeroDivisionError" in r["error"] or "division" in r["error"]
    # kode non-teks
    r = cs.execute(None)  # type: ignore[arg-type]
    print(f"[12] None -> ok={r['ok']} err={r['error']}")
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 13. Isolasi + capabilities dilaporkan jujur
# ---------------------------------------------------------------------------
def test_13_isolasi_dan_capabilities():
    # kode di sandbox TIDAK bisa mengubah proses induk
    marker = "KATALIR_ISOLATION_MARKER"
    os.environ.pop(marker, None)
    r = cs.execute(
        "import os\nos.environ['KATALIR_ISOLATION_MARKER'] = 'bocor'")
    print(f"[13] import os di sandbox -> ok={r['ok']} err={str(r['error'])[:50]}")
    assert r["ok"] is False
    assert marker not in os.environ, "kebocoran: sandbox mengubah env induk!"

    caps = cs.capabilities()
    print(f"[13] capabilities={caps}")
    assert caps["timeout_s"] == 30
    assert caps["memory_mb"] == 128
    assert "python" in caps["languages"]
    # os_resource_limits TIDAK diklaim benar bila modul resource tidak ada
    try:
        import resource  # noqa: F401
        assert caps["os_resource_limits"] is True
    except ImportError:
        assert caps["os_resource_limits"] is False, (
            "capabilities mengklaim batas OS padahal `resource` tidak ada!")


# ---------------------------------------------------------------------------
# BONUS: JavaScript (dilaporkan apa adanya bila node tidak ada)
# ---------------------------------------------------------------------------
def test_14_javascript_atau_dilaporkan():
    r = cs.execute("const x = [1,2,3].map(n => n*n);\n"
                   "const result = x.reduce((a,b) => a+b, 0);",
                   language="javascript")
    print(f"[14] js available={cs.capabilities()['javascript_available']} "
          f"ok={r['ok']} result={r['result']} err={str(r['error'])[:60]}")
    if cs.capabilities()["javascript_available"]:
        assert r["ok"] is True, r["error"]
        assert r["result"] == 14        # 1+4+9
    else:
        assert r["ok"] is False
        assert "node" in r["error"].lower()
    # JS: pola berbahaya tetap ditolak walau tanpa runtime
    r = cs.execute("const x = require('child_process');", language="javascript")
    print(f"[14] js require() -> ok={r['ok']} err={r['error']}")
    assert r["ok"] is False and "require" in r["error"]
