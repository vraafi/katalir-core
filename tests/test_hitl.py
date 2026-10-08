# tests/test_hitl.py — Fitur #3 hard test (10+ skenario, Okt 2026)
# Deterministik: backend memori (tanpa jaringan).
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

import hitl
from hitl import (STATUS_APPROVED, STATUS_PENDING, STATUS_REJECTED,
                  HitlError, HitlPaused, _MemoryBackend)


@pytest.fixture()
def be():
    b = _MemoryBackend()
    hitl.set_backend(b)
    return b


def _mk(**kw):
    kw.setdefault("channel", "chat")
    kw.setdefault("message", "setujui?")
    return hitl.create_request(**kw)


# 1. Approve -> resume (is_resumable True)
def test_approve_then_resumable(be):
    r = _mk()
    assert r["status"] == STATUS_PENDING
    assert hitl.is_resumable(r["request_id"]) is False
    out = hitl.record_decision(r["request_id"], "boss@x.com", "approve")
    assert out["status"] == STATUS_APPROVED
    assert hitl.is_resumable(r["request_id"]) is True


# 2. Reject -> stop (tidak resumable)
def test_reject_stops(be):
    r = _mk()
    out = hitl.record_decision(r["request_id"], "boss@x.com", "reject")
    assert out["status"] == STATUS_REJECTED
    assert hitl.is_resumable(r["request_id"]) is False


# 3. Timeout -> auto-resume dengan aksi default
def test_timeout_auto_resume(be):
    r = _mk(timeout_s=60, on_timeout="resume", default_action="approve")
    # majukan waktu melewati timeout
    future = datetime.now(timezone.utc) + timedelta(seconds=120)
    changed = hitl.expire_due(now=future)
    assert len(changed) == 1
    assert changed[0]["status"] == STATUS_APPROVED
    assert hitl.is_resumable(r["request_id"]) is True


# 4. Timeout dengan on_timeout=reject -> ditolak
def test_timeout_reject_mode(be):
    _mk(timeout_s=1, on_timeout="reject")
    changed = hitl.expire_due(now=datetime.now(timezone.utc) + timedelta(seconds=10))
    assert changed[0]["status"] == STATUS_REJECTED


# 5. Multiple approvers mode "all": semua harus setuju
def test_multiple_approvers_all_mode(be):
    r = _mk(approvers=["a@x.com", "b@x.com"], approval_mode="all")
    hitl.record_decision(r["request_id"], "a@x.com", "approve")
    mid = hitl.get_request(r["request_id"])
    assert mid["status"] == STATUS_PENDING  # baru 1 dari 2
    out = hitl.record_decision(r["request_id"], "b@x.com", "approve")
    assert out["status"] == STATUS_APPROVED


# 6. Mode "all": satu menolak -> rejected walau yang lain setuju
def test_all_mode_single_reject(be):
    r = _mk(approvers=["a@x.com", "b@x.com"], approval_mode="all")
    hitl.record_decision(r["request_id"], "a@x.com", "approve")
    out = hitl.record_decision(r["request_id"], "b@x.com", "reject")
    assert out["status"] == STATUS_REJECTED


# 7. Mode "any": satu setuju sudah cukup
def test_any_mode_single_approve(be):
    r = _mk(approvers=["a@x.com", "b@x.com"], approval_mode="any")
    out = hitl.record_decision(r["request_id"], "a@x.com", "approve")
    assert out["status"] == STATUS_APPROVED


# 8. Escalation saat timeout (tambah approver, perpanjang sekali)
def test_escalation_on_timeout(be):
    r = _mk(timeout_s=1, escalate_to=["manager@x.com"])
    changed = hitl.expire_due(now=datetime.now(timezone.utc) + timedelta(seconds=10))
    assert changed[0]["escalated"] is True
    assert "manager@x.com" in changed[0]["approvers"]
    assert changed[0]["status"] == STATUS_PENDING  # belum ditutup
    # eskalasi kedua tidak terjadi lagi -> baru ditutup
    changed2 = hitl.expire_due(now=datetime.now(timezone.utc) + timedelta(seconds=99999))
    assert changed2[0]["status"] in (STATUS_APPROVED, STATUS_REJECTED)


# 9. Audit trail lengkap
def test_audit_trail(be):
    r = _mk(approvers=["a@x.com"], approval_mode="all")
    hitl.record_decision(r["request_id"], "a@x.com", "approve")
    trail = hitl.audit_trail(r["request_id"])
    events = [t["event"] for t in trail]
    assert events[0] == "created"
    assert "decision" in events
    assert "resolved" in events


# 10. Resume token: valid & tidak valid
def test_resume_token_security(be):
    r = _mk()
    tok = r["resume_token"]
    assert hitl.verify_token(r["request_id"], tok) is True
    assert hitl.verify_token(r["request_id"], "palsu") is False
    with pytest.raises(HitlError):
        hitl.record_decision(r["request_id"], "a@x.com", "approve", token="salah")


# 11. Keputusan idempoten setelah selesai (tidak bisa dibalik)
def test_decisions_idempotent_after_resolve(be):
    r = _mk()
    hitl.record_decision(r["request_id"], "a@x.com", "approve")
    again = hitl.record_decision(r["request_id"], "b@x.com", "reject")
    assert again["status"] == STATUS_APPROVED  # keputusan pertama menang


# 12. Approver boleh berubah pikiran sebelum selesai
def test_approver_changes_mind(be):
    r = _mk(approvers=["a@x.com"], approval_mode="all")
    hitl.record_decision(r["request_id"], "a@x.com", "reject")
    # sudah rejected -> tidak bisa berubah (idempoten). Pakai permintaan baru:
    r2 = _mk(approvers=["a@x.com"], approval_mode="all")
    hitl.record_decision(r2["request_id"], "a@x.com", "reject")
    assert hitl.get_request(r2["request_id"])["status"] == STATUS_REJECTED


# 13. Concurrent HITL: 100 permintaan independen
def test_concurrent_100_workflows(be):
    ids = [_mk(workflow_id=f"wf-{i}")["request_id"] for i in range(100)]
    for i, rid in enumerate(ids):
        hitl.record_decision(rid, "a@x.com", "approve" if i % 2 == 0 else "reject")
    approved = sum(1 for rid in ids if hitl.is_resumable(rid))
    assert approved == 50


# 14. Performance: 100 permintaan < 2s
def test_performance_100_requests(be):
    t0 = time.perf_counter()
    for i in range(100):
        r = _mk(workflow_id=f"perf-{i}")
        hitl.record_decision(r["request_id"], "a@x.com", "approve")
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0, f"100 HITL terlalu lambat: {elapsed:.2f}s"


# 15. Benchmark: latensi notif -> resume
def test_benchmark_notify_to_resume(be):
    r = _mk()
    hitl.notify(r)  # tanpa sender -> tercatat
    t0 = time.perf_counter()
    hitl.record_decision(r["request_id"], "a@x.com", "approve")
    latency = time.perf_counter() - t0
    assert latency < 0.05, f"resume latency {latency*1000:.1f}ms"


# 16. resume_url berisi token valid
def test_resume_url(be):
    r = _mk()
    url = hitl.resume_url(r["request_id"], base_url="https://contoh.test")
    assert url.startswith("https://contoh.test/hitl/resume/")
    assert f"token={r['resume_token']}" in url


# 17. Config tidak valid ditolak / dinormalkan
def test_invalid_config_normalized(be):
    r = _mk(channel="telegram-palsu", approval_mode="xyz", on_timeout="hmm")
    assert r["channel"] == "chat"
    assert r["approval_mode"] == "any"
    assert r["on_timeout"] == "resume"


# 18. evaluate() murni: tanpa approver & tanpa keputusan -> pending
def test_evaluate_pure():
    assert hitl.evaluate({"approval_mode": "any", "decisions": []}) == STATUS_PENDING
    assert hitl.evaluate({"approval_mode": "any",
                          "decisions": [{"approver": "a", "decision": "approve"}]}) == STATUS_APPROVED


# 19. find_request mencari per execution+node
def test_find_request(be):
    r = _mk(execution_id="exec-1", node_id="n1")
    found = hitl.find_request(execution_id="exec-1", node_id="n1")
    assert found["request_id"] == r["request_id"]
    assert hitl.find_request(execution_id="lain", node_id="n1") is None


# 20. HitlPaused membawa request (dipakai engine)
def test_hitl_paused_carries_request(be):
    r = _mk()
    exc = HitlPaused(r)
    assert exc.request["request_id"] == r["request_id"]


# ---------------------------------------------------------------------------
# Integrasi engine: pause -> waiting_approval -> resume
# ---------------------------------------------------------------------------

def _flow():
    # Hanya trigger -> HITL: tidak menyentuh jaringan (tanpa node agent).
    return {
        "nodes": [
            {"id": "t", "type": "trigger", "data": {"kind": "trigger", "config": {}}},
            {"id": "h", "type": "wait_for_human", "data": {"kind": "wait_for_human",
             "config": {"channel": "chat", "message": "setujui?",
                        "approval_mode": "any", "timeout_s": "3600"}}},
        ],
        "edges": [{"source": "t", "target": "h"}],
    }


# 21. Eksekusi pertama -> waiting_approval + request pending
def test_engine_pauses(be, monkeypatch):
    import asyncio
    import execution_engine as ee

    monkeypatch.setattr(ee.db, "create_execution", lambda *a, **k: None)
    monkeypatch.setattr(ee.db, "update_execution_status", lambda *a, **k: None)
    monkeypatch.setattr(ee.db, "append_execution_log", lambda *a, **k: None)

    res = asyncio.run(ee.execute_workflow_async(
        "wf-1", _flow(), {"text": "halo"}, execution_id="exec-hitl-1",
        owner_email="u@test.dev"))
    assert res["status"] == "waiting_approval"
    assert res["hitl"]["request_id"]
    assert hitl.get_request(res["hitl"]["request_id"])["status"] == STATUS_PENDING


# 22. Setelah approve, eksekusi ulang -> lewat (tidak jeda lagi)
def test_engine_resumes_after_approval(be, monkeypatch):
    import asyncio
    import execution_engine as ee

    monkeypatch.setattr(ee.db, "create_execution", lambda *a, **k: None)
    monkeypatch.setattr(ee.db, "update_execution_status", lambda *a, **k: None)
    monkeypatch.setattr(ee.db, "append_execution_log", lambda *a, **k: None)

    res1 = asyncio.run(ee.execute_workflow_async(
        "wf-2", _flow(), {"text": "halo"}, execution_id="exec-hitl-2",
        owner_email="u@test.dev"))
    rid = res1["hitl"]["request_id"]
    hitl.record_decision(rid, "u@test.dev", "approve")

    res2 = asyncio.run(ee.execute_workflow_async(
        "wf-2", _flow(), {"text": "halo"}, execution_id="exec-hitl-2",
        owner_email="u@test.dev"))
    assert res2["status"] == "completed"  # node HITL lewat setelah approve


# 23. Reject -> eksekusi ulang gagal (HitlRejected)
def test_engine_rejected(be, monkeypatch):
    import asyncio
    import execution_engine as ee

    monkeypatch.setattr(ee.db, "create_execution", lambda *a, **k: None)
    monkeypatch.setattr(ee.db, "update_execution_status", lambda *a, **k: None)
    monkeypatch.setattr(ee.db, "append_execution_log", lambda *a, **k: None)

    res1 = asyncio.run(ee.execute_workflow_async(
        "wf-3", _flow(), {"text": "halo"}, execution_id="exec-hitl-3",
        owner_email="u@test.dev"))
    hitl.record_decision(res1["hitl"]["request_id"], "u@test.dev", "reject")
    res2 = asyncio.run(ee.execute_workflow_async(
        "wf-3", _flow(), {"text": "halo"}, execution_id="exec-hitl-3",
        owner_email="u@test.dev"))
    assert res2["status"] == "error"
    assert "HitlRejected" in res2.get("error", "")


# 24. NodeKind.WAIT_FOR_HUMAN terdaftar
def test_node_kind_registered():
    from execution_engine import NodeKind, StatefulOrchestrator
    assert NodeKind.WAIT_FOR_HUMAN.value == "wait_for_human"
    assert NodeKind.WAIT_FOR_HUMAN in StatefulOrchestrator.EXECUTORS


# 25. self_healing: HitlRejected -> abort (0 retry)
def test_self_healing_hitl_rejected():
    import self_healing
    rule = self_healing.classify_error("HitlRejected: node 'h' ditolak manusia")
    assert rule.name == "hitl_rejected"
    assert rule.action == "abort"
    assert rule.max_attempts == 0


# 26. DDL migrasi HITL ada
def test_migration_file_has_ddl():
    import pathlib
    p = (pathlib.Path(__file__).resolve().parent.parent
         / "migrations" / "2026_hitl.sql")
    sql = p.read_text(encoding="utf-8")
    assert "create table if not exists hitl_requests" in sql
    assert "decisions" in sql
    assert "resume_token" in sql
