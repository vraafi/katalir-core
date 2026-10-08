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


# ---------------------------------------------------------------------------
# Regresi temuan hard-test LIVE (Redis nyata) — Okt 2026
# ---------------------------------------------------------------------------

# 13. `KATALIR_VISIBILITY_TIMEOUT` BENAR-BENAR dibaca (dulu hanya didokumentasi)
def test_13_visibility_timeout_dibaca_dari_env(monkeypatch):
    monkeypatch.setenv("KATALIR_VISIBILITY_TIMEOUT", "1.5")
    b = qm.RedisQueueBackend(url="redis://127.0.0.1:6379/0")
    assert b.visibility_timeout == 1.5
    # argumen eksplisit MENANG atas env
    b2 = qm.RedisQueueBackend(url="redis://127.0.0.1:6379/0",
                              visibility_timeout=7.0)
    assert b2.visibility_timeout == 7.0
    monkeypatch.delenv("KATALIR_VISIBILITY_TIMEOUT", raising=False)
    assert qm.RedisQueueBackend(url="redis://127.0.0.1:6379/0").visibility_timeout == 60.0


# 14. QueueManager meneruskan visibility_timeout + melaporkannya di health()
def test_14_queue_manager_laporkan_visibility_timeout(monkeypatch):
    monkeypatch.setenv("KATALIR_VISIBILITY_TIMEOUT", "2.5")
    m = qm.QueueManager(backend="auto", redis_url="redis://127.0.0.1:6399/0")
    assert "visibility_timeout" in m.health()
    # backend memori -> tidak ada lease (0.0), tapi kuncinya tetap ada
    assert m.health()["visibility_timeout"] == 0.0


# 15. queue_bridge: fungsi sinkron ber-`asyncio.create_task` dari thread worker
def test_15_queue_bridge_memberi_event_loop_ke_thread():
    """Tanpa bridge ini, `launch_execution` gagal 'no running event loop'."""
    import asyncio

    import queue_bridge

    def sinkron_yang_butuh_loop(x):
        # persis pola execution_engine.launch_execution
        return asyncio.create_task(asyncio.sleep(0, result=x * 2))

    async def _tunggu(task):
        return await task

    runner = queue_bridge.LoopRunner(name="test-bridge")
    try:
        # dipanggil dari THREAD BIASA (tanpa event loop) -> dulu RuntimeError
        hasil: list = []
        th = threading.Thread(target=lambda: hasil.append(
            runner.call(sinkron_yang_butuh_loop, 21)))
        th.start()
        th.join(timeout=10)
        assert not th.is_alive(), "run_sync menggantung"
        assert hasil, "run_sync tidak mengembalikan Task"

        task = hasil[0]
        # Task harus benar-benar SELESAI (bukan dibatalkan saat loop ditutup).
        # Kalau implementasinya `asyncio.run()` sekali jalan, loop ditutup dan
        # task ini langsung dibatalkan -> assert di bawah GAGAL.
        fut = asyncio.run_coroutine_threadsafe(_tunggu(task), runner.start())
        assert fut.result(timeout=5) == 42
        assert task.done() and not task.cancelled()
    finally:
        runner.stop()


# 16. /queue/* endpoint baru terdaftar + wajib token
def test_16_endpoint_queue_baru_terdaftar():
    import api_server
    paths = {r.path for r in api_server.app.routes}
    for p in ("/queue/health", "/queue/stats", "/queue/enqueue", "/queue/dlq",
              "/queue/recover", "/queue/workers", "/queue/reclaim",
              "/queue/dlq/replay", "/queue/ui"):
        assert p in paths, f"endpoint hilang: {p}"
    # tanpa token -> 401 (bukan 500)
    from fastapi.testclient import TestClient
    with TestClient(api_server.app) as c:
        for p in ("/queue/workers", "/queue/stats", "/queue/dlq"):
            assert c.get(p).status_code == 401
        assert c.get("/queue/ui").status_code == 200


# 17. put() memakai satu skrip Lua (1 round-trip) — inti throughput 10k job
def test_17_put_pakai_lua_satu_round_trip(monkeypatch):
    """Kalau put() kembali ke pipeline 2 perintah, throughput jatuh -> gagal."""
    calls: list = []

    class FakeRedis:
        def __init__(self):
            self.store = {}

        def script_load(self, src):
            calls.append("script_load")
            return "sha-put"

        def evalsha(self, sha, numkeys, *args):
            calls.append("evalsha")
            return 1

        def eval(self, src, numkeys, *args):  # noqa: A003
            calls.append("eval")
            return 1

    b = qm.RedisQueueBackend(url="redis://x/0")
    fake = FakeRedis()
    monkeypatch.setattr(b, "_client", lambda: fake)
    b.put(qm.Job(id="j1", payload={"n": 1}))
    assert "evalsha" in calls, f"put() tidak memakai Lua: {calls}"
    assert "script_load" in calls
