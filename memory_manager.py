# memory_manager.py — AI Agent Memory (Fitur #11, 8 Okt 2026)
# ======================================================================
# 3-layer memory di Supabase Postgres + pgvector (pola Tiger Data):
#   - episodic   : "apa yang terjadi" (QA chat, event workflow)
#   - semantic   : fakta/pengetahuan (dedup similarity >= 0.95)
#   - procedural : (reserved; preferensi user ada di agent_preferences)
#
# Keputusan riset (docs/implementation-log-2026-10-08.md):
#   - mem01-engine v0.1.0 -> butuh Docker + DB sendiri -> ditolak.
#   - jevmem              -> SQLite-centric, bukan Supabase-native -> ditolak.
#   - pgvector native     -> DIPILIH (vector 0.8.2 aktif di Supabase proyek ini,
#     DDL terverifikasi 8 Okt: tabel agent_memory + agent_preferences + RPC
#     match_agent_memory dengan guard auth.uid()).
#
# Embedding: gemini-embedding-001 via pool GEMINI_KEY_1..13
# (gemini_key_pool.discover_keys), output_dimensionality=1536 -> cocok dengan
# kolom vector(1536). OpenAI ada-002 tidak dipakai (OPENAI_API_KEY kosong,
# terverifikasi 8 Okt; brief sendiri mengizinkan Gemini).
#
# SEMUA metode SYNC (httpx.Client) — dipakai dari endpoint FastAPI sync dan
# hook /chat. Kegagalan embedding/DB tidak boleh menjatuhkan pemanggil:
# method melempar exception TERSISTRUKTUR (MemoryUnavailable) yang pemanggil
# di /chat tangkap + abaikan.
# ======================================================================

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Optional

import httpx

import database as db
import gemini_key_pool

EMBED_MODEL = "gemini-embedding-001"
EMBED_DIM = 1536
EMBED_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
             f"{EMBED_MODEL}:embedContent")
DEDUP_SIMILARITY = 0.95
MEMORY_TYPES = ("episodic", "semantic", "procedural")
# Budget latensi recall di jalur /chat: embed query harus selesai cepat
# atau memory dilewati (chat tidak boleh menunggu lama).
EMBED_TIMEOUT_S = float(os.getenv("MEMORY_EMBED_TIMEOUT_S", "8"))

#: Batas panjang satu memori (karakter). Model embedding punya batas token
#: sendiri; ini batas aplikasi supaya pelanggaran tertangkap lebih awal dengan
#: pesan yang jelas, bukan galat API yang buram.
MAX_CONTENT_CHARS = int(os.getenv("MEMORY_MAX_CONTENT_CHARS", "20000"))

#: Batas atas top_k untuk recall (dipaksa di query).
MAX_RECALL_TOP_K = int(os.getenv("MEMORY_MAX_RECALL_TOP_K", "50"))


class MemoryUnavailable(RuntimeError):
    """Embedding provider / DB gagal — pemanggil /chat mengabaikan."""


def memory_enabled() -> bool:
    return (os.getenv("AGENT_MEMORY_ENABLED", "1").strip().lower()
            not in ("0", "false", "no"))


def _svc():
    return db.get_write_client()


def _now() -> datetime:
    return datetime.now(dt_timezone.utc)


# ---------------------------------------------------------------------------
# Jam server DB (BUG-TTL, 8 Okt 2026)
# ---------------------------------------------------------------------------
# `expires_at` adalah timestamp ABSOLUT yang nanti dibandingkan Postgres
# dengan `now()` miliknya sendiri di RPC match_agent_memory. Kalau kita
# menghitungnya dari jam container aplikasi, drift sekecil apa pun (terbukti
# ~2 detik di runner uji) langsung membuat `expires_at < now()` untuk TTL
# pendek -> memori baru sudah "kedaluwarsa" sejak lahir.
# Solusi: ambil basis waktu DARI DB, dengan cache pendek supaya tidak
# menambah satu round-trip per penulisan memori.
_DB_CLOCK_CACHE: dict[str, object] = {"value": None, "at": 0.0}
_DB_CLOCK_TTL_S = 30.0


def db_now() -> datetime:
    """Waktu sekarang menurut Postgres (sumber kebenaran untuk expires_at).

    Fallback ke jam lokal bila RPC gagal — memori tidak boleh gagal total
    hanya karena jam tidak terbaca (drift kecil lebih baik daripada error).
    """
    cached = _DB_CLOCK_CACHE.get("value")
    age = time.monotonic() - float(_DB_CLOCK_CACHE.get("at") or 0.0)
    if isinstance(cached, datetime) and age < _DB_CLOCK_TTL_S:
        return cached + timedelta(seconds=age)
    try:
        res = _svc().rpc("memory_now", {}).execute()
        raw = res.data
        if isinstance(raw, list) and raw:
            raw = raw[0]
        if isinstance(raw, dict):
            raw = raw.get("now") or raw.get("memory_now")
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)
        dt = dt.astimezone(dt_timezone.utc)
        _DB_CLOCK_CACHE["value"] = dt
        _DB_CLOCK_CACHE["at"] = time.monotonic()
        return dt
    except Exception as exc:  # noqa: BLE001 - jam DB opsional
        print(f"[memory] jam DB tidak terbaca, pakai jam lokal: "
              f"{type(exc).__name__}: {str(exc)[:100]}")
        return _now()


def _iso(dt: datetime) -> str:
    return dt.astimezone(dt_timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Embedding (pool rotation)
# ---------------------------------------------------------------------------

def generate_embedding(text: str, task_type: str = "retrieval_document") -> list[float]:
    """Embedding 1536-dim via Gemini pool. Rotasi kunci saat 429/5xx/400."""
    if not text or not text.strip():
        raise MemoryUnavailable("teks kosong tidak bisa di-embed")
    keys = gemini_key_pool.discover_keys()
    if not keys:
        raise MemoryUnavailable("tidak ada kunci Gemini (GEMINI_KEY_1..13)")
    payload = {
        "model": f"models/{EMBED_MODEL}",
        "content": {"parts": [{"text": text[:8000]}]},
        "task_type": task_type,
        "output_dimensionality": EMBED_DIM,
    }
    last_exc: Exception | None = None
    for name, key, _fp in keys:
        try:
            r = httpx.post(EMBED_URL, params={"key": key}, json=payload,
                           timeout=EMBED_TIMEOUT_S)
            if r.status_code == 200:
                values = (r.json().get("embedding") or {}).get("values") or []
                if len(values) != EMBED_DIM:
                    raise MemoryUnavailable(
                        f"dim embedding {len(values)} != {EMBED_DIM}")
                return values
            last_exc = RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
            if r.status_code in (400, 403, 429, 500, 502, 503):
                continue  # coba kunci berikutnya
            break
        except MemoryUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - network error -> rotasi
            last_exc = exc
            continue
    raise MemoryUnavailable(f"semua kunci embedding gagal: {last_exc}")


# ---------------------------------------------------------------------------
# MemoryManager
# ---------------------------------------------------------------------------

class MemoryManager:
    """Memory per (user_id, agent_id). Semua method sinkron."""

    def __init__(self, user_id: str, agent_id: str = "default"):
        self.user_id = str(user_id)
        self.agent_id = str(agent_id or "default")

    # ---- remember ---------------------------------------------------------

    def remember(self, content: str, memory_type: str = "semantic",
                 metadata: Optional[dict] = None,
                 ttl_seconds: Optional[int] = None,
                 agent_id: Optional[str] = None) -> dict:
        """Simpan memory. Dedup: similarity >= 0.95 -> UPDATE baris lama."""
        if memory_type not in MEMORY_TYPES:
            raise ValueError(f"memory_type harus salah satu dari {MEMORY_TYPES}")
        content = (content or "").strip()
        if not content:
            raise ValueError("content kosong")
        # Temuan hard test: TIDAK ADA batas panjang, sehingga konten raksasa
        # lolos sampai ke API embedding dan gagal di sana dengan galat yang
        # tidak informatif (bukan 4xx yang rapi). Batasi di sini.
        if len(content) > MAX_CONTENT_CHARS:
            raise ValueError(
                f"content terlalu panjang ({len(content)} > "
                f"{MAX_CONTENT_CHARS} karakter)")
        agent = str(agent_id or self.agent_id)
        try:
            embedding = generate_embedding(content, task_type="retrieval_document")
        except MemoryUnavailable:
            raise
        # BUG-TTL: basis waktu HARUS jam DB, bukan jam aplikasi.
        basis = db_now()
        expires_at = (_iso(basis + timedelta(seconds=int(ttl_seconds)))
                      if ttl_seconds else None)

        svc = _svc()
        # dedup dalam scope (user, agent)
        dup = self._find_similar_row(embedding, agent)
        if dup and (dup.get("similarity") or 0) >= DEDUP_SIMILARITY:
            upd = {"content": content, "embedding": embedding,
                   "metadata": metadata or {}, "updated_at": _iso(basis)}
            if expires_at:
                upd["expires_at"] = expires_at
            res = (svc.table("agent_memory").update(upd)
                   .eq("id", dup["id"]).eq("user_id", self.user_id).execute())
            return (res.data or [{}])[0]

        row = {"user_id": self.user_id, "agent_id": agent, "content": content,
               "embedding": embedding, "memory_type": memory_type,
               "metadata": metadata or {}}
        if expires_at:
            row["expires_at"] = expires_at
        res = svc.table("agent_memory").insert(row).execute()
        return (res.data or [{}])[0]

    # ---- recall -----------------------------------------------------------

    def recall(self, query: str, top_k: int = 5,
               memory_type: Optional[str] = None,
               agent_id: Optional[str] = None) -> list[dict]:
        """Semantic search cosine via RPC match_agent_memory."""
        try:
            q_emb = generate_embedding(query, task_type="retrieval_query")
        except MemoryUnavailable:
            raise
        params = {
            "query_embedding": q_emb,
            "match_count": max(1, min(int(top_k), MAX_RECALL_TOP_K)),
            "filter_user_id": self.user_id,
            "filter_agent_id": str(agent_id or self.agent_id),
            "filter_memory_type": memory_type,
        }
        res = _svc().rpc("match_agent_memory", params).execute()
        return res.data or []

    def _find_similar_row(self, embedding: list[float],
                          agent: str) -> Optional[dict]:
        try:
            res = _svc().rpc("match_agent_memory", {
                "query_embedding": embedding,
                "match_count": 1,
                "filter_user_id": self.user_id,
                "filter_agent_id": agent,
                "filter_memory_type": None,
            }).execute()
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as exc:  # noqa: BLE001 - dedup gagal -> insert biasa
            print(f"[memory] dedup lookup gagal (lanjut insert): {exc}")
            return None

    # ---- forget -----------------------------------------------------------

    def forget(self, memory_id: str) -> bool:
        """Soft delete: set expires_at = sekarang (retention guard menyaring).

        Idempoten: baris yang SUDAH expired tidak di-update lagi (return
        False) supaya endpoint bisa membedakan "baru dilupakan" vs "404".
        id yang bukan uuid -> False (tanpa error PostgREST 22P02)."""
        try:
            uuid.UUID(str(memory_id))
        except ValueError:
            return False
        # BUG-TTL: soft delete juga pakai jam DB supaya langsung tersaring.
        stamp = _iso(db_now())
        res = (_svc().table("agent_memory")
               .update({"expires_at": stamp, "updated_at": stamp})
               .eq("id", str(memory_id))
               .eq("user_id", self.user_id)
               .is_("expires_at", "null")
               .execute())
        return bool(res.data)

    # ---- preferences ------------------------------------------------------

    def get_preference(self, key: str) -> Optional[dict]:
        res = (_svc().table("agent_preferences").select("value, confidence")
               .eq("user_id", self.user_id).eq("key", str(key))
               .limit(1).execute())
        rows = res.data or []
        return rows[0] if rows else None

    def set_preference(self, key: str, value: dict, confidence: float = 1.0) -> dict:
        if not isinstance(value, dict):
            raise ValueError("value harus object/dict")
        row = {"user_id": self.user_id, "key": str(key), "value": value,
               "confidence": float(confidence), "updated_at": _iso(_now())}
        res = (_svc().table("agent_preferences")
               .upsert(row, on_conflict="user_id,key").execute())
        return (res.data or [{}])[0]

    def list_preferences(self) -> list[dict]:
        res = (_svc().table("agent_preferences")
               .select("key, value, confidence, updated_at")
               .eq("user_id", self.user_id).order("key").execute())
        return res.data or []


# ---------------------------------------------------------------------------
# Hook /chat (dipanggil api_server) — helper supaya handler tetap ramping
# ---------------------------------------------------------------------------

def build_memory_context(user_id: str, agent_id: str, query: str) -> str:
    """Konteks memori untuk system prompt. SELALU aman: exception apapun
    -> string kosong (chat tidak boleh gagal karena memory)."""
    if not memory_enabled():
        return ""
    try:
        mm = MemoryManager(user_id=user_id, agent_id=agent_id)
        parts: list[str] = []
        try:
            mems = mm.recall(query, top_k=5)
            if mems:
                lines = "\n".join(f"- {m.get('content', '')}" for m in mems)
                parts.append("Memori relevan dari interaksi sebelumnya:\n" + lines)
        except Exception as exc:  # noqa: BLE001
            print(f"[memory] recall dilewati: {type(exc).__name__}: {str(exc)[:120]}")
        try:
            prefs = mm.list_preferences()
            if prefs:
                kv = "; ".join(
                    f"{p['key']}={json.dumps(p['value'], ensure_ascii=False)}"
                    for p in prefs)
                parts.append("Preferensi user: " + kv)
        except Exception as exc:  # noqa: BLE001
            print(f"[memory] preferensi dilewati: {type(exc).__name__}: {str(exc)[:120]}")
        return "\n\n".join(parts)
    except Exception as exc:  # noqa: BLE001
        print(f"[memory] build_memory_context gagal: {type(exc).__name__}: {str(exc)[:120]}")
        return ""


def remember_chat_turn(user_id: str, agent_id: str, user_message: str,
                       assistant_reply: str) -> None:
    """Simpan giliran chat sebagai memori EPISODIC (fire-and-forget, dipanggil
    dari thread daemon). Kegagalan benar-benar diabaikan."""
    try:
        if not memory_enabled():
            return
        snippet = (assistant_reply or "")[:500]
        content = f"User bertanya: {user_message[:500]}\nAsisten menjawab: {snippet}"
        MemoryManager(user_id=user_id, agent_id=agent_id).remember(
            content, memory_type="episodic")
    except Exception as exc:  # noqa: BLE001
        print(f"[memory] episodic write dilewati: {type(exc).__name__}: {str(exc)[:120]}")
