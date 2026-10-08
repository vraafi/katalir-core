# tests/test_plugin_system.py — Fitur #11 hard test (12 skenario, Okt 2026)
# Deterministik, in-process: handler disuntik (tidak ada impor kode asing).
from __future__ import annotations

import time

import pytest

import plugin_system as ps


def _handler(cap, kwargs):
    return {"capability": cap, "kwargs": kwargs}


def _manifest(name="acme.tools", version="1.0.0", caps=None, deps=None,
              minv=""):
    return ps.PluginManifest(name=name, version=version, entry="main:run",
                             capabilities=caps if caps is not None else ["http"],
                             dependencies=deps or {},
                             min_katalir_version=minv, author="Acme",
                             description="Contoh plugin")


# 1. Install plugin -> aktif
def test_01_install():
    m = ps.PluginManager()
    out = m.install(_manifest(), _handler)
    assert out["name"] == "acme.tools" and out["enabled"] is True
    assert m.registry.get("acme.tools").enabled is True
    assert m.call("acme.tools", "http", url="x")["capability"] == "http"


# 2. Uninstall -> tidak crash
def test_02_uninstall():
    m = ps.PluginManager()
    m.install(_manifest(), _handler)
    assert m.uninstall("acme.tools") is True
    assert m.registry.get("acme.tools") is None
    assert m.uninstall("acme.tools") is False       # idempoten, tidak crash
    with pytest.raises(ps.PluginError):
        m.call("acme.tools", "http")


# 3. Sandbox: plugin tidak akses internal
def test_03_sandbox():
    m = ps.PluginManager()
    m.install(_manifest(caps=["http", "log"]), _handler)
    assert m.call("acme.tools", "log", msg="hi")["capability"] == "log"
    # capability yang TIDAK dideklarasikan -> ditolak
    with pytest.raises(ps.CapabilityDenied):
        m.call("acme.tools", "kv", key="x")


# 4. Version update OK
def test_04_version_update():
    m = ps.PluginManager()
    m.install(_manifest(version="1.0.0"), _handler)
    out = m.install(_manifest(version="1.2.0"), _handler)
    assert out["updated"] is True
    assert m.registry.get("acme.tools").manifest.version == "1.2.0"
    # menurunkan versi ditolak
    with pytest.raises(ps.PluginError):
        m.install(_manifest(version="0.9.0"), _handler)


def test_04b_semver_helpers():
    assert ps.semver_gt("1.2.0", "1.1.9") is True
    assert ps.semver_gt("1.0.0", "2.0.0") is False
    assert ps.semver_satisfies("1.5.0", ">=1.0.0") is True
    assert ps.semver_satisfies("0.9.0", ">=1.0.0") is False
    assert ps.semver_satisfies("1.5.0", "^1.2.0") is True
    assert ps.semver_satisfies("2.0.0", "^1.2.0") is False


# 5. Resolusi dependensi
def test_05_dependencies():
    m = ps.PluginManager()
    m.install(_manifest(name="acme.base", version="1.0.0"), _handler)
    m.install(_manifest(name="acme.tools", version="1.0.0",
                        deps={"acme.base": ">=1.0.0"}), _handler)
    urutan = m.resolve_dependencies(
        _manifest(name="acme.tools", deps={"acme.base": ">=1.0.0"}))
    assert urutan == ["acme.base", "acme.tools"]
    # dependensi hilang
    with pytest.raises(ps.DependencyError):
        m.install(_manifest(name="acme.need", deps={"acme.missing": "*"}),
                  _handler)
    # versi tak memenuhi
    with pytest.raises(ps.DependencyError):
        m.install(_manifest(name="acme.need2", deps={"acme.base": ">=9.0.0"}),
                  _handler)


def test_05b_dependency_cycle():
    m = ps.PluginManager()
    # daftarkan langsung (lewati install) untuk membentuk siklus
    m.registry.register(_manifest(name="a", deps={"b": "*"}), _handler)
    m.registry.register(_manifest(name="b", deps={"a": "*"}), _handler)
    with pytest.raises(ps.DependencyError):
        m.resolve_dependencies(_manifest(name="a", deps={"b": "*"}))


# 6. Marketplace: browse + search
def test_06_marketplace_search():
    m = ps.PluginManager()
    m.install(_manifest(name="acme.mail", caps=["notify"]), _handler)
    m.install(_manifest(name="acme.report", caps=["http"]), _handler)
    semua = m.registry.list()
    assert len(semua) == 2
    hasil = m.registry.search("mail")
    assert len(hasil) == 1 and hasil[0]["name"] == "acme.mail"
    assert len(m.registry.search("acme")) == 2
    assert m.registry.search("zzz") == []


# 7. Review workflow: submit + approve
def test_07_review():
    m = ps.PluginManager()
    rev = m.submit_for_review(_manifest())
    assert rev["status"] == "pending" and rev["errors"] == []
    ok = m.approve(rev["request_id"], reviewer="admin@katalir.io")
    assert ok["status"] == "approved" and ok["reviewer"] == "admin@katalir.io"
    # plugin dengan pelanggaran tidak bisa disetujui
    buruk = m.submit_for_review(_manifest(caps=["secrets"]))
    with pytest.raises(ps.PluginBlocked):
        m.approve(buruk["request_id"])
    # reject
    rev2 = m.submit_for_review(_manifest(name="acme.x"))
    rej = m.reject(rev2["request_id"], reason="dokumentasi kurang")
    assert rej["status"] == "rejected" and rej["reason"] == "dokumentasi kurang"


# 8. Plugin berbahaya -> diblokir
def test_08_malicious_blocked():
    m = ps.PluginManager()
    for cap in ("secrets", "db", "env", "exec", "shell", "filesystem"):
        with pytest.raises(ps.PluginBlocked):
            m.install(_manifest(name=f"evil.{cap}", caps=[cap]), _handler)
    # capability tak dikenal juga ditolak
    with pytest.raises(ps.PluginError):
        m.install(_manifest(name="weird", caps=["teleport"]), _handler)
    assert m.registry.list() == []


# 9. Compatibility check
def test_09_compatibility():
    m = ps.PluginManager(katalir_version="1.6.0")
    with pytest.raises(ps.CompatibilityError):
        m.install(_manifest(name="future", minv="99.0.0"), _handler)
    out = m.install(_manifest(name="okplugin", minv="1.0.0"), _handler)
    assert out["enabled"] is True


# 10. Performa: 100 plugin
def test_10_performance_100():
    m = ps.PluginManager()
    t0 = time.perf_counter()
    for i in range(100):
        m.install(_manifest(name=f"acme.p{i}", caps=["http"]), _handler)
    dt = time.perf_counter() - t0
    assert len(m.registry.list()) == 100
    assert dt < 3.0, f"100 install terlalu lambat: {dt:.3f}s"


# 11. Benchmark overhead panggilan
def test_11_call_overhead():
    m = ps.PluginManager()
    m.install(_manifest(), _handler)
    t0 = time.perf_counter()
    for i in range(1000):
        m.call("acme.tools", "http", n=i)
    dt = (time.perf_counter() - t0) / 1000
    assert dt < 0.002, f"overhead/panggilan terlalu tinggi: {dt*1e6:.0f}us"


# 12. Security: plugin tidak bisa akses secret
def test_12_no_secret_access():
    m = ps.PluginManager()
    m.install(_manifest(caps=["http"]), _handler)
    for cap in ("secrets", "vault", "db", "env", "exec"):
        with pytest.raises(ps.CapabilityDenied):
            m.call("acme.tools", cap)
    # sandbox langsung juga menolak
    sb = ps.Sandbox(_manifest(caps=["http"]))
    with pytest.raises(ps.CapabilityDenied):
        sb.call("secrets", _handler, path="x")
    # audit mencatat blokir instalasi
    m2 = ps.PluginManager()
    with pytest.raises(ps.PluginBlocked):
        m2.install(_manifest(name="evil2", caps=["secrets"]), _handler)
    assert any(a["action"] == "install_blocked" for a in m2.audit())


# 13. Regresi: kebijakan panjang nama HARUS monoton/koheren.
#     Bug ditemukan saat hard test LIVE: pola lama
#     `^[a-z0-9]([a-z0-9._-]{1,62}[a-z0-9])?$` menerima nama 1 karakter ("x")
#     tapi MENOLAK nama 2 karakter ("ok") — kebijakan panjang yang tidak
#     monoton. Sekarang ambang minimum eksplisit >= 3 karakter.
def test_13_nama_panjang_koheren():
    m = ps.PluginManager()
    # 1 dan 2 karakter: ditolak konsisten.
    for buruk in ("x", "ok"):
        with pytest.raises(ps.PluginError):
            m.install(_manifest(name=buruk, caps=["http"]), _handler)
    # 3 karakter (batas bawah) dan nama bergaya npm: diterima.
    for baik in ("abc", "acme.tools", "a_b-c", "p100"):
        out = m.install(_manifest(name=baik, caps=["http"]), _handler)
        assert out["enabled"] is True
    # Karakter di luar charset / posisi terlarang: ditolak.
    for buruk2 in ("Bad", "-lead", "trail-", "spasi name", "a" * 65):
        with pytest.raises(ps.PluginError):
            m.install(_manifest(name=buruk2, caps=["http"]), _handler)


# 14. Durability: plugin bertahan lintas "restart" (store -> hydrate).
#     Registry in-memory hilang saat proses mati; manifest disimpan di store
#     sehingga pemasangan pulih setelah restart.
def test_14_persistensi_hydrate():
    store = ps.PluginStore()
    m1 = ps.PluginManager(store=store, owner="u@katalir")
    m1.install(_manifest(name="acme.persist", caps=["log"]), _handler)
    m1.install(_manifest(name="acme.persist2", version="2.1.0", caps=["http"]),
               _handler)
    m1.set_enabled("acme.persist2", False)
    assert len(store.list("u@katalir")) == 2

    # "restart": manajer BARU, store sama.
    m2 = ps.PluginManager(store=store, owner="u@katalir")
    assert m2.registry.list() == []
    dimuat = m2.hydrate(_handler)
    assert sorted(dimuat) == ["acme.persist", "acme.persist2"]
    # status enabled ikut pulih, bukan selalu True.
    assert m2.registry.get("acme.persist").enabled is True
    assert m2.registry.get("acme.persist2").enabled is False
    # versi asli ikut pulih.
    assert m2.registry.get("acme.persist2").manifest.version == "2.1.0"
    # audit mencatat hydrate.
    assert any(a["action"] == "hydrate" for a in m2.audit())


# 15. Isolasi tenant: plugin owner A TIDAK boleh terlihat oleh owner B.
def test_15_isolasi_tenant():
    store = ps.PluginStore()
    a = ps.PluginManager(store=store, owner="a@katalir")
    b = ps.PluginManager(store=store, owner="b@katalir")
    a.install(_manifest(name="acme.only-a", caps=["log"]), _handler)
    b.install(_manifest(name="acme.only-b", caps=["log"]), _handler)

    assert [r["name"] for r in store.list("a@katalir")] == ["acme.only-a"]
    assert [r["name"] for r in store.list("b@katalir")] == ["acme.only-b"]

    # uninstall di A tidak menyentuh B.
    a.uninstall("acme.only-a")
    assert store.list("a@katalir") == []
    assert len(store.list("b@katalir")) == 1
    assert b.registry.get("acme.only-b") is not None


# 16. Hydrate defensif: manifest rusak / tidak kompatibel DILEWATI, tidak
#     mematikan startup, dan manifest yang sah tetap dimuat.
def test_16_hydrate_defensif():
    store = ps.PluginStore()
    m = ps.PluginManager(store=store, owner="u@katalir")
    m.install(_manifest(name="acme.baik", caps=["log"]), _handler)
    # sisipkan baris rusak langsung ke store (mensimulasikan data DB kotor)
    store._rows[("u@katalir", "rusak")] = {
        "owner": "u@katalir", "name": "rusak", "version": "x.y",
        "manifest": {"name": "rusak", "version": "bukan-semver",
                     "entry": "m:r", "capabilities": ["log"]},
        "enabled": True}
    store._rows[("u@katalir", "masa-depan")] = {
        "owner": "u@katalir", "name": "masa-depan", "version": "1.0.0",
        "manifest": {"name": "masa-depan", "version": "1.0.0", "entry": "m:r",
                     "capabilities": ["log"], "min_katalir_version": "99.0.0"},
        "enabled": True}

    m2 = ps.PluginManager(store=store, owner="u@katalir",
                          katalir_version="1.6.0")
    dimuat = m2.hydrate(_handler)
    assert dimuat == ["acme.baik"]          # 2 baris buruk dilewati
    assert len(m2.registry.list()) == 1
