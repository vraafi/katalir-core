"""FASE 1 — persistensi ledger ke DB (connector_store).

Menguji bahwa ledger aktivasi hidup di Supabase, bukan di berkas yang
gitignored. Dua jalur diuji: dengan DB (mock clinet) dan tanpa DB (fallback).
"""
from __future__ import annotations

import json
import pathlib
import sys
from unittest import mock

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import connector_store as cs  # noqa: E402


# --------------------------------------------------------------------------
# FIXTURES
# --------------------------------------------------------------------------

class _FakeTable:
    def __init__(self, store, name):
        self._store = store
        self._name = name
        self._rows = None
        self._select = None

    def select(self, cols):
        self._select = cols
        return self

    def upsert(self, rows, on_conflict=None):
        self._rows = rows
        return self

    def execute(self):
        if self._rows is not None:
            for r in self._rows:
                self._store[self._name][r["connector_id"]] = r
            return mock.Mock(data=list(self._rows))
        return mock.Mock(data=list(self._store.get(self._name, {}).values()))


class _FakeClient:
    def __init__(self, store):
        self._store = store

    def table(self, name):
        self._store.setdefault(name, {})
        return _FakeTable(self._store, name)


@pytest.fixture
def fake_db(monkeypatch, tmp_path):
    """DB palsu + berkas lokal dialihkan ke tmp_path."""
    store: dict[str, dict] = {"connector_activation": {}, "connector_health": {}}
    client = _FakeClient(store)
    monkeypatch.setattr(cs, "available", lambda: True)
    monkeypatch.setattr(cs, "_write_client", lambda: client)
    monkeypatch.setattr(cs, "_read_client", lambda: client)
    monkeypatch.setattr(cs, "_LOCAL_PATH", tmp_path / "connector_activation.json")
    return store


@pytest.fixture
def no_db(monkeypatch, tmp_path):
    monkeypatch.setattr(cs, "available", lambda: False)
    monkeypatch.setattr(cs, "_LOCAL_PATH", tmp_path / "connector_activation.json")
    return tmp_path


# --------------------------------------------------------------------------
# B — BASIC
# --------------------------------------------------------------------------

def test_b1_upsert_then_load(fake_db):
    res = cs.upsert_activation([
        {"connector_id": "a/1", "transport": "streamable_http"},
        {"connector_id": "a/2", "transport": "http"},
    ])
    assert res["written"] == 2
    assert res["backend"] == "db"
    assert cs.load_activation_ids() == {"a/1", "a/2"}


def test_b2_upsert_is_idempotent(fake_db):
    rows = [{"connector_id": "x/1"}, {"connector_id": "x/2"}]
    cs.upsert_activation(rows)
    cs.upsert_activation(rows)
    assert cs.load_activation_ids() == {"x/1", "x/2"}
    assert len(fake_db["connector_activation"]) == 2


# --------------------------------------------------------------------------
# E — EDGE
# --------------------------------------------------------------------------

def test_e1_empty_iterable(fake_db):
    res = cs.upsert_activation([])
    assert res["written"] == 0
    assert cs.load_activation_ids() == set()


def test_e2_batching_splits(fake_db):
    rows = [{"connector_id": f"b/{i}"} for i in range(450)]
    res = cs.upsert_activation(rows, batch=200)
    assert res["batches"] == 3
    assert res["written"] == 450


def test_e3_runtime_verified_defaulted(fake_db):
    cs.upsert_activation([{"connector_id": "d/1"}])
    assert fake_db["connector_activation"]["d/1"]["runtime_verified"] is True


# --------------------------------------------------------------------------
# X — ERROR / FALLBACK
# --------------------------------------------------------------------------

def test_x1_no_db_falls_back_to_file(no_db):
    (no_db / "connector_activation.json").write_text(
        json.dumps({"activated": {"f/1": True, "f/2": True}}), encoding="utf-8")
    assert cs.load_activation_ids() == {"f/1", "f/2"}


def test_x2_no_db_and_no_file_is_empty(no_db):
    assert cs.load_activation_ids() == set()


def test_x3_corrupt_file_returns_empty(no_db):
    (no_db / "connector_activation.json").write_text("{bukan json", encoding="utf-8")
    assert cs.load_activation_ids() == set()


def test_x4_db_read_error_falls_back(monkeypatch, tmp_path):
    (tmp_path / "connector_activation.json").write_text(
        json.dumps({"activated": {"g/1": True}}), encoding="utf-8")
    monkeypatch.setattr(cs, "_LOCAL_PATH", tmp_path / "connector_activation.json")
    monkeypatch.setattr(cs, "available", lambda: True)

    class Boom:
        def table(self, *a):
            raise RuntimeError("connection reset")
    monkeypatch.setattr(cs, "_read_client", lambda: Boom())
    assert cs.load_activation_ids() == {"g/1"}


def test_x5_migrate_without_db_reports_reason(no_db):
    (no_db / "connector_activation.json").write_text(
        json.dumps({"activated": {"h/1": True}}), encoding="utf-8")
    res = cs.migrate_file_to_db()
    assert res["migrated"] == 0
    assert "tidak terkonfigurasi" in res["reason"]


# --------------------------------------------------------------------------
# P — PERFORMANCE
# --------------------------------------------------------------------------

def test_p1_large_batch_reasonable(fake_db):
    import time
    rows = [{"connector_id": f"p/{i}"} for i in range(1000)]
    t0 = time.time()
    cs.upsert_activation(rows, batch=200)
    assert time.time() - t0 < 5.0
    assert len(fake_db["connector_activation"]) == 1000


def test_p2_load_is_cached_at_registry_level(monkeypatch):
    import mcp_registry as mr
    calls = {"n": 0}

    def counted():
        calls["n"] += 1
        return {"cached/1"}

    monkeypatch.setattr(cs, "available", lambda: True)
    monkeypatch.setattr(cs, "load_activation_ids", counted)
    monkeypatch.setattr(mr, "_ACTIVATED_IDS", None)
    mr._activated_ids()
    mr._activated_ids()
    mr._activated_ids()
    assert calls["n"] == 1  # hanya sekali; sisanya dari cache memori


# --------------------------------------------------------------------------
# S — SECURITY
# --------------------------------------------------------------------------

def test_s1_no_secrets_in_describe(fake_db):
    """describe() tidak boleh membocorkan kredensial.

    Catatan: hanya NILAI field yang diperiksa — `local_cache` memuat path tmp
    yang namanya diturunkan dari nama tes ini, sehingga kata 'secret' bisa
    muncul secara insidental di path dan bukan merupakan kebocoran.
    """
    d = cs.describe()
    assert set(d) == {"db_available", "activation_rows", "health", "tables",
                      "local_cache"}
    blob = json.dumps({k: v for k, v in d.items() if k != "local_cache"}).lower()
    for bad in ("service_role", "password", "api_key"):
        assert bad not in blob


def test_s2_classify_never_returns_alive_on_500():
    assert cs.classify(500) == "DEAD"
    assert cs.classify(502) == "DEAD"
    assert cs.classify(503, error="bad gateway") == "DEAD"


# --------------------------------------------------------------------------
# I — INTEGRATION
# --------------------------------------------------------------------------

def test_i1_classify_matrix():
    assert cs.classify(200, tools_count=5) == "ALIVE"
    assert cs.classify(200, tools_count=0) == "ALIVE"   # 0 tool tetap alive
    assert cs.classify(401) == "AUTH"
    assert cs.classify(403) == "AUTH"
    assert cs.classify(None, error="missing_bearer") == "AUTH"
    assert cs.classify(None, error="ProxyError: 502 Bad Gateway") == "DEAD"
    assert cs.classify(None) == "UNKNOWN"
    # 200 tanpa data = UNKNOWN, BUKAN alive (koreksi kejujuran)
    assert cs.classify(200) == "ALIVE"                  # 200 polos tanpa error
    assert cs.classify(200, error="{'code': -32601}") == "UNKNOWN"


def test_i2_record_health_and_summary(fake_db):
    cs.record_health([
        {"connector_id": "h/1", "verdict": "ALIVE", "http_status": 200, "tools_count": 3},
        {"connector_id": "h/2", "verdict": "AUTH", "http_status": 401},
        {"connector_id": "h/3", "verdict": "DEAD", "http_status": 502},
    ])
    s = cs.health_summary()
    assert s["ALIVE"] == 1
    assert s["AUTH"] == 1
    assert s["DEAD"] == 1
    assert s["total"] == 3


def test_i3_migrate_file_to_db(fake_db, tmp_path):
    (tmp_path / "connector_activation.json").write_text(
        json.dumps({"activated": {"m/1": True, "m/2": True}}), encoding="utf-8")
    res = cs.migrate_file_to_db()
    assert res["migrated"] == 2
    assert res["backend"] == "db"
    assert cs.load_activation_ids() == {"m/1", "m/2"}


def test_i4_prune_removes_file_only_on_success(fake_db, tmp_path):
    p = tmp_path / "connector_activation.json"
    p.write_text(json.dumps({"activated": {"n/1": True}}), encoding="utf-8")
    cs.migrate_file_to_db(prune_file=True)
    assert not p.exists()
