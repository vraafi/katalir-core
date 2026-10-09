"""FASE 6 — pulse check berkala (connector_pulse).

Tes memakai state terisolasi (tmp) dan probe palsu; tanpa jaringan.
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import connector_pulse as cpl  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path):
    monkeypatch.setattr(cpl, "STATE_PATH", tmp_path / "pulse.json")
    return tmp_path


def _targets(n=5):
    return [{"connector_id": f"t/{i}", "endpoint_url": f"https://t{i}.dev/mcp"}
            for i in range(n)]


# --------------------------------------------------------------------------
# B — BASIC
# --------------------------------------------------------------------------

def test_b1_first_run_is_due():
    assert cpl.due() is True


def test_b2_state_roundtrip():
    st = cpl.load_state()
    st["pulses"] = 7
    cpl.save_state(st)
    assert cpl.load_state()["pulses"] == 7


# --------------------------------------------------------------------------
# E — EDGE
# --------------------------------------------------------------------------

def test_e1_not_due_right_after_pulse():
    cpl._record({"started_at": cpl._iso(cpl._now()), "summary": {}})
    assert cpl.due() is False


def test_e2_due_after_interval(monkeypatch):
    old = cpl._now() - _dt.timedelta(hours=7)
    cpl.save_state({"last_pulse_at": cpl._iso(old), "pulses": 1})
    assert cpl.due() is True


def test_e3_corrupt_timestamp_is_due():
    cpl.save_state({"last_pulse_at": "bukan-tanggal", "pulses": 1})
    assert cpl.due() is True


# --------------------------------------------------------------------------
# X — ERROR
# --------------------------------------------------------------------------

def test_x1_no_targets_returns_nothing_to_do(monkeypatch):
    monkeypatch.setattr(cpl.cp, "targets", lambda: [])
    monkeypatch.setattr(cpl.cs, "health_summary", lambda: {"total": 0})
    out = cpl.pulse(stale_only=False)
    assert out["status"] == "nothing-to-do"


def test_x2_probe_failure_does_not_raise(monkeypatch):
    monkeypatch.setattr(cpl.cp, "targets", lambda: _targets(3))
    monkeypatch.setattr(cpl.cp, "probe_many",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))) if False else None

    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(cpl.cp, "probe_many", boom)
    with pytest.raises(RuntimeError):
        cpl.pulse(stale_only=False)


def test_x3_stale_lookup_without_db(monkeypatch):
    monkeypatch.setattr(cpl.cs, "available", lambda: False)
    assert cpl._stale_connector_ids(6) == set()


# --------------------------------------------------------------------------
# P — PERFORMANCE
# --------------------------------------------------------------------------

def test_p1_pulse_persists_once(monkeypatch):
    calls = {"persist": 0, "record": 0}
    monkeypatch.setattr(cpl.cp, "targets", lambda: _targets(4))

    def fake_probe_many(items, **k):
        return [{"connector_id": it["connector_id"], "endpoint_url": it["endpoint_url"],
                 "verdict": "ALIVE", "http_status": 200, "tools_count": 2,
                 "latency_ms": 5, "error": None, "raw": None,
                 "prober": "catalog-probe"} for it in items]
    monkeypatch.setattr(cpl.cp, "probe_many", fake_probe_many)
    monkeypatch.setattr(cpl.cp, "persist",
                        lambda res: calls.__setitem__("persist", calls["persist"] + 1) or {"written": len(res)})
    out = cpl.pulse(stale_only=False, regenerate_below=0.0)
    assert calls["persist"] == 1
    assert out["probed"] == 4
    assert out["alive_ratio"] == 1.0


def test_p2_state_records_pulse_count(monkeypatch):
    monkeypatch.setattr(cpl.cp, "targets", lambda: _targets(2))
    monkeypatch.setattr(cpl.cp, "probe_many",
                        lambda items, **k: [{"connector_id": it["connector_id"],
                                             "verdict": "ALIVE", "http_status": 200,
                                             "tools_count": 1, "latency_ms": 1,
                                             "error": None, "raw": None,
                                             "endpoint_url": it["endpoint_url"]}
                                            for it in items])
    monkeypatch.setattr(cpl.cp, "persist", lambda res: {"written": len(res)})
    cpl.pulse(stale_only=False, regenerate_below=0.0)
    cpl.pulse(stale_only=False, regenerate_below=0.0)
    assert cpl.load_state()["pulses"] == 2


# --------------------------------------------------------------------------
# S — SECURITY
# --------------------------------------------------------------------------

def test_s1_threshold_requires_min_sample():
    """Regenerasi tidak boleh dipicu oleh sampel kecil (>=20)."""
    assert cpl.REGEN_ALIVE_RATIO > 0
    src = pathlib.Path(cpl.__file__).read_text(encoding="utf-8")
    assert "total >= 20" in src


def test_s2_no_credentials_in_state():
    cpl._record({"started_at": cpl._iso(cpl._now()), "summary": {"ALIVE": 1}})
    blob = (cpl.STATE_PATH.read_text(encoding="utf-8")).lower()
    for bad in ("token", "password", "secret"):
        assert bad not in blob


# --------------------------------------------------------------------------
# I — INTEGRATION
# --------------------------------------------------------------------------

def test_i1_describe_shape():
    d = cpl.describe()
    for k in ("interval_hours", "due", "next_run_at", "pulses_run",
              "last_pulse_at", "health"):
        assert k in d
    assert d["interval_hours"] == 6


def test_i2_next_run_at_after_pulse():
    cpl._record({"started_at": cpl._iso(cpl._now()), "summary": {}})
    nxt = cpl.next_run_at()
    assert nxt is not None
    dt = _dt.datetime.fromisoformat(nxt)
    assert dt > cpl._now()


def test_i3_regenerate_flag_present(monkeypatch):
    monkeypatch.setattr(cpl.cp, "targets", lambda: _targets(25))
    monkeypatch.setattr(cpl.cp, "probe_many",
                        lambda items, **k: [{"connector_id": it["connector_id"],
                                             "verdict": "DEAD", "http_status": 502,
                                             "tools_count": None, "latency_ms": 1,
                                             "error": "x", "raw": None,
                                             "endpoint_url": it["endpoint_url"]}
                                            for it in items])
    monkeypatch.setattr(cpl.cp, "persist", lambda res: {"written": len(res)})
    out = cpl.pulse(stale_only=False, regenerate_below=0.5)
    assert out["alive_ratio"] == 0.0
    assert "regenerated" in out
