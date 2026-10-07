# rate_limit.py - Sliding-window rate limiter in-memory untuk POST /chat
# =====================================================================
# BUG-5 (adversarial test 2026-10-07, docs/security/
# adversarial-test-n8n-hardcore-user-2026-10-07.md): `POST /chat` TIDAK
# membatasi jumlah request per user. Bukti: burst 8 paralel -> 8/8 HTTP 200
# (median 16.7 s), tidak ada satu pun HTTP 429; 13 LLM key / 27 RPM lalu
# kehabisan RPM -> 503 cooldown menyebar ke SEMUA user (orphan rate limit).
#
# Desain:
#   * Sliding-window log (deque timestamp per key) - pola standar tanpa
#     dependensi eksternal (repo ini tidak memakai slowapi/redis; lihat
#     referensi: diskusi FastAPI/Starlette "in-memory sliding window").
#   * Thread-SAFE: endpoint `/chat` adalah `def` (sync) dan berjalan di
#     threadpool Starlette, jadi setiap mutasi di bawah `threading.Lock`.
#   * In-memory per proses uvicorn. Di Railway 1 replica ini setara global;
#     bila nanti di-scale N replica, limit jadi per-replica (N x lebih
#     longgar) - butuh store terpusat (Redis) kalau perlu ketat global.
#   * Key = user id JWT (bukan email) supaya stabil terhadap perubahan
#     identitas dan tidak bocor ke log.
#
# Konfigurasi (env, dibaca saat import):
#   CHAT_RATE_LIMIT       - maksimum request per window per user (default 10).
#                           <= 0 menonaktifkan limiter (fail-open disengaja,
#                           dipakai untuk E2E lokal yang menembak /chat cepat).
#   CHAT_RATE_WINDOW_SEC  - panjang window dalam detik (default 60).
#
# Pemakaian (api_server.chat):
#   ok, retry_after = chat_limiter.check(user_id)
#   if not ok: raise HTTPException(429, ..., headers={"Retry-After": ...})
# =====================================================================

from __future__ import annotations

import math
import os
import threading
import time
from collections import deque


def _env_number(name: str, default: float) -> float:
    """Baca angka dari env; nilai kosong/tidak valid -> default (fail-aman).

    Gagal parse TIDAK boleh menjatuhkan server (rate limit tetap ada dengan
    default) dan tidak boleh menonaktifkan limit diam-diam.
    """
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        print(f"[rate_limit] env {name}={raw!r} bukan angka -> pakai default {default}")
        return default


class SlidingWindowLimiter:
    """Rate limiter sliding-window per key, thread-safe, tanpa dependensi.

    `max_calls <= 0` menonaktifkan limiter (semua check selalu lolos).
    """

    def __init__(self, max_calls: int, window_sec: float, clock=time.monotonic):
        self.max_calls = int(max_calls)
        self.window_sec = float(window_sec)
        self._clock = clock
        self._lock = threading.Lock()
        # key -> deque timestamp (monotonic) permintaan yang MASIH dalam window
        self._hits: dict[str, deque[float]] = {}
        self._checks = 0

    # ------------------------------------------------------------------
    def check(self, key: str) -> tuple[bool, float]:
        """Catat satu permintaan untuk `key`.

        Returns:
            (allowed, retry_after_detik)
            - allowed=True  -> permintaan dicatat (slot terpakai).
            - allowed=False -> permintaan DITOLAK dan TIDAK dicatat, supaya
              percobaan gagal yang beruntun tidak menunda pemulihan window
              (typical sliding-window behaviour).
        """
        if self.max_calls <= 0:
            return True, 0.0

        now = self._clock()
        with self._lock:
            self._checks += 1
            dq = self._hits.get(key)
            if dq is None:
                dq = deque()
                self._hits[key] = dq

            cutoff = now - self.window_sec
            while dq and dq[0] <= cutoff:
                dq.popleft()

            if len(dq) < self.max_calls:
                dq.append(now)
                if self._checks % 500 == 0:
                    self._sweep_locked(now)
                return True, 0.0

            # Window penuh: hitungan pertama (dq[0]) adalah yang pertama lewat.
            retry_after = (dq[0] + self.window_sec) - now
            return False, max(1.0, math.ceil(retry_after))

    # ------------------------------------------------------------------
    def _sweep_locked(self, now: float) -> None:
        """Hapus key yang window-nya sudah habis (cegah pertumbuhan memori).

        HARUS dipanggil saat `self._lock` sudah dipegang.
        """
        cutoff = now - self.window_sec
        stale = [
            k for k, dq in self._hits.items()
            if not dq or dq[-1] <= cutoff
        ]
        for k in stale:
            del self._hits[k]

    # ------------------------------------------------------------------
    def reset(self) -> None:
        """Kosongkan seluruh hitungan (dipakai test / pembersihan)."""
        with self._lock:
            self._hits.clear()
            self._checks = 0

    def snapshot(self, key: str) -> int:
        """Jumlah slot terpakai untuk `key` dalam window saat ini (untuk test)."""
        now = self._clock()
        with self._lock:
            dq = self._hits.get(key)
            if not dq:
                return 0
            cutoff = now - self.window_sec
            return sum(1 for t in dq if t > cutoff)


# ---------------------------------------------------------------------------
# Instance global untuk POST /chat (BUG-5).
# ---------------------------------------------------------------------------
DEFAULT_MAX_CALLS = int(_env_number("CHAT_RATE_LIMIT", 10))
DEFAULT_WINDOW_SEC = _env_number("CHAT_RATE_WINDOW_SEC", 60.0)

chat_limiter = SlidingWindowLimiter(DEFAULT_MAX_CALLS, DEFAULT_WINDOW_SEC)

# ---------------------------------------------------------------------------
# TIER TAMBAHAN (brief 7 Okt 2026, BAGIAN 6):
#   * build workflow : maks 5 per menit per user
#   * tool call      : maks 20 per menit per user
#   * request        : maks 100 per jam per user (di atas limit 10/menit /chat)
# Semua memakai kelas sliding-window yang sama; env `<= 0` menonaktifkan.
# ---------------------------------------------------------------------------
WORKFLOW_BUILD_LIMIT = int(_env_number("WORKFLOW_BUILD_RATE_LIMIT", 5))
WORKFLOW_BUILD_WINDOW_SEC = _env_number("WORKFLOW_BUILD_RATE_WINDOW_SEC", 60.0)
workflow_build_limiter = SlidingWindowLimiter(WORKFLOW_BUILD_LIMIT,
                                              WORKFLOW_BUILD_WINDOW_SEC)

TOOL_CALL_LIMIT = int(_env_number("TOOL_CALL_RATE_LIMIT", 20))
TOOL_CALL_WINDOW_SEC = _env_number("TOOL_CALL_RATE_WINDOW_SEC", 60.0)
tool_call_limiter = SlidingWindowLimiter(TOOL_CALL_LIMIT, TOOL_CALL_WINDOW_SEC)

REQUEST_HOURLY_LIMIT = int(_env_number("REQUEST_HOURLY_RATE_LIMIT", 100))
REQUEST_HOURLY_WINDOW_SEC = _env_number("REQUEST_HOURLY_RATE_WINDOW_SEC", 3600.0)
request_hourly_limiter = SlidingWindowLimiter(REQUEST_HOURLY_LIMIT,
                                              REQUEST_HOURLY_WINDOW_SEC)


def all_limiters() -> list["SlidingWindowLimiter"]:
    """Semua limiter global (dipakai test/fixture untuk reset antar-tes)."""
    return [chat_limiter, workflow_build_limiter, tool_call_limiter,
            request_hourly_limiter]


def reset_all() -> None:
    """Kosongkan hitungan SEMUA limiter (fixture tes)."""
    for lim in all_limiters():
        lim.reset()
