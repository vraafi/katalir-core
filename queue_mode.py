# queue_mode.py — Fitur #6: Queue Mode Scaling (Okt 2026)
# ======================================================================
# Eksekusi workflow lewat ANTRIAN + worker pool supaya bisa di-scale horizontal:
# instance utama menerima request -> push ke queue; worker mengambil job ->
# eksekusi -> update. Supabase tetap source of truth.
#
# RISET (Okt 2026):
#   - ARQ: resmi MAINTENANCE-ONLY -> ditolak sebagai default.
#   - RQ: retry/scheduling kini built-in, tapi fork-per-job & pickle.
#   - Dramatiq: pilihan umum "RQ-alternatif" (retry/rate-limit bawaan).
#   - Taskiq: async-native, ekosistem lebih muda.
#   - KEPUTUSAN: implementasi backend ANTRIAN in-house (memori untuk test +
#     Redis opsional via `redis` yang diimpor MALAS). Nol dependensi wajib;
#     Redis tidak tersedia -> degradasi anggun ke memori (single-instance).
# ======================================================================

from __future__ import annotations

import heapq
import itertools
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

    def size(self) -> int:
        with self._lock:
            return len(self._heap)


class RedisQueueBackend:
    """Backend Redis (opsional). `redis` diimpor malas.

    Dipakai bila `KATALIR_REDIS_URL` diisi. Karena queue Redis sebenarnya
    memakai list + worker proses terpisah, di sini kita memakai Redis untuk
    PERSISTENSI payload job dan tetap mengandalkan indeks prioritas lokal
    (cukup untuk memvalidasi perilaku queue mode pada satu instance).
    """

    name = "redis"

    def __init__(self, url: str = "") -> None:
        self.url = url or os.environ.get("KATALIR_REDIS_URL", "")
        self._local = MemoryQueueBackend()
        self._r = None

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
            self._r = redis.Redis.from_url(self.url, decode_responses=True)
            self._r.ping()
        return self._r

    # Redis tidak wajib di-hard-test (butuh server); operasi didelegasikan ke
    # indeks lokal sambil mencerminkan payload ke Redis bila tersedia.
    def put(self, job: Job) -> None:
        self._local.put(job)
        try:
            import json
            self._client().set(f"katalir:job:{job.id}", json.dumps(job.to_dict()))
        except Exception:  # noqa: BLE001 - Redis down -> tetap jalan lokal
            pass

    def get(self, timeout: float = 0.0):
        return self._local.get(timeout)

    def ack(self, job_id, result=None):
        self._local.ack(job_id, result)

    def requeue(self, job_id):
        self._local.requeue(job_id)

    def dead(self, job_id, error):
        self._local.dead(job_id, error)

    def inflight(self):
        return self._local.inflight()

    def dlq(self):
        return self._local.dlq()

    def jobs(self):
        return self._local.jobs()

    def size(self):
        return self._local.size()


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

    def _find(self, job_id: str) -> Optional[Job]:
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
    """Pilih backend terbaik yang tersedia + sediakan worker pool."""

    def __init__(self, backend: str = "auto") -> None:
        self.backend_name = "memory"
        self.queue = JobQueue(MemoryQueueBackend())
        if backend in ("auto", "redis"):
            r = RedisQueueBackend()
            if r.available():
                try:
                    r._client()  # ping
                    self.queue = JobQueue(r)
                    self.backend_name = "redis"
                except Exception:  # noqa: BLE001 - Redis down -> memori
                    self.backend_name = "memory"
            elif backend == "redis":
                # diminta eksplisit tapi tidak ada -> degradasi anggun
                self.backend_name = "memory"

    def pool(self, handler: Callable[[Job], Any],
             concurrency: int = 1) -> WorkerPool:
        return WorkerPool(self.queue, handler, concurrency)

    def health(self) -> dict:
        return {"backend": self.backend_name, **self.queue.stats()}
