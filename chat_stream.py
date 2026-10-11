"""chat_stream.py — streaming SSE untuk /chat + idle watchdog.

MASALAH YANG DISELESAIKAN
-------------------------
Endpoint /chat lama mengembalikan SATU respons JSON setelah seluruh agentic
loop selesai. Untuk jawaban panjang ini berarti: tidak ada umpan balik, proxy
memutus koneksi yang menganggur, dan klien tidak tahu apakah server masih
hidup. Streaming SSE + watchdog menyelesaikannya:

  * **Heartbeat** setiap ``HEARTBEAT_INTERVAL`` detik -> koneksi tidak dianggap
    mati oleh proxy/klien walau model masih "berpikir".
  * **Idle watchdog** -> bila TIDAK ada chunk baru selama ``IDLE_TIMEOUT``
    detik, stream di-abort dengan frame ``error`` yang jelas (bukan menggantung
    tanpa batas).
  * **Urutan chunk terjaga** -> satu task ``__anext__`` hidup pada satu waktu.
  * **Cleanup saat klien memutus** -> generator ditutup -> task pending
    di-cancel (tidak ada kebocoran).
  * **Fallback** -> bila streaming gagal SEBELUM chunk pertama, pemanggil bisa
    jatuh ke respons non-streaming.
  * **Reconnect** -> klien mengirim ``Last-Event-ID``; stream melanjutkan dari
    indeks berikutnya (setiap frame punya ``id``).

Catatan jujur: mesin agent Katalir belum men-*stream* token dari provider LLM,
jadi sumber chunk di endpoint adalah potongan dari jawaban final. Lapisan di
modul ini (watchdog/heartbeat/fallback) sudah siap untuk sumber token-nyata
begitu provider mengekspos streaming.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Any, AsyncIterator, Awaitable, Callable

#: Detik tanpa chunk sebelum stream di-abort.
IDLE_TIMEOUT = 30.0

#: Detik antar heartbeat.
HEARTBEAT_INTERVAL = 10.0

#: Ukuran potongan teks (karakter) untuk sumber berbasis teks.
CHUNK_SIZE = 48

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


class StreamAborted(Exception):
    """Stream di-abort karena idle melebihi batas."""


def sse_frame(event: str, data: Any, *, event_id: str | None = None) -> str:
    """Bentuk satu frame SSE (``event``/``id``/``data`` + baris kosong)."""
    lines = [f"event: {event}"]
    if event_id is not None:
        lines.append(f"id: {event_id}")
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False,
                                                            default=str)
    # `data` multi-baris harus dipecah per baris (aturan SSE).
    for line in payload.splitlines() or [""]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


def text_chunks(text: str, size: int = CHUNK_SIZE) -> list[str]:
    """Pecah teks menjadi potongan ``size`` karakter (non-kosong)."""
    if not text:
        return []
    return [text[i:i + size] for i in range(0, len(text), size)]


async def stream_with_watchdog(
    source: AsyncIterator[Any] | Awaitable[AsyncIterator[Any]],
    *,
    idle_timeout: float = IDLE_TIMEOUT,
    heartbeat_interval: float = HEARTBEAT_INTERVAL,
    start_index: int = 0,
    on_abort: Callable[[], None] | None = None,
    clock: Callable[[], float] | None = None,
) -> AsyncIterator[str]:
    """Bungkus ``source`` menjadi frame SSE dengan heartbeat + watchdog.

    Setiap chunk ``source`` menjadi frame ``event: chunk`` dengan ``id`` =
    indeks absolut (untuk resume). Tidak ada dua ``__anext__`` yang berjalan
    bersamaan, sehingga pembatalan tidak merusak async generator sumber.
    """
    now = clock or time.monotonic
    if asyncio.iscoroutine(source) or isinstance(source, Awaitable):
        source = await source  # type: ignore[assignment]
    it = source.__aiter__()

    loop = asyncio.get_running_loop()
    index = 0
    task: asyncio.Task = loop.create_task(it.__anext__())
    last_activity = now()

    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=heartbeat_interval)
            if not done:
                if now() - last_activity >= idle_timeout:
                    yield sse_frame("error", {
                        "error": "idle_timeout",
                        "message": (f"Tidak ada data selama {idle_timeout:.0f} detik; "
                                    "stream dihentikan."),
                        "idle_seconds": round(now() - last_activity, 3),
                    }, event_id=str(index))
                    if on_abort is not None:
                        on_abort()
                    return
                yield sse_frame("heartbeat", {"ts": time.time()}, event_id=str(index))
                continue

            try:
                chunk = task.result()
            except StopAsyncIteration:
                yield sse_frame("done", {"ok": True, "chunks": index}, event_id=str(index))
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - error di sumber -> frame error
                yield sse_frame("error", {
                    "error": type(exc).__name__,
                    "message": str(exc),
                }, event_id=str(index))
                return

            last_activity = now()
            if index < start_index:
                # Reconnect: buang chunk yang sudah pernah dikirim klien.
                index += 1
                task = loop.create_task(it.__anext__())
                continue
            yield sse_frame("chunk", {"index": index, "data": chunk},
                            event_id=str(index))
            index += 1
            task = loop.create_task(it.__anext__())
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
        # Tutup sumber bila ia async generator (lepas resource).
        aclose = getattr(it, "aclose", None)
        if aclose is not None:
            with contextlib.suppress(BaseException):
                await aclose()


async def stream_text(text: str, **kwargs: Any) -> AsyncIterator[str]:
    """Sumber praktis: pecah ``text`` menjadi chunk lalu bungkus watchdog."""
    async def gen() -> AsyncIterator[str]:
        for c in text_chunks(text):
            yield c
    async for frame in stream_with_watchdog(gen(), **kwargs):
        yield frame


async def collect(frames: AsyncIterator[str]) -> list[str]:
    """Helper test: kumpulkan semua frame."""
    return [f async for f in frames]


def parse_frame(frame: str) -> dict:
    """Parse satu frame SSE -> {event, id, data} (helper test/klien)."""
    event = None
    event_id = None
    data_lines: list[str] = []
    for line in frame.splitlines():
        if line.startswith("event:"):
            event = line[len("event:"):].strip()
        elif line.startswith("id:"):
            event_id = line[len("id:"):].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:"):].lstrip(" "))
    raw = "\n".join(data_lines)
    try:
        data = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        data = raw
    return {"event": event, "id": event_id, "data": data}


async def stream_or_fallback(
    stream_factory: Callable[[], AsyncIterator[str]],
    fallback: Callable[[], Awaitable[dict]],
    *,
    first_chunk_timeout: float = 5.0,
) -> AsyncIterator[str]:
    """Coba streaming; bila gagal sebelum chunk pertama -> pakai ``fallback``.

    Bila sumber mengirim error/timeout pada frame pertama, fallback dipanggil
    dan hasilnya dikirim sebagai satu frame ``fallback``.
    """
    agen = stream_factory().__aiter__()
    try:
        first = await asyncio.wait_for(agen.__anext__(), timeout=first_chunk_timeout)
    except (asyncio.TimeoutError, StopAsyncIteration, Exception) as exc:  # noqa: BLE001
        result = await fallback()
        yield sse_frame("fallback", result, event_id="fallback")
        with contextlib.suppress(BaseException):
            await agen.aclose()  # type: ignore[attr-defined]
        return
    parsed = parse_frame(first)
    if parsed.get("event") == "error":
        result = await fallback()
        yield sse_frame("fallback", result, event_id="fallback")
        with contextlib.suppress(BaseException):
            await agen.aclose()  # type: ignore[attr-defined]
        return
    yield first
    async for frame in agen:
        yield frame


__all__ = [
    "CHUNK_SIZE",
    "HEARTBEAT_INTERVAL",
    "IDLE_TIMEOUT",
    "SSE_HEADERS",
    "StreamAborted",
    "collect",
    "parse_frame",
    "sse_frame",
    "stream_or_fallback",
    "stream_text",
    "stream_with_watchdog",
    "text_chunks",
]
