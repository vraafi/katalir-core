#!/usr/bin/env python
"""worker_main.py — Worker proses untuk Queue Mode Scaling (Fitur #6).

Worker adalah PROSES TERPISAH dari instance API: instance utama hanya menerima
request dan mendorong job ke antrian (Redis), lalu N worker mengambil job,
menjalankannya, dan menulis hasilnya. Karena seluruh state antrian hidup di
Redis (bukan di memori proses), worker bisa ditambah/dimatikan kapan saja dan
dijalankan di mesin lain — inilah "horizontal scaling".

Pakai:
    python worker_main.py                        # concurrency = CPU count
    python worker_main.py --concurrency 4
    python worker_main.py --once                 # proses antrian lalu keluar
    python worker_main.py --stats                # cetak health lalu keluar

Env:
    KATALIR_REDIS_URL / REDIS_URL   redis://host:port/db
    KATALIR_WORKER_CONCURRENCY      default: jumlah CPU
    KATALIR_VISIBILITY_TIMEOUT      detik sebelum job 'running' dianggap
                                    milik worker MATI (default 60)

Keluar dengan SIGINT/SIGTERM: graceful — job yang sedang jalan diselesaikan
dulu (batas `--grace` detik), lalu antrian tidak diambil lagi.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import queue_mode as qm  # noqa: E402


def _handler(job: qm.Job):
    """Jalankan satu job.

    Di produksi payload memuat `workflow_id`/`flow_data` dan handler memanggil
    `execution_engine.launch_execution` (sama seperti worker in-process di
    `api_server._queue_handler`). Handler ini juga menerima job "uji"
    (`{"sleep": n}` / `{"fail": true}`) supaya antrian dapat di-hard-test
    end-to-end tanpa memerlukan workflow nyata.
    """
    p = job.payload or {}

    if p.get("sleep"):
        time.sleep(float(p["sleep"]))
    if p.get("fail"):
        raise RuntimeError(str(p.get("fail_message") or "job gagal disengaja"))

    if p.get("workflow_id"):
        # `launch_execution` sinkron tapi memakai `asyncio.create_task` di
        # dalamnya -> wajib dijalankan di dalam event loop. Worker ini jalan di
        # thread tanpa loop, jadi pakai bridge (loop persisten) supaya job
        # workflow tidak selalu DEAD dengan "no running event loop".
        import queue_bridge
        import execution_engine as engine
        return queue_bridge.run_sync(
            engine.launch_execution,
            p.get("workflow_id"), p.get("flow_data") or {},
            p.get("trigger_input") or {}, owner_email=p.get("owner_email", ""))

    return {"ok": True, "job_id": job.id, "echo": p}


def _health(mgr: qm.QueueManager, pool: qm.WorkerPool) -> dict:
    h = pool.health()
    h["backend"] = mgr.backend_name
    h["redis"] = mgr.redis_info
    h["pid"] = os.getpid()
    return h


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Katalir queue worker")
    ap.add_argument("--concurrency", type=int,
                    default=int(os.getenv("KATALIR_WORKER_CONCURRENCY")
                                or (os.cpu_count() or 2)))
    ap.add_argument("--once", action="store_true",
                    help="proses antrian sampai kosong lalu keluar")
    ap.add_argument("--stats", action="store_true",
                    help="cetak health JSON lalu keluar")
    ap.add_argument("--grace", type=float,
                    default=float(os.getenv("KATALIR_WORKER_GRACE", "10")))
    ap.add_argument("--reclaim-interval", type=float, default=5.0,
                    help="interval detik untuk mengklaim ulang job worker mati")
    args = ap.parse_args(argv)

    mgr = qm.QueueManager(backend="auto")
    if args.stats:
        print(json.dumps(mgr.health(), indent=2, default=str))
        return 0

    if mgr.backend_name != "redis":
        print(json.dumps({
            "level": "error",
            "msg": "backend Redis tidak tersedia; set KATALIR_REDIS_URL",
            "backend": mgr.backend_name,
        }))
        return 2

    pool = mgr.pool(_handler, concurrency=args.concurrency)
    berhenti = {"flag": False}

    def _stop(signum, _frame):  # noqa: ANN001
        berhenti["flag"] = True
        print(json.dumps({"level": "info", "msg": "sinyal diterima",
                          "signal": signum}), flush=True)

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(s, _stop)
        except (ValueError, OSError):  # platform tanpa sinyal itu
            pass

    print(json.dumps({"level": "info", "msg": "worker mulai", **_health(mgr, pool)}),
          flush=True)

    if args.once:
        n = pool.drain(timeout=float(os.getenv("KATALIR_DRAIN_TIMEOUT", "120")))
        print(json.dumps({"level": "info", "msg": "drain selesai",
                          "processed": n, **_health(mgr, pool)}), flush=True)
        return 0

    pool.start()
    terakhir_reclaim = 0.0
    try:
        while not berhenti["flag"]:
            time.sleep(0.2)
            now = time.monotonic()
            if now - terakhir_reclaim >= args.reclaim_interval:
                terakhir_reclaim = now
                # Worker yang mati tidak pernah ack -> job-nya diklaim ulang.
                n = mgr.reclaim_expired()
                if n:
                    print(json.dumps({"level": "warn",
                                      "msg": "reclaim job worker mati",
                                      "count": n}), flush=True)
    finally:
        pool.stop(graceful=True, timeout=args.grace)
        print(json.dumps({"level": "info", "msg": "worker berhenti",
                          **_health(mgr, pool)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
