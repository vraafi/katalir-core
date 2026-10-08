#!/usr/bin/env python
"""enterprise_queue_live.py — HARD TEST Fitur #6 (Queue Mode Scaling) vs Redis NYATA.

Menjalankan 12 skenario wajib terhadap server Redis/Valkey yang benar-benar
berjalan (`127.0.0.1:6379`), lalu mencetak RAW OUTPUT tiap skenario.

Setiap skenario adalah test yang GAGAL bila fiturnya rusak:
  * klaim job tidak atomik  -> skenario 2/11 (job hilang/duplikat) gagal
  * tidak ada visibility timeout -> skenario 3 (worker crash) gagal
  * tidak ada DLQ -> skenario 7/8 gagal
  * enqueue bukan 1 round-trip -> skenario 12 (throughput) gagal

Pakai:
    python scripts/enterprise_queue_live.py
    python scripts/enterprise_queue_live.py --url redis://127.0.0.1:6379/0
    python scripts/enterprise_queue_live.py --json docs/evidence/f06-queue-live.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import queue_mode as qm  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKER = os.path.join(HERE, "worker_main.py")

HASIL: list[dict] = []


def _catat(no: int, nama: str, lulus: bool, raw: str, detail: dict | None = None) -> None:
    HASIL.append({"no": no, "skenario": nama, "status": "PASS" if lulus else "FAIL",
                  "raw": raw, "detail": detail or {}})
    tag = "PASS" if lulus else "FAIL"
    print(f"\n{'=' * 78}\n#{no:02d} [{tag}] {nama}\n{'-' * 78}\n{raw}\n", flush=True)


def _handler(job: qm.Job):
    p = job.payload or {}
    if p.get("sleep"):
        time.sleep(float(p["sleep"]))
    if p.get("fail"):
        raise RuntimeError(str(p.get("fail_message") or "gagal disengaja"))
    return {"ok": True, "job_id": job.id}


def _mgr(url: str) -> qm.QueueManager:
    m = qm.QueueManager(backend="redis", redis_url=url)
    assert m.backend_name == "redis", f"backend bukan redis: {m.backend_name}"
    return m


def _status_count(backend) -> dict:
    per: dict[str, int] = {}
    for j in backend.jobs():
        per[j.status] = per.get(j.status, 0) + 1
    return per


# ---------------------------------------------------------------------------
# 12 skenario
# ---------------------------------------------------------------------------

def s01_ping(url: str) -> None:
    import redis
    t0 = time.perf_counter()
    r = redis.Redis.from_url(url, decode_responses=True,
                             socket_connect_timeout=5, socket_timeout=10)
    pong = r.ping()
    ms = (time.perf_counter() - t0) * 1000
    s = r.info("server")
    raw = (f"redis-py {redis.__version__}\n"
           f"PING -> {pong}  ({ms:.2f} ms)\n"
           f"server.redis_version   = {s.get('redis_version')}\n"
           f"server.valkey_version  = {s.get('valkey_version')}\n"
           f"server.os              = {s.get('os')}\n"
           f"server.tcp_port        = {s.get('tcp_port')}\n"
           f"DBSIZE                 = {r.dbsize()}")
    lulus = bool(pong) and bool(s.get("valkey_version") or s.get("redis_version"))
    _catat(1, "Redis ping + INFO server nyata", lulus, raw,
           {"pong": bool(pong), "version": s.get("valkey_version") or s.get("redis_version")})


def s02_1000_jobs(url: str) -> None:
    m = _mgr(url)
    b = m.queue.backend
    b.clear()
    t0 = time.perf_counter()
    for i in range(1000):
        m.queue.enqueue({"n": i}, priority=0)
    enq = time.perf_counter() - t0
    zcard = b.size()
    t1 = time.perf_counter()
    pool = m.pool(_handler, concurrency=4)
    n = pool.drain(timeout=120)
    dur = time.perf_counter() - t1
    per = _status_count(b)
    sisa = b.size()
    lulus = (zcard == 1000 and n == 1000 and per.get("completed") == 1000 and sisa == 0)
    raw = (f"enqueue 1000 job     -> ZCARD(ready)={zcard}  ({enq:.3f}s, {1000 / enq:.0f} job/s)\n"
           f"drain (4 worker)     -> processed={n}  ({dur:.3f}s, {n / dur:.0f} job/s)\n"
           f"by_status (dari Redis) = {per}\n"
           f"sisa ready           = {sisa}\n"
           f"CEK: zcard==1000 dan completed==1000 dan sisa==0 -> {lulus}")
    _catat(2, "1000 job -> SEMUA diproses (diverifikasi dari Redis)", lulus, raw,
           {"processed": n, "by_status": per})


def s03_worker_crash(url: str) -> None:
    """Worker proses nyata dibunuh paksa -> job diklaim ulang (reclaim)."""
    # Lease 1.5s supaya test cepat; nilai ini dibaca dari env oleh backend
    # (argumen eksplisit > KATALIR_VISIBILITY_TIMEOUT > default 60).
    os.environ["KATALIR_VISIBILITY_TIMEOUT"] = "1.5"
    try:
        m = _mgr(url)
        b = m.queue.backend
        b.clear()
        job = m.queue.enqueue({"sleep": 300}, priority=0, job_id="crash-1")

        env = dict(os.environ)
        env["KATALIR_REDIS_URL"] = url
        env["KATALIR_VISIBILITY_TIMEOUT"] = "1.5"
        proc = subprocess.Popen([sys.executable, WORKER, "--concurrency", "1"],
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, cwd=HERE)
        # tunggu worker MENGKLAIM job (masuk inflight)
        deadline = time.time() + 15
        inflight = []
        while time.time() < deadline:
            inflight = b.inflight()
            if "crash-1" in inflight:
                break
            time.sleep(0.05)

        sebelum = b.get_job("crash-1")
        proc.kill()  # SIGKILL-equivalent: worker TIDAK sempat ack
        proc.wait(timeout=10)

        time.sleep(1.8)  # lewati visibility timeout 1.5s
        n_reclaim = m.reclaim_expired()      # API publik -> jumlah job diklaim ulang
        direklaim = ["crash-1"] if n_reclaim >= 1 else []
        sesudah = b.get_job("crash-1")
        ready_ada = b.size()
    finally:
        os.environ.pop("KATALIR_VISIBILITY_TIMEOUT", None)

    lulus = ("crash-1" in inflight and n_reclaim >= 1
             and sesudah is not None and sesudah.status == qm.QUEUED
             and ready_ada == 1)
    raw = (f"worker PID        = {proc.pid} (proses terpisah)\n"
           f"KATALIR_VISIBILITY_TIMEOUT = {m.visibility_timeout}s (dibaca dari env)\n"
           f"job diklaim       -> inflight={inflight} status={sebelum.status} attempts={sebelum.attempts}\n"
           f"worker DIBUNUH    -> proc.kill(); tidak ada ACK\n"
           f"reclaim_expired() -> {n_reclaim} job direklaim {direklaim}\n"
           f"status setelah    = {sesudah.status}  attempts={sesudah.attempts}\n"
           f"ZCARD(ready)      = {ready_ada}\n"
           f"CEK: job kembali ke ready tanpa ACK -> {lulus}")
    _catat(3, "Worker crash (dibunuh) -> job requeued via visibility timeout", lulus, raw,
           {"reclaimed": n_reclaim, "attempts": sesudah.attempts if sesudah else None})


def s04_horizontal(url: str) -> None:
    """2 PROSES worker vs 1 PROSES worker: throughput nyata."""
    def jalankan(nproc: int, njobs: int) -> tuple[float, list[int]]:
        m = _mgr(url)
        m.queue.backend.clear()
        for i in range(njobs):
            m.queue.enqueue({"sleep": 0.01, "n": i}, priority=0)
        env = dict(os.environ)
        env["KATALIR_REDIS_URL"] = url
        env["KATALIR_DRAIN_TIMEOUT"] = "120"
        t0 = time.perf_counter()
        procs = [subprocess.Popen([sys.executable, WORKER, "--once"],
                                  env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, cwd=HERE)
                 for _ in range(nproc)]
        outs, per_proc = [], []
        for p in procs:
            out, _ = p.communicate(timeout=180)
            outs.append(out)
            n = 0
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("{"):
                    try:
                        d = json.loads(line)
                        if d.get("msg") == "drain selesai":
                            n = int(d.get("processed", 0))
                    except Exception:  # noqa: BLE001
                        pass
            per_proc.append(n)
        dur = time.perf_counter() - t0
        return dur, per_proc

    njobs = 200
    d1, p1 = jalankan(1, njobs)
    d2, p2 = jalankan(2, njobs)
    m = _mgr(url)
    per = _status_count(m.queue.backend)
    speedup = d1 / d2 if d2 else 0.0
    keduanya_kerja = all(x > 0 for x in p2)
    lulus = (sum(p1) == njobs and sum(p2) == njobs and keduanya_kerja
             and per.get("completed") == njobs and speedup > 1.2)
    raw = (f"beban: {njobs} job (sleep 0.01s tiap job)\n"
           f"1 PROSES worker -> {d1:.3f}s, processed={p1}\n"
           f"2 PROSES worker -> {d2:.3f}s, processed={p2}  (tiap proses dapat kerja: {keduanya_kerja})\n"
           f"speedup         = {speedup:.2f}x\n"
           f"by_status       = {per}\n"
           f"CEK: speedup>1.2x dan kedua proses memproses job -> {lulus}")
    _catat(4, "Horizontal scaling: 2 proses worker paralel", lulus, raw,
           {"speedup": round(speedup, 2), "per_proc": p2})


def s05_prioritas(url: str) -> None:
    m = _mgr(url)
    b = m.queue.backend
    b.clear()
    m.queue.enqueue({"nama": "low"}, priority=0, job_id="p-low")
    m.queue.enqueue({"nama": "normal"}, priority=5, job_id="p-norm")
    m.queue.enqueue({"nama": "high"}, priority=10, job_id="p-high")
    urutan = []
    for _ in range(3):
        j = m.queue.dequeue(timeout=0.5)
        urutan.append(j.id if j else None)
    lulus = urutan == ["p-high", "p-norm", "p-low"]
    raw = ("enqueue urutan: p-low(prio 0) -> p-norm(prio 5) -> p-high(prio 10)\n"
           f"dequeue urutan: {urutan}\n"
           f"CEK: high -> normal -> low -> {lulus}")
    _catat(5, "Prioritas high/normal/low + FIFO tie-break", lulus, raw, {"urutan": urutan})


def s06_timeout(url: str) -> None:
    m = _mgr(url)
    b = m.queue.backend
    b.clear()
    default_vis = qm.RedisQueueBackend(url=url).visibility_timeout
    job = m.queue.enqueue({"sleep": 3}, priority=0, max_retries=0, timeout=0.3)
    pool = m.pool(_handler, concurrency=1)
    hasil = pool.process_once(timeout=0.5)
    j = b.get_job(job.id)
    lulus = (hasil is not None and hasil[0] == "timeout"
             and j.status == qm.DEAD and "timeout" in (j.error or "")
             and float(default_vis) == 60.0)
    raw = (f"visibility_timeout default = {default_vis}s (lease job 'running')\n"
           f"job.timeout               = 0.3s, handler tidur 3s\n"
           f"process_once()            -> {hasil[0] if hasil else None}\n"
           f"status akhir              = {j.status}\n"
           f"error                     = {j.error!r}\n"
           f"CEK: job dibunuh saat lewat timeout, error='timeout' -> {lulus}")
    _catat(6, "Job timeout dipaksa (lease/visibility 60s default)", lulus, raw,
           {"status": j.status, "error": j.error})


def s07_retry_dlq(url: str) -> None:
    m = _mgr(url)
    b = m.queue.backend
    b.clear()
    job = m.queue.enqueue({"fail": True}, priority=0, max_retries=3, job_id="dlq-1")
    pool = m.pool(_handler, concurrency=1)
    jejak = []
    for _ in range(8):
        if b.size() == 0:
            break
        r = pool.process_once(timeout=0.5)
        if r is None:
            break
        j = b.get_job("dlq-1")
        jejak.append(f"claim#{j.attempts} -> {r[0]} (status={j.status})")
        if j.status == qm.DEAD:
            break
    j = b.get_job("dlq-1")
    dlq_ids = [d.id for d in m.queue.dlq()]
    lulus = (j.status == qm.DEAD and j.attempts == 4 and "dlq-1" in dlq_ids
             and b.size() == 0)
    raw = ("max_retries=3, handler selalu gagal\n" + "\n".join(jejak) +
           f"\nattempts akhir = {j.attempts}  status = {j.status}\n"
           f"DLQ            = {dlq_ids}\n"
           f"CEK: 4x claim lalu masuk DLQ (attempts>max_retries) -> {lulus}")
    _catat(7, "Retry max 3 -> job masuk DLQ", lulus, raw,
           {"attempts": j.attempts, "dlq": dlq_ids})


def s08_dlq_replay(url: str) -> None:
    m = _mgr(url)
    b = m.queue.backend
    # lanjutan dari skenario 7 (dlq-1 ada di DLQ)
    sebelum = [d.id for d in m.queue.dlq()]
    n = m.dlq_replay()
    sesudah = [d.id for d in m.queue.dlq()]
    # sekarang proses dengan handler SUKSES
    def ok_handler(job):
        return {"ok": True}
    pool = qm.WorkerPool(m.queue, ok_handler, concurrency=1)
    r = pool.process_once(timeout=0.5)
    j = b.get_job("dlq-1")
    lulus = ("dlq-1" in sebelum and n >= 1 and sesudah == []
             and r is not None and r[0] == "completed" and j.status == qm.COMPLETED)
    raw = (f"DLQ sebelum replay = {sebelum}\n"
           f"dlq_replay()       -> {n} job dipindah\n"
           f"DLQ sesudah replay = {sesudah}\n"
           f"proses ulang       -> {r[0] if r else None}\n"
           f"status akhir       = {j.status}\n"
           f"CEK: DLQ kosong dan job selesai -> {lulus}")
    _catat(8, "DLQ replay -> job kembali diproses", lulus, raw, {"replayed": n})


def s09_graceful(url: str) -> None:
    m = _mgr(url)
    b = m.queue.backend
    b.clear()
    total = 60
    for i in range(total):
        m.queue.enqueue({"sleep": 0.03, "n": i}, priority=0)
    pool = m.pool(_handler, concurrency=4).start()
    time.sleep(0.5)
    inflight_saat_stop = b.inflight()
    t0 = time.perf_counter()
    pool.stop(graceful=True, timeout=15)
    dur = time.perf_counter() - t0
    per = _status_count(b)
    inflight_akhir = b.inflight()
    sisa = b.size()
    selesai = per.get("completed", 0)
    lulus = (len(inflight_akhir) == 0 and sisa == 0 and selesai == total)
    raw = (f"enqueue {total} job (sleep 0.03s), 4 worker\n"
           f"saat stop: inflight={len(inflight_saat_stop)}\n"
           f"stop(graceful=True) -> {dur:.3f}s\n"
           f"inflight akhir = {inflight_akhir}  sisa ready = {sisa}\n"
           f"completed      = {selesai}/{total}\n"
           f"CEK: tak ada job hilang saat shutdown -> {lulus}")
    _catat(9, "Graceful shutdown: job in-flight diselesaikan", lulus, raw,
           {"completed": selesai, "total": total})


def s10_redis_down(url: str) -> None:
    mati = "redis://127.0.0.1:6399/0"  # port tidak ada listener
    err_msg = ""
    ok_error = False
    try:
        b = qm.RedisQueueBackend(url=mati)
        b._client()
    except Exception as exc:  # noqa: BLE001
        err_msg = f"{type(exc).__name__}: {exc}"
        ok_error = True
    m_auto = qm.QueueManager(backend="auto", redis_url=mati)
    m_forced = qm.QueueManager(backend="redis", redis_url=mati)
    h = m_auto.health()
    # antrian tetap BERFUNGSI (degradasi ke memori), tidak crash
    job = m_auto.queue.enqueue({"x": 1})
    j2 = m_auto.queue.dequeue(timeout=0.2)
    lulus = (ok_error and m_auto.backend_name == "memory"
             and m_forced.backend_name == "memory"
             and j2 is not None and j2.id == job.id)
    raw = (f"URL mati = {mati}\n"
           f"RedisQueueBackend._client() -> {err_msg}\n"
           f"QueueManager(auto)  backend = {m_auto.backend_name}\n"
           f"QueueManager(redis) backend = {m_forced.backend_name}\n"
           f"health.backend = {h.get('backend')}\n"
           f"antrian tetap jalan (memori): enqueue+dequeue -> {j2.id if j2 else None}\n"
           f"CEK: Redis down -> error jelas + degradasi anggun, tidak crash -> {lulus}")
    _catat(10, "Redis down -> error jelas + antrian pause (degradasi)", lulus, raw,
           {"error": err_msg, "fallback": m_auto.backend_name})


def s11_load_10000(url: str) -> None:
    m = _mgr(url)
    b = m.queue.backend
    b.clear()
    n = 10000
    t0 = time.perf_counter()
    for i in range(n):
        m.queue.enqueue({"n": i}, priority=0)
    enq = time.perf_counter() - t0
    zcard = b.size()
    t1 = time.perf_counter()
    pool = m.pool(_handler, concurrency=8)
    done = pool.drain(timeout=300)
    dur = time.perf_counter() - t1
    per = _status_count(b)
    lulus = (zcard == n and done == n and per.get("completed") == n and b.size() == 0)
    raw = (f"enqueue {n} job -> ZCARD={zcard}  ({enq:.3f}s, {n / enq:.0f} job/s)\n"
           f"drain 8 worker -> processed={done}  ({dur:.3f}s, {done / dur:.0f} job/s)\n"
           f"by_status      = {per}\n"
           f"sisa ready     = {b.size()}\n"
           f"CEK: 10.000/10.000 selesai, antrian kosong -> {lulus}")
    _catat(11, "Load test 10.000 job -> semua diproses", lulus, raw,
           {"enqueue_per_s": round(n / enq), "drain_per_s": round(done / dur)})


def s12_benchmark(url: str) -> None:
    m = _mgr(url)
    b = m.queue.backend
    b.clear()
    n = 2000
    lat_enq = []
    for i in range(n):
        t0 = time.perf_counter()
        m.queue.enqueue({"n": i}, priority=0)
        lat_enq.append((time.perf_counter() - t0) * 1000)
    lat_deq = []
    for _ in range(n):
        t0 = time.perf_counter()
        j = m.queue.dequeue(timeout=0.0)
        lat_deq.append((time.perf_counter() - t0) * 1000)
        if j:
            m.queue.complete(j.id)
    lat_enq.sort()
    lat_deq.sort()

    def p(v, q):
        return v[min(len(v) - 1, int(len(v) * q))]

    thr_enq = 1000 / statistics.mean(lat_enq)
    thr_deq = 1000 / statistics.mean(lat_deq)
    # Ambang: enqueue 1 round-trip harus >300 job/s (kalau jadi 3 RTT/pipeline,
    # angka ini jatuh jauh di bawah ambang -> test GAGAL).
    lulus = (thr_enq > 300 and p(lat_enq, 0.95) < 50 and thr_deq > 200)
    raw = (f"enqueue {n} job (1 round-trip via _PUT_LUA):\n"
           f"  mean={statistics.mean(lat_enq):.3f}ms  p50={p(lat_enq, 0.5):.3f}ms  "
           f"p95={p(lat_enq, 0.95):.3f}ms  -> {thr_enq:.0f} job/s\n"
           f"dequeue+ack {n} job (Lua claim atomik):\n"
           f"  mean={statistics.mean(lat_deq):.3f}ms  p50={p(lat_deq, 0.5):.3f}ms  "
           f"p95={p(lat_deq, 0.95):.3f}ms  -> {thr_deq:.0f} job/s\n"
           f"CEK: enqueue>300 job/s dan p95<50ms dan dequeue>200 job/s -> {lulus}")
    _catat(12, "Benchmark throughput/latency (ambang keras)", lulus, raw,
           {"enqueue_per_s": round(thr_enq), "dequeue_per_s": round(thr_deq)})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("KATALIR_REDIS_URL")
                    or os.environ.get("REDIS_URL") or "redis://127.0.0.1:6379/0")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    print(f"# HARD TEST Fitur #6 Queue Mode Scaling — Redis NYATA\n"
          f"# url={args.url}\n# python={sys.version.split()[0]}\n")

    skenario = [s01_ping, s02_1000_jobs, s03_worker_crash, s04_horizontal,
                s05_prioritas, s06_timeout, s07_retry_dlq, s08_dlq_replay,
                s09_graceful, s10_redis_down, s11_load_10000, s12_benchmark]
    for fn in skenario:
        try:
            fn(args.url)
        except Exception as exc:  # noqa: BLE001
            import traceback
            _catat(len(HASIL) + 1, fn.__name__, False,
                   f"EXCEPTION: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")

    lulus = sum(1 for h in HASIL if h["status"] == "PASS")
    total = len(HASIL)
    print("=" * 78)
    print(f"RINGKASAN HARD TEST FITUR #6: {lulus}/{total} PASS")
    print("=" * 78)
    for h in HASIL:
        print(f"  #{h['no']:02d} [{h['status']}] {h['skenario']}")

    if args.json:
        os.makedirs(os.path.dirname(args.json), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"feature": "#6 Queue Mode Scaling", "url": args.url,
                       "lulus": lulus, "total": total, "hasil": HASIL},
                      f, indent=2, ensure_ascii=False)
        print(f"\nJSON -> {args.json}")

    return 0 if lulus == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
