"""queue_bridge.py — jembatan sinkron→asyncio untuk worker Queue Mode.

MASALAH NYATA (ketangkap verifikasi endpoint `/queue/*`, bukan unit test):
`execution_engine.launch_execution()` adalah fungsi SINKRON, tetapi di
dalamnya memanggil `asyncio.create_task(...)`. `create_task` WAJIB dipanggil
saat ada event loop yang SEDANG berjalan di thread itu. Worker antrian
berjalan di `threading.Thread` / `ThreadPoolExecutor` yang **tidak punya
event loop**, jadi setiap job ber-payload `workflow_id` langsung gagal:

    RuntimeError: no running event loop
    -> job retry 3x -> attempts 4 -> DEAD -> DLQ (100% job workflow gagal)

Bukti raw sebelum perbaikan (dari `/queue/workers` + HGETALL Redis):
    "workers":{"processed":0,"failed":100,...}
    HGETALL katalir:q:job:<id> -> 'error': 'RuntimeError: no running event loop'

SOLUSI: satu event loop asyncio PERSISTEN per proses, dijalankan di thread
latar. Handler worker menyerahkan pemanggilan fungsi sinkron ke loop itu
lewat `run_coroutine_threadsafe`, sehingga `create_task` sah dan task
eksekusi benar-benar hidup sampai selesai (kalau memakai `asyncio.run()`
sekali jalan, task-nya langsung dibatalkan saat loop ditutup).

Dipilih `run_coroutine_threadsafe` + loop persisten, bukan `asyncio.run()`
per job, karena:
  * `asyncio.run()` menutup loop setelah coroutine selesai -> task yang
    di-`create_task` di dalamnya DIBATALKAN, eksekusi workflow tidak jalan.
  * Loop persisten = satu loop untuk semua job, tidak ada overhead
    membuat/menutup loop per job (penting pada 10.000 job).
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable


class LoopRunner:
    """Loop asyncio persisten di thread latar (satu per proses)."""

    def __init__(self, name: str = "katalir-queue-loop") -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._name = name
        self._lock = threading.Lock()

    # -- siklus hidup ------------------------------------------------------
    def start(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None and self._thread is not None \
                    and self._thread.is_alive():
                return self._loop
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=self._run, args=(loop,),
                                      name=self._name, daemon=True)
            self._loop = loop
            self._thread = thread
            thread.start()
            return loop

    @staticmethod
    def _run(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            loop, thread = self._loop, self._thread
            self._loop, self._thread = None, None
        if loop is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=timeout)

    # -- pemanggilan -------------------------------------------------------
    def call(self, fn: Callable[..., Any], *args: Any,
             timeout: float = 300.0, **kwargs: Any) -> Any:
        """Jalankan `fn(*args)` DI DALAM loop persisten, kembalikan hasilnya.

        Karena `fn` dieksekusi saat loop berjalan, `asyncio.create_task` di
        dalam `fn` sah dan task-nya hidup di loop yang sama (tidak dibatalkan).
        """
        loop = self.start()

        async def _wrapper() -> Any:
            return fn(*args, **kwargs)

        fut = asyncio.run_coroutine_threadsafe(_wrapper(), loop)
        return fut.result(timeout=timeout)


#: Runner proses-wide (dipakai worker in-process di api_server dan worker_main).
_RUNNER = LoopRunner()


def run_sync(fn: Callable[..., Any], *args: Any, timeout: float = 300.0,
             **kwargs: Any) -> Any:
    """Panggil fungsi sinkron yang butuh event loop, dari thread mana pun."""
    return _RUNNER.call(fn, *args, timeout=timeout, **kwargs)


def shutdown() -> None:
    _RUNNER.stop()
