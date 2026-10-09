"""TASK 2 — 12 hard test untuk `connector_batch_executor.py` (batch execution FASE 3).

Distribusi sesuai brief: 2 basic, 2 edge, 2 error, 2 performance, 1 security,
1 E2E + regresi.

Murni/offline: runner disuntikkan untuk menguji logika gate tanpa jaringan.
"""

from __future__ import annotations

import time

import pytest

import connector_batch_executor as bx


# ---------------------------------------------------------------------------
# Fixtures / helper
# ---------------------------------------------------------------------------


def _entry(i: int, transport: str = "streamable_http") -> dict:
    return {
        "id": f"conn-{i:03d}",
        "endpoint_url": f"https://host{i}.example.com/mcp",
        "install_config": {"transport": transport, "package": f"pkg-{i}"},
        "tools_count": 2,
        "auth_type": "api_key",
    }


def _ok_runner(works: bool = True):
    """Runner palsu: menandai semua entri aktif bila `works`."""
    calls = {"n": 0}

    def runner(batch, **kw):
        calls["n"] += 1

        class _L:
            def __init__(self, ids):
                self._ids = ids

            def is_active(self, cid):
                return works and cid in self._ids

            def stats(self):
                return {"activated": len(self._ids) if works else 0,
                        "skipped": 0 if works else len(self._ids)}

        ids = {str(e.get("id")) for e in batch} if works else set()
        led = _L(ids)
        report = {"stage": "catalog", "duration_s": 0.001,
                  "stats": led.stats()}
        return led, report

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


# ---------------------------------------------------------------------------
# B — basic
# ---------------------------------------------------------------------------


def test_b1_memecah_20_per_batch_dan_lulus_gate():
    """B1: 60 entri -> 3 batch @20, semuanya lulus gate, 60 selesai."""
    entries = [_entry(i) for i in range(60)]
    res = bx.run_batches(entries, size=20, runner=_ok_runner(True))
    assert res["batches_total"] == 3
    assert res["batches_completed"] == 3
    assert res["batches_failed"] == 0
    assert res["connectors_completed"] == 60
    assert res["gate"] == "PASS"


def test_b2_ukuran_batch_default_20():
    """B2: default brief = 20 connector per batch."""
    assert bx.DEFAULT_BATCH_SIZE == 20
    batches = bx.chunk_entries([_entry(i) for i in range(45)])
    assert len(batches) == 3
    assert [len(b) for b in batches] == [20, 20, 5]


# ---------------------------------------------------------------------------
# E — edge
# ---------------------------------------------------------------------------


def test_e1_batch_ekor_lebih_kecil_tetap_lulus():
    """E1: sisa pembagian (5 entri) harus lulus, bukan ditolak karena size!=20."""
    entries = [_entry(i) for i in range(25)]  # 20 + 5
    res = bx.run_batches(entries, size=20, runner=_ok_runner(True))
    assert res["batches_total"] == 2
    assert res["batches_completed"] == 2
    assert res["gate"] == "PASS"


def test_e2_partisi_deterministik_dan_stabil():
    """E2: urutan masukan berbeda -> partisi & hasil sama (berbasis id)."""
    a = [_entry(i) for i in range(40)]
    b = list(reversed(a))
    pa = [[e["id"] for e in batch] for batch in bx.chunk_entries(a, 20)]
    pb = [[e["id"] for e in batch] for batch in bx.chunk_entries(b, 20)]
    assert pa == pb
    # tidak ada id yang hilang atau dobel
    flat = [i for batch in pa for i in batch]
    assert len(flat) == len(set(flat)) == 40


# ---------------------------------------------------------------------------
# X — error handling
# ---------------------------------------------------------------------------


def test_x1_gate_menolak_batch_yang_tidak_executable():
    """X1: batch tanpa entri executable -> FAIL & berhenti (bukan dilanjut)."""
    entries = [_entry(i) for i in range(20)]
    res = bx.run_batches(entries, size=20, runner=_ok_runner(False),
                        max_attempts=2)
    assert res["gate"] == "HALTED"
    assert res["batches_failed"] == 1
    assert res["batches_completed"] == 0
    assert res["stopped_at"] == [1]


def test_x2_retry_sampai_max_attempts_lalu_berhenti():
    """X2: batch gagal diulang tepat `max_attempts` kali lalu dinyatakan gagal."""
    runner = _ok_runner(False)
    entries = [_entry(i) for i in range(20)]
    ex = bx.BatchExecutor(size=20, max_attempts=3, runner=runner)
    res = ex.run_batch(entries, 1)
    assert res["verdict"] == "FAIL"
    assert res["attempt"] == 3
    assert runner.calls["n"] == 3, f"dipanggil {runner.calls['n']}x"


def test_x3_repair_hook_dipanggil_dan_bisa_menyelamatkan_batch():
    """X3: hook repair memperbaiki batch sehingga percobaan berikutnya lulus."""
    state = {"fixed": False}

    def repair(batch, attempt, gate):
        state["fixed"] = True
        return batch  # "diperbaiki"

    def runner(batch, **kw):
        class _L:
            def is_active(self, cid):
                return state["fixed"]

            def stats(self):
                return {"activated": len(batch) if state["fixed"] else 0,
                        "skipped": 0 if state["fixed"] else len(batch)}

        return _L(), {"stats": _L().stats()}

    ex = bx.BatchExecutor(size=20, max_attempts=3, runner=runner, repair=repair)
    res = ex.run_batch([_entry(i) for i in range(20)], 1)
    assert state["fixed"] is True
    assert res["verdict"] == "PASS"


def test_x4_ukuran_batch_invalid_ditolak():
    """X4: size<=0 -> BatchError (bukan loop tak berujung)."""
    with pytest.raises(bx.BatchError):
        bx.chunk_entries([_entry(0)], size=0)
    with pytest.raises(bx.BatchError):
        bx.BatchExecutor(size=0)
    with pytest.raises(bx.BatchError):
        bx.BatchExecutor(size=20, max_attempts=0)


def test_x5_input_kosong_tidak_crash():
    """X5: daftar entri kosong -> laporan sah, gate PASS, 0 batch."""
    res = bx.run_batches([], size=20, runner=_ok_runner(True))
    assert res["batches_total"] == 0
    assert res["batches_completed"] == 0
    assert res["gate"] == "PASS"


def test_x6_entri_tanpa_id_tetap_terbaca():
    """X6: entri tanpa `id` memakai slug/nama; tanpa keduanya -> string kosong."""
    assert bx._entry_id({"slug": "s1"}) == "s1"
    assert bx._entry_id({"name": "n1"}) == "n1"
    assert bx._entry_id({}) == ""
    assert bx._entry_id("plain") == "plain"


# ---------------------------------------------------------------------------
# P — performance
# ---------------------------------------------------------------------------


def test_p1_2000_entri_terbagi_cepat():
    """P1: mempartisi 2.000 entri < 1 detik."""
    entries = [_entry(i) for i in range(2000)]
    t0 = time.perf_counter()
    batches = bx.chunk_entries(entries, 20)
    dt = time.perf_counter() - t0
    assert len(batches) == 100
    assert dt < 1.0, f"{dt:.3f}s"


def test_p2_eksekusi_100_batch_murni_cepat():
    """P2: 100 batch murni (2.000 entri) selesai < 5 detik."""
    entries = [_entry(i) for i in range(2000)]
    t0 = time.perf_counter()
    res = bx.run_batches(entries, size=20, runner=_ok_runner(True))
    dt = time.perf_counter() - t0
    assert res["batches_completed"] == 100
    assert dt < 5.0, f"{dt:.3f}s"


# ---------------------------------------------------------------------------
# S — security
# ---------------------------------------------------------------------------


def test_s1_ledger_persist_tidak_menulis_kredensial(tmp_path):
    """S1: ledger progres hanya memuat id/status — bukan endpoint rahasia/token."""
    entries = [_entry(i) for i in range(25)]
    runner = _ok_runner(True)
    ex = bx.BatchExecutor(size=20, runner=runner)
    ex.run(entries)
    p = tmp_path / "prog.json"
    bx.save_ledger(ex.ledger, p)
    blob = p.read_text(encoding="utf-8").lower()
    for bad in ("password", "client_secret", "api_key=", "bearer ", "authorization"):
        assert bad not in blob, bad
    # id entri tetap tercatat (bukti progres nyata)
    assert "conn-000" in p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# I — E2E
# ---------------------------------------------------------------------------


def test_i1_e2e_katalog_nyata_3_batch_lulus_gate():
    """I1: E2E terhadap katalog nyata — aktifkan 60 connector dalam 3 batch @20."""
    import connector_activator as act

    catalog = act.load_catalog()
    planned = [e for e in catalog if act.activation_plan(e)["ok"]]
    assert len(planned) >= 60, f"hanya {len(planned)} connector dapat dieksekusi"

    # Pilih 60 deterministik
    sample = sorted(planned, key=lambda e: str(e.get("id")))[:60]
    res = bx.run_batches(sample, size=20, runner=bx.default_runner)

    assert res["batches_total"] == 3
    assert res["batches_completed"] == 3, res
    assert res["batches_failed"] == 0
    assert res["connectors_completed"] == 60
    assert res["gate"] == "PASS"

    # Lead time wajar untuk 3 batch murni.
    assert res["duration_s"] < 30.0
