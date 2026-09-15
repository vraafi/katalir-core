# model_discovery.py — Dynamic model discovery (jangan hardcode list).
# Pola 2026: free-router list-models.mjs, Research (discover at runtime
# via client.models.list — never hard-coded), free-llm-api-resources.
"""Query live model chat-capable dari provider API + cache 1 jam."""

import logging
import os
import time

log = logging.getLogger("model_discovery")

CACHE_TTL_S = 3600

GEMINI_FALLBACK = [
    {"id": "gemma-4-31b-it", "name": "Gemma 4 31B",
     "provider": "Google (Gemini)", "tier": "free"},
    {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash",
     "provider": "Google (Gemini)", "tier": "free",
     "hint": "Cepat, hemat token"},
    {"id": "gemma-4-9b-it", "name": "Gemma 4 9B",
     "provider": "Google (Gemini)", "tier": "free",
     "hint": "Ringan & hemat"},
]

PLUS_CHAT_MODELS = frozenset({"gemini-1.5-pro"})

_cache: dict = {"ts": 0.0, "models": []}


def _gemini_key() -> str | None:
    return (
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GEMINI_KEY_1")
    )


def fetch_gemini_models() -> list[dict]:
    """Query live via genai.Client; hanya generateContent (chat-capable)."""
    from google import genai

    api_key = _gemini_key()
    if not api_key:
        raise RuntimeError("API key Gemini tidak ditemukan.")
    client = genai.Client(api_key=api_key)
    out: list[dict] = []
    for m in client.models.list():
        actions = list(getattr(m, "supported_actions", None) or [])
        if "generateContent" not in actions:
            continue
        full = str(getattr(m, "name", "") or "")
        mid = full.replace("models/", "") if full.startswith("models/") else full
        if not mid or "embedding" in mid.lower():
            continue
        out.append({
            "id": mid,
            "name": str(getattr(m, "display_name", None) or mid),
            "provider": "Google (Gemini)",
            "tier": "free",
        })
    # Gerbang paid-only: discovery mentah memuat 41 model termasuk yang RPD 0
    # (semua *-pro*, image/tts/lyria/robotics). Tanpa filter ini user bisa
    # memilih `gemini-3.1-pro-preview`, lalu request-nya dialihkan gateway ke
    # model lain -> jawaban datang dari model yang bukan pilihannya.
    # Non-chat/media dibuang oleh `_NON_CHAT`; paid-only oleh allowlist.
    from gateway_roster import filter_free_models

    out = filter_free_models(out)
    default_id = os.getenv("AGENT_MODEL", "gemma-4-31b-it")
    out.sort(key=lambda d: (d["id"] != default_id, d["id"]))
    return out


def _gateway_roster(force: bool = False) -> list[dict]:
    """Roster dari free-llm-gateway (probe empiris) bila gateway terkonfigurasi.

    Mengembalikan [] bila gateway belum di-set / roster kosong, sehingga
    pemanggil bisa jatuh ke discovery Gemini langsung. Penyegaran roster
    berjalan di latar belakang (non-blocking) supaya request tidak menggantung.
    """
    try:
        from gateway_roster import gateway_config, roster_catalog

        if not gateway_config()[0]:
            return []
        gw = roster_catalog(force=force)
        if gw:
            log.info("Roster gateway: %d model live diserve.", len(gw))
        return gw
    except Exception as exc:  # noqa: BLE001 - gateway opsional
        log.warning("Roster gateway gagal (%s).", exc)
        return []


def get_available_models(force_refresh: bool = False) -> list[dict]:
    """Discovery + cache 1 jam.

    Prioritas 1: roster gateway — model diverifikasi EMPIRIS lewat probe
    (hanya yang terbukti menjawab yang di-serve), karena katalog gateway masih
    memuat alias mati (has_key:true tapi upstream 410/404/500).
    Prioritas 2 (fallback): discovery Gemini langsung via genai.Client.
    """
    now = time.time()
    if not force_refresh and _cache["models"] and (now - _cache["ts"]) < CACHE_TTL_S:
        return _cache["models"]

    gw = _gateway_roster(force_refresh)
    if gw:
        _cache["ts"] = now
        _cache["models"] = gw
        return gw

    models: list[dict] = []
    try:
        models.extend(fetch_gemini_models())
    except Exception as exc:  # noqa: BLE001 - API down -> fallback
        log.warning("Gemini discovery gagal (%s) -> fallback.", exc)
        models.extend([dict(m) for m in GEMINI_FALLBACK])
    for label in ("Groq", "NVIDIA"):
        log.info("%s discovery: tersedia bila multi-provider router mendarat.", label)
    ids = {m["id"] for m in models}
    for pid in PLUS_CHAT_MODELS:
        if pid not in ids:
            models.append({"id": pid, "name": "Gemini Advanced",
                           "provider": "Google (Gemini)", "tier": "plus"})
    _cache["ts"] = now
    _cache["models"] = models
    return models
