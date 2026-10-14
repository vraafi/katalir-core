"""A/B terkontrol di VPS: kode LAMA (backup) vs kode BARU (deployed).

Stub pool + resolver identik untuk keduanya, jadi satu-satunya variabel adalah
perubahan kode fallback. Membuktikan: kondisi "semua kunci model cooldown"
dulu 503, sekarang dilayani model cadangan.
"""
import json
import shutil
import sys

CORE = "/root/katalir-core"
sys.path.insert(0, CORE)
shutil.copy(f"{CORE}/api_server.py.bak-modelfb-20261014-041314",
            "/tmp/old_api_server.py")
sys.path.insert(0, "/tmp")

import api_server as NEW          # noqa: E402
import old_api_server as OLD      # noqa: E402

GM = "google/gemma-4-31b-it"


class _Stop(Exception):
    """Dibuat klien -> model sudah terpilih (artinya tidak 503)."""


class _StubPool:
    def __init__(self, ready):
        self.ready = ready
        self.calls = []

    @property
    def size(self):
        return 13

    def acquire(self, model=""):
        self.calls.append(model)
        return (f"fp-{model}", "k") if model in self.ready else None

    def label(self, fp):
        return fp

    def client(self, fp):
        raise _Stop(fp)


def run(mod, ready):
    pool = _StubPool(ready)
    mod.gemini_key_pool.pool = lambda: pool
    mod._gateway_target = lambda: None
    mod._resolve_model = lambda m, t: (GM, False, None)
    try:
        mod._agentic_run_direct("hai", "ab@test.dev", model=GM, user_tier="free")
        return "SELESAI_TANPA_EXCEPTION", pool.calls
    except _Stop:
        return "FALLBACK_DILAYANI", pool.calls
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {str(exc)[:90]}", pool.calls


READY = {"gemini-3.5-flash-lite", "gemini-2.5-flash"}
print("SKENARIO A: kunci gemma cooldown, gemini-3.5-flash-lite siap")
for label, mod in (("LAMA", OLD), ("BARU", NEW)):
    hasil, calls = run(mod, READY)
    print(f"  {label:4} -> {hasil}")
    print(f"        acquire dipanggil: {calls}")

print("\nSKENARIO B: SELURUH rantai kehabisan kunci (kapasitas nyata)")
for label, mod in (("LAMA", OLD), ("BARU", NEW)):
    hasil, calls = run(mod, set())
    print(f"  {label:4} -> {hasil}")
    print(f"        acquire dipanggil: {calls}")
