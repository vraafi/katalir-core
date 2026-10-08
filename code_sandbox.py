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
# Batas data workflow yang boleh diinjeksi sebagai variabel. 256 KB cukup untuk
# payload trigger realistis (satu halaman webhook) dan tetap jauh di bawah
# batas memori sandbox (128 MB).
CODE_MAX_VARS_BYTES = 262_144

# Bahasa yang didukung.
LANGUAGES = ("python", "javascript")

#: Nama variabel yang menerima data workflow di dalam kode user.
#:
#: KENAPA BUKAN `input`:
#:   `input` DITOLAK oleh penjaga AST (lihat `validate_python`) sebagai nama
#:   terlarang — ia memanggil `input()` yang bisa membaca stdin. Kalau
#:   variabel data dinamai `input`, setiap kode yang MEMBACANYA akan ditolak
#:   sandbox: fiturnya mati sebelum lahir. Nama ini juga harus cocok dengan
#:   yang dipakai jalur JavaScript (`const input_data = …`) supaya user hanya
#:   perlu mengingat SATU nama untuk kedua bahasa.
VARS_NAME = "input_data"

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

        # --- str.format attribute traversal --------------------------------
        # `'{0.__class__.__base__.__subclasses__}'.format(1)` MELEWATI kedua
        # penjaga (AST FORBIDDEN_ATTRS dan _safe_getattr) karena str.format
        # melakukan pencarian atributnya sendiri. Terbukti bocor: __class__,
        # __mro__, __subclasses__, dan alamat memori (ASLR).
        # Semua eskalasi klasik butuh dunder di NAMA FIELD, jadi cukup tolak
        # dunder di bagian field (sebelum `!`/`:`), tanpa menyentuh format spec
        # yang sah seperti '{0:.2f}'.
        if isinstance(node, _ast.Constant) and isinstance(node.value, str):
            teks = node.value
            if "{" in teks and "__" in teks:
                import string as _string
                try:
                    for _lit, nama_field, _spec, _konv in (
                            _string.Formatter().parse(teks)):
                        if nama_field and "__" in nama_field:
                            raise SandboxError(
                                "akses atribut dunder lewat str.format tidak "
                                f"diizinkan: {{{nama_field}}}")
                except SandboxError:
                    raise
                except Exception:
                    # Format tidak valid -> biarkan jalur sintaks normal
                    # yang menanganinya.
                    pass

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
    import json, sys, os, threading, time

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

    # ------------------------------------------------------------------
    # Penjaga str.format — BERBASIS RUNTIME, bukan pemindaian literal.
    #
    # Kenapa: pemindaian konstanta string di AST (LAPIS 1) hanya melihat
    # literal SATU PER SATU, sehingga string yang DIRAKIT lolos:
    #
    #     "{0." + "__class__" + "}".format(1)   -> bocor <class 'int'>
    #     "{0." + chr(95)*2 + "class" + chr(95)*2 + "}".format(1)
    #
    # Terbukti: 5/5 vektor rakitan bocor (C1,C2,C3,C4,C7).
    # Perbaikan yang benar: pindai string format SESUDAH DIRAKIT, saat runtime.
    # Caranya: transformasi AST mengubah `X.format(...)` menjadi
    # `katalir_attr_format(X)(...)`, sehingga string yang benar-benar dipakai
    # selalu diperiksa. Jalur "ambil atribut tanpa memanggil"
    # (`f = "{0."+"__class__"+"}".format; f(1)`) juga tertutup karena
    # transformasinya di level Attribute, bukan Call.
    # ------------------------------------------------------------------
    def _scan_format(teks):
        import string as _s

        def _periksa(fmt, kedalaman=0):
            if kedalaman > 4:
                return
            for _lit, field, spec, _konv in _s.Formatter().parse(fmt):
                if field and "__" in field:
                    raise AttributeError(
                        "akses atribut dunder lewat format tidak diizinkan: "
                        "{" + field + "}")
                if spec:
                    _periksa(spec, kedalaman + 1)

        _periksa(teks)

    def katalir_attr_format(obj):
        if obj is str:                       # str.format(fmt, *a) tak-terikat
            def _unbound(fmt, *a, **kw):
                _scan_format(fmt)
                return str.format(fmt, *a, **kw)
            return _unbound
        if isinstance(obj, str):             # "fmt".format(*a)
            def _bound(*a, **kw):
                _scan_format(obj)
                return str.format(obj, *a, **kw)
            return _bound
        return obj.format                    # objek lain: serahkan ke metodenya

    def katalir_attr_format_map(obj):
        if obj is str:
            def _unbound(fmt, mapping):
                _scan_format(fmt)
                return str.format_map(fmt, mapping)
            return _unbound
        if isinstance(obj, str):
            def _bound(mapping):
                _scan_format(obj)
                return str.format_map(obj, mapping)
            return _bound
        return obj.format_map

    def _tutup_format(kode):
        """Ubah X.format / X.format_map menjadi pemanggilan terjaga."""
        import ast as _a

        class _T(_a.NodeTransformer):
            def visit_Attribute(self, node):
                self.generic_visit(node)
                if node.attr in ("format", "format_map"):
                    nama = ("katalir_attr_format" if node.attr == "format"
                            else "katalir_attr_format_map")
                    return _a.Call(
                        func=_a.Name(id=nama, ctx=_a.Load()),
                        args=[node.value], keywords=[])
                return node

        pohon = _T().visit(_a.parse(kode))
        _a.fix_missing_locations(pohon)
        return _a.unparse(pohon)

    def _safe_getattr(obj, name, *a):
        if name in ("__subclasses__", "__globals__", "__bases__", "__mro__",
                    "__code__", "__closure__", "__reduce__", "__reduce_ex__",
                    "__getattribute__", "__builtins__", "func_globals",
                    "f_globals", "f_locals", "gi_frame", "cr_frame"):
            raise AttributeError(f"akses atribut tidak diizinkan: {name}")
        return getattr(obj, name, *a)

    def _rss_mb():
        """Memori terpakai proses ini dalam MB, lintas-platform.

        Windows: pakai PagefileUsage (commit charge), BUKAN WorkingSetSize.
        Alasannya penting dan sudah dibuktikan: `bytes(512*1024*1024)`
        meng-commit 512MB tapi WorkingSetSize tetap ~38MB karena halaman nol
        di-commit malas (lazy). Dengan WorkingSetSize, memory bomb TIDAK
        terdeteksi. PagefileUsage naik 12MB -> 525MB -> 2577MB pada kasus yang
        sama, jadi itulah metrik yang benar.
        Linux: /proc/self/statm (RLIMIT_AS sudah menangani batas virtual).
        """
        try:
            if sys.platform.startswith("win"):
                import ctypes
                from ctypes import wintypes

                class _PMC(ctypes.Structure):
                    _fields_ = [
                        ("cb", wintypes.DWORD),
                        ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t),
                    ]
                k32 = ctypes.windll.kernel32
                # WAJIB: tanpa argtypes/restype, HANDLE dipotong ke 32-bit dan
                # K32GetProcessMemoryInfo mengembalikan 0 (gagal senyap).
                k32.GetCurrentProcess.restype = wintypes.HANDLE
                k32.GetCurrentProcess.argtypes = []
                fn = k32.K32GetProcessMemoryInfo
                fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC),
                               wintypes.DWORD]
                fn.restype = wintypes.BOOL
                pmc = _PMC()
                pmc.cb = ctypes.sizeof(_PMC)
                if not fn(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
                    return None
                return max(pmc.PagefileUsage, pmc.WorkingSetSize) / (1024.0 * 1024.0)
            with open("/proc/self/statm", "r") as fh:
                halaman = int(fh.read().split()[1])
            return halaman * (os.sysconf("SC_PAGE_SIZE") / (1024.0 * 1024.0))
        except Exception:
            return None

    def _start_memory_watchdog(batas_mb):
        """Hentikan proses bila RSS melewati batas — SEMUA platform.

        Kenapa perlu: `resource.setrlimit` hanya ada di Linux. Di Windows
        batas memori sebelumnya TIDAK ditegakkan sama sekali (terbukti: alokasi
        4 GB berhasil, ok=True, padahal cap 128 MB). Watchdog ini menutup celah
        itu tanpa mengubah perilaku di Linux (yang sudah punya RLIMIT_AS).
        """
        def _loop():
            # Beri ruang untuk alokasi wajar sebelum mulai menembak.
            while True:
                time.sleep(0.05)
                rss = _rss_mb()
                if rss is not None and rss > batas_mb:
                    try:
                        print(json.dumps({
                            "ok": False,
                            "os_limits": "watchdog",
                            "error": (f"memory limit terlampaui: "
                                      f"{rss:.0f}MB > {batas_mb}MB "
                                      f"(dihentikan oleh watchdog)"),
                        }), flush=True)
                    except Exception:
                        pass
                    os._exit(137)          # SIGKILL-equivalent
        t = threading.Thread(target=_loop, daemon=True)
        t.start()

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

        # ---- LAPIS 3b: watchdog memori lintas-platform --------------------
        # Menegakkan batas memori di platform TANPA `resource` (mis. Windows),
        # tempat RLIMIT_AS tidak tersedia sehingga cap 128MB dulu tidak berlaku.
        _start_memory_watchdog(mem_mb)

        # ---- LAPIS 1 (ulang di sini): RestrictedPython -------------------
        try:
            from RestrictedPython import compile_restricted, safe_globals
            from RestrictedPython.Guards import safe_builtins
            from RestrictedPython.PrintCollector import PrintCollector

            # Terapkan penjaga str.format SEBELUM compile_restricted, supaya
            # RestrictedPython melihat bentuk yang sudah terjaga.
            kode = _tutup_format(kode)
            bytecode = compile_restricted(kode, "<kode-user>", "exec")

            g = dict(safe_globals)
            g["__builtins__"] = dict(safe_builtins)
            g["_print_"] = PrintCollector      # dipanggil SEBAGAI KELAS
            g["_getattr_"] = _safe_getattr
            g["_getitem_"] = lambda ob, key: ob[key]
            g["_getiter_"] = iter              # WAJIB: dipakai oleh for/comp
            g["_write_"] = lambda ob: ob
            g["_inplacevar_"] = _inplacevar
            g["katalir_attr_format"] = katalir_attr_format
            g["katalir_attr_format_map"] = katalir_attr_format_map

            import builtins as _b
            for nama in payload.get("allow", []):
                if nama in safe_builtins:
                    g[nama] = safe_builtins[nama]
                elif nama in SAFE_NAMES and hasattr(_b, nama):
                    g[nama] = getattr(_b, nama)

            ns = dict(g)
            # Data workflow masuk sebagai SATU variabel (VARS_NAME), BUKAN
            # sebagai substitusi teks ke dalam kode — lihat catatan panjang di
            # `_exec_code` (execution_engine.py). Satu variabel, bukan sebar
            # kunci: nama variabel jadi tetap (tidak bisa menabrak apa pun) dan
            # kunci payload boleh berbentuk apa saja.
            # Kunci sudah dibersihkan di proses API oleh `sanitize_vars`, tapi
            # penjaga kedua di sini murah dan menjaga runner tetap aman walau
            # dipanggil tanpa lewat `execute()`.
            _data = payload.get("vars")
            if isinstance(_data, dict):
                ns["input_data"] = _data
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


def _win_memory_job(memory_mb: int):
    """Windows: Job Object yang menegakkan batas memori TANPA kerja sama proses.

    Kenapa perlu: `resource.setrlimit` tidak ada di Windows, dan watchdog
    berbasis thread Python TIDAK BISA menangkap `bytes(4GB)` karena alokasi itu
    satu panggilan C yang memegang GIL — thread watchdog tidak pernah dijadwalkan
    (dibuktikan: 4 GB berhasil dalam 0,23 s). Job Object ditegakkan KERNEL:
    alokasi yang melewati batas GAGAL (MemoryError), bukan membunuh proses.

    Mengembalikan HANDLE job, atau None bila tidak tersedia/gagal.
    """
    try:
        import ctypes
        from ctypes import wintypes

        class _IO_COUNTERS(ctypes.Structure):
            _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                        ("WriteOperationCount", ctypes.c_ulonglong),
                        ("OtherOperationCount", ctypes.c_ulonglong),
                        ("ReadTransferCount", ctypes.c_ulonglong),
                        ("WriteTransferCount", ctypes.c_ulonglong),
                        ("OtherTransferCount", ctypes.c_ulonglong)]

        class _BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                        ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _EXT(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _BASIC),
                        ("IoInfo", _IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = ctypes.windll.kernel32
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None

        JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
        JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

        info = _EXT()
        info.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
        info.ProcessMemoryLimit = int(memory_mb) * 1024 * 1024
        k32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.SetInformationJobObject.restype = wintypes.BOOL
        if not k32.SetInformationJobObject(
                job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info), ctypes.sizeof(info)):
            k32.CloseHandle(job)
            return None
        return job
    except Exception:  # noqa: BLE001
        return None


def _win_assign_job(job, proc) -> bool:
    """Masukkan proses anak ke Job Object. False bila gagal."""
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        return bool(k32.AssignProcessToJobObject(
            job, wintypes.HANDLE(int(proc._handle))))
    except Exception:  # noqa: BLE001
        return False


def _tolak_json(obj: Any) -> Any:
    """`default=` untuk json.dumps: TOLAK objek yang bukan data murni."""
    raise TypeError(f"nilai bukan data JSON: {type(obj).__name__}")


def sanitize_vars(vars_in: Any) -> dict:
    """Ubah data workflow menjadi nilai JSON-murni yang aman diinjeksi.

    JSON round-trip di sini BUKAN formalitas — ia adalah sanitizer:

      * Hanya dict/list/str/int/float/bool/None yang selamat. Objek Python apa
        pun (modul, kelas, fungsi, file handle, generator) GAGAL serialisasi
        dan dibuang. Jadi tidak ada jalan bagi objek berkemampuan-kode untuk
        masuk ke namespace sandbox lewat jalur data.
      * Nilai yang gagal diserialisasi DIBUANG satu per satu — bukan diganti
        `str(obj)`, karena `str()` pada objek tak dikenal memanggil `__repr__`
        milik objek itu.

    Kunci TIDAK disaring, dan itu keputusan sadar: data masuk sebagai SATU
    variabel (`VARS_NAME`), jadi kunci apa pun hanyalah isi data — ia tidak
    bisa lagi menimpa nama internal runner atau menyamar sebagai `result`.
    Menyaring kunci justru akan membuang data senyap pada payload nyata yang
    berkunci `@timestamp`, `user-id`, atau `_meta`.
    """
    if not isinstance(vars_in, dict):
        return {}
    bersih: dict[str, Any] = {}
    for kunci, nilai in vars_in.items():
        try:
            bersih[str(kunci)] = json.loads(
                json.dumps(nilai, default=_tolak_json))
        except Exception:  # noqa: BLE001 - nilai buruk = dibuang, bukan crash
            continue
    if len(json.dumps(bersih, default=_tolak_json)) > CODE_MAX_VARS_BYTES:
        raise SandboxError(
            f"data workflow terlalu besar (>{CODE_MAX_VARS_BYTES} byte)")
    return bersih


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
               allow: Optional[list[str]] = None,
               vars: Optional[dict] = None) -> dict:
    """Jalankan kode Python di subprocess terisolasi.

    `vars` adalah data workflow yang diekspos ke kode user sebagai SATU
    variabel `input_data` (lihat `VARS_NAME`). Ia selalu melewati
    `sanitize_vars` — hanya data JSON murni yang bisa masuk.

    Return dict: {ok, result, error, stdout, stderr, duration_s,
                  os_limits, killed}
    """
    validate_python(code)          # Lapis 1 di proses API (cepat & portabel)

    payload = json.dumps({
        "code": code,
        "memory_mb": int(memory_mb),
        "cpu_s": int(timeout_s),
        "allow": list(allow or SAFE_BUILTIN_NAMES),
        "vars": sanitize_vars(vars),
    })
    t0 = time.monotonic()
    killed = False
    # Windows: pasang Job Object SEBELUM kode user berjalan. Anak ditahan
    # dulu (menunggu stdin) sehingga tidak ada balapan antara pembuatan proses
    # dan pemasangan batas memori.
    _job = _win_memory_job(memory_mb) if sys.platform == "win32" else None
    try:
        if _job:
            proc = subprocess.Popen(
                [_python_bin(), "-c", _PY_RUNNER],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, env=_python_env(),
            )
            _win_assign_job(_job, proc)
            try:
                stdout, stderr = proc.communicate(payload, timeout=timeout_s)
                rc = proc.returncode
            except subprocess.TimeoutExpired:
                killed = True
                proc.kill()
                stdout, stderr = proc.communicate()
                rc = -9
            finally:
                try:
                    import ctypes
                    ctypes.windll.kernel32.CloseHandle(_job)
                except Exception:  # noqa: BLE001
                    pass
        else:
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
            # stdout = keluaran `print()` user SAJA.
            # Sebelumnya penetapan ini bersyarat (`if printed:`), sehingga saat
            # kode TIDAK memanggil print() nilainya tetap `_potong(stdout)` —
            # yaitu baris JSON internal runner. Node Code menampilkan field ini
            # apa adanya ke user, jadi bocoran itu terbaca sebagai "output".
            hasil["stdout"] = _potong(data.get("printed") or "")
            if data.get("error"):
                # Dipotong juga: sebelumnya `error` LOLOS tanpa batas sehingga
                # exception 100KB mengalir utuh ke respons API (stdout/stderr
                # sudah dipotong, error tidak).
                hasil["error"] = _potong(data["error"])
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
                   memory_mb: int = CODE_MEMORY_MB,
                   vars: Optional[dict] = None) -> dict:
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

    # Data workflow diinjeksi sebagai variabel `input_data`, BUKAN sebagai
    # substitusi teks ke dalam kode (alasan sama seperti jalur Python).
    #
    # Kenapa `JSON.parse("<literal>")` dan bukan objek literal langsung:
    # pada objek literal JavaScript, kunci `__proto__` MENYETEL prototipe
    # (prototype pollution), sedangkan `JSON.parse` membuatnya sebagai properti
    # biasa. Karena kunci di sini berasal dari data workflow milik user, itu
    # perbedaan yang penting. String literal-nya sendiri dihasilkan oleh
    # json.dumps dari json.dumps, jadi selalu ter-escape dengan benar.
    _json_text = json.dumps(sanitize_vars(vars), ensure_ascii=True)
    _literal = json.dumps(_json_text).replace("\u2028", "\\u2028") \
                                    .replace("\u2029", "\\u2029")
    _prelude = f"const {VARS_NAME} = JSON.parse({_literal});\n"

    pembungkus = (
        "const __out = [];\n"
        "const console = { log: (...a) => __out.push(a.map(x => "
        "typeof x === 'object' ? JSON.stringify(x) : String(x)).join(' ')) };\n"
        f"{_prelude}"
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
                # Sama seperti jalur Python: stdout hanya berisi `console.log`
                # user, bukan baris JSON internal runner.
                log = data.get("log")
                hasil["stdout"] = _potong(
                    "\n".join(str(x) for x in log)
                    if isinstance(log, list) else "")
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
            vars: Optional[dict] = None,
            execution_id: Optional[str] = None,
            step_id: Optional[str] = None) -> dict:
    """Titik masuk tunggal untuk node Code.

    Selalu mengembalikan dict (tidak pernah melempar untuk kode user yang
    buruk) supaya mesin workflow bisa menandai node gagal dengan rapi.

    `vars` = data workflow yang diekspos ke kode sebagai `input_data`.
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
                               allow=allow, vars=vars)
        elif language == "javascript":
            hasil = run_javascript(code, timeout_s=timeout_s,
                                   memory_mb=memory_mb, vars=vars)
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
    # Sejak perbaikan hard test: batas memori ditegakkan di SEMUA platform.
    # Linux -> RLIMIT_AS; Windows -> Job Object (kernel). Sebelumnya di Windows
    # cap 128MB tidak berlaku sama sekali (alokasi 4 GB berhasil).
    if os_limits:
        memory_mechanism = "RLIMIT_AS"
    elif sys.platform == "win32" and _win_memory_job(CODE_MEMORY_MB):
        memory_mechanism = "Windows Job Object (JOB_OBJECT_LIMIT_PROCESS_MEMORY)"
    else:
        memory_mechanism = "tidak ditegakkan"
    return {
        "languages": list(LANGUAGES),
        "python_available": True,
        "javascript_available": _cari_node() is not None,
        "timeout_s": CODE_TIMEOUT_S,
        "memory_mb": CODE_MEMORY_MB,
        "max_output_bytes": CODE_MAX_OUTPUT_BYTES,
        "max_code_bytes": CODE_MAX_CODE_BYTES,
        "data_variable": VARS_NAME,
        "max_data_bytes": CODE_MAX_VARS_BYTES,
        "os_resource_limits": os_limits,
        "memory_enforced": memory_mechanism != "tidak ditegakkan",
        "memory_mechanism": memory_mechanism,
        "network_default": "blocked (tanpa impor)",
        "filesystem_default": "blocked (tanpa open)",
        "ast_guard": "RestrictedPython + allowlist + tolak dunder di str.format",
        "platform": sys.platform,
    }


def info() -> dict:
    """Ringkasan sandbox untuk `/version` — permukaan publik, bukan internal.

    Dipisah dari `capabilities()` (yang melaporkan MEKANISME penegakan) supaya
    `/version` bisa menjawab "fitur ini tersambung ke mana saja" tanpa
    membocorkan detail implementasi keamanan.
    """
    caps = capabilities()
    return {
        "enabled": True,
        "languages": caps["languages"],
        "javascript_available": caps["javascript_available"],
        "max_timeout_s": caps["timeout_s"],
        "memory_limit_mb": caps["memory_mb"],
        "memory_enforced": caps["memory_enforced"],
        "data_variable": caps["data_variable"],
        "endpoints": ["code_node", "mcp_execute_code"],
    }
