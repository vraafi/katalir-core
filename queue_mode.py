# queue_mode.py — Fitur #6: Queue Mode Scaling (Okt 2026)
# ======================================================================
# Eksekusi workflow lewat ANTRIAN + worker pool supaya bisa di-scale horizontal:
# instance utama menerima request -> push ke queue; worker mengambil job ->
# eksekusi -> update. Supabase tetap source of truth.
#
# RISET (Okt 2026):
#   - `arq` 0.28.0 (2026-04-16): masih PRA-1.0 -> gagal kriteria "production-
#     ready >=1.0" (https://pypi.org/pypi/arq/json).
#   - `rq` 2.12.0 (2026-08-30): matang, MIT; sejak v2.2 (Jun 2025) punya
#     `SpawnWorker` sehingga Windows didukung tanpa `os.fork()`. Namun worker
#     RQ = PROSES terpisah yang memanggil fungsi top-level (pickle); engine
#     Katalir memanggil `engine.launch_execution` di dalam proses FastAPI
#     (asyncio), jadi integrasi RQ menuntut jembatan proses tambahan.
#   - `celery` 5.6.3 (2026-03-26): matang tapi sinkron & berat untuk app
#     asyncio; `dramatiq` 2.2.1 (2026-09-02) juga sinkron.
#   - `redis` 8.1.0 (2026-07-30): klien RESMI, aktif, MIT -> lolos kriteria.
#   - KEPUTUSAN: Redis sebagai ANTRIAN SEBENARNYA lewat klien resmi `redis`
#     8.1.0, dengan klaim ATOMIK (skrip Lua) supaya aman lintas proses.
#     Alasan: (a) `redis` memenuhi semua kriteria library; (b) klaim atomik +
#     `inflight` berbatas waktu memberi jaminan yang sama dengan broker job
#     sungguhan (worker mati -> job diklaim ulang); (c) tetap asyncio-friendly
#     tanpa proses tambahan yang harus di-deploy; (d) Redis tidak tersedia ->
#     degradasi anggun ke memori (single instance).
# ======================================================================

from __future__ import annotations

import heapq
import itertools
import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

#: Status job.
QUEUED = "queued"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
DEAD = "dead"

DEFAULT_MAX_RETRIES = 3


class QueueError(Exception):
    pass


class QueueUnavailable(QueueError):
    """Backend antrian (mis. Redis) tidak tersedia."""


@dataclass
class Job:
    id: str
    payload: dict
    priority: int = 0
    max_retries: int = DEFAULT_MAX_RETRIES
    timeout: Optional[float] = None
    attempts: int = 0
    status: str = QUEUED
    result: Any = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    ended_at: Optional[float] = None

    def to_dict(self) -> dict:
        return {"id": self.id, "payload": self.payload, "priority": self.priority,
                "attempts": self.attempts, "status": self.status,
                "error": self.error, "result": self.result}


# ---------------------------------------------------------------------------
# Backend antrian: memori (default) + Redis (opsional, lazy)
# ---------------------------------------------------------------------------

class MemoryQueueBackend:
    """Antrian prioritas in-process (heap). Thread-safe."""

    name = "memory"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._heap: list[tuple[int, int, str]] = []
        self._seq = itertools.count()
        self._jobs: dict[str, Job] = {}
        self._inflight: set[str] = set()
        self._dlq: list[str] = []

    def available(self) -> bool:
        return True

    def put(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job
            heapq.heappush(self._heap, (-job.priority, next(self._seq), job.id))

    def get(self, timeout: float = 0.0) -> Optional[Job]:
        batas = time.time() + max(0.0, timeout)
        while True:
            with self._lock:
                if self._heap:
                    _, _, jid = heapq.heappop(self._heap)
                    job = self._jobs.get(jid)
                    if job is not None and job.status == QUEUED:
                        job.status = RUNNING
                        job.started_at = time.time()
                        job.attempts += 1
                        self._inflight.add(jid)
                        return job
                    continue
            if time.time() >= batas:
                return None
            time.sleep(0.002)

    def ack(self, job_id: str, result: Any = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            self._inflight.discard(job_id)
            if job:
                job.status = COMPLETED
                job.result = result
                job.ended_at = time.time()

    def requeue(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            self._inflight.discard(job_id)
            if job:
                job.status = QUEUED
                heapq.heappush(self._heap,
                               (-job.priority, next(self._seq), job.id))

    def dead(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            self._inflight.discard(job_id)
            if job:
                job.status = DEAD
                job.error = error
                job.ended_at = time.time()
                self._dlq.append(job_id)

    def inflight(self) -> list[str]:
        with self._lock:
            return sorted(self._inflight)

    def dlq(self) -> list[Job]:
        with self._lock:
            return [self._jobs[j] for j in self._dlq]

    def jobs(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def size(self) -> int:
        with self._lock:
            return len(self._heap)


#: Namespace kunci Redis. Semua kunci satu antrian berada di bawah prefix ini.
REDIS_KEY_NS = "katalir:q"

#: Lua: ambil satu job dari ZSET `ready` SECARA ATOMIK + tandai running.
#:
#: Kenapa Lua: `ZPOPMIN` lalu `HSET` sebagai dua round-trip punya jendela balapan
#: — dua worker bisa mengklaim job yang sama, atau job hilang bila worker mati
#: di antara keduanya. Satu skrip = satu operasi atomik di server Redis, jadi
#: klaim aman untuk BANYAK PROSES sekaligus (syarat horizontal scaling).
#: KEYS[1]=ready  KEYS[2]=prefix job  KEYS[3]=inflight
#: ARGV[1]=sekarang  ARGV[2]=deadline visibilitas
_CLAIM_LUA = """
local res = redis.call('ZPOPMIN', KEYS[1])
if #res == 0 then return nil end
local id = res[1]
redis.call('HSET', KEYS[2] .. id, 'status', 'running', 'started_at', ARGV[1])
redis.call('HINCRBY', KEYS[2] .. id, 'attempts', 1)
redis.call('ZADD', KEYS[3], ARGV[2], id)
return id
"""

#: Lua: simpan job + masukkan ke ZSET `ready` dalam SATU round-trip.
#: `INCR seq` dan `ZADD` harus memakai nilai seq yang sama, jadi keduanya tidak
#: bisa dipisah ke pipeline biasa. Satu skrip = 1 round-trip, penting untuk
#: enqueue massal (10.000 job).
#: KEYS[1]=seq  KEYS[2]=ready  KEYS[3]=job:<id>
#: ARGV[1]=priority  ARGV[2]=job_id  ARGV[3..]=pasangan field,value
_PUT_LUA = """
local seq = redis.call('INCR', KEYS[1])
local args = {}
for i = 3, #ARGV do args[#args + 1] = ARGV[i] end
redis.call('HSET', KEYS[3], unpack(args))
local score = (-tonumber(ARGV[1])) * 1000000000000 + seq
redis.call('ZADD', KEYS[2], score, ARGV[2])
return seq
"""


class RedisQueueBackend:
    """Backend antrian BERBASIS REDIS — dipakai lintas PROSES (horizontal).

    Berbeda dari versi lama (yang hanya mencerminkan payload ke Redis sambil
    tetap memakai indeks lokal), implementasi ini menjadikan Redis sebagai
    antrian SEBENARNYA:

      * `ready`     ZSET  score = (-prioritas, seq)  -> prioritas tinggi dulu,
                          tie-break FIFO.
      * `job:<id>`  HASH  seluruh field job (payload JSON, status, attempts…).
      * `inflight`  ZSET  score = deadline visibilitas. Worker yang mati
                          meninggalkan entri kedaluwarsa -> `reclaim_expired()`
                          mengembalikannya ke `ready` (bukti "worker crash ->
                          job requeued").
      * `dlq`       LIST  id job yang habis retry.
      * `seq`       INCR  nomor urut monotonik untuk tie-break FIFO.

    Klaim job memakai Lua atomik (`_CLAIM_LUA`) supaya aman untuk banyak worker
    di banyak proses sekaligus.

    `redis` diimpor MALAS: nol dependensi wajib, dan Redis mati -> `available()`
    False sehingga `QueueManager` turun ke backend memori.
    """

    name = "redis"

    def __init__(self, url: str = "", namespace: str = REDIS_KEY_NS,
                 visibility_timeout: float = 0.0) -> None:
        self.url = (url or os.environ.get("KATALIR_REDIS_URL")
                    or os.environ.get("REDIS_URL") or "")
        self.ns = namespace
        # `visibility_timeout` = lease job 'running'. Worker yang mati tidak
        # pernah ack, jadi setelah lease lewat job diklaim ulang. Argumen
        # eksplisit > env KATALIR_VISIBILITY_TIMEOUT > default 60 detik.
        # (Sebelumnya env ini hanya didokumentasikan di worker_main.py tapi
        # TIDAK PERNAH dibaca — bug nyata yang ketangkap hard test #3.)
        if not visibility_timeout:
            try:
                visibility_timeout = float(
                    os.environ.get("KATALIR_VISIBILITY_TIMEOUT") or 60.0)
            except (TypeError, ValueError):
                visibility_timeout = 60.0
        self.visibility_timeout = float(visibility_timeout)
        self._r = None
        self._sha: Optional[str] = None
        self._sha_put: Optional[str] = None
        self._lock = threading.RLock()

    # -- kunci -------------------------------------------------------------
    @property
    def k_ready(self) -> str:
        return f"{self.ns}:ready"

    @property
    def k_inflight(self) -> str:
        return f"{self.ns}:inflight"

    @property
    def k_dlq(self) -> str:
        return f"{self.ns}:dlq"

    @property
    def k_seq(self) -> str:
        return f"{self.ns}:seq"

    @property
    def k_job_prefix(self) -> str:
        return f"{self.ns}:job:"

    def k_job(self, job_id: str) -> str:
        return f"{self.k_job_prefix}{job_id}"

    # -- koneksi -----------------------------------------------------------
    def available(self) -> bool:
        if not self.url:
            return False
        try:
            import redis  # noqa: F401
        except ImportError:
            return False
        return True

    def _client(self):
        if self._r is None:
            import redis
            self._r = redis.Redis.from_url(
                self.url, decode_responses=True,
                socket_connect_timeout=5, socket_timeout=10,
                health_check_interval=30)
            self._r.ping()
        return self._r

    def info(self) -> dict:
        """Info server nyata (bukti koneksi ke provider, bukan tiruan)."""
        s = self._client().info("server")
        return {"server": s.get("valkey_version") or s.get("redis_version"),
                "mode": s.get("redis_mode", "standalone"),
                "os": s.get("os"), "url_host": self.url.split("@")[-1]}

    # -- serialisasi -------------------------------------------------------
    @staticmethod
    def _encode(job: Job) -> dict:
        return {"id": job.id, "payload": json.dumps(job.payload or {}),
                "priority": str(int(job.priority)),
                "max_retries": str(int(job.max_retries)),
                "timeout": "" if job.timeout is None else str(float(job.timeout)),
                "attempts": str(int(job.attempts)), "status": job.status,
                "error": job.error or "", "result": "",
                "created_at": str(job.created_at),
                "started_at": "" if job.started_at is None else str(job.started_at),
                "ended_at": "" if job.ended_at is None else str(job.ended_at)}

    @staticmethod
    def _decode(h: dict) -> Job:
        def _f(v, d=None):
            try:
                return float(v)
            except (TypeError, ValueError):
                return d

        def _i(v, d=0):
            try:
                return int(v)
            except (TypeError, ValueError):
                return d

        try:
            payload = json.loads(h.get("payload") or "{}")
        except Exception:  # noqa: BLE001
            payload = {}
        return Job(
            id=h.get("id", ""), payload=payload,
            priority=_i(h.get("priority")), max_retries=_i(h.get("max_retries"), 3),
            timeout=_f(h.get("timeout")), attempts=_i(h.get("attempts")),
            status=h.get("status", QUEUED), error=h.get("error", ""),
            created_at=_f(h.get("created_at"), time.time()),
            started_at=_f(h.get("started_at")), ended_at=_f(h.get("ended_at")))

    def _score(self, job: Job) -> float:
        """Prioritas tinggi dulu, lalu FIFO. Skor lebih kecil = lebih dulu."""
        seq = self._client().incr(self.k_seq)
        return (-int(job.priority)) * 1e12 + seq

    # -- operasi antrian ---------------------------------------------------
    def put(self, job: Job) -> None:
        """Enqueue dalam SATU round-trip lewat `_PUT_LUA`.

        `INCR seq` dan `ZADD ready` harus memakai nilai seq yang SAMA, jadi
        keduanya tidak bisa dipisah ke pipeline biasa. Satu skrip = 1 RTT —
        penting agar enqueue 10.000 job tidak menjadi 30.000 round-trip.
        """
        r = self._client()
        flat: list = []
        for k, v in self._encode(job).items():
            flat.append(k)
            flat.append(v)
        argv = [str(int(job.priority)), job.id] + flat
        keys = (3, self.k_seq, self.k_ready, self.k_job(job.id))
        if self._sha_put is None:
            try:
                self._sha_put = r.script_load(_PUT_LUA)
            except Exception:  # noqa: BLE001 - EVALSHA tak didukung -> EVAL
                self._sha_put = ""
        try:
            if self._sha_put:
                r.evalsha(self._sha_put, *keys, *argv)
            else:
                r.eval(_PUT_LUA, *keys, *argv)
        except Exception:  # noqa: BLE001 - script hilang setelah restart
            self._sha_put = ""
            r.eval(_PUT_LUA, *keys, *argv)

    def get(self, timeout: float = 0.0):
        r = self._client()
        if self._sha is None:
            try:
                self._sha = r.script_load(_CLAIM_LUA)
            except Exception:  # noqa: BLE001 - EVALSHA tak didukung -> EVAL
                self._sha = ""
        batas = time.time() + max(0.0, timeout)
        while True:
            now = time.time()
            try:
                if self._sha:
                    jid = r.evalsha(self._sha, 3, self.k_ready,
                                    self.k_job_prefix, self.k_inflight,
                                    repr(now), repr(now + self.visibility_timeout))
                else:
                    jid = r.eval(_CLAIM_LUA, 3, self.k_ready,
                                 self.k_job_prefix, self.k_inflight,
                                 repr(now), repr(now + self.visibility_timeout))
            except Exception:  # noqa: BLE001 - script hilang setelah restart
                self._sha = None
                continue
            if jid:
                h = r.hgetall(self.k_job(jid))
                if h:
                    return self._decode(h)
                continue
            if time.time() >= batas:
                return None
            time.sleep(0.005)

    def _finish(self, job_id: str, status: str, error: str = "",
                result: Any = None) -> None:
        r = self._client()
        pipe = r.pipeline(transaction=True)
        pipe.hset(self.k_job(job_id), mapping={
            "status": status, "error": error or "",
            "result": "" if result is None else json.dumps(result, default=str),
            "ended_at": repr(time.time())})
        pipe.zrem(self.k_inflight, job_id)
        if status == DEAD:
            pipe.rpush(self.k_dlq, job_id)
        pipe.execute()

    def ack(self, job_id: str, result: Any = None) -> None:
        self._finish(job_id, COMPLETED, result=result)

    def requeue(self, job_id: str) -> None:
        r = self._client()
        h = r.hgetall(self.k_job(job_id))
        if not h:
            return
        job = self._decode(h)
        pipe = r.pipeline(transaction=True)
        pipe.hset(self.k_job(job_id), mapping={"status": QUEUED, "error": ""})
        pipe.zrem(self.k_inflight, job_id)
        pipe.zadd(self.k_ready, {job_id: self._score(job)})
        pipe.execute()

    def dead(self, job_id: str, error: str) -> None:
        self._finish(job_id, DEAD, error=error)

    def inflight(self) -> list[str]:
        return sorted(self._client().zrange(self.k_inflight, 0, -1))

    def reclaim_expired(self, now: Optional[float] = None) -> list[str]:
        """Kembalikan job 'running' yang deadline-nya LEWAT (worker mati).

        Inilah mekanisme "worker crash -> job requeued": worker tidak pernah
        memanggil ack, jadi entri `inflight` kedaluwarsa dan diklaim ulang.
        """
        r = self._client()
        now = time.time() if now is None else now
        kadaluarsa = r.zrangebyscore(self.k_inflight, "-inf", repr(now))
        for jid in kadaluarsa:
            self.requeue(jid)
        return list(kadaluarsa)

    def dlq(self) -> list[Job]:
        ids = self._client().lrange(self.k_dlq, 0, -1)
        out = []
        for jid in ids:
            h = self._client().hgetall(self.k_job(jid))
            if h:
                out.append(self._decode(h))
        return out

    def dlq_replay(self) -> list[str]:
        """Pindahkan semua job DLQ kembali ke antrian (replay)."""
        r = self._client()
        ids = r.lrange(self.k_dlq, 0, -1)
        for jid in ids:
            h = r.hgetall(self.k_job(jid))
            if not h:
                continue
            r.hset(self.k_job(jid), mapping={"status": QUEUED, "error": ""})
            r.zadd(self.k_ready, {jid: self._score(self._decode(h))})
        if ids:
            r.delete(self.k_dlq)
        return list(ids)

    def jobs(self) -> list[Job]:
        r = self._client()
        out: list[Job] = []
        for key in r.scan_iter(match=f"{self.k_job_prefix}*", count=500):
            h = r.hgetall(key)
            if h:
                out.append(self._decode(h))
        return out

    def get_job(self, job_id: str) -> Optional[Job]:
        h = self._client().hgetall(self.k_job(job_id))
        return self._decode(h) if h else None

    def size(self) -> int:
        return int(self._client().zcard(self.k_ready))

    def clear(self) -> None:
        """Bersihkan SELURUH kunci antrian (dipakai test/benchmark)."""
        r = self._client()
        keys = list(r.scan_iter(match=f"{self.ns}:*", count=500))
        if keys:
            r.delete(*keys)



# ---------------------------------------------------------------------------
# Antrian tingkat tinggi (retry, DLQ, statistik)
# ---------------------------------------------------------------------------

class JobQueue:
    def __init__(self, backend: Optional[Any] = None) -> None:
        self.backend = backend or MemoryQueueBackend()
        self._lock = threading.RLock()

    def enqueue(self, payload: dict, priority: int = 0,
                max_retries: int = DEFAULT_MAX_RETRIES,
                timeout: Optional[float] = None,
                job_id: Optional[str] = None) -> Job:
        job = Job(id=job_id or uuid.uuid4().hex[:12], payload=payload,
                  priority=int(priority), max_retries=int(max_retries),
                  timeout=timeout)
        self.backend.put(job)
        return job

    def dequeue(self, timeout: float = 0.0) -> Optional[Job]:
        return self.backend.get(timeout)

    def complete(self, job_id: str, result: Any = None) -> None:
        self.backend.ack(job_id, result)

    def fail(self, job_id: str, error: str) -> str:
        """Tandai gagal. Return 'requeued' bila masih ada sisa retry, else 'dead'."""
        job = self._find(job_id)
        if job is None:
            return DEAD
        if job.attempts <= job.max_retries:
            self.backend.requeue(job_id)
            return "requeued"
        self.backend.dead(job_id, error)
        return DEAD

    def recover_inflight(self) -> int:
        """Requeue semua job 'running' (simulasi worker crash). Return jumlah."""
        n = 0
        for jid in list(self.backend.inflight()):
            self.backend.requeue(jid)
            n += 1
        return n

    def reclaim_expired(self) -> int:
        """Requeue job yang deadline visibilitasnya LEWAT (worker mati).

        Hanya backend Redis yang punya; backend memori mengembalikan 0 karena
        seluruh state hidup di proses yang sama (tak ada worker terpisah).
        """
        fn = getattr(self.backend, "reclaim_expired", None)
        return len(fn()) if callable(fn) else 0

    def dlq_replay(self) -> int:
        """Kembalikan job DLQ ke antrian. Hanya backend Redis."""
        fn = getattr(self.backend, "dlq_replay", None)
        return len(fn()) if callable(fn) else 0

    def _find(self, job_id: str) -> Optional[Job]:
        # Backend modern punya `get_job` O(1) (Redis: HGETALL satu kunci).
        # Jangan pindai seluruh job: pada 10.000 job itu O(n) per kegagalan.
        getter = getattr(self.backend, "get_job", None)
        if callable(getter):
            return getter(job_id)
        for j in self.backend.jobs():
            if j.id == job_id:
                return j
        return None

    def stats(self) -> dict:
        jobs = self.backend.jobs()
        per: dict[str, int] = {}
        for j in jobs:
            per[j.status] = per.get(j.status, 0) + 1
        return {"total": len(jobs), "queued": self.backend.size(),
                "inflight": len(self.backend.inflight()),
                "dlq": len(self.backend.dlq()), "by_status": per}

    def dlq(self) -> list[Job]:
        return self.backend.dlq()


# ---------------------------------------------------------------------------
# Worker pool (health, scale, graceful shutdown)
# ---------------------------------------------------------------------------

class WorkerPool:
    """Pool worker yang mengambil job dari antrian dan menjalankannya.

    `handler(job) -> result` disuntik (di produksi memanggil execution engine).
    """

    def __init__(self, queue: JobQueue, handler: Callable[[Job], Any],
                 concurrency: int = 1) -> None:
        self.queue = queue
        self.handler = handler
        self.concurrency = max(1, int(concurrency))
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.processed = 0
        self.failed = 0
        self._lock = threading.Lock()

    # -- satu iterasi (dipakai test & loop worker) -------------------------
    def process_once(self, timeout: float = 0.0) -> Optional[tuple[str, Job]]:
        job = self.queue.dequeue(timeout=timeout)
        if job is None:
            return None
        try:
            hasil = self._run(job)
        except FutTimeout:
            self.queue.fail(job.id, "timeout")
            with self._lock:
                self.failed += 1
            return ("timeout", job)
        except Exception as exc:  # noqa: BLE001 - handler error = job gagal
            self.queue.fail(job.id, f"{type(exc).__name__}: {exc}")
            with self._lock:
                self.failed += 1
            return ("failed", job)
        self.queue.complete(job.id, hasil)
        with self._lock:
            self.processed += 1
        return ("completed", job)

    def _run(self, job: Job) -> Any:
        if not job.timeout:
            return self.handler(job)
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(self.handler, job)
            return fut.result(timeout=job.timeout)

    # -- pool --------------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            hasil = self.process_once(timeout=0.05)
            if hasil is None and self._stop.is_set():
                break

    def start(self) -> "WorkerPool":
        for _ in range(self.concurrency):
            t = threading.Thread(target=self._loop, daemon=True)
            t.start()
            self._threads.append(t)
        return self

    def scale(self, n: int) -> int:
        """Tambah/kurangi worker saat runtime. Return jumlah worker aktif."""
        n = max(1, int(n))
        while len(self._threads) < n:
            t = threading.Thread(target=self._loop, daemon=True)
            t.start()
            self._threads.append(t)
        while len(self._threads) > n:
            self._stop_one()
        self.concurrency = n
        return len(self._threads)

    def _stop_one(self) -> None:
        # Hentikan satu worker dengan menandai stop lalu start ulang sisanya.
        # (Implementasi sederhana: kurangi target dan biarkan thread keluar.)
        self._stop.set()
        time.sleep(0.02)
        self._threads.pop()
        self._stop.clear()

    def stop(self, graceful: bool = True, timeout: float = 5.0) -> None:
        """Hentikan pool. `graceful=True` menunggu job in-flight selesai."""
        if graceful:
            batas = time.time() + timeout
            while self.queue.backend.inflight() and time.time() < batas:
                time.sleep(0.01)
        self._stop.set()
        for t in self._threads:
            t.join(timeout=1.0)
        self._threads = []

    def drain(self, timeout: float = 10.0) -> int:
        """Proses antrian sampai kosong (single-threaded, deterministik)."""
        batas = time.time() + timeout
        n = 0
        while time.time() < batas:
            if self.process_once(timeout=0.01) is None:
                if self.queue.backend.size() == 0:
                    break
            else:
                n += 1
        return n

    def health(self) -> dict:
        return {"workers": len(self._threads), "concurrency": self.concurrency,
                "processed": self.processed, "failed": self.failed,
                "queue": self.queue.stats()}


# ---------------------------------------------------------------------------
# Facade: pilih backend (Redis -> fallback memori)
# ---------------------------------------------------------------------------

class QueueManager:
    """Pilih backend terbaik yang tersedia + sediakan worker pool.

    `backend` = "auto" | "redis" | "memory". Pada "auto", Redis dipakai bila
    `KATALIR_REDIS_URL`/`REDIS_URL` terisi DAN `PING` berhasil; kalau tidak,
    turun ke memori (single instance) tanpa mematikan aplikasi.
    """

    def __init__(self, backend: str = "auto",
                 redis_url: str = "",
                 visibility_timeout: float = 0.0) -> None:
        self.backend_name = "memory"
        self.redis_url = redis_url
        self.redis_info: dict = {}
        self.visibility_timeout = 0.0
        self.queue = JobQueue(MemoryQueueBackend())
        if backend in ("auto", "redis"):
            r = RedisQueueBackend(url=redis_url,
                                  visibility_timeout=visibility_timeout)
            if r.available():
                try:
                    r._client()  # ping -> benar-benar tersambung
                    self.queue = JobQueue(r)
                    self.backend_name = "redis"
                    self.visibility_timeout = r.visibility_timeout
                    try:
                        self.redis_info = r.info()
                    except Exception:  # noqa: BLE001 - INFO opsional
                        self.redis_info = {}
                except Exception:  # noqa: BLE001 - Redis down -> memori
                    self.backend_name = "memory"
            elif backend == "redis":
                # diminta eksplisit tapi tidak ada -> degradasi anggun
                self.backend_name = "memory"

    def pool(self, handler: Callable[[Job], Any],
             concurrency: int = 1) -> WorkerPool:
        return WorkerPool(self.queue, handler, concurrency)

    def health(self) -> dict:
        return {"backend": self.backend_name, "redis": self.redis_info,
                "visibility_timeout": self.visibility_timeout,
                **self.queue.stats()}

    def reclaim_expired(self) -> int:
        return self.queue.reclaim_expired()

    def dlq_replay(self) -> int:
        return self.queue.dlq_replay()
