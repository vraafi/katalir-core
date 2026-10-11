"""Hard test TASK 6 — streaming SSE /chat + idle watchdog.

12 skenario: streaming dasar, idle abort, heartbeat, cleanup disconnect,
100 stream paralel, urutan chunk, error graceful, fallback, performa chunk
pertama, tidak bocor, reconnect, dan regresi format frame.
"""
from __future__ import annotations

import asyncio
import time

import pytest

import chat_stream as cs

HB = 0.05          # heartbeat cepat untuk test
IDLE = 0.15        # idle cepat untuk test


def _run(coro):
    return asyncio.run(coro)


async def _agen(items, *, delay=0.0, fail_at=None, finally_flag=None):
    try:
        for i, x in enumerate(items):
            if fail_at is not None and i == fail_at:
                raise RuntimeError("boom di sumber")
            if delay:
                await asyncio.sleep(delay)
            yield x
    finally:
        if finally_flag is not None:
            finally_flag.append(True)


# 1. Streaming basic -> chunk diterima ------------------------------------
def test_01_streaming_basic():
    async def go():
        return await cs.collect(cs.stream_with_watchdog(
            _agen(["a", "b", "c"]), heartbeat_interval=HB, idle_timeout=IDLE))
    frames = _run(go())
    events = [cs.parse_frame(f)["event"] for f in frames]
    assert events == ["chunk", "chunk", "chunk", "done"]
    data = [cs.parse_frame(f)["data"]["data"] for f in frames[:-1]]
    assert data == ["a", "b", "c"]


# 2. Idle > batas -> abort dengan pesan -----------------------------------
def test_02_idle_abort():
    async def slow():
        yield "pertama"
        await asyncio.sleep(10)      # tidak pernah selesai
        yield "tak tercapai"

    async def go():
        return await cs.collect(cs.stream_with_watchdog(
            slow(), heartbeat_interval=HB, idle_timeout=IDLE))
    frames = _run(go())
    parsed = [cs.parse_frame(f) for f in frames]
    assert parsed[0]["event"] == "chunk"
    assert parsed[-1]["event"] == "error"
    assert parsed[-1]["data"]["error"] == "idle_timeout"
    assert "idle_seconds" in parsed[-1]["data"]


# 3. Heartbeat setiap interval --------------------------------------------
def test_03_heartbeat():
    async def slow():
        await asyncio.sleep(HB * 3.2)
        yield "x"

    async def go():
        return await cs.collect(cs.stream_with_watchdog(
            slow(), heartbeat_interval=HB, idle_timeout=5.0))
    frames = [cs.parse_frame(f) for f in _run(go())]
    hb = [f for f in frames if f["event"] == "heartbeat"]
    assert len(hb) >= 2
    assert frames[-1]["event"] in ("done", "chunk")


# 4. Client disconnect -> cleanup -----------------------------------------
def test_04_disconnect_cleanup():
    flag: list[bool] = []

    async def go():
        agen = cs.stream_with_watchdog(
            _agen(["a", "b", "c", "d"], delay=0.01, finally_flag=flag),
            heartbeat_interval=HB, idle_timeout=IDLE)
        first = await agen.__anext__()
        assert cs.parse_frame(first)["event"] == "chunk"
        await agen.aclose()          # klien memutus
        return flag

    _run(go())
    assert flag, "sumber tidak ditutup setelah klien memutus"


# 5. Concurrent 100 streams -----------------------------------------------
def test_05_concurrent_streams():
    async def one(n):
        return await cs.collect(cs.stream_with_watchdog(
            _agen([f"c{n}-{i}" for i in range(3)]),
            heartbeat_interval=HB, idle_timeout=5.0))

    async def go():
        return await asyncio.gather(*[one(n) for n in range(100)])

    results = _run(go())
    assert len(results) == 100
    for n, frames in enumerate(results):
        chunks = [cs.parse_frame(f)["data"]["data"] for f in frames[:-1]]
        assert chunks == [f"c{n}-0", f"c{n}-1", f"c{n}-2"]


# 6. Chunk order preserved -------------------------------------------------
def test_06_order_preserved():
    items = [f"x{i}" for i in range(50)]

    async def go():
        return await cs.collect(cs.stream_with_watchdog(
            _agen(items), heartbeat_interval=HB, idle_timeout=5.0))
    frames = [cs.parse_frame(f) for f in _run(go())]
    got = [f["data"]["data"] for f in frames if f["event"] == "chunk"]
    ids = [f["id"] for f in frames if f["event"] == "chunk"]
    assert got == items
    assert ids == [str(i) for i in range(50)]


# 7. Error in stream -> graceful ------------------------------------------
def test_07_error_graceful():
    async def go():
        return await cs.collect(cs.stream_with_watchdog(
            _agen(["ok", "boom"], fail_at=1),
            heartbeat_interval=HB, idle_timeout=IDLE))
    frames = [cs.parse_frame(f) for f in _run(go())]
    assert frames[0]["event"] == "chunk"
    assert frames[-1]["event"] == "error"
    assert frames[-1]["data"]["error"] == "RuntimeError"


# 8. Fallback non-streaming -----------------------------------------------
def test_08_fallback_on_error():
    async def bad_stream():
        async def gen():
            raise RuntimeError("gagal sebelum chunk pertama")
            yield  # pragma: no cover
        return gen()

    async def fallback():
        return {"status": "success", "reply": "jawaban non-stream"}

    async def go():
        return await cs.collect(cs.stream_or_fallback(
            lambda: cs.stream_with_watchdog(bad_stream()),
            fallback))

    frames = [cs.parse_frame(f) for f in _run(go())]
    assert frames[0]["event"] == "fallback"
    assert frames[0]["data"]["reply"] == "jawaban non-stream"


def test_08b_no_fallback_when_stream_ok():
    def good():
        return cs.stream_with_watchdog(
            _agen(["a", "b"]), heartbeat_interval=HB, idle_timeout=IDLE)

    async def fallback():
        return {"status": "fallback"}

    async def go():
        return await cs.collect(cs.stream_or_fallback(good, fallback))
    frames = [cs.parse_frame(f) for f in _run(go())]
    assert [f["event"] for f in frames] == ["chunk", "chunk", "done"]


# 9. Performance: first chunk < 100ms -------------------------------------
def test_09_first_chunk_latency():
    async def go():
        agen = cs.stream_with_watchdog(
            _agen(["halo"]), heartbeat_interval=HB, idle_timeout=IDLE)
        t0 = time.perf_counter()
        first = await agen.__anext__()
        dt = (time.perf_counter() - t0) * 1000
        await agen.aclose()
        return dt, cs.parse_frame(first)["event"]

    dt, ev = _run(go())
    assert ev == "chunk"
    assert dt < 100.0, f"chunk pertama {dt:.1f} ms"


# 10. Tidak bocor (semua task selesai) ------------------------------------
def test_10_no_leak():
    async def go():
        await cs.collect(cs.stream_with_watchdog(
            _agen(["a", "b", "c"]), heartbeat_interval=HB, idle_timeout=IDLE))
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()
                   and not t.done()]
        return pending

    pending = _run(go())
    assert pending == [], f"task pending bocor: {pending}"


# 11. Reconnect (resume via start_index) ----------------------------------
def test_11_reconnect_resume():
    async def go():
        return await cs.collect(cs.stream_with_watchdog(
            _agen(["a", "b", "c", "d"]), heartbeat_interval=HB,
            idle_timeout=IDLE, start_index=2))
    frames = [cs.parse_frame(f) for f in _run(go())]
    ids = [f["id"] for f in frames if f["event"] == "chunk"]
    assert ids == ["2", "3"]      # melanjutkan dari indeks 2


# 12. Regresi format frame ------------------------------------------------
def test_12_frame_format_and_helpers():
    f = cs.sse_frame("chunk", {"a": 1}, event_id="7")
    assert f.startswith("event: chunk\n")
    assert "id: 7\n" in f
    assert f.endswith("\n\n")
    assert cs.parse_frame(f) == {"event": "chunk", "id": "7", "data": {"a": 1}}

    # data multi-baris dipecah per baris
    f2 = cs.sse_frame("chunk", {"t": "baris1\nbaris2"})
    assert f2.count("data: ") == 1  # JSON tidak mengandung newline literal

    assert cs.text_chunks("") == []
    assert cs.text_chunks("abcdef", 2) == ["ab", "cd", "ef"]
    assert "".join(cs.text_chunks("x" * 100)) == "x" * 100
    assert cs.SSE_HEADERS["Cache-Control"] == "no-cache"


def test_12b_stream_text_helper():
    async def go():
        return await cs.collect(cs.stream_text("halo dunia", heartbeat_interval=HB,
                                               idle_timeout=IDLE))
    frames = [cs.parse_frame(f) for f in _run(go())]
    text = "".join(f["data"]["data"] for f in frames if f["event"] == "chunk")
    assert text == "halo dunia"
    assert frames[-1]["event"] == "done"
