# tests/test_queue_mode.py — Fitur #6 hard test (12 skenario, Okt 2026)
# Deterministik, tanpa Redis: backend memori. Handler disuntik.
from __future__ import annotations

import threading
import time

import pytest

import queue_mode as qm


def _handler_ok(job):
    return {"ok": job.payload.get("n")}


# 1. 100 workflow -> semua diproses
def test_01_100_jobs_processed():
    q = qm.JobQueue()
    pool = qm.WorkerPool(q, _handler_ok)
    for i in range(100):
        q.enqueue({"n": i})
    n = pool.drain()
    assert n == 100
    assert q.stats()["by_status"].get("completed") == 100
    assert q.stats()["queued"] == 0


# 2. Worker crash -> job requeued
def test_02_worker_crash_requeue():
    q = qm.JobQueue()
    q.enqueue({"n": 1})
    job = q.dequeue()                     # ambil -> RUNNING (inflight)
    assert job.status == qm.RUNNING
    assert q.backend.inflight() == [job.id]
    n = q.recover_inflight()              # simulasi worker mati
    assert n == 1
    assert q.backend.inflight() == []
    lagi = q.dequeue()
    assert lagi is not None and lagi.id == job.id


# 3. Redis down -> degradasi anggun ke memori
def test_03_redis_down_graceful(monkeypatch):
    monkeypatch.delenv("KATALIR_REDIS_URL", raising=False)
    mgr = qm.QueueManager(backend="redis")
    assert mgr.backend_name == "memory"
    assert mgr.health()["backend"] == "memory"
    # tetap berfungsi
    mgr.queue.enqueue({"n": 1})
    pool = mgr.pool(_handler_ok)
    assert pool.drain() == 1


# 4. Concurrent workers (5)
def test_04_concurrent_workers():
    q = qm.JobQueue()
    pool = qm.WorkerPool(q, _handler_ok, concurrency=5)
    for i in range(50):
        q.enqueue({"n": i})
    pool.start()
    batas = time.time() + 5
    while q.stats()["by_status"].get("completed", 0) < 50 and time.time() < batas:
        time.sleep(0.01)
    pool.stop()
    assert q.stats()["by_status"].get("completed") == 50
    assert pool.health()["workers"] == 0  # sudah dihentikan


# 5. Prioritas job
def test_05_priority():
    q = qm.JobQueue()
    q.enqueue({"n": "low"}, priority=1)
    q.enqueue({"n": "high"}, priority=10)
    q.enqueue({"n": "mid"}, priority=5)
    urutan = [q.dequeue().payload["n"] for _ in range(3)]
    assert urutan == ["high", "mid", "low"]


# 6. Job timeout
def test_06_timeout():
    def lambat(job):
        time.sleep(0.3)
        return "selesai"
    q = qm.JobQueue()
    pool = qm.WorkerPool(q, lambat)
    q.enqueue({"n": 1}, timeout=0.05, max_retries=0)
    status, job = pool.process_once()
    assert status == "timeout"
    assert job.status == qm.DEAD


# 7. Retry (max 3)
def test_07_retry_max():
    percobaan = {"n": 0}

    def gagal(job):
        percobaan["n"] += 1
        raise RuntimeError("boom")
    q = qm.JobQueue()
    pool = qm.WorkerPool(q, gagal)
    q.enqueue({"x": 1}, max_retries=3)
    for _ in range(10):
        if pool.process_once() is None:
            break
    assert percobaan["n"] == 4            # 1 awal + 3 retry
    assert q.stats()["dlq"] == 1


def test_07b_retry_lalu_sukses():
    percobaan = {"n": 0}

    def kadang(job):
        percobaan["n"] += 1
        if percobaan["n"] < 3:
            raise RuntimeError("sementara")
        return "ok"
    q = qm.JobQueue()
    pool = qm.WorkerPool(q, kadang)
    q.enqueue({"x": 1}, max_retries=3)
    for _ in range(6):
        if q.stats()["by_status"].get("completed"):
            break
        pool.process_once()
    assert q.stats()["by_status"].get("completed") == 1


# 8. Dead letter queue
def test_08_dlq():
    def gagal(job):
        raise ValueError("permanen")
    q = qm.JobQueue()
    pool = qm.WorkerPool(q, gagal)
    q.enqueue({"x": 1}, max_retries=0)
    pool.process_once()
    dlq = q.dlq()
    assert len(dlq) == 1 and dlq[0].status == qm.DEAD
    assert "ValueError" in dlq[0].error


# 9. Load test 1000 job
def test_09_load_1000():
    q = qm.JobQueue()
    pool = qm.WorkerPool(q, _handler_ok)
    for i in range(1000):
        q.enqueue({"n": i})
    t0 = time.perf_counter()
    n = pool.drain(timeout=20)
    dt = time.perf_counter() - t0
    assert n == 1000
    assert dt < 10, f"1000 job terlalu lambat: {dt:.2f}s"


# 10. Scaling: tambah worker runtime
def test_10_scale_runtime():
    q = qm.JobQueue()
    pool = qm.WorkerPool(q, _handler_ok, concurrency=1)
    pool.start()
    assert pool.health()["workers"] == 1
    aktif = pool.scale(5)
    assert aktif == 5
    for i in range(30):
        q.enqueue({"n": i})
    batas = time.time() + 5
    while q.stats()["by_status"].get("completed", 0) < 30 and time.time() < batas:
        time.sleep(0.01)
    pool.stop()
    assert q.stats()["by_status"].get("completed") == 30


# 11. Graceful shutdown
def test_11_graceful_shutdown():
    def lambat(job):
        time.sleep(0.05)
        return "ok"
    q = qm.JobQueue()
    pool = qm.WorkerPool(q, lambat, concurrency=2)
    for i in range(10):
        q.enqueue({"n": i})
    pool.start()
    time.sleep(0.02)
    pool.stop(graceful=True, timeout=3)
    assert q.backend.inflight() == []     # tidak ada job menggantung
    assert pool.health()["workers"] == 0


# 12. Benchmark throughput
def test_12_throughput_benchmark():
    q = qm.JobQueue()
    pool = qm.WorkerPool(q, _handler_ok)
    for i in range(500):
        q.enqueue({"n": i})
    t0 = time.perf_counter()
    pool.drain(timeout=20)
    dt = time.perf_counter() - t0
    tps = 500 / dt if dt else 0
    assert tps > 100, f"throughput terlalu rendah: {tps:.0f} job/s"
