"""Hard test Gap #3 — prompt caching Anthropic (padanan n8n "prompt caching").

Fitur n8n: *"Anthropic Node: Add prompt caching to the Message operation"*
(Text → Message). Padanan Katalir: ``llm_stream.apply_anthropic_cache`` +
``build_payload(..., cache_system=..., cache_messages=...)``.

Prinsip penting: caching adalah **optimasi biaya**, bukan perubahan semantik.
Karena itu jalur default HARUS identik dengan sebelumnya (tanpa bendera apa
pun), dan hanya Anthropic yang mendapat penanda ``cache_control`` — provider
OpenAI-compatible & Gemini meng-cache otomatis di sisi server.

Skenario:
  01  Tanpa bendera -> payload identik dengan perilaku lama (tanpa cache_control)
  02  cache_system=True -> system menjadi blok ber-cache_control ephemeral
  03  cache_messages=1 -> hanya pesan terakhir yang ditandai
  04  cache_messages > jumlah pesan -> dijepit (tidak IndexError)
  05  Pesan dengan content berupa list blok -> breakpoint di blok terakhir
  06  cache_system tanpa system -> tidak ada blok kosong yang dibuat
  07  Provider non-Anthropic mengabaikan bendera (tidak ada field liar)
  08  Streaming tetap jalan dengan caching aktif (end-to-end)
  09  Aturan prefiks Anthropic: system SEBELUM messages (tools→system→messages)
  10  Regresi: temperature tetap ada saat tanpa system, hilang saat ada system
  11  Regresi: max_tokens default 4096 bila tidak diberikan
  12  Jalur default tidak mengubah objek masukan pemanggil (tanpa mutasi)
"""
from __future__ import annotations

import asyncio
import copy
import json

import llm_stream as LS

ANTH = LS.Provider("anthropic", "anthropic", ("ANTHROPIC_API_KEY",), (),
                   "https://api.anthropic.com/v1")
SYS = "Kamu adalah asisten Katalir. " * 40
MSGS = [{"role": "user", "content": "halo"},
        {"role": "assistant", "content": "hai"},
        {"role": "user", "content": "lanjut"}]


def _payload(**kw):
    return LS.build_payload(ANTH, "claude-x", MSGS, system=SYS, **kw)[2]


# ---------------------------------------------------------------------------
# 01
# ---------------------------------------------------------------------------
def test_01_default_tanpa_cache_control():
    body = _payload()
    teks = json.dumps(body)
    print(f"[01] ada_cache_control={'cache_control' in teks} system_tipe="
          f"{type(body['system']).__name__}")
    assert "cache_control" not in teks
    assert body["system"] == SYS
    assert body["stream"] is True


# ---------------------------------------------------------------------------
# 02
# ---------------------------------------------------------------------------
def test_02_cache_system():
    body = _payload(cache_system=True)
    sys_blok = body["system"]
    print(f"[02] system={json.dumps(sys_blok)[:140]}")
    assert isinstance(sys_blok, list) and len(sys_blok) == 1
    assert sys_blok[0]["type"] == "text"
    assert sys_blok[0]["text"] == SYS
    assert sys_blok[0]["cache_control"] == {"type": "ephemeral"}
    # Pesan TIDAK ikut ditandai.
    assert all(isinstance(m["content"], str) for m in body["messages"])


# ---------------------------------------------------------------------------
# 03
# ---------------------------------------------------------------------------
def test_03_cache_messages_terakhir():
    body = _payload(cache_system=True, cache_messages=1)
    print(f"[03] pesan[-1]={json.dumps(body['messages'][-1])[:150]}")
    assert body["messages"][-1]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert isinstance(body["messages"][0]["content"], str)
    assert isinstance(body["messages"][1]["content"], str)


# ---------------------------------------------------------------------------
# 04
# ---------------------------------------------------------------------------
def test_04_cache_messages_dijepit():
    body = _payload(cache_messages=99)
    print(f"[04] semua pesan ditandai: "
          f"{[bool(m['content'][0].get('cache_control')) for m in body['messages']]}")
    assert len(body["messages"]) == 3
    assert all(m["content"][0]["cache_control"] == {"type": "ephemeral"}
               for m in body["messages"])
    # Negatif / nol -> tidak menandai apa pun.
    assert _payload(cache_messages=0)["messages"][0]["content"] == "halo"
    assert _payload(cache_messages=-5)["messages"][0]["content"] == "halo"


# ---------------------------------------------------------------------------
# 05
# ---------------------------------------------------------------------------
def test_05_pesan_blok_list():
    msgs = [{"role": "user",
             "content": [{"type": "text", "text": "bagian A"},
                         {"type": "text", "text": "bagian B"}]}]
    _sys, keluar = LS.apply_anthropic_cache(None, msgs, cache_messages=1)
    print(f"[05] {json.dumps(keluar[0])}")
    assert keluar[0]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in keluar[0]["content"][0]
    assert len(keluar[0]["content"]) == 2


# ---------------------------------------------------------------------------
# 06
# ---------------------------------------------------------------------------
def test_06_cache_system_tanpa_system():
    body = LS.build_payload(ANTH, "claude-x", MSGS, system=None,
                            cache_system=True)[2]
    print(f"[06] kunci={sorted(body)} system={body.get('system')!r}")
    assert "system" not in body
    # Tanpa system, temperature tetap dikirim (perilaku lama dipertahankan).
    assert body["temperature"] == 0.7


# ---------------------------------------------------------------------------
# 07
# ---------------------------------------------------------------------------
def test_07_provider_lain_mengabaikan():
    for nama, base in (("openai", "https://api.openai.com/v1"),
                       ("deepseek", "https://api.deepseek.com/v1"),
                       ("gemini", "https://g/v1beta")):
        p = LS.Provider(nama, LS.PROVIDERS[nama].kind, (), (), base)
        body = LS.build_payload(p, "m", MSGS, system=SYS,
                                cache_system=True, cache_messages=2)[2]
        teks = json.dumps(body)
        print(f"[07] {nama}: ada_cache_control={'cache_control' in teks}")
        assert "cache_control" not in teks, (
            f"{nama} tidak punya field cache_control; menambahkannya membuat 400")
        if p.kind == "openai":
            assert body["stream"] is True
        # Gemini memakai :streamGenerateContent di URL, bukan field `stream`.
        else:
            assert "contents" in body and "generationConfig" in body


# ---------------------------------------------------------------------------
# 08
# ---------------------------------------------------------------------------
def test_08_streaming_dengan_cache():
    import contextlib

    sse = "\n".join([
        'event: content_block_delta',
        'data: {"type":"content_block_delta","delta":{"text":"Hai"}}', '',
        'data: {"type":"message_stop"}', '',
    ])
    ditangkap = {}

    class Tr:
        def __call__(self, url, *, headers, payload, timeout=120.0):
            ditangkap["payload"] = payload

            @contextlib.asynccontextmanager
            async def cm():
                async def gen():
                    for ln in sse.splitlines():
                        yield ln
                yield gen()
            return cm()

    r = asyncio.run(LS.collect_llm_text(LS.stream_llm(
        "anthropic", "claude-x", MSGS, env={"ANTHROPIC_API_KEY": "k"},
        system=SYS, cache_system=True, cache_messages=1,
        transport_factory=Tr())))
    print(f"[08] teks={r['text']!r} cache_aktif="
          f"{'cache_control' in json.dumps(ditangkap['payload'])}")
    assert r["text"] == "Hai" and r["error"] is None
    assert ditangkap["payload"]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert ditangkap["payload"]["messages"][-1]["content"][0]["cache_control"]


# ---------------------------------------------------------------------------
# 09
# ---------------------------------------------------------------------------
def test_09_urutan_prefiks_anthropic():
    """Cache Anthropic berbasis prefiks: system harus lebih dulu dari messages."""
    body = _payload(cache_system=True, cache_messages=1)
    kunci = list(body)
    print(f"[09] urutan kunci={kunci}")
    assert kunci.index("system") < kunci.index("messages")
    # Hanya DUA breakpoint (batas maksimum 4 di API Anthropic, kita pakai 2).
    n = json.dumps(body).count("cache_control")
    print(f"[09] jumlah breakpoint={n}")
    assert n == 2


# ---------------------------------------------------------------------------
# 10
# ---------------------------------------------------------------------------
def test_10_temperature_regresi():
    tanpa_system = LS.build_payload(ANTH, "m", MSGS)[2]
    assert tanpa_system["temperature"] == 0.7
    assert "system" not in tanpa_system
    # Dengan system, temperature TIDAK dikirim (perilaku lama dipertahankan).
    assert "temperature" not in _payload()
    assert "temperature" not in _payload(cache_system=True)
    assert "temperature" not in LS.build_payload(
        ANTH, "m", MSGS, system=SYS, temperature=0.2)[2]
    print("[10] temperature: dikirim tanpa system, tidak dikirim dengan system")


# ---------------------------------------------------------------------------
# 11
# ---------------------------------------------------------------------------
def test_11_max_tokens_default():
    assert _payload()["max_tokens"] == 4096
    assert LS.build_payload(ANTH, "m", MSGS, max_tokens=64)[2]["max_tokens"] == 64
    print("[11] max_tokens default 4096, dapat ditimpa")


# ---------------------------------------------------------------------------
# 12
# ---------------------------------------------------------------------------
def test_12_tanpa_mutasi_masukan():
    asli = copy.deepcopy(MSGS)
    LS.apply_anthropic_cache(SYS, MSGS, cache_system=True, cache_messages=2)
    LS.build_payload(ANTH, "m", MSGS, system=SYS, cache_system=True,
                     cache_messages=2)
    print(f"[12] masukan utuh={MSGS == asli}")
    assert MSGS == asli, "fungsi caching tidak boleh memutasi daftar pemanggil"
    assert all(isinstance(m["content"], str) for m in MSGS)
