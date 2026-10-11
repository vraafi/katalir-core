"""Hard test Gap #1 — streaming token-level dari LLM (iterasi 3).

14 skenario. Semua memakai **transport palsu** (tanpa jaringan) sehingga
pengukuran time-to-first-token (TTFT) deterministik.

Skenario:
  01  Parser SSE OpenAI: delta berturut-turut
  02  Parser SSE OpenAI: `[DONE]`, komentar, `event:`, data tanpa spasi
  03  Parser SSE Anthropic: hanya `content_block_delta`
  04  Parser SSE Gemini: parts digabung, kandidat kosong aman
  05  Aliran end-to-end OpenAI -> teks utuh
  06  Aliran end-to-end Anthropic
  07  Aliran end-to-end Gemini
  08  TTFT < 500 ms (jam terkendali, deterministik)
  09  Urutan event: meta sebelum delta pertama, done terakhir
  10  Kredensial hilang -> frame error yang informatif (bukan crash)
  11  HTTP 4xx/5xx -> frame error
  12  Pembatalan di tengah aliran -> sumber ditutup, tanpa kebocoran
  13  Jembatan ke chat_stream: frame SSE + heartbeat + done
  14  Regresi: build_payload/headers benar untuk keempat keluarga API
"""
from __future__ import annotations

import asyncio
import contextlib
import json

import pytest

import llm_stream as LS

# ---------------------------------------------------------------------------
# Transport palsu (tanpa jaringan)
# ---------------------------------------------------------------------------
class FakeTransport:
    """Transport deterministik: men-``yield`` baris dari teks, opsional delay."""

    def __init__(self, text: str, *, delay: float = 0.0,
                 status: int = 200, raise_exc: Exception | None = None):
        self.text = text
        self.delay = delay
        self.status = status
        self.raise_exc = raise_exc
        self.ditutup = False

    def __call__(self, url, *, headers, payload, timeout=120.0):
        luar = self

        @contextlib.asynccontextmanager
        async def cm():
            if luar.raise_exc is not None:
                raise luar.raise_exc
            if luar.status >= 400:
                raise LS.LLMStreamError(f"HTTP {luar.status} dari {url}: badan")

            async def gen():
                for ln in luar.text.splitlines():
                    if luar.delay:
                        await asyncio.sleep(luar.delay)
                    yield ln

            try:
                yield gen()
            finally:
                luar.ditutup = True

        return cm()


class Jam:
    """Jam monoton buatan: naik tetap tiap pemanggilan (deterministik)."""

    def __init__(self, langkah: float = 0.001):
        self.t = 1000.0
        self.langkah = langkah

    def __call__(self) -> float:
        self.t += self.langkah
        return self.t


OPENAI_SSE = "\n".join([
    'data: {"choices":[{"delta":{"role":"assistant"}}]}',
    '',
    'data: {"choices":[{"delta":{"content":"Halo"}}]}',
    '',
    'data: {"choices":[{"delta":{"content":" dunia"}}]}',
    '',
    'data: {"choices":[{"delta":{"content":"!"}}]}',
    '',
    'data: [DONE]',
    '',
])

ANTHROPIC_SSE = "\n".join([
    'event: message_start',
    'data: {"type":"message_start","message":{"id":"m1"}}',
    '',
    'event: content_block_delta',
    'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hai"}}',
    '',
    'event: content_block_delta',
    'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":" kamu"}}',
    '',
    'event: message_stop',
    'data: {"type":"message_stop"}',
    '',
])

GEMINI_SSE = "\n".join([
    'data: {"candidates":[{"content":{"parts":[{"text":"Oi"}]}}]}',
    '',
    'data: {"candidates":[{"content":{"parts":[{"text":" hai"}]}}]}',
    '',
    'data: {"candidates":[{"content":{"parts":[]}}]}',
    '',
])

ENV = {"OPENAI_API_KEY": "k-openai", "ANTHROPIC_API_KEY": "k-anth",
       "GEMINI_API_KEY": "k-gem"}


def _jalankan(coro):
    return asyncio.run(coro)


def _collect(provider, body, **kw):
    return _jalankan(LS.collect_llm_text(LS.stream_llm(
        provider, "m-1", [{"role": "user", "content": "hai"}],
        env=ENV, transport_factory=FakeTransport(body), **kw)))


# ---------------------------------------------------------------------------
# 01
# ---------------------------------------------------------------------------
def test_01_parser_openai_delta():
    lines = OPENAI_SSE.splitlines()
    delta = [LS.parse_openai_sse(x) for x in lines]
    delta = [d for d in delta if d]
    print(f"[01] delta={delta}")
    assert delta == ["Halo", " dunia", "!"]


# ---------------------------------------------------------------------------
# 02
# ---------------------------------------------------------------------------
def test_02_parser_openai_tepi():
    assert LS.parse_openai_sse("data: [DONE]") is None
    assert LS.parse_openai_sse("") is None
    assert LS.parse_openai_sse(": komentar keepalive") is None
    assert LS.parse_openai_sse("event: message") is None
    assert LS.parse_openai_sse("id: 42") is None
    assert LS.parse_openai_sse("data:{\"choices\":[{\"delta\":{\"content\":\"x\"}}]}") == "x"
    assert LS.parse_openai_sse("data: {rusak json") is None
    assert LS.parse_openai_sse("data: {\"choices\":[]}") is None
    assert LS.parse_openai_sse("data: {\"choices\":[{\"delta\":{}}]}") is None
    print("[02] semua tepi SSE ditangani")


# ---------------------------------------------------------------------------
# 03
# ---------------------------------------------------------------------------
def test_03_parser_anthropic():
    delta = [LS.parse_anthropic_sse(x) for x in ANTHROPIC_SSE.splitlines()]
    delta = [d for d in delta if d]
    print(f"[03] delta={delta}")
    assert delta == ["Hai", " kamu"]
    # `content_block_start` / `message_delta` tidak dianggap teks.
    assert LS.parse_anthropic_sse(
        'data: {"type":"content_block_start","content_block":{"type":"text"}}') is None


# ---------------------------------------------------------------------------
# 04
# ---------------------------------------------------------------------------
def test_04_parser_gemini():
    delta = [LS.parse_gemini_sse(x) for x in GEMINI_SSE.splitlines()]
    delta = [d for d in delta if d]
    print(f"[04] delta={delta}")
    assert delta == ["Oi", " hai"]
    gabung = LS.parse_gemini_sse(
        'data: {"candidates":[{"content":{"parts":[{"text":"a"},{"text":"b"}]}}]}')
    assert gabung == "ab"
    assert LS.parse_gemini_sse('data: {"candidates":[]}') is None


# ---------------------------------------------------------------------------
# 05
# ---------------------------------------------------------------------------
def test_05_aliran_openai():
    r = _collect("openai", OPENAI_SSE)
    print(f"[05] {json.dumps(r, ensure_ascii=False)}")
    assert r["text"] == "Halo dunia!"
    assert r["chunks"] == 3
    assert r["error"] is None


# ---------------------------------------------------------------------------
# 06
# ---------------------------------------------------------------------------
def test_06_aliran_anthropic():
    r = _collect("anthropic", ANTHROPIC_SSE)
    print(f"[06] {json.dumps(r, ensure_ascii=False)}")
    assert r["text"] == "Hai kamu" and r["chunks"] == 2


# ---------------------------------------------------------------------------
# 07
# ---------------------------------------------------------------------------
def test_07_aliran_gemini():
    r = _collect("gemini", GEMINI_SSE)
    print(f"[07] {json.dumps(r, ensure_ascii=False)}")
    assert r["text"] == "Oi hai" and r["chunks"] == 2


# ---------------------------------------------------------------------------
# 08 — TTFT < 500 ms
# ---------------------------------------------------------------------------
def test_08_ttft_di_bawah_anggaran():
    """Jam terkendali: 1 ms per pembacaan jam, 2 baris sebelum delta pertama."""
    jam = Jam(0.001)

    async def alir():
        return await LS.collect_llm_text(LS.stream_llm(
            "openai", "m-1", [{"role": "user", "content": "hai"}],
            env=ENV, transport_factory=FakeTransport(OPENAI_SSE), clock=jam))

    r = asyncio.run(alir())
    print(f"[08] ttft={r['ttft_ms']} ms total={r['total_ms']} ms "
          f"anggaran={LS.TTFT_BUDGET_MS} ms")
    assert r["ttft_ms"] is not None
    assert r["ttft_ms"] < LS.TTFT_BUDGET_MS, (
        f"TTFT {r['ttft_ms']} ms melewati anggaran {LS.TTFT_BUDGET_MS} ms")
    # TTFT harus jauh lebih kecil dari total -> benar-benar streaming, bukan
    # "tunggu selesai baru kirim".
    assert r["ttft_ms"] < r["total_ms"]


# ---------------------------------------------------------------------------
# 09 — urutan event
# ---------------------------------------------------------------------------
def test_09_urutan_event():
    ev = _jalankan(_kumpulkan_event())
    print(f"[09] {[e.kind for e in ev]}")
    kinds = [e.kind for e in ev]
    assert kinds[0] == "meta", "meta (ttft) harus sebelum delta pertama"
    assert kinds[-1] == "done"
    assert kinds.count("meta") == 1 and kinds.count("done") == 1
    assert "delta" in kinds
    assert kinds.index("meta") < kinds.index("delta")


async def _kumpulkan_event():
    out = []
    async for e in LS.stream_llm("openai", "m-1",
                                 [{"role": "user", "content": "hai"}],
                                 env=ENV,
                                 transport_factory=FakeTransport(OPENAI_SSE)):
        out.append(e)
    return out


# ---------------------------------------------------------------------------
# 10 — kredensial hilang
# ---------------------------------------------------------------------------
def test_10_kredensial_hilang():
    ev = _jalankan(_kumpulkan_tanpa_env())
    print(f"[10] {[ (e.kind, e.text[:60]) for e in ev ]}")
    assert len(ev) == 1 and ev[0].kind == "error"
    assert "OPENAI_API_KEY" in ev[0].text
    assert ev[0].data["error"] == "LLMStreamError"


async def _kumpulkan_tanpa_env():
    return [e async for e in LS.stream_llm(
        "openai", "m-1", [{"role": "user", "content": "hai"}],
        env={}, transport_factory=FakeTransport(OPENAI_SSE))]


# ---------------------------------------------------------------------------
# 11 — HTTP error
# ---------------------------------------------------------------------------
def test_11_http_error():
    r = _jalankan(LS.collect_llm_text(LS.stream_llm(
        "openai", "m-1", [{"role": "user", "content": "hai"}], env=ENV,
        transport_factory=FakeTransport(OPENAI_SSE, status=429))))
    print(f"[11] error={r['error']}")
    assert r["error"] and "429" in r["error"]
    assert r["chunks"] == 0


# ---------------------------------------------------------------------------
# 12 — pembatalan
# ---------------------------------------------------------------------------
def test_12_pembatalan_menutup_sumber():
    tr = FakeTransport(OPENAI_SSE)

    async def alir_lalu_batal():
        agen = LS.stream_llm("openai", "m-1", [{"role": "user", "content": "hai"}],
                             env=ENV, transport_factory=tr).__aiter__()
        pertama = await agen.__anext__()      # ambil satu event
        await agen.aclose()
        return pertama

    ev = asyncio.run(alir_lalu_batal())
    print(f"[12] event pertama={ev.kind} transport_ditutup={tr.ditutup}")
    assert ev.kind in ("meta", "delta")
    assert tr.ditutup, "context manager transport tidak ditutup saat dibatalkan"


# ---------------------------------------------------------------------------
# 13 — jembatan ke chat_stream
# ---------------------------------------------------------------------------
def test_13_jembatan_chat_stream():
    async def kumpul():
        return [f async for f in LS.stream_llm_frames(
            "openai", "m-1", [{"role": "user", "content": "hai"}],
            env=ENV, transport_factory=FakeTransport(OPENAI_SSE),
            watchdog={"idle_timeout": 5.0, "heartbeat_interval": 0.05})]

    frames = asyncio.run(kumpul())
    kinds = []
    teks = ""
    for f in frames:
        d = LS_parse(f)
        kinds.append(d.get("event"))
        if d.get("event") == "chunk":
            teks += d["data"]["data"]
    print(f"[13] kinds={kinds} teks={teks!r}")
    assert kinds[0] == "chunk" and kinds[-1] == "done"
    assert teks == "Halo dunia!"
    assert all(f.startswith("event:") for f in frames)


def LS_parse(frame: str) -> dict:
    from chat_stream import parse_frame
    return parse_frame(frame)


# ---------------------------------------------------------------------------
# 14 — regresi payload/headers
# ---------------------------------------------------------------------------
def test_14_payload_dan_headers():
    # OpenAI-compatible
    p = LS.provider_for("deepseek")
    url, _h, body = LS.build_payload(
        LS.Provider("deepseek", "openai", (), (), "https://api.deepseek.com/v1"),
        "deepseek-chat", [{"role": "user", "content": "x"}])
    assert url == "https://api.deepseek.com/v1/chat/completions"
    assert body["stream"] is True and body["model"] == "deepseek-chat"

    # Anthropic: system dipisah + max_tokens wajib
    url, _h, body = LS.build_payload(
        LS.Provider("anthropic", "anthropic", (), (), "https://api.anthropic.com/v1"),
        "claude-x", [{"role": "user", "content": "x"}], system="kamu asisten")
    assert url.endswith("/v1/messages") and body["system"] == "kamu asisten"
    assert body["max_tokens"] > 0

    # Gemini: contents/parts + systemInstruction
    url, _h, body = LS.build_payload(
        LS.Provider("gemini", "gemini", (), (), "https://g/v1beta"),
        "gemini-2.5-flash", [{"role": "user", "content": "x"}], system="sys")
    assert ":streamGenerateContent" in url
    assert body["contents"][0]["parts"][0]["text"] == "x"
    assert body["systemInstruction"]["parts"][0]["text"] == "sys"

    # Header auth per keluarga
    assert LS._auth_headers(LS.provider_for("anthropic"), "K")["x-api-key"] == "K"
    assert LS._auth_headers(LS.provider_for("gemini"), "K")["x-goog-api-key"] == "K"
    assert LS._auth_headers(LS.provider_for("groq"), "K")["Authorization"] == "Bearer K"
    # Gemini butuh ?alt=sse agar benar-benar streaming.
    assert LS._transport_url(LS.provider_for("gemini"),
                             "https://g/v1beta/models/m:streamGenerateContent",
                             "K").endswith("?alt=sse")
    # Provider tak dikenal -> error jelas, bukan KeyError.
    with pytest.raises(LS.LLMStreamError):
        LS.provider_for("tidak-ada")
    print("[14] payload + headers + url OK untuk 4 keluarga API")
