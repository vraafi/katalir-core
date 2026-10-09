"""Uji Fitur #3 — Self-healing persistence & execution recovery.

12 kategori: 3 basic, 2 durability, 3 edge, 2 performance, 2 security
(+ ekstra). Semua waktu deterministik lewat jam yang disuntik; tidak ada
`sleep` di seluruh berkas.
"""
from __future__ import annotations

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import recovery as R  # noqa: E402


# ---------------------------------------------------------------------------
# Perkakas
# ---------------------------------------------------------------------------

class Clock:
    """Jam palsu — semua uji waktu deterministik."""

    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> float:
        self.t += dt
        return self.t


def make_sup(clock: Clock, **kw) -> R.ExecutionSupervisor:
    kw.setdefault("stall_timeout_sec", 30.0)
    kw.setdefault("visibility_timeout_sec", 60.0)
    return R.ExecutionSupervisor(clock=clock, **kw)


# ===========================================================================
# B — BASIC
# ===========================================================================

def test_b1_idempotency_key_is_deterministic():
    """B1: kunci idempotensi stabil & peka terhadap perubahan input."""
    a = R.idempotency_key("order-1", "created")
    b = R.idempotency_key("order-1", "created")
    c = R.idempotency_key("order-1", "updated")
    assert a == b and len(a) == 64
    assert a != c
    # Kunci per-attempt berbeda dari kunci dasar -> retry tetap boleh jalan.
    assert R.recovery_key("ex-1", 0) != R.recovery_key("ex-1", 1)
    assert R.recovery_key("ex-1", 0) == R.recovery_key("ex-1", 0)


def test_b2_stall_detected_and_restarted():
    """B2: eksekusi tanpa heartbeat melewati ambang -> terdeteksi & diulang."""
    clk = Clock()
    seen = []
    sup = make_sup(clk, on_recover=lambda rec, a: seen.append((rec.execution_id, a)))
    sup.register("ex-b2", workflow_id="wf-1", max_attempts=3)
    sup.start("ex-b2")
    clk.advance(10)
    sup.heartbeat("ex-b2")
    clk.advance(31)              # 31 s sejak heartbeat > ambang 30 s

    found = sup.scan()
    assert [f["detector"] for f in found] == ["stall"]
    plan = sup.decide(found[0])
    assert plan["action"] == "restart"
    out = sup.remediate(found[0])
    assert out["applied"] is True
    assert sup.records["ex-b2"].status == R.PENDING
    assert seen == [("ex-b2", "restart")]


def test_b3_error_classification_matches_retry_policy():
    """B3: 5xx/429/401/network boleh diulang; 4xx data/izin tidak."""
    retry_cases = ["HTTP 503", "502 Bad Gateway", "429 rate limit",
                   "401 token expired", "connection reset by peer",
                   "request timed out", "deadlock found"]
    no_retry = ["422 Unprocessable Entity", "400 bad request",
                "404 not found", "403 forbidden", "409 conflict",
                "invalid JSON payload"]
    for c in retry_cases:
        assert R.classify_error(c)["retryable"] is True, c
    for c in no_retry:
        assert R.classify_error(c)["retryable"] is False, c
    # Status numerik eksplisit menang atas tebakan teks.
    assert R.classify_error("misterius", status=503)["kind"] == "transient"
    assert R.classify_error("misterius", status=422)["retryable"] is False


# ===========================================================================
# D — DURABILITY
# ===========================================================================

def test_d1_state_survives_restart(tmp_path):
    """D1: catatan eksekusi bertahan setelah supervisor dibangun ulang."""
    spool = str(tmp_path / "rec.json")
    clk = Clock()
    sup = make_sup(clk, spool_path=spool)
    sup.register("ex-d1", workflow_id="wf-d", max_attempts=2)
    sup.start("ex-d1")
    clk.advance(40)

    sup2 = make_sup(clk, spool_path=spool)
    assert "ex-d1" in sup2.records
    rec = sup2.records["ex-d1"]
    assert rec.status == R.RUNNING
    assert rec.workflow_id == "wf-d"
    # Eksekusi yatim tetap terdeteksi setelah restart.
    assert [f["detector"] for f in sup2.startup_scan()] == ["startup-recovery"]


def test_d2_recovered_key_survives_restart(tmp_path):
    """D2: kunci pemulihan bertahan -> aksi TIDAK diulang setelah restart."""
    spool = str(tmp_path / "rec2.json")
    clk = Clock()
    sup = make_sup(clk, spool_path=spool)
    sup.register("ex-d2", max_attempts=5)
    sup.start("ex-d2")
    clk.advance(31)
    f = sup.scan()[0]
    first = sup.remediate(f)
    assert first["duplicate"] is False

    # Paksa state kembali ke RUNNING (mensimulasikan pemulihan yang tidak
    # selesai lalu proses restart) — kunci harus tetap menghalangi.
    sup.records["ex-d2"].status = R.RUNNING
    sup.records["ex-d2"].started_at = clk.t
    sup.records["ex-d2"].heartbeat_at = clk.t
    sup._persist()

    sup2 = make_sup(clk, spool_path=spool)
    sup2.records["ex-d2"].status = R.RUNNING
    clk.advance(31)
    f2 = sup2.scan()[0]
    second = sup2.remediate(f2)
    assert second["duplicate"] is True
    assert second["applied"] is False


# ===========================================================================
# E — EDGE
# ===========================================================================

def test_e1_attempts_exhausted_goes_to_quarantine():
    """E1: jatah habis -> karantina, bukan restart tanpa akhir."""
    clk = Clock()
    sup = make_sup(clk, on_recover=lambda rec, a: a)
    sup.register("ex-e1", max_attempts=2)
    for i in range(6):
        sup.start("ex-e1")
        clk.advance(31)
        found = sup.scan()
        if not found:
            break
        out = sup.remediate(found[0])
        if out["action"] == "quarantine":
            assert sup.records["ex-e1"].status == R.ERROR
            assert i >= 1
            break
    else:
        pytest.fail("tidak pernah masuk karantina")
    assert sup.records["ex-e1"].attempt >= 2


def test_e2_queue_recovery_for_pending_jobs():
    """E2: job 'pending' terlalu lama -> queue-recovery (bukan stall)."""
    clk = Clock()
    sup = make_sup(clk)
    sup.register("ex-pending", max_attempts=2)
    clk.advance(10)
    assert sup.scan() == []          # belum melewati visibility 60 s
    clk.advance(55)                  # total 65 s
    found = sup.scan()
    assert [f["detector"] for f in found] == ["queue-recovery"]
    out = sup.remediate(found[0])
    assert out["action"] == "restart"
    assert sup.records["ex-pending"].attempt == 0    # belum pernah jalan


def test_e3_all_five_detectors_and_guard_reject_unknown():
    """E3: 5 detektor n8n didukung; nilai lain ditolak; start-failure tercatat."""
    assert R.DETECTORS == ("stall", "queue-recovery", "startup-recovery",
                           "start-failure", "workflow-deactivation")
    clk = Clock()
    sup = make_sup(clk)
    sup.register("ex-e3", max_attempts=3)
    with pytest.raises(R.RecoveryError):
        sup.signal_crash("ex-e3", "detektor-karangan")
    info = sup.mark_start_failure("ex-e3", "503 saat start")
    assert info["detector"] == "start-failure"
    assert info["retryable"] is True
    # deactivation: eksekusi lama menunggu -> ditandai
    sup2 = make_sup(clk, visibility_timeout_sec=10)
    sup2.register("ex-w", max_attempts=1)
    sup2.records["ex-w"].status = R.WAITING
    clk.advance(45)
    assert [f["detector"] for f in sup2.scan()] == ["workflow-deactivation"]
    # backoff menolak attempt < 1
    with pytest.raises(R.RecoveryError):
        R.backoff_delay_ms(0)
    with pytest.raises(R.RecoveryError):
        R.ExecutionSupervisor(stall_timeout_sec=0)


# ===========================================================================
# P — PERFORMANCE
# ===========================================================================

def test_p1_scan_5000_executions():
    """P1: memindai 5.000 eksekusi tetap cepat."""
    clk = Clock()
    sup = make_sup(clk)
    for i in range(5000):
        sup.register(f"ex-{i}", workflow_id=f"wf-{i}", max_attempts=2)
        if i % 3 == 0:
            sup.start(f"ex-{i}")
    t0 = time.perf_counter()
    found = sup.scan()
    elapsed = time.perf_counter() - t0
    assert len(found) == 0, f"pemindaian salah lapor: {len(found)}"
    assert elapsed < 2.0, f"terlalu lambat: {elapsed:.3f}s"


def test_p2_backoff_is_capped_and_jittered():
    """P2: backoff tumbuh lalu mentok di cap, dan jitter benar-benar bervariasi."""
    # Nilai deterministik dengan rng=0 -> batas bawah (expo/2).
    lows = [R.backoff_delay_ms(i, kind="transient", rng=lambda: 0.0)
            for i in range(1, 8)]
    for a, b in zip(lows, lows[1:]):
        assert b >= a, "backoff tidak monoton"
    assert max(lows) <= 60_000, f"melewati cap: {max(lows)}"

    # Batas atas dengan rng=1 -> expo (dibatasi cap).
    high = R.backoff_delay_ms(20, kind="transient", rng=lambda: 1.0)
    assert high == 60_000

    # Jitter nyata: nilai acak menghasilkan sebaran.
    vals = {R.backoff_delay_ms(3, kind="transient") for _ in range(200)}
    assert len(vals) > 50, f"jitter tidak bervariasi: {len(vals)} nilai unik"


# ===========================================================================
# S — SECURITY
# ===========================================================================

def test_s1_compensating_action_rolls_back_once():
    """S1: kompensasi (rollback) dijalankan sekali, meski dipanggil berkali-kali."""
    g = R.IdempotencyGuard()
    calls = []
    key = R.idempotency_key("ex-s1", "charge")
    assert g.claim(key, meta={"amount": 100}) is True
    assert g.claim(key) is False, "klaim kedua harus ditolak"
    out1 = g.compensate(key, lambda: calls.append("undo") or {"refunded": 100})
    out2 = g.compensate(key, lambda: calls.append("undo-lagi") or {})
    assert out1["compensated"] is True
    assert out2.get("duplicate") is True
    assert calls == ["undo"], "rollback dijalankan lebih dari sekali"
    g.commit(key)
    assert g.seen(key) is True
    # release -> kunci benar-benar bisa dipakai lagi
    g.release(key)
    assert g.claim(key) is True


def test_s2_crash_signal_is_idempotent_and_hooked_isolated():
    """S2: sinyal crash tidak diulang; hook rusak tidak merusak supervisor."""
    clk = Clock()
    calls = []

    def bad_hook(rec, det):
        calls.append(det)
        raise RuntimeError("hook sengaja rusak")

    sup = make_sup(clk, on_crash=bad_hook, on_recover=bad_hook)
    sup.register("ex-s2", max_attempts=1)
    sup.start("ex-s2")
    first = sup.signal_crash("ex-s2", "stall")
    assert first["duplicate"] is False and first["status"] == R.CRASHED
    second = sup.signal_crash("ex-s2", "stall")
    assert second["duplicate"] is True
    assert calls == ["stall"], "hook crash dipanggil lebih dari sekali"
    assert sup.records["ex-s2"].error_kind == "crash"
    # Hook yang meledak tidak membuat remediate melempar.
    # Palsukan eksekusi "hidup lagi tapi bisu": RUNNING + heartbeat basi.
    rec = sup.records["ex-s2"]
    rec.status = R.RUNNING
    rec.crash_signalled = False
    rec.started_at = clk.t
    rec.heartbeat_at = clk.t
    clk.advance(100)                 # 100 s tanpa heartbeat -> stall
    findings = sup.scan()
    assert [f["detector"] for f in findings] == ["stall"]
    out = sup.remediate(findings[0])
    assert isinstance(out, dict)
    # Hook on_recover meledak -> dicatat sebagai tidak teraplikasi,
    # tetapi remediate tetap mengembalikan dict (tanpa exception).
    assert out["applied"] is False
    assert "hook sengaja rusak" in str(out["result"])


# ===========================================================================
# X — EKSTRA
# ===========================================================================

def test_x1_guard_spool_survives_restart(tmp_path):
    """X1: kunci idempotensi bertahan lintas restart proses."""
    spool = str(tmp_path / "guard.json")
    g1 = R.IdempotencyGuard(spool_path=spool)
    k = R.idempotency_key("evt", 1)
    assert g1.claim(k) is True
    g1.commit(k, result={"ok": True})

    g2 = R.IdempotencyGuard(spool_path=spool)
    assert g2.seen(k) is True
    assert g2.claim(k) is False, "duplikat lolos setelah restart"
    assert g2.stats()["by_state"] == {"committed": 1}


def test_x2_startup_scan_orphan_worker():
    """X2: worker pemilik tidak ada di daftar -> eksekusi yatim dipulihkan."""
    clk = Clock()
    sup = make_sup(clk)
    sup.register("ex-alive", max_attempts=2)
    sup.register("ex-orphan", max_attempts=2)
    sup.start("ex-alive", worker_id="w-1")
    sup.start("ex-orphan", worker_id="w-9")
    clk.advance(1)
    sup.heartbeat("ex-alive")

    found = {f["execution_id"]: f for f in
             sup.startup_scan(known_worker_ids=["w-1"])}
    assert "ex-orphan" in found
    assert "ex-alive" not in found
    assert found["ex-orphan"]["orphan_worker"] is True
    assert found["ex-orphan"]["detector"] == "startup-recovery"


def test_x3_run_once_and_stats_reporting():
    """X3: `run_once` menjalankan siklus penuh; statistik akurat."""
    clk = Clock()
    sup = make_sup(clk, on_recover=lambda rec, a: a)
    for i in range(3):
        sup.register(f"ex-r{i}", max_attempts=2)
        sup.start(f"ex-r{i}")
    clk.advance(31)
    out = sup.run_once()
    assert out["scanned"] == 3
    assert out["found"] == 3
    assert len(out["actions"]) == 3
    assert all(a["action"] == "restart" for a in out["actions"])
    st = sup.stats()
    assert st["total"] == 3
    assert st["by_status"][R.PENDING] == 3
    assert st["recovered"] == 3
    assert st["actions"] == 3
    assert st["detectors"] == list(R.DETECTORS)

    # Putaran kedua tidak melakukan apa-apa (status sudah pending & muda).
    assert sup.run_once()["found"] == 0


def test_x4_describe_and_env_factory():
    """X4: konfigurasi dari env + ringkasan katalog benar."""
    env = {
        "KATALIR_STALL_TIMEOUT_SEC": "15",
        "KATALIR_VISIBILITY_TIMEOUT_SEC": "45",
        "KATALIR_HEARTBEAT_INTERVAL_SEC": "3",
        "KATALIR_INSTANCE_ID": "node-7",
    }
    sup = R.supervisor_from_env(env)
    assert sup.stall_timeout_sec == 15.0
    assert sup.visibility_timeout_sec == 45.0
    assert sup.heartbeat_interval_sec == 3.0
    assert sup.instance_id == "node-7"
    d = R.describe(env)
    assert d["detectors"] == list(R.DETECTORS)
    assert set(d["retryable_kinds"]) == set(R.RETRYABLE_KINDS)
    assert set(d["non_retryable_kinds"]) == set(R.NON_RETRYABLE_KINDS)
    assert d["stall_timeout_sec"] == 15.0
    assert "jitter" in d
    # env kosong -> nilai default (tidak melempar)
    base = R.supervisor_from_env({})
    assert base.stall_timeout_sec == R.DEFAULT_STALL_TIMEOUT_SEC
    # env rusak -> jatuh ke default, bukan melempar
    bad = R.supervisor_from_env({"KATALIR_STALL_TIMEOUT_SEC": "bukan-angka"})
    assert bad.stall_timeout_sec == R.DEFAULT_STALL_TIMEOUT_SEC


def test_x5_guard_batches_writes_but_commit_forces_persist(tmp_path):
    """X5: tulis spool digabung (anti O(n^2)) tetapi commit memaksa tulis."""
    import time as _t
    spool = str(tmp_path / "guard.json")
    g = R.IdempotencyGuard(spool_path=spool, persist_interval_sec=60.0)
    for i in range(500):
        g.claim(f"k-{i}")
    # Jendela 60 s: tulisan ditunda, tetapi seluruh klaim tetap di memori.
    assert g.claim("k-0") is False
    assert g.stats()["total"] == 500
    # commit() WAJIB menembus jendela -> isi spool harus memuat status commit.
    # Karena commit menulis SELURUH dict, klaim yang tertunda ikut tersimpan,
    # sehingga flush() berikutnya tidak perlu menulis lagi (dirty=false).
    g.commit("k-0", result={"ok": 1})
    raw = json.load(open(spool, encoding="utf-8"))
    assert raw["k-0"]["state"] == "committed"
    assert raw["k-0"]["result"] == {"ok": 1}
    assert len(raw) == 500, "commit harus menyertakan seluruh klaim"
    assert g.flush() is False, "tidak ada tulisan tertunda setelah commit"
    # Klaim BARU setelah commit lagi-lagi masuk jendela -> flush wajib jalan.
    g.claim("k-baru")
    assert g.flush() is True
    assert len(json.load(open(spool, encoding="utf-8"))) == 501


def test_x6_deactivation_timeout_is_configurable():
    """X6: ambang workflow-deactivation bisa diatur terpisah."""
    clk = Clock()
    sup = R.ExecutionSupervisor(clock=clk, visibility_timeout_sec=10.0)
    # Default = 4x visibility (perilaku n8n).
    assert sup.deactivation_timeout_sec == 40.0
    clk2 = Clock()
    sup2 = R.ExecutionSupervisor(clock=clk2, visibility_timeout_sec=10.0,
                                 deactivation_timeout_sec=7.0)
    assert sup2.deactivation_timeout_sec == 7.0
    sup2.register("ex-d", max_attempts=1)
    sup2.records["ex-d"].status = R.WAITING
    sup2.records["ex-d"].created_at = clk2.t
    clk2.advance(6)
    assert sup2.scan() == []
    clk2.advance(2)                      # total 8 s > 7 s
    dets = [f["detector"] for f in sup2.scan()]
    assert dets == ["workflow-deactivation"], dets
    # Nilai tidak wajar ditolak.
    import pytest as _pt
    with _pt.raises(R.RecoveryError):
        R.ExecutionSupervisor(deactivation_timeout_sec=-1.0)


def test_x7_register_stamps_time_from_injected_clock():
    """X7: created_at memakai jam yang disuntik (detektor tidak buta)."""
    clk = Clock(5000.0)
    sup = make_sup(clk)
    rec = sup.register("ex-clock", max_attempts=1)
    assert rec.created_at == 5000.0
    # Tanpa stempel ini, age_sec akan negatif terhadap time.time() asli.
    clk.advance(61)
    assert [f["detector"] for f in sup.scan()] == ["queue-recovery"]
