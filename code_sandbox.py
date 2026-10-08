# code_sandbox.py — Fitur #6 (8 Okt 2026)
# ======================================================================
# Code Node (Sandbox): jalankan kode Python TIDAK TEPERCAYA dari node
# workflow, dengan pertahanan BERLAPIS.
#
# RISET (docs/fitur-06-code-sandbox.md):
#   Temuan keamanan penting: CVE-2026-76825 (CVSS 8.4 High) adalah
#   SANDBOX ESCAPE pada RestrictedPython < 8.4 — lewat string.Formatter
#   yang melakukan traversal atribut tanpa melewati safer_getattr.
#   Diperbaiki di 8.4. Versi terpasang di sini: 8.5 -> TIDAK terpengaruh.
#   Ini alasan mengapa "AST saja tidak cukup" diterapkan sebagai prinsip.
#
# TIGA LAPIS (defence in depth):
#   Lapis 1 — AST: `compile_restricted` menolak sintaks berbahaya SEBELUM
#             dieksekusi (import, eval, exec, open, __subclasses__, …).
#             PORTABEL: bekerja sama di Windows & Linux.
#   Lapis 2 — PROSES TERPISAH: kode user tidak pernah berjalan di proses
#             API. Ia hidup di subprocess dengan interpreter bersih.
#   Lapis 3 — BATAS OS (Linux/Railway): `resource.setrlimit` untuk
#             RLIMIT_AS (memori), RLIMIT_CPU, RLIMIT_NOFILE, RLIMIT_FSIZE.
#             Di Windows modul `resource` tidak ada -> lapis ini dilewati
#             dan itu DILAPORKAN di hasil (`os_limits`), tidak disembunyikan.
#   Timeout bekerja di SEMUA platform lewat hard-kill subprocess.
#
# PEMBATASAN YANG DINYATAKAN JUJUR (bukan klaim berlebihan):
#   - "Tanpa jaringan" dijamin oleh Lapis 1 (import socket/urllib dll.
#     ditolak). Bila kelak ada allowlist import, jaringan WAJIB dikunci
#     juga di lapis OS (namespace/iptables) — belum dilakukan di sini.
#   - Batas memori 128 MB ditegakkan OS hanya di Linux. Di Windows batas
#     itu tidak ditegakkan; AST + timeout tetap berlaku.
#
# SEMUA fungsi sinkron (dipakai dari endpoint FastAPI sync).
# ======================================================================

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
import uuid
from typing import Any, Optional

# --- Batas bawaan (sesuai brief) -------------------------------------------
CODE_TIMEOUT_S = 30           # brief: timeout 30s
CODE_MEMORY_MB = 128          # brief: memori 128MB
CODE_MAX_OUTPUT_BYTES = 64_000
CODE_MAX_CODE_BYTES = 100_000

# Bahasa yang didukung.
LANGUAGES = ("python", "javascript")

# Modul yang DILARANG diimpor (kalau kelak ada allowlist impor).
FORBIDDEN_MODULES = frozenset({
    "os", "sys", "subprocess", "shutil", "socket", "ssl", "http", "urllib",
    "urllib2", "urllib3", "requests", "httpx", "ftplib", "smtplib", "telnetlib",
    "ctypes", "cffi", "mmap", "multiprocessing", "threading", "asyncio",
    "importlib", "builtins", "__builtin__", "gc", "inspect", "pickle",
    "marshal", "shelve", "dbm", "sqlite3", "pty", "tty", "termios", "fcntl",
    "resource", "signal", "platform", "tempfile", "glob", "pathlib", "io",
    "code", "codeop", "compileall", "runpy", "pkgutil", "site", "sysconfig",
    "webbrowser", "antigravity", "this", "cgi", "wsgiref", "xmlrpc",
})

# Nama yang tidak boleh muncul sebagai atribut (sumber escape klasik).
FORBIDDEN_ATTRS = frozenset({
    "__subclasses__", "__bases__", "__mro__", "__globals__", "__code__",
    "__closure__", "__func__", "__self__", "__dict__", "__class__",
    "__reduce__", "__reduce_ex__", "__getattribute__", "__subclasshook__",
    "__init_subclass__", "__loader__", "__spec__", "__builtins__",
    "func_globals", "gi_frame", "f_locals", "f_globals", "f_builtins",
    "cr_frame", "cr_globals",
})

# Nama yang boleh dipakai dari builtins (allowlist eksplisit, bukan blocklist).
SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "bool", "bytes", "callable", "chr", "complex",
    "dict", "divmod", "enumerate", "filter", "float", "format", "frozenset",
    "hash", "hex", "id", "int", "isinstance", "issubclass", "iter", "len",
    "list", "map", "max", "min", "next", "oct", "ord", "pow", "range",
    "repr", "reversed", "round", "set", "slice", "sorted", "str", "sum",
    "tuple", "type", "zip",
    # Pengecualian
    "ArithmeticError", "AssertionError", "AttributeError", "Exception",
    "IndexError", "KeyError", "LookupError", "NameError", "RuntimeError",
    "StopIteration", "TypeError", "ValueError", "ZeroDivisionError",
)


class SandboxError(Exception):
    """Kesalahan yang dapat dilaporkan ke pemanggil (bukan crash)."""


# ---------------------------------------------------------------------------
# LAPIS 1 — Validasi AST (portabel, dijalankan di proses API)
# ---------------------------------------------------------------------------

def validate_python(code: str) -> None:
    """Tolak kode yang berbahaya SEBELUM dijalankan.

    Melempar SandboxError dengan alasan yang jelas. Ini lapis pertama dan
    satu-satunya yang portabel — karena itu ia yang paling ketat.
    """
    import ast as _ast

    if not code or not code.strip():
        raise SandboxError("kode kosong")
    if len(code.encode("utf-8")) > CODE_MAX_CODE_BYTES:
        raise SandboxError(
            f"kode terlalu panjang (>{CODE_MAX_CODE_BYTES} byte)")

    try:
        tree = _ast.parse(code)
    except SyntaxError as exc:
        raise SandboxError(f"sintaks tidak valid: {exc.msg} (baris {exc.lineno})")

    for node in _ast.walk(tree):
        # --- import apa pun dilarang (default: tanpa impor) ---------------
        if isinstance(node, _ast.Import):
            nama = ", ".join(a.name.split(".")[0] for a in node.names)
            raise SandboxError(f"import tidak diizinkan: {nama}")
        if isinstance(node, _ast.ImportFrom):
            nama = (node.module or "").split(".")[0]
            raise SandboxError(f"import tidak diizinkan: {nama}")
        # --- panggilan terlarang ------------------------------------------
        if isinstance(node, _ast.Call):
            fn = node.func
            if isinstance(fn, _ast.Name) and fn.id in {
                    "eval", "exec", "compile", "__import__", "open", "input",
                    "globals", "locals", "vars", "dir", "getattr", "setattr",
                    "delattr", "memoryview", "breakpoint", "exit", "quit"}:
                raise SandboxError(f"fungsi tidak diizinkan: {fn.id}()")
            if isinstance(fn, _ast.Attribute) and fn.attr in {
                    "system", "popen", "spawn", "spawnl", "spawnv", "execv",
                    "execve", "fork", "kill", "run", "call", "check_output",
                    "Popen", "eval", "exec", "compile", "__import__"}:
                raise SandboxError(f"pemanggilan tidak diizinkan: .{fn.attr}()")
        # --- akses atribut berbahaya --------------------------------------
        if isinstance(node, _ast.Attribute) and node.attr in FORBIDDEN_ATTRS:
            raise SandboxError(f"akses atribut tidak diizinkan: .{node.attr}")
        # --- sinkronisasi/OS lewat nama -----------------------------------
        if isinstance(node, _ast.Name) and node.id in {
                "__import__", "open", "eval", "exec", "compile", "globals",
                "locals", "vars", "breakpoint", "input"}:
            raise SandboxError(f"nama tidak diizinkan: {node.id}")

    # RestrictedPython sebagai lapis AST KEDUA (independen dari di atas).
    # Ini yang secara langsung menutup kelas CVE-2026-76825.
    try:
        from RestrictedPython import compile_restricted
        compile_restricted(code, "<kode-user>", "exec")
    except Exception as exc:  # noqa: BLE001
        raise SandboxError(f"ditolak RestrictedPython: {exc}") from exc


def validate_javascript(code: str) -> None:
    """Validasi sederhana untuk JavaScript (node).

    Katalir tidak menanam runtime JS di proses API. Validasi ini menolak
    pola berbahaya sebelum kode dikirim ke `node` (yang harus ada bila
    bahasa javascript diminta).
    """
    if not code or not code.strip():
        raise SandboxError("kode kosong")
    if len(code.encode("utf-8")) > CODE_MAX_CODE_BYTES:
        raise SandboxError(f"kode terlalu panjang (>{CODE_MAX_CODE_BYTES} byte)")
    terlarang = [
        "require(", "import ", "process.", "child_process", "fs.", "eval(",
        "Function(", "__proto__", "constructor[", "globalThis", "Reflect.",
        "Proxy(", "Symbol(", "module.exports", "importScripts",
    ]
    rendah = code
    for pola in terlarang:
        if pola in rendah:
            raise SandboxError(f"pola tidak diizinkan di JavaScript: {pola!r}")


def validate(code: str, language: str = "python") -> None:
    if language not in LANGUAGES:
        raise SandboxError(f"bahasa tidak didukung: {language!r} (pilih {LANGUAGES})")
    if language == "python":
        validate_python(code)
    else:
        validate_javascript(code)


# ---------------------------------------------------------------------------
# LAPIS 2 + 3 — Runner di proses terpisah
# ---------------------------------------------------------------------------

_PY_RUNNER = textwrap.dedent('''
    # Runner sandbox Katalir — hidup di PROSES TERPISAH.
    # Menerima JSON di stdin, menulis JSON di stdout.
    import json, sys

    # Allowlist builtins yang dikenal-amAN. Didefinisikan ULANG di sini karena
    # runner adalah program mandiri (tidak mengimpor modul Katalir).
    SAFE_NAMES = {
        "abs", "all", "any", "bool", "bytes", "callable", "chr", "complex",
        "dict", "divmod", "enumerate", "filter", "float", "format",
        "frozenset", "hash", "hex", "id", "int", "isinstance", "issubclass",
        "iter", "len", "list", "map", "max", "min", "next", "oct", "ord",
        "pow", "range", "repr", "reversed", "round", "set", "slice",
        "sorted", "str", "sum", "tuple", "type", "zip",
    }

    def _inplacevar(op, x, y):
        if op == "+=":  return x + y
        if op == "-=":  return x - y
        if op == "*=":  return x * y
        if op == "/=":  return x / y
        if op == "//=": return x // y
        if op == "%=":  return x % y
        if op == "**=": return x ** y
        return x

    def _safe_getattr(obj, name, *a):
        if name in ("__subclasses__", "__globals__", "__bases__", "__mro__",
                    "__code__", "__closure__", "__reduce__", "__reduce_ex__",
                    "__getattribute__", "__builtins__", "func_globals",
                    "f_globals", "f_locals", "gi_frame", "cr_frame"):
            raise AttributeError(f"akses atribut tidak diizinkan: {name}")
        return getattr(obj, name, *a)

    def main():
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except Exception as exc:
            print(json.dumps({"ok": False, "error": f"payload tidak valid: {exc}"}))
            return

        kode      = payload.get("code", "")
        mem_mb    = int(payload.get("memory_mb", 128))
        cpu_s     = int(payload.get("cpu_s", 30))
        os_limits = "off"

        # ---- LAPIS 3: batas OS (hanya ada di Linux/Railway) --------------
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_AS,
                               (mem_mb * 1024 * 1024, mem_mb * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
            resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
            resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
            os_limits = "on"
        except Exception:
            os_limits = "unavailable"

        # ---- LAPIS 1 (ulang di sini): RestrictedPython -------------------
        try:
            from RestrictedPython import compile_restricted, safe_globals
            from RestrictedPython.Guards import safe_builtins
            from RestrictedPython.PrintCollector import PrintCollector

            bytecode = compile_restricted(kode, "<kode-user>", "exec")

            g = dict(safe_globals)
            g["__builtins__"] = dict(safe_builtins)
            g["_print_"] = PrintCollector      # dipanggil SEBAGAI KELAS
            g["_getattr_"] = _safe_getattr
            g["_getitem_"] = lambda ob, key: ob[key]
            g["_getiter_"] = iter              # WAJIB: dipakai oleh for/comp
            g["_write_"] = lambda ob: ob
            g["_inplacevar_"] = _inplacevar

            import builtins as _b
            for nama in payload.get("allow", []):
                if nama in safe_builtins:
                    g[nama] = safe_builtins[nama]
                elif nama in SAFE_NAMES and hasattr(_b, nama):
                    g[nama] = getattr(_b, nama)

            ns = dict(g)
            exec(bytecode, ns)

            keluaran = ""
            pc = ns.get("_print")
            if pc is not None and hasattr(pc, "txt"):
                # PrintCollector.txt adalah LIST potongan teks.
                txt = pc.txt
                keluaran = "".join(txt) if isinstance(txt, list) else str(txt)
        except Exception as exc:
            print(json.dumps({"ok": False, "os_limits": os_limits,
                              "error": f"{type(exc).__name__}: {exc}"}))
            return

        hasil = None
        for nama in ("result", "output", "hasil", "return_value"):
            if nama in ns:
                try:
                    json.dumps(ns[nama])
                    hasil = ns[nama]
                    break
                except Exception:
                    hasil = str(ns[nama])
                    break

        print(json.dumps({"ok": True, "os_limits": os_limits,
                          "result": hasil, "printed": keluaran}))

    main()
''')


def _python_bin() -> str:
    """Interpreter untuk subprocess sandbox.

    HARUS sama dengan interpreter yang menjalankan modul ini: RestrictedPython
    terpasang di lingkungan ITU. (Bug nyata yang ditemukan saat uji: `python`
    di PATH bisa 3.13 tanpa RestrictedPython sementara modul berjalan di 3.12
    yang punya — sandbox lalu selalu gagal "No module named RestrictedPython".)
    """
    return sys.executable or "python"


def _python_env() -> dict:
    """Lingkungan minimal untuk subprocess.

    `-I` (isolated) sengaja TIDAK dipakai karena ia mengabaikan PYTHONPATH —
    padahal kita justru butuh mewariskan lokasi paket (RestrictedPython).
    Isolasi datang dari AST + batas OS + proses terpisah, bukan dari `-I`.
    """
    env = {
        "PYTHONIOENCODING": "utf-8",
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
    }
    # Wariskan lokasi paket supaya RestrictedPython pasti ketemu.
    pp = [p for p in sys.path if p and os.path.isdir(p)]
    if pp:
        env["PYTHONPATH"] = os.pathsep.join(pp)
    return env


def run_python(code: str, *, timeout_s: int = CODE_TIMEOUT_S,
               memory_mb: int = CODE_MEMORY_MB,
               allow: Optional[list[str]] = None) -> dict:
    """Jalankan kode Python di subprocess terisolasi.

    Return dict: {ok, result, error, stdout, stderr, duration_s,
                  os_limits, killed}
    """
    validate_python(code)          # Lapis 1 di proses API (cepat & portabel)

    payload = json.dumps({
        "code": code,
        "memory_mb": int(memory_mb),
        "cpu_s": int(timeout_s),
        "allow": list(allow or SAFE_BUILTIN_NAMES),
    })
    t0 = time.monotonic()
    killed = False
    try:
        p = subprocess.run(
            [_python_bin(), "-c", _PY_RUNNER],
            input=payload, capture_output=True, text=True,
            timeout=timeout_s,
            env=_python_env(),
        )
        stdout, stderr, rc = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as exc:
        killed = True
        out = exc.stdout or b""
        err = exc.stderr or b""
        stdout = out.decode("utf-8", "replace") if isinstance(out, bytes) else (out or "")
        stderr = err.decode("utf-8", "replace") if isinstance(err, bytes) else (err or "")
        rc = -9
    durasi = time.monotonic() - t0

    hasil: dict[str, Any] = {
        "ok": False, "result": None, "error": None,
        "stdout": _potong(stdout), "stderr": _potong(stderr),
        "duration_s": round(durasi, 3), "os_limits": "unknown",
        "killed": killed, "language": "python",
    }
    if killed:
        hasil["error"] = f"timeout: eksekusi dihentikan setelah {timeout_s}s"
        return hasil

    # Baris terakhir stdout adalah JSON hasil runner.
    for baris in reversed(stdout.strip().splitlines()):
        baris = baris.strip()
        if baris.startswith("{") and baris.endswith("}"):
            try:
                data = json.loads(baris)
            except json.JSONDecodeError:
                continue
            hasil["ok"] = bool(data.get("ok"))
            hasil["result"] = data.get("result")
            hasil["os_limits"] = data.get("os_limits", "unknown")
            printed = data.get("printed") or ""
            if printed:
                hasil["stdout"] = _potong(printed)
            if data.get("error"):
                hasil["error"] = data["error"]
            return hasil

    if not hasil["error"]:
        if rc != 0:
            tail = (stderr or "").strip().splitlines()
            hasil["error"] = (tail[-1][:300] if tail
                              else f"proses keluar dengan kode {rc}")
        else:
            hasil["error"] = "runner tidak mengembalikan hasil"
    return hasil


def run_javascript(code: str, *, timeout_s: int = CODE_TIMEOUT_S,
                   memory_mb: int = CODE_MEMORY_MB) -> dict:
    """Jalankan JavaScript lewat `node` bila tersedia.

    Tidak ada runtime JS di proses API — bila `node` tidak ada, ini
    dilaporkan jujur sebagai error, bukan dipalsukan.
    """
    validate_javascript(code)
    node_bin = _cari_node()
    if not node_bin:
        return {"ok": False, "result": None,
                "error": "runtime JavaScript (node) tidak tersedia di lingkungan ini",
                "stdout": "", "stderr": "", "duration_s": 0.0,
                "os_limits": "n/a", "killed": False, "language": "javascript"}

    pembungkus = (
        "const __out = [];\n"
        "const console = { log: (...a) => __out.push(a.map(x => "
        "typeof x === 'object' ? JSON.stringify(x) : String(x)).join(' ')) };\n"
        f"{code}\n"
        "process.stdout.write(JSON.stringify({ok:true, result: "
        "(typeof result !== 'undefined' ? result : null), log: __out}));"
    )
    t0 = time.monotonic()
    killed = False
    try:
        # PENTING: flag V8 harus memakai bentuk `--flag=value`. Bentuk
        # `--max-old-space-size 128` membuat node membaca argumen BERIKUTNYA
        # sebagai nilainya -> "illegal value for flag of type size_t".
        p = subprocess.run(
            [node_bin, f"--max-old-space-size={int(memory_mb)}",
             "-e", pembungkus],
            capture_output=True, text=True, timeout=timeout_s,
            env=_node_env())
        stdout, stderr, rc = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as exc:
        killed = True
        stdout = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = (exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        rc = -9
    durasi = time.monotonic() - t0
    hasil: dict[str, Any] = {
        "ok": False, "result": None, "error": None,
        "stdout": _potong(stdout), "stderr": _potong(stderr),
        "duration_s": round(durasi, 3), "os_limits": "node",
        "killed": killed, "language": "javascript",
    }
    if killed:
        hasil["error"] = f"timeout: eksekusi dihentikan setelah {timeout_s}s"
        return hasil
    for baris in reversed(stdout.strip().splitlines()):
        baris = baris.strip()
        if baris.startswith("{") and baris.endswith("}"):
            try:
                data = json.loads(baris)
                hasil["ok"] = bool(data.get("ok"))
                hasil["result"] = data.get("result")
                log = data.get("log")
                if isinstance(log, list) and log:
                    hasil["stdout"] = _potong("\n".join(str(x) for x in log))
                return hasil
            except json.JSONDecodeError:
                continue
    if rc != 0:
        tail = (stderr or "").strip().splitlines()
        hasil["error"] = tail[-1][:300] if tail else f"node keluar dengan kode {rc}"
    else:
        hasil["error"] = "tidak ada nilai `result` yang dihasilkan"
    return hasil


def _cari_node() -> Optional[str]:
    import shutil as _sh
    for nama in ("node", "node.exe"):
        path = _sh.which(nama)
        if path:
            return path
    return None


def _node_env() -> dict:
    """Lingkungan bersih untuk node.

    PENTING: JANGAN mewariskan NODE_OPTIONS. Di lingkungan pengembangan
    (dan bisa juga di CI) NODE_OPTIONS membawa flag eksperimental/proxy
    yang membuat `node -e` gagal ("bad option: --experimental-wasm-exnref").
    Lebih penting lagi: mewariskan env induk apa adanya ke sandbox adalah
    kebocoran — sandbox harus menerima lingkungan seminimal mungkin.
    """
    return {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "HOME": os.environ.get("HOME", os.environ.get("USERPROFILE", "")),
    }


def _potong(s: Any, batas: int = CODE_MAX_OUTPUT_BYTES) -> str:
    if s is None:
        return ""
    if not isinstance(s, str):
        s = str(s)
    if len(s) <= batas:
        return s
    return s[:batas] + f"\n...[dipotong, {len(s) - batas} byte lagi]"


# ---------------------------------------------------------------------------
# API tingkat tinggi untuk node Code di workflow
# ---------------------------------------------------------------------------

def execute(code: str, language: str = "python", *,
            timeout_s: int = CODE_TIMEOUT_S,
            memory_mb: int = CODE_MEMORY_MB,
            allow: Optional[list[str]] = None,
            execution_id: Optional[str] = None,
            step_id: Optional[str] = None) -> dict:
    """Titik masuk tunggal untuk node Code.

    Selalu mengembalikan dict (tidak pernah melempar untuk kode user yang
    buruk) supaya mesin workflow bisa menandai node gagal dengan rapi.
    """
    if not isinstance(code, str):
        return {"ok": False, "result": None, "error": "kode harus berupa teks",
                "stdout": "", "stderr": "", "duration_s": 0.0,
                "os_limits": "n/a", "killed": False, "language": language}

    # Batas waktu tidak boleh melebihi hard cap.
    timeout_s = max(1, min(int(timeout_s), CODE_TIMEOUT_S))
    memory_mb = max(16, min(int(memory_mb), CODE_MEMORY_MB))

    try:
        if language == "python":
            hasil = run_python(code, timeout_s=timeout_s, memory_mb=memory_mb,
                               allow=allow)
        elif language == "javascript":
            hasil = run_javascript(code, timeout_s=timeout_s,
                                   memory_mb=memory_mb)
        else:
            return {"ok": False, "result": None,
                    "error": f"bahasa tidak didukung: {language!r}",
                    "stdout": "", "stderr": "", "duration_s": 0.0,
                    "os_limits": "n/a", "killed": False, "language": language}
    except SandboxError as exc:
        return {"ok": False, "result": None, "error": str(exc),
                "stdout": "", "stderr": "", "duration_s": 0.0,
                "os_limits": "n/a", "killed": False, "language": language}

    hasil["execution_id"] = execution_id
    hasil["step_id"] = step_id
    return hasil


def capabilities() -> dict:
    """Laporkan batas nyata lingkungan — dipakai UI/observabilitas.

    Tidak mengklaim lebih dari yang benar-benar ditegakkan.
    """
    try:
        import resource  # noqa: F401
        os_limits = True
    except ImportError:
        os_limits = False
    return {
        "languages": list(LANGUAGES),
        "python_available": True,
        "javascript_available": _cari_node() is not None,
        "timeout_s": CODE_TIMEOUT_S,
        "memory_mb": CODE_MEMORY_MB,
        "os_resource_limits": os_limits,
        "network_default": "blocked (tanpa impor)",
        "filesystem_default": "blocked (tanpa open)",
        "ast_guard": "RestrictedPython + allowlist",
        "platform": sys.platform,
    }
