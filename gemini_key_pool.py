"""gemini_key_pool.py - Rotasi kunci Gemini (Opsi A diperluas) + cooldown per kunci.

Bukti empiris (2026-09-16) yang menentukan desain modul ini:
  * `.env` memuat `GEMINI_KEY_1..13`, tetapi kode lama hanya membaca SATU kunci
    (`GOOGLE_API_KEY or GEMINI_API_KEY or GEMINI_KEY_1`). Satu respons 429
    karena itu mematikan SELURUH jalur cadangan Gemini (single point of failure).
  * 13 kunci terbukti UNIK (fingerprint SHA-256 berbeda) -> rotasi benar-benar
    menggilir, bukan no-op alias seperti temuan awal (saat itu hanya 1 kunci unik).
  * Payload 429 asli (`_e_429_payload.json`):
        quotaId    = GenerateRequestsPerMinutePerProjectPerModel-FreeTier
        quotaValue = 5
        retryDelay = 5s
    -> ini kuota **RPM per-model**, BUKAN "RPD harian habis" seperti yang
    tertulis di HANDOFF sebelumnya. TTL cooldown harus mengikuti payload ini.
  * 404 "This model ... is no longer available to new users" untuk
    `gemini-2.5-flash-lite` pada 5 kunci, sementara 8 kunci lain 200
    -> entitlement berbeda per (kunci, model), jadi blokir harus PER PASANGAN.

KEAMANAN: nilai kunci tidak pernah dicetak/dikembalikan di log. Label yang
dipakai adalah `NAMA#<fingerprint8>` sehingga nol karakter rahasia bocor.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time

log = logging.getLogger("gemini_key_pool")

# Google menghitung kuota "PerMinute" atas jendela menit yang berjalan, dan
# `retryDelay` hanyalah estimasi (limit 5/menit -> menunggu 5s sering masih
# 429). Lantai ini membuat cooldown benar-benar melewati jendela kuota.
_RPM_FLOOR_S = 60.0
_RPD_FALLBACK_S = 24 * 3600.0
_ENTITLEMENT_S = 6 * 3600.0
_OVERLOAD_S = 20.0
_MAX_KEY_SLOTS = 20

# Batas waktu SATU panggilan Gemini (detik). Ini bukan hiasan: terbukti di SDK
# terpasang (`google/genai/_api_client.py`, v1.65.0) bahwa
#   * `_RETRY_ATTEMPTS` default = 5 (termasuk panggilan awal) dengan backoff
#     sampai 60s, dan retry pada 408/429/5xx;
#   * bila `HttpOptions.timeout` tidak diisi, httpx dipanggil TANPA timeout.
# Akibatnya satu `send_message` yang menggantung bisa melewati anggaran `/chat`
# (45s) DAN timeout juru uji E2E (60s) -> gejala nyata "POST /chat
# status=-1, time=-1" (klien tidak pernah menerima respons). Rotasi kunci
# ditangani pool, jadi percobaan internal SDK dimatikan (`attempts=1`).
CALL_TIMEOUT_S = float(os.getenv("GEMINI_CALL_TIMEOUT_S", "20"))

_RETRY_RE = re.compile(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s")
_QUOTA_ID_RE = re.compile(r"['\"]quotaId['\"]\s*:\s*['\"]([^'\"]+)")


def fingerprint(key: str) -> str:
    """8 hex pertama SHA-256 kunci. Identitas aman untuk log & dedup."""
    return hashlib.sha256((key or "").encode("utf-8")).hexdigest()[:8]


def mask_key(key: str) -> str:
    """Mask untuk pesan yang benar-benar butuh bentuk kunci (`AIza****b96d`)."""
    k = key or ""
    if len(k) <= 8:
        return "****"
    return f"{k[:4]}****{k[-4:]}"


def discover_keys(env=None) -> list[tuple[str, str, str]]:
    """Kumpulkan `(nama, kunci, fingerprint)` dari env, tanpa duplikat.

    Slot `GEMINI_KEY_1..N` dipindai berurutan; `GOOGLE_API_KEY` /
    `GEMINI_API_KEY` tetap didukung sebagai kompatibilitas ke belakang.
    Alias yang menunjuk kunci yang sama dibuang lewat fingerprint, sehingga
    satu kunci tidak pernah "berpura-pura" menjadi dua entri rotasi.
    """
    env = os.environ if env is None else env
    raw: list[tuple[str, str]] = []
    for i in range(1, _MAX_KEY_SLOTS + 1):
        val = (env.get(f"GEMINI_KEY_{i}") or "").strip()
        if val:
            raw.append((f"GEMINI_KEY_{i}", val))
    for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "GEMINI_KEY"):
        val = (env.get(name) or "").strip()
        if val:
            raw.append((name, val))

    seen: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for name, val in raw:
        fp = fingerprint(val)
        if fp in seen:
            continue
        seen.add(fp)
        out.append((name, val, fp))
    return out


def classify_error(exc) -> tuple[str, float]:
    """Petakan error Gemini -> `(jenis, cooldown_detik)`.

    jenis:
      * `rate_limited` — kuota habis (429/RESOURCE_EXHAUSTED).
      * `entitlement`  — model tidak tersedia untuk project kunci ini (404).
      * `overloaded`   — gangguan sementara upstream (503/504/UNAVAILABLE/overload,
                         termasuk `DEADLINE_EXCEEDED` dan `ServerError`).
      * `unknown`      — bukan kelas di atas; pool tidak menandai apa pun.

    TTL diambil dari payload (bukan angka karangan): `PerDay` -> tunggu reset,
    `PerMinute` -> lantai 60s karena jendela kuota adalah satu menit.
    """
    text = str(exc)
    low = text.lower()
    if "429" in text or "resource_exhausted" in low or "quota" in low:
        m = _RETRY_RE.search(text)
        retry = float(m.group(1)) if m else 5.0
        qid_m = _QUOTA_ID_RE.search(text)
        qid = qid_m.group(1) if qid_m else ""
        if qid and "perday" in qid.lower():
            return "rate_limited", _RPD_FALLBACK_S
        return "rate_limited", max(retry, _RPM_FLOOR_S)
    if "404" in text or "not_found" in low or "no longer available" in low:
        return "entitlement", _ENTITLEMENT_S
    # Gangguan sementara upstream. `504 DEADLINE_EXCEEDED` / `ServerError` masuk
    # ke sini setelah E2E produksi (2026-09-16) menangkap `POST /chat` menjawab
    # **500** `"Terjadi kesalahan internal: ServerError: 504 DEADLINE_EXCEEDED"`:
    # pola itu dulu "tak dikenal", jadi pool TIDAK merotasi kunci dan error lolos
    # ke handler 500 — padahal ini transien (klien cukup diminta coba lagi, dan
    # kunci/model lain sangat mungkin belum kena).
    if ("503" in text or "504" in text or "unavailable" in low
            or "overloaded" in low or "internal error" in low
            or "deadline" in low or "timeout" in low or "timed out" in low
            or "servererror" in low or "server error" in low):
        return "overloaded", _OVERLOAD_S
    return "unknown", 0.0


_warned_no_retry = False


def _warn_retry_unsupported() -> None:
    """Lapor SEKALI bahwa SDK lama tidak mendukung `HttpRetryOptions`."""
    global _warned_no_retry
    if _warned_no_retry:
        return
    _warned_no_retry = True
    log.warning(
        "google-genai terpasang tanpa `HttpRetryOptions` (versi lama): retry "
        "internal SDK TIDAK bisa dimatikan, jadi satu panggilan bisa mengulang "
        "sendiri dan menembus anggaran /chat. Naikkan pin `google-genai` di "
        "requirements.txt (diverifikasi pada 1.65.0)."
    )


def http_options(types_mod):
    """`HttpOptions` yang aman untuk SDK Gemini lama MAUPUN baru.

    REGRESI PRODUKSI 2026-09-16 (nyata, tertangkap dari E2E `chat-auth`):
    Railway memasang `requirements.txt` (`google-genai==1.6.0`) yang **tidak
    punya** `types.HttpRetryOptions` (dibuktikan dari wheel 1.6.0) sehingga
    `pool.client()` melempar `AttributeError` dan `POST /chat` menjawab **500**
    `"Terjadi kesalahan internal: AttributeError: module 'google.genai.types'
    has no attribute 'HttpRetryOptions'"`. Mesin dev memakai 1.65.0, jadi bug
    ini NOL kali muncul lokal — persis kelas bug "hijau di dev, merah di prod".

    `HttpOptions.timeout` sudah ada sejak SDK lama, jadi batas waktu SELALU
    dipasang; `attempts=1` hanya bila SDK mendukung, dan ketiadaannya tidak
    senyap (lihat `_warn_retry_unsupported`).

    Catatan satuan: `HttpOptions.timeout` satuannya MILIDETIK (SDK membagi
    /1000 sebelum menyerahkan ke httpx per request) — salah satuan di sini
    berarti salah batas waktu di produksi.
    """
    kwargs = {"timeout": int(CALL_TIMEOUT_S * 1000)}
    retry_cls = getattr(types_mod, "HttpRetryOptions", None)
    if retry_cls is None:
        _warn_retry_unsupported()
    else:
        kwargs["retry_options"] = retry_cls(attempts=1)
    return types_mod.HttpOptions(**kwargs)


class KeyPool:
    """Round-robin kunci dengan cooldown PER KUNCI dan blokir PER (KUNCI, MODEL).

    `entries` boleh diberikan langsung (dipakai tes) atau `None` untuk memindai
    env. `now_fn` dapat diganti agar tes cooldown deterministik.
    """

    def __init__(self, entries=None, now_fn=time.time):
        if entries is None:
            entries = discover_keys()
        self._now = now_fn
        self._lock = threading.Lock()
        self._entries: list[tuple[str, str, str]] = [
            (str(n), str(k), str(fp)) for (n, k, fp) in entries
        ]
        self._idx = 0
        self._cool: dict[str, float] = {}
        self._blocked: dict[tuple[str, str], float] = {}
        self._clients: dict[str, object] = {}
        self._hits: dict[str, int] = {fp: 0 for (_, _, fp) in self._entries}

    # -- introspeksi ------------------------------------------------------
    @property
    def size(self) -> int:
        return len(self._entries)

    def label(self, fp: str) -> str:
        """Label aman untuk log: `GEMINI_KEY_3#e733b96d` (tanpa nilai kunci)."""
        for name, _, f in self._entries:
            if f == fp:
                return f"{name}#{fp}"
        return fp

    def key_for(self, fp: str) -> str | None:
        for _, key, f in self._entries:
            if f == fp:
                return key
        return None

    def stats(self) -> dict:
        """Ringkasan untuk log: jumlah kunci, kena cooldown, pasangan diblokir."""
        now = self._now()
        return {
            "keys": len(self._entries),
            "cooling": sum(1 for fp, t in self._cool.items() if t > now),
            "blocked_pairs": sum(1 for t in self._blocked.values() if t > now),
            "used": {self.label(fp): c for fp, c in self._hits.items() if c},
        }

    # -- pemilihan kunci --------------------------------------------------
    def available(self, model: str = "") -> list[str]:
        """Fingerprint kunci yang siap dipakai untuk `model` saat ini."""
        now = self._now()
        out: list[str] = []
        for _, _, fp in self._entries:
            if self._cool.get(fp, 0.0) > now:
                continue
            if model and self._blocked.get((fp, model), 0.0) > now:
                continue
            out.append(fp)
        return out

    def acquire(self, model: str = "") -> tuple[str, str] | None:
        """Ambil `(fingerprint, kunci)` berikutnya yang siap.

        `None` berarti SEMUA kunci sedang kena cooldown/blokir. Pemanggil harus
        memperlakukannya sebagai kegagalan sementara (503 "coba lagi") dan tidak
        menebak-nebak kunci yang sedang dihukum.
        """
        with self._lock:
            total = len(self._entries)
            if not total:
                return None
            now = self._now()
            for step in range(total):
                i = (self._idx + step) % total
                _, key, fp = self._entries[i]
                if self._cool.get(fp, 0.0) > now:
                    continue
                if model and self._blocked.get((fp, model), 0.0) > now:
                    continue
                self._idx = (i + 1) % total
                self._hits[fp] = self._hits.get(fp, 0) + 1
                return fp, key
            return None

    # -- penandaan hasil --------------------------------------------------
    def mark(self, fp: str, model: str, exc=None, kind: str | None = None,
             ttl: float | None = None) -> str:
        """Tandai hasil percobaan `key` pada SATU model.
        
        KONTRAK (dibuktikan dari payload 429 asli, bukan asumsi):
          - `rate_limited`: payload berbunyi
            `GenerateRequestsPerDayPerProjectPerModel-FreeTier` /
            `...PerMinutePerProjectPerModel-FreeTier` -> kuota Google bercakupan
            PER (PROJECT, MODEL). Model lain pada kunci yang sama sebenarnya masih
            bisa melayani, tetapi pembekuan di sini SENGAJA konservatif dan berlaku
            untuk seluruh model kunci itu, sesuai spec task "cooldown per key,
            bukan per akun". Pembekuan per (key, model) yang lebih hemat kapasitas
            dicatat sebagai pending refinement di HANDOFF.
          - `entitlement` (404 "no longer available to new users"): kunci SAH, hanya
            model itu yang tidak tersedia untuk project-nya -> blokir HANYA pasangan
            (key, model).
        """
        if exc is not None and kind is None:
            kind, auto_ttl = classify_error(exc)
            ttl = auto_ttl if ttl is None else ttl
        kind = kind or "unknown"
        ttl = 0.0 if ttl is None else float(ttl)
        if ttl <= 0:
            return kind
        with self._lock:
            until = self._now() + ttl
            pair = (fp, model)
            if kind == "rate_limited":
                self._cool[fp] = max(self._cool.get(fp, 0.0), until)
            else:
                self._blocked[pair] = max(self._blocked.get(pair, 0.0), until)
        return kind

    # -- klien ------------------------------------------------------------
    def client(self, fp: str):
        """`genai.Client` ter-cache per kunci (pembuatan baru terukur ~0,86s)."""
        cached = self._clients.get(fp)
        if cached is not None:
            return cached
        key = self.key_for(fp)
        if not key:
            raise KeyError(f"fingerprint {fp} tidak ada di pool")
        from google import genai  # impor lokal: pool tetap ringan tanpa gemini
        from google.genai import types

        with self._lock:
            if fp not in self._clients:
                self._clients[fp] = genai.Client(
                    api_key=key,
                    # `http_options()` (bukan `types.HttpRetryOptions` langsung):
                    # SDK lama (prod = `google-genai` 1.6.0 dari requirements.txt)
                    # tidak punya kelas itu -> dulu AttributeError -> /chat 500.
                    http_options=http_options(types),
                )
            return self._clients[fp]


_pool: KeyPool | None = None
_pool_lock = threading.Lock()


def pool() -> KeyPool:
    """Pool global (dibangun sekali, aman dari banyak thread)."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = KeyPool()
    return _pool


def reset(entries=None) -> KeyPool:
    """Bangun ulang pool global (dipakai tes, atau bila `.env` berubah saat runtime)."""
    global _pool
    with _pool_lock:
        _pool = KeyPool(entries=entries)
    return _pool
