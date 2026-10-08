# tests/test_environments.py — Fitur #4 hard test (12 skenario, Okt 2026)
# Deterministik: store memori, tanpa DB/jaringan.
from __future__ import annotations

import threading
import time

import pytest

import environments as env


def _flow(nodes):
    return {"nodes": [{"id": n, "kind": "code"} for n in nodes],
            "edges": []}


@pytest.fixture
def eng():
    return env.Environments()


# 1. Create di dev -> promote ke staging
def test_01_dev_to_staging(eng):
    eng.create("u@x.com", "dev", "wf-1", _flow(["a", "b"]))
    hasil = eng.promote("u@x.com", "wf-1", "dev", "staging")
    assert hasil["status"] == "promoted" and hasil["to"] == "staging"
    rec = eng.store.latest("u@x.com", "staging", "wf-1")
    assert rec and len(rec["flow_data"]["nodes"]) == 2


# 2. Promote staging -> production dengan approval
def test_02_production_approval(eng):
    eng.create("u@x.com", "dev", "wf-1", _flow(["a"]))
    eng.promote("u@x.com", "wf-1", "dev", "staging")
    with pytest.raises(env.ApprovalRequired) as exc:
        eng.promote("u@x.com", "wf-1", "staging", "production")
    rid = exc.value.request_id
    assert eng.store.latest("u@x.com", "production", "wf-1") is None
    hasil = eng.approve(rid, "admin@x.com", role="admin")
    assert hasil["status"] == "promoted" and hasil["to"] == "production"
    assert eng.store.latest("u@x.com", "production", "wf-1") is not None


def test_02b_skip_urutan_ditolak(eng):
    eng.create("u@x.com", "dev", "wf-1", _flow(["a"]))
    with pytest.raises(env.EnvError):
        eng.promote("u@x.com", "wf-1", "dev", "production", role="admin",
                    approver="admin@x.com")


# 3. Isolasi credential antar environment
def test_03_credential_isolation(eng):
    k_dev = env.credential_key("u@x.com", "dev", "gmail")
    k_prod = env.credential_key("u@x.com", "production", "gmail")
    assert k_dev != k_prod
    assert "dev" in k_dev and "production" in k_prod
    ref = env.resolve_credential_ref("u@x.com", "production", "gmail", "pass")
    assert ref == "secret://env:production:gmail/pass"
    with pytest.raises(env.UnknownEnvironment):
        env.credential_key("u@x.com", "qa", "gmail")


# 4. Environment selector (daftar)
def test_04_environment_selector(eng):
    eng.create("u@x.com", "dev", "wf-1", _flow(["a"]))
    eng.create("u@x.com", "dev", "wf-2", _flow(["b"]))
    eng.create("u@x.com", "staging", "wf-1", _flow(["a"]))
    assert eng.list("u@x.com", "dev") == ["wf-1", "wf-2"]
    assert eng.list("u@x.com", "staging") == ["wf-1"]
    assert env.ENVIRONMENTS == ("dev", "staging", "production")


# 5. Rollback dari production
def test_05_rollback(eng):
    eng.create("u@x.com", "dev", "wf-1", _flow(["a"]))
    eng.promote("u@x.com", "wf-1", "dev", "staging")
    eng.promote("u@x.com", "wf-1", "staging", "production",
                approver="admin@x.com")
    # ubah lagi: promote versi baru dengan node berbeda
    eng.create("u@x.com", "dev", "wf-1", _flow(["a", "c"]))
    eng.promote("u@x.com", "wf-1", "dev", "staging")
    eng.promote("u@x.com", "wf-1", "staging", "production",
                approver="admin@x.com")
    assert len(eng.store.latest("u@x.com", "production", "wf-1")["flow_data"]["nodes"]) == 2
    hasil = eng.rollback("u@x.com", "wf-1", "production", version=1)
    assert hasil["status"] == "rolled_back"
    akhir = eng.store.latest("u@x.com", "production", "wf-1")
    assert len(akhir["flow_data"]["nodes"]) == 1


# 6. Diff antar environment
def test_06_diff(eng):
    eng.create("u@x.com", "dev", "wf-1", _flow(["a", "b"]))
    eng.promote("u@x.com", "wf-1", "dev", "staging")
    eng.create("u@x.com", "dev", "wf-1", _flow(["a", "b", "c"]))
    d = eng.diff("u@x.com", "wf-1", "staging", "dev")
    assert "c" in d["nodes_added"]
    assert d["changed"] is True
    assert d["env_a"] == "staging" and d["env_b"] == "dev"


# 7. Concurrent edit di 2 environment
def test_07_concurrent_environments(eng):
    def kerja(envname):
        for i in range(50):
            eng.create("u@x.com", envname, f"wf-{envname}-{i}", _flow(["a"]))

    t1 = threading.Thread(target=kerja, args=("dev",))
    t2 = threading.Thread(target=kerja, args=("staging",))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert len(eng.list("u@x.com", "dev")) == 50
    assert len(eng.list("u@x.com", "staging")) == 50


# 8. Migration workflow existing -> dev
def test_08_migrate_existing(eng):
    rec = eng.import_existing("u@x.com", "wf-lama", _flow(["x", "y"]))
    assert rec["env"] == "dev" and rec["version"] == 1
    assert eng.list("u@x.com", "dev") == ["wf-lama"]


# 9. Config spesifik per environment
def test_09_env_specific_config(eng):
    eng.create("u@x.com", "dev", "wf-1", _flow(["a"]),
               config={"base_url": "https://dev.api"})
    eng.promote("u@x.com", "wf-1", "dev", "staging")
    dev = eng.store.latest("u@x.com", "dev", "wf-1")
    stg = eng.store.latest("u@x.com", "staging", "wf-1")
    assert dev["config"]["base_url"].endswith("dev.api")
    # config ikut terbawa saat promosi (sumber kebenaran = env sumber)
    assert stg["config"]["base_url"] == dev["config"]["base_url"]


# 10. Performa: 100 workflow
def test_10_performance_100(eng):
    t0 = time.perf_counter()
    for i in range(100):
        eng.create("u@x.com", "dev", f"wf-{i}", _flow(["a", "b"]))
        eng.promote("u@x.com", f"wf-{i}", "dev", "staging")
    dt = time.perf_counter() - t0
    assert len(eng.list("u@x.com", "staging")) == 100
    assert dt < 2.0, f"100 workflow terlalu lambat: {dt:.3f}s"


# 11. Audit log promosi
def test_11_audit_log(eng):
    eng.create("u@x.com", "dev", "wf-1", _flow(["a"]))
    eng.promote("u@x.com", "wf-1", "dev", "staging")
    trail = eng.audit_trail("u@x.com")
    aksi = [t["action"] for t in trail]
    assert "create" in aksi and "promote" in aksi
    prom = [t for t in trail if t["action"] == "promote"][0]
    assert prom["env"] == "staging" and prom["from"] == "dev"


# 12. Access control per environment
def test_12_access_control(eng):
    eng.create("u@x.com", "dev", "wf-1", _flow(["a"]), role="developer")
    eng.promote("u@x.com", "wf-1", "dev", "staging", role="developer")
    # developer tidak boleh promosi ke production
    with pytest.raises(env.Forbidden):
        eng.promote("u@x.com", "wf-1", "staging", "production",
                    role="developer")
    # viewer tidak boleh menulis sama sekali
    with pytest.raises(env.Forbidden):
        eng.create("u@x.com", "dev", "wf-2", _flow(["b"]), role="viewer")


# 13. Bandingkan versi antar environment
def test_13_compare(eng):
    eng.create("u@x.com", "dev", "wf-1", _flow(["a"]))
    cmp = eng.compare_environments("u@x.com", "wf-1")
    assert cmp["dev"]["version"] == 1
    assert cmp["staging"] is None and cmp["production"] is None
