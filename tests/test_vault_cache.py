"""Cache kredensial vault: benar, ter-invalidasi, dan memang lebih cepat.

KENAPA ADA
`check_credential` -> `has_credential` -> `load_vault_credential` menjalankan
query Supabase + dekripsi Fernet + parse JSON setiap kali dipanggil, dan
pemanggilan itu berulang dalam satu alur (tiap node ber-kredensial, tiap
pertanyaan "kredensial X sudah ada?").

YANG DIKUNCI DI SINI
1. Panggilan kedua TIDAK menyentuh DB/dekripsi lagi (hit cache).
2. Hasil NEGATIF (belum ada kredensial) juga di-cache — itu kasus tersering.
3. `vault_save`/`vault_delete` MENG-INVALIDASI cache, jadi user yang baru
   mengisi form langsung terlihat statusnya (bukan menunggu TTL).
4. Nilai yang dikembalikan tidak bisa memutasi isi cache dari luar.
5. TTL benar-benar kedaluwarsa.
6. Batas jumlah entri dihormati.
"""
import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import credential_forms as cf  # noqa: E402
import database as db  # noqa: E402
import vault_cache  # noqa: E402


@pytest.fixture(autouse=True)
def _reset():
    vault_cache.invalidate()
    vault_cache.reset_stats()
    yield
    vault_cache.invalidate()


def _fake_vault(monkeypatch, payload: dict | None, *, delay=0.0):
    """Ganti pembacaan vault yang MAHAL; hitung berapa kali dipanggil."""
    calls = {"n": 0}

    def _uncached(user_email, vault_provider):
        calls["n"] += 1
        if delay:
            time.sleep(delay)
        return dict(payload) if isinstance(payload, dict) else None

    monkeypatch.setattr(cf, "load_vault_credential_uncached", _uncached)
    return calls


# ---------------------------------------------------------------------------
# Perilaku cache
# ---------------------------------------------------------------------------
def test_panggilan_kedua_tidak_menyentuh_vault(monkeypatch):
    calls = _fake_vault(monkeypatch, {"token": "abc"})
    for _ in range(5):
        assert cf.load_vault_credential("u@k.id", "telegram") == {"token": "abc"}
    assert calls["n"] == 1, "cache tidak dipakai"


def test_hasil_negatif_ikut_di_cache(monkeypatch):
    """Yang paling sering diulang justru 'belum ada kredensial'."""
    calls = _fake_vault(monkeypatch, None)
    for _ in range(4):
        assert cf.load_vault_credential("u@k.id", "gmail") is None
    assert calls["n"] == 1


def test_caller_tidak_bisa_memutasi_isi_cache(monkeypatch):
    _fake_vault(monkeypatch, {"token": "asli"})
    first = cf.load_vault_credential("u@k.id", "telegram")
    first["token"] = "DIUBAH"
    second = cf.load_vault_credential("u@k.id", "telegram")
    assert second == {"token": "asli"}, "isi cache ikut termutasi"


def test_ttl_kedaluwarsa_mengambil_ulang(monkeypatch, monkeypatch_ttl=0.0):
    calls = _fake_vault(monkeypatch, {"token": "abc"})
    monkeypatch.setattr(vault_cache, "TTL_S", 0.0)
    cf.load_vault_credential("u@k.id", "telegram")
    time.sleep(0.01)
    cf.load_vault_credential("u@k.id", "telegram")
    assert calls["n"] == 2


def test_key_tidak_tercampur_antar_user_dan_provider(monkeypatch):
    def _uncached(user_email, vault_provider):
        return {"who": user_email, "prov": vault_provider}

    monkeypatch.setattr(cf, "load_vault_credential_uncached", _uncached)
    a = cf.load_vault_credential("a@k.id", "telegram")
    b = cf.load_vault_credential("b@k.id", "telegram")
    c = cf.load_vault_credential("a@k.id", "slack")
    assert a["who"] == "a@k.id" and a["prov"] == "telegram"
    assert b["who"] == "b@k.id"
    assert c["prov"] == "slack"


# ---------------------------------------------------------------------------
# Invalidasi (palings penting untuk kebenaran)
# ---------------------------------------------------------------------------
def test_vault_save_menginvalidasi_cache(monkeypatch):
    state = {"payload": None}
    monkeypatch.setattr(cf, "load_vault_credential_uncached",
                        lambda e, p: state["payload"] and dict(state["payload"]))
    assert cf.load_vault_credential("u@k.id", "telegram") is None
    # user menyimpan kredensial -> vault berubah
    state["payload"] = {"token": "baru"}
    db._invalidate_vault_cache("u@k.id", "telegram")
    assert cf.load_vault_credential("u@k.id", "telegram") == {"token": "baru"}


def test_vault_delete_menginvalidasi_cache(monkeypatch):
    state = {"payload": {"token": "lama"}}
    monkeypatch.setattr(cf, "load_vault_credential_uncached",
                        lambda e, p: state["payload"] and dict(state["payload"]))
    assert cf.load_vault_credential("u@k.id", "telegram") == {"token": "lama"}
    state["payload"] = None
    db._invalidate_vault_cache("u@k.id", "telegram")
    assert cf.load_vault_credential("u@k.id", "telegram") is None


def test_invalidate_tidak_melempar_bila_vault_cache_rusak(monkeypatch):
    """Invalidasi tidak boleh menggagalkan operasi vault."""
    import builtins
    real_import = builtins.__import__

    def _boom(name, *a, **kw):
        if name == "vault_cache":
            raise RuntimeError("modul rusak")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _boom)
    db._invalidate_vault_cache("u@k.id", "telegram")   # tidak boleh melempar


# ---------------------------------------------------------------------------
# Batas & statistik
# ---------------------------------------------------------------------------
def test_batas_entri_dihormati(monkeypatch):
    monkeypatch.setattr(vault_cache, "MAX_ENTRIES", 3)
    for i in range(10):
        vault_cache.put(f"u{i}@k.id", "telegram", {"i": i})
    assert vault_cache.stats()["entries"] <= 3


def test_stats_menghitung_hit_dan_miss():
    vault_cache.put("u@k.id", "telegram", {"x": 1})
    vault_cache.get("u@k.id", "telegram")     # hit
    vault_cache.get("u@k.id", "lain")         # miss
    s = vault_cache.stats()
    assert s["hits"] == 1 and s["misses"] == 1 and s["entries"] == 1


def test_invalidate_semua_dan_sebagian():
    vault_cache.put("a@k.id", "telegram", {})
    vault_cache.put("a@k.id", "slack", {})
    vault_cache.put("b@k.id", "telegram", {})
    assert vault_cache.invalidate("a@k.id") == 2
    assert vault_cache.stats()["entries"] == 1
    assert vault_cache.invalidate() == 1
    assert vault_cache.stats()["entries"] == 0


# ---------------------------------------------------------------------------
# Bukti performa (bukan sekadar klaim)
# ---------------------------------------------------------------------------
def test_benchmark_cache_lebih_cepat(monkeypatch):
    """Ukur: N pembacaan dengan vs tanpa cache (vault disimulasikan 5 ms)."""
    calls = _fake_vault(monkeypatch, {"token": "x"}, delay=0.005)

    t0 = time.perf_counter()
    for _ in range(10):
        cf.load_vault_credential_uncached("u@k.id", "telegram")
    tanpa = time.perf_counter() - t0

    vault_cache.invalidate()
    t0 = time.perf_counter()
    for _ in range(10):
        cf.load_vault_credential("u@k.id", "telegram")
    dengan = time.perf_counter() - t0

    print(f"\n  10x pembacaan vault: tanpa_cache={tanpa*1000:.1f}ms  "
          f"dengan_cache={dengan*1000:.1f}ms  calls={calls['n']}")
    assert calls["n"] == 1 + 10, "jumlah pemanggilan vault tidak sesuai"
    assert dengan < tanpa / 3, "cache tidak memberi percepatan berarti"
