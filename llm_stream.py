"""llm_stream.py — streaming token-level dari LLM (Gap #1, iterasi 3).

MASALAH YANG DITUTUP
--------------------
Iterasi 2 menambahkan ``chat_stream.py`` (frame SSE + heartbeat + watchdog),
tetapi **sumbernya masih teks yang sudah lengkap** — ``stream_text()`` memecah
string menjadi potongan. Untuk jawaban 30 detik, pengguna tetap menunggu 30
detik sebelum karakter pertama muncul. Yang diminta n8n/UX 2026 adalah
*time-to-first-token* (TTFT) rendah: token pertama tampil < 500 ms.

Modul ini menyediakan klien streaming **nyata** ke empat keluarga API:

===================  ==============================  ==========================
Provider             Endpoint                        Bentuk delta
===================  ==============================  ==========================
OpenAI / Groq /      ``POST /chat/completions``      ``choices[0].delta.content``
DeepSeek / NVIDIA /  ``stream: true``
9Router (gateway)
Anthropic            ``POST /messages``              ``content_block_delta`` →
                     ``stream: true``                ``delta.text``
Gemini               ``POST /models/<m>:            ``candidates[0].content.
                     streamGenerateContent``         parts[*].text``
===================  ==============================  ==========================

PRINSIP DESAIN
--------------
1. **Tanpa jaringan saat tes.** Transport HTTP disuntik lewat argumen
   ``transport`` (async context manager yang men-``yield`` baris SSE).
   Produksi memakai ``httpx_transport``; tes memakai transport palsu sehingga
   dapat mengukur TTFT deterministik dan tidak flaky.
2. **Parser murni.** ``parse_openai_sse`` / ``parse_anthropic_sse`` /
   ``parse_gemini_sse`` adalah fungsi murni ``str -> str | None`` yang bisa
   diuji tanpa I/O. Format SSE yang aneh (``[DONE]``, ``event:``, komentar
   ``:``, ``data:`` tanpa spasi, baris kosong) ditangani eksplisit.
3. **Streaming tidak boleh mematikan fitur lama.** ``stream_llm`` mengembalikan
   ``AsyncIterator[StreamEvent]``; ``chat_stream.stream_with_watchdog``
   membungkusnya menjadi frame SSE sehingga heartbeat/abort/resume tetap jalan.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Iterable, Mapping, Sequence

#: Ambang brief: token pertama harus muncul sebelum ini (ms).
TTFT_BUDGET_MS = 500.0


class LLMStreamError(RuntimeError):
    """Kegagalan streaming LLM (HTTP, protokol, atau kredensial)."""


@dataclass
class StreamEvent:
    """Satu kejadian dalam aliran token."""

    kind: str                       # "delta" | "done" | "error" | "meta"
    text: str = ""
    data: dict = field(default_factory=dict)
    t_ms: float = 0.0               # waktu sejak stream dibuka

    def as_dict(self) -> dict:
        return {"kind": self.kind, "text": self.text,
                "t_ms": round(self.t_ms, 3), **({"data": self.data} if self.data else {})}


# ---------------------------------------------------------------------------
# Parser SSE (murni — tanpa I/O)
# ---------------------------------------------------------------------------
def sse_payload(line: str) -> str | None:
    """Isi ``data:`` dari satu baris SSE, atau None bila bukan baris data.

    Menangani: komentar (``:``), ``event:``/``id:``/``retry:``, ``data:`` tanpa
    spasi, dan baris kosong. SSE spec: satu spasi setelah ':' dibuang.
    """
    if not line:
        return None
    if line.startswith(":"):
        return None
    if not line.startswith("data:"):
        return None
    val = line[5:]
    if val.startswith(" "):
        val = val[1:]
    return val


def _load_json(payload: str) -> Any:
    try:
        return json.loads(payload)
    except (ValueError, TypeError):
        return None


def parse_openai_sse(line: str) -> str | None:
    """Delta teks dari aliran OpenAI-compatible. ``None`` = bukan delta teks.

    ``data: [DONE]`` menandai akhir; ia dikembalikan sebagai ``None`` (bukan
    teks) supaya pemanggil tidak perlu tahu sentinel vendor.
    """
    payload = sse_payload(line)
    if payload is None or payload.strip() == "[DONE]":
        return None
    obj = _load_json(payload)
    if not isinstance(obj, Mapping):
        return None
    choices = obj.get("choices")
    if not isinstance(choices, Sequence) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, Mapping):
        return None
    delta = first.get("delta")
    if isinstance(delta, Mapping):
        txt = delta.get("content")
        if isinstance(txt, str) and txt:
            return txt
    # Beberapa vendor (mis. saat penutup) hanya mengirim `message`.
    msg = first.get("message")
    if isinstance(msg, Mapping):
        txt = msg.get("content")
        if isinstance(txt, str) and txt:
            return txt
    return None


def parse_anthropic_sse(line: str) -> str | None:
    """Delta teks dari aliran ``/v1/messages`` (event ``content_block_delta``)."""
    payload = sse_payload(line)
    if payload is None:
        return None
    obj = _load_json(payload)
    if not isinstance(obj, Mapping):
        return None
    if obj.get("type") != "content_block_delta":
        return None
    delta = obj.get("delta")
    if not isinstance(delta, Mapping):
        return None
    txt = delta.get("text")
    if isinstance(txt, str) and txt:
        return txt
    return None


def parse_gemini_sse(line: str) -> str | None:
    """Delta teks dari ``streamGenerateContent`` (kandidat pertama)."""
    payload = sse_payload(line)
    if payload is None:
        return None
    obj = _load_json(payload)
    if not isinstance(obj, Mapping):
        return None
    cands = obj.get("candidates")
    if not isinstance(cands, Sequence) or not cands:
        return None
    first = cands[0]
    if not isinstance(first, Mapping):
        return None
    content = first.get("content")
    if not isinstance(content, Mapping):
        return None
    parts = content.get("parts")
    if not isinstance(parts, Sequence):
        return None
    out = []
    for p in parts:
        if isinstance(p, Mapping) and isinstance(p.get("text"), str):
            out.append(p["text"])
    joined = "".join(out)
    return joined or None


# ---------------------------------------------------------------------------
# Registry provider
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Provider:
    """Deskripsi satu provider streaming."""

    name: str
    kind: str                     # "openai" | "anthropic" | "gemini"
    key_envs: tuple[str, ...]
    url_envs: tuple[str, ...] = ()
    default_base: str = ""


PROVIDERS: dict[str, Provider] = {
    "openai": Provider("openai", "openai", ("OPENAI_API_KEY",),
                       ("OPENAI_BASE_URL",), "https://api.openai.com/v1"),
    "groq": Provider("groq", "openai", ("GROQ_API_KEY",),
                     ("GROQ_BASE_URL",), "https://api.groq.com/openai/v1"),
    "deepseek": Provider("deepseek", "openai", ("DEEPSEEK_API_KEY",),
                         ("DEEPSEEK_BASE_URL",), "https://api.deepseek.com/v1"),
    "nvidia": Provider("nvidia", "openai", ("NVIDIA_API_KEY",),
                       ("NVIDIA_BASE_URL",),
                       "https://integrate.api.nvidia.com/v1"),
    "9router": Provider("9router", "openai", ("NINEROUTER_KEY",),
                        ("NINEROUTER_EXTERNAL_URL", ""), ""),
    "gateway": Provider("gateway", "openai",
                        ("LLM_GATEWAY_KEY", "FREELM_GATEWAY_KEY", "GATEWAY_KEY"),
                        ("LLM_GATEWAY_URL", "FREELM_GATEWAY_URL", "GATEWAY_URL"),
                        ""),
    "anthropic": Provider("anthropic", "anthropic", ("ANTHROPIC_API_KEY",),
                          ("ANTHROPIC_BASE_URL",), "https://api.anthropic.com/v1"),
    "gemini": Provider("gemini", "gemini", ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
                       ("GEMINI_BASE_URL",),
                       "https://generativelanguage.googleapis.com/v1beta"),
}

PARSERS: dict[str, Callable[[str], str | None]] = {
    "openai": parse_openai_sse,
    "anthropic": parse_anthropic_sse,
    "gemini": parse_gemini_sse,
}


def provider_for(name: str) -> Provider:
    key = (name or "").strip().lower()
    if key not in PROVIDERS:
        raise LLMStreamError(
            f"provider '{name}' tidak dikenal (pilihan: "
            f"{', '.join(sorted(PROVIDERS))})")
    return PROVIDERS[key]


def resolve_credentials(prov: Provider,
                        env: Mapping[str, str] | None = None) -> tuple[str, str]:
    """(base_url, api_key) dari env. Melempar bila kunci tidak ada.

    ``env`` dapat disuntik di tes; default ``os.environ``.
    """
    import os
    e = env if env is not None else os.environ
    key = ""
    for n in prov.key_envs:
        v = (e.get(n) or "").strip()
        if v:
            key = v
            break
    if not key:
        raise LLMStreamError(
            f"kredensial {prov.name} tidak ada (env: {', '.join(prov.key_envs)})")
    base = prov.default_base
    for n in prov.url_envs:
        v = (e.get(n) or "").strip()
        if v:
            base = v
            break
    if not base:
        raise LLMStreamError(f"base URL {prov.name} tidak ada")
    return base.rstrip("/"), key


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------
#: Transport = callable(async context manager) -> AsyncIterator[str] baris SSE.
#: Produksi memakai `httpx_transport`; tes menyuntik transport palsu sehingga
#: pengukuran TTFT tidak bergantung jaringan.
def httpx_transport(url: str, *, headers: Mapping[str, str], payload: dict,
                    timeout: float = 120.0) -> Any:
    """Transport produksi berbasis ``httpx.AsyncClient.stream``."""
    import contextlib

    @contextlib.asynccontextmanager
    async def _cm() -> AsyncIterator[Any]:
        import httpx
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, headers=dict(headers),
                                     json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")
                    raise LLMStreamError(
                        f"HTTP {resp.status_code} dari {url}: {body[:300]}")
                yield resp.aiter_lines()

    return _cm()


def iter_lines_from_text(text: str) -> Iterable[str]:
    """Bantu tes: pecah teks SSE menjadi baris (tanpa newline)."""
    return text.splitlines()


async def iter_deltas(lines: AsyncIterator[str] | Iterable[str],
                      parser: Callable[[str], str | None]) -> AsyncIterator[str]:
    """Ubah aliran baris SSE menjadi aliran delta teks."""
    if hasattr(lines, "__aiter__"):
        async for line in lines:  # type: ignore[union-attr]
            d = parser(line)
            if d:
                yield d
    else:
        for line in lines:  # type: ignore[union-attr]
            d = parser(line)
            if d:
                yield d


# ---------------------------------------------------------------------------
# Penyusun payload per keluarga API
# ---------------------------------------------------------------------------
def apply_anthropic_cache(system: str | None,
                          messages: Sequence[Mapping[str, Any]],
                          *, cache_system: bool = False,
                          cache_messages: int = 0) -> tuple[Any, list[dict]]:
    """Tandai breakpoint cache Anthropic (padanan n8n "prompt caching").

    Anthropic menghitung cache dari PREFIKS: ``tools`` → ``system`` →
    ``messages``. Menaruh ``cache_control`` pada blok system membuat seluruh
    system prompt (biasanya instruksi panjang + knowledge base) di-cache
    sehingga panggilan berikutnya hanya membayar token keluaran baru.

    ``cache_messages=n`` menandai ``n`` pesan TERAKHIR sebagai breakpoint
    tambahan (berguna untuk percakapan multi-turn yang tumbuh).

    Mengembalikan ``(system_atau_None, messages)`` dalam bentuk yang diterima
    ``/v1/messages``. Tanpa bendera apa pun, kembalian identik dengan input —
    sehingga aman dipakai sebagai jalur default.
    """
    keluar = [dict(m) for m in messages]
    if cache_messages > 0:
        n = min(int(cache_messages), len(keluar))
        for m in keluar[len(keluar) - n:]:
            isi = m.get("content")
            if isinstance(isi, str):
                m["content"] = [{"type": "text", "text": isi,
                                 "cache_control": {"type": "ephemeral"}}]
            elif isinstance(isi, list) and isi:
                blok = [dict(b) for b in isi]
                blok[-1] = {**blok[-1], "cache_control": {"type": "ephemeral"}}
                m["content"] = blok
    if system and cache_system:
        sys_out: Any = [{"type": "text", "text": system,
                         "cache_control": {"type": "ephemeral"}}]
    else:
        sys_out = system
    return sys_out, keluar


def build_payload(prov: Provider, model: str, messages: Sequence[Mapping[str, Any]],
                  *, temperature: float = 0.7, max_tokens: int | None = None,
                  system: str | None = None,
                  cache_system: bool = False,
                  cache_messages: int = 0) -> tuple[str, dict, dict]:
    """(url, headers, payload) untuk satu provider.

    Anthropic memisahkan ``system`` dari ``messages``; Gemini memakai
    ``contents``/``parts`` — perbedaan itu diseragamkan di sini supaya
    call-site tidak bercabang.

    Prompt caching: hanya Anthropic yang butuh penanda eksplisit
    (``cache_control``). OpenAI/Groq/DeepSeek/Gemini meng-cache otomatis di
    sisi server berdasarkan prefiks, jadi ``cache_system`` sengaja DIABAIKAN
    untuk mereka — bukan bug, memang tidak ada field-nya di API.
    """
    if prov.kind == "anthropic":
        sys_out, msgs = apply_anthropic_cache(
            system, messages, cache_system=cache_system,
            cache_messages=cache_messages)
        # Urutan kunci mengikuti urutan prefiks cache Anthropic
        # (tools -> system -> messages) supaya struktur payload mencerminkan
        # cara cache dihitung.
        body: dict = {"model": model}
        if sys_out is not None:
            body["system"] = sys_out
        body["messages"] = msgs
        body["stream"] = True
        body["max_tokens"] = max_tokens or 4096
        if sys_out is None:
            body["temperature"] = temperature
        url = f"{prov.default_base}/messages"
        return url, {}, body

    if prov.kind == "gemini":
        contents = []
        for m in messages:
            role = "model" if m.get("role") == "assistant" else "user"
            contents.append({"role": role,
                             "parts": [{"text": str(m.get("content") or "")}]})
        gen: dict = {"temperature": temperature}
        if max_tokens:
            gen["maxOutputTokens"] = max_tokens
        body = {"contents": contents, "generationConfig": gen}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        url = f"{prov.default_base}/models/{model}:streamGenerateContent"
        return url, {}, body

    body = {
        "model": model,
        "messages": [dict(m) for m in messages],
        "stream": True,
        "temperature": temperature,
    }
    if max_tokens:
        body["max_tokens"] = max_tokens
    return f"{prov.default_base}/chat/completions", {}, body


def _auth_headers(prov: Provider, key: str) -> dict:
    if prov.kind == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01",
                "content-type": "application/json"}
    if prov.kind == "gemini":
        return {"x-goog-api-key": key, "content-type": "application/json"}
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _transport_url(prov: Provider, url: str, key: str) -> str:
    """Gemini menerima kunci juga via query ``?alt=sse`` (dipakai untuk SSE)."""
    if prov.kind == "gemini":
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}alt=sse"
    return url


# ---------------------------------------------------------------------------
# API utama
# ---------------------------------------------------------------------------
async def stream_llm(
    provider: str,
    model: str,
    messages: Sequence[Mapping[str, Any]],
    *,
    env: Mapping[str, str] | None = None,
    system: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    transport_factory: Callable[..., Any] | None = None,
    clock: Callable[[], float] | None = None,
    cache_system: bool = False,
    cache_messages: int = 0,
) -> AsyncIterator[StreamEvent]:
    """Alirkan token dari LLM sebagai ``StreamEvent``.

    ``transport_factory`` menggantikan ``httpx_transport`` di tes. Signature-nya
    sama: ``(url, *, headers, payload, timeout) -> async CM``.

    Emisi:
      * ``meta``  — sekali, memuat ``ttft_ms`` dihitung saat delta pertama.
      * ``delta`` — potongan teks berurutan.
      * ``done``  — sekali, memuat ``chunks`` dan ``total_ms``.
      * ``error`` — bila gagal; stream berhenti setelahnya.
    """
    now = clock or time.monotonic
    t0 = now()
    prov = provider_for(provider)
    try:
        base, key = resolve_credentials(prov, env)
        prov = Provider(prov.name, prov.kind, prov.key_envs, prov.url_envs, base)
        url, _hdr, payload = build_payload(
            prov, model, messages, temperature=temperature,
            max_tokens=max_tokens, system=system,
            cache_system=cache_system, cache_messages=cache_messages)
        headers = _auth_headers(prov, key)
        factory = transport_factory or httpx_transport
        cm = factory(_transport_url(prov, url, key), headers=headers,
                     payload=payload)
        parser = PARSERS[prov.kind]
    except Exception as exc:  # noqa: BLE001 - konfigurasi -> frame error
        yield StreamEvent("error", text=str(exc), t_ms=(now() - t0) * 1000,
                          data={"error": type(exc).__name__})
        return

    chunks = 0
    ttft: float | None = None
    try:
        async with cm as lines:
            async for delta in iter_deltas(lines, parser):
                if ttft is None:
                    ttft = (now() - t0) * 1000
                    yield StreamEvent("meta", t_ms=ttft,
                                      data={"ttft_ms": round(ttft, 3),
                                            "provider": prov.name,
                                            "model": model})
                chunks += 1
                yield StreamEvent("delta", text=delta, t_ms=(now() - t0) * 1000)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - kegagalan jaringan/protokol
        yield StreamEvent("error", text=str(exc), t_ms=(now() - t0) * 1000,
                          data={"error": type(exc).__name__, "chunks": chunks})
        return

    yield StreamEvent("done", t_ms=(now() - t0) * 1000,
                      data={"chunks": chunks,
                            "ttft_ms": None if ttft is None else round(ttft, 3),
                            "total_ms": round((now() - t0) * 1000, 3)})


async def collect_llm_text(events: AsyncIterator[StreamEvent]) -> dict:
    """Bantu tes/CLI: gabungkan aliran menjadi teks + metrik."""
    parts: list[str] = []
    ttft = None
    total = 0.0
    err = None
    chunks = 0
    async for ev in events:
        if ev.kind == "delta":
            parts.append(ev.text)
            chunks += 1
        elif ev.kind == "meta":
            ttft = ev.data.get("ttft_ms")
        elif ev.kind == "error":
            err = ev.text
        elif ev.kind == "done":
            total = ev.data.get("total_ms", 0.0)
    return {"text": "".join(parts), "chunks": chunks, "ttft_ms": ttft,
            "total_ms": total, "error": err}


# ---------------------------------------------------------------------------
# Jembatan ke chat_stream (frame SSE + watchdog)
# ---------------------------------------------------------------------------
async def stream_llm_frames(provider: str, model: str,
                            messages: Sequence[Mapping[str, Any]],
                            **kwargs: Any) -> AsyncIterator[str]:
    """Alirkan LLM langsung sebagai frame SSE ``chat_stream`` (TTFT rendah).

    Kwarg ``watchdog`` (dict) diteruskan ke ``stream_with_watchdog``.
    """
    from chat_stream import stream_with_watchdog

    wd = dict(kwargs.pop("watchdog", {}) or {})

    async def gen() -> AsyncIterator[Any]:
        async for ev in stream_llm(provider, model, messages, **kwargs):
            if ev.kind == "delta":
                yield ev.text
            elif ev.kind == "error":
                raise LLMStreamError(ev.text)

    async for frame in stream_with_watchdog(gen(), **wd):
        yield frame


__all__ = [
    "TTFT_BUDGET_MS",
    "LLMStreamError",
    "PARSERS",
    "PROVIDERS",
    "Provider",
    "StreamEvent",
    "apply_anthropic_cache",
    "build_payload",
    "collect_llm_text",
    "httpx_transport",
    "iter_deltas",
    "iter_lines_from_text",
    "parse_anthropic_sse",
    "parse_gemini_sse",
    "parse_openai_sse",
    "provider_for",
    "resolve_credentials",
    "sse_payload",
    "stream_llm",
    "stream_llm_frames",
]
