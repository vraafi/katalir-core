# retry_policy.py — Fitur #3 (8 Okt 2026)
# ======================================================================
# Retry + exponential backoff + DLQ + circuit breaker untuk node workflow.
#
# RISET (docs/fitur-03-retry-dlq.md):
#   tenacity 9.2.1  (rilis 7 Okt 2026 — 1 hari sebelum sesi ini) -> retry
#   pybreaker 1.4.1                                              -> sirkuit
#   Keduanya DIVERIFIKASI perilakunya, bukan diasumsikan:
#     - tenacity: 4 percobaan dgn backoff, dan ValueError TIDAK di-retry
#     - pybreaker: sirkuit terbuka tepat setelah fail_max gagal
#
# KEPUTUSAN DESAIN PENTING:
#   1. HANYA error yang "layak dicoba ulang" yang di-retry. Kesalahan
#      pemrograman (ValueError, TypeError, KeyError) TIDAK di-retry —
#      mengulanginya hanya memperlambat kegagalan tanpa mengubah hasil.
#   2. Circuit breaker pakai implementasi SENDIRI yang state-nya persisten
#      di Postgres. pybreaker menyimpan state di memori; Railway restart
#      akan "melupakan" sirkuit yang sedang terbuka sehingga proteksi hilang.
#      pybreaker tetap dipakai sebagai referensi semantik + untuk pemakaian
#      in-process, tapi sumber kebenaran state ada di tabel circuit_breakers.
#   3. DLQ mencatat SETIAP node yang menyerah, lengkap dengan payload,
#      supaya bisa dijalankan ulang tanpa menebak-nebak.
#
# SEMUA fungsi yang menyentuh data user menerima user_id dan memfilternya.
# ======================================================================

from __future__ import annotations

import json
import random
import time
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Callable, Optional

import database as db

# ---------------------------------------------------------------------------
# Konfigurasi backoff (dipakai juga oleh jalur tenacity)
# ---------------------------------------------------------------------------
MAX_ATTEMPTS = 4
BASE_DELAY_SECONDS = 0.5
MAX_DELAY_SECONDS = 30.0
JITTER_RATIO = 0.25            # +/- 25% supaya klien tidak serempak

# Error yang LAYAK dicoba ulang: gangguan sementara (jaringan/IO/server).
RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    ConnectionError, TimeoutError, OSError, IOError,
)

# Error yang TIDAK layak dicoba ulang: kesalahan pemrograman / input.
NON_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    ValueError, TypeError, KeyError, AttributeError, NotImplementedError,
    ZeroDivisionError,
)

# Circuit breaker default
CB_FAIL_MAX = 5
CB_RESET_TIMEOUT = 60          # detik sebelum half-open


def _svc():
    return db.get_write_client()


def _now() -> datetime:
    return datetime.now(dt_timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(dt_timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 1. Klasifikasi error — ini yang menentukan benar/salahnya retry
# ---------------------------------------------------------------------------

def is_retryable(exc: BaseException) -> bool:
    """True bila exception layak dicoba ulang.

    Urutan penting: NON_RETRYABLE diperiksa lebih dulu, karena sebagian
    subclass (mis. TimeoutError adalah subclass OSError) bisa cocok dua-duanya.
    """
    if isinstance(exc, NON_RETRYABLE_EXCEPTIONS):
        return False
    if isinstance(exc, RETRYABLE_EXCEPTIONS):
        return True
    return False


def backoff_delay(attempt: int, *, base: float = BASE_DELAY_SECONDS,
                  cap: float = MAX_DELAY_SECONDS,
                  jitter: float = JITTER_RATIO) -> float:
    """Delay eksponensial + jitter untuk percobaan ke-`attempt` (1-based).

    attempt=1 -> ~base, 2 -> ~2*base, 3 -> ~4*base, ... dibatasi `cap`.
    Jitter mencegah thundering herd (banyak node gagal serempak).
    """
    attempt = max(1, int(attempt))
    raw = min(base * (2 ** (attempt - 1)), cap)
    if raw >= cap:
        # Di batas atas: jitter hanya ke BAWAH, supaya nilai akhir TIDAK
        # melewati `cap`. Sebelumnya jitter diterapkan setelah cap sehingga
        # delay nyata bisa mencapai cap*(1+jitter) = 37,5s padahal cap=30s.
        # Jitter tetap ada (mencegah thundering herd) tapi tidak melanggar cap.
        return max(0.0, cap - random.uniform(0.0, cap * jitter))
    delta = raw * jitter
    return max(0.0, raw + random.uniform(-delta, delta))


# ---------------------------------------------------------------------------
# 2. Eksekusi node dengan retry
# ---------------------------------------------------------------------------

def with_retry(fn: Callable[[], Any], *, step_id: str = "",
               max_attempts: int = MAX_ATTEMPTS,
               sleep: Callable[[float], None] = time.sleep,
               on_attempt: Optional[Callable[[int, BaseException], None]] = None
               ) -> tuple[bool, Any, Optional[str], int]:
    """Jalankan `fn` dengan retry + backoff.

    Mengembalikan (sukses, hasil, pesan_error, jumlah_percobaan).
    `sleep` bisa disuntik agar tes tidak benar-benar menunggu.
    """
    percobaan = 0
    error_akhir: Optional[str] = None
    for percobaan in range(1, max_attempts + 1):
        try:
            return True, fn(), None, percobaan
        except Exception as exc:  # noqa: BLE001 - semua error ditangani
            error_akhir = f"{type(exc).__name__}: {exc}"
            if on_attempt:
                try:
                    on_attempt(percobaan, exc)
                except Exception:  # noqa: BLE001
                    pass
            if not is_retryable(exc):
                # kesalahan pemrograman -> jangan buang waktu mengulang
                return False, None, error_akhir, percobaan
            if percobaan < max_attempts:
                sleep(backoff_delay(percobaan))
    return False, None, error_akhir, percobaan


# ---------------------------------------------------------------------------
# 3. Circuit breaker persisten (state di DB, bukan memori)
# ---------------------------------------------------------------------------

def _cb_row(name: str) -> dict:
    rows = (_svc().table("circuit_breakers").select("*")
            .eq("name", name).limit(1).execute()).data or []
    if rows:
        return rows[0]
    row = {"name": name, "state": "closed", "fail_count": 0,
           "fail_max": CB_FAIL_MAX, "reset_timeout": CB_RESET_TIMEOUT}
    try:
        return (_svc().table("circuit_breakers").insert(row)
                .execute()).data[0]
    except Exception:  # noqa: BLE001 - balapan insert -> baca lagi
        rows = (_svc().table("circuit_breakers").select("*")
                .eq("name", name).limit(1).execute()).data or []
        return rows[0] if rows else row


def circuit_allows(name: str) -> bool:
    """Apakah panggilan ke `name` diizinkan?

    open + belum lewat reset_timeout  -> TOLAK (fail fast)
    open + sudah lewat reset_timeout  -> izinkan SATU percobaan (half-open)
    """
    cb = _cb_row(name)
    state = cb.get("state") or "closed"
    if state == "closed":
        return True
    if state == "half_open":
        return True
    # open
    opened = cb.get("opened_at")
    if not opened:
        return True
    try:
        t = datetime.fromisoformat(str(opened).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt_timezone.utc)
    except ValueError:
        return True
    if _now() - t >= timedelta(seconds=int(cb.get("reset_timeout") or CB_RESET_TIMEOUT)):
        _svc().table("circuit_breakers").update(
            {"state": "half_open", "updated_at": _iso(_now())}
        ).eq("name", name).execute()
        return True
    return False


def circuit_success(name: str) -> None:
    """Catat keberhasilan -> tutup sirkuit, reset hitungan."""
    _svc().table("circuit_breakers").update({
        "state": "closed", "fail_count": 0, "opened_at": None,
        "last_error": None, "updated_at": _iso(_now()),
    }).eq("name", name).execute()


def circuit_failure(name: str, error: str = "") -> str:
    """Catat kegagalan -> buka sirkuit bila melewati fail_max.

    Mengembalikan state setelah update ('closed' atau 'open').
    """
    svc = _svc()
    cb = _cb_row(name)
    gagal = int(cb.get("fail_count") or 0) + 1
    fail_max = int(cb.get("fail_max") or CB_FAIL_MAX)
    state = "closed"
    upd: dict[str, Any] = {
        "fail_count": gagal, "last_failure_at": _iso(_now()),
        "last_error": (error or "")[:1000], "updated_at": _iso(_now()),
    }
    if gagal >= fail_max:
        state = "open"
        upd["state"] = "open"
        upd["opened_at"] = _iso(_now())
    svc.table("circuit_breakers").update(upd).eq("name", name).execute()
    return state


def circuit_state(name: str) -> str:
    return (_cb_row(name).get("state") or "closed")


def circuit_reset(name: str) -> None:
    """Paksa tutup (dipakai operator setelah insiden selesai)."""
    circuit_success(name)


# ---------------------------------------------------------------------------
# 4. Dead Letter Queue
# ---------------------------------------------------------------------------

def _aman_json(v: Any) -> Any:
    try:
        json.dumps(v)
        return v
    except (TypeError, ValueError):
        return {"_repr": str(v)[:2000]}


def push_dlq(*, execution_id: Optional[str], workflow_id: Optional[str],
             user_id: str, step_id: str, node_type: str = "",
             attempts: int = 0, last_error: str = "",
             payload: Any = None) -> Optional[dict]:
    """Masukkan node yang menyerah ke DLQ.

    Idempoten: constraint dlq_exec_step_key unique (execution_id, step_id),
    jadi kegagalan berulang pada node yang sama tidak menumpuk baris.

    CATATAN (BUG 42P10, 8 Okt): versi pertama memakai partial unique index
    yang TIDAK bisa jadi target ON CONFLICT -> upsert selalu gagal. Kegagalan
    itu tersembunyi karena ditelan `except`. Sekarang kegagalan dicetak
    dengan awalan jelas dan dikembalikan None, jadi tes bisa menangkapnya.
    DLQ tetap tidak boleh menjatuhkan alur utama (pengecualian ditangkap).
    """
    if not execution_id:
        print("[dlq] DILEWATI: execution_id kosong (DLQ butuh eksekusi induk)")
        return None
    row = {
        "execution_id": execution_id, "workflow_id": workflow_id,
        "user_id": str(user_id), "step_id": step_id,
        "node_type": node_type or "", "attempts": int(attempts or 0),
        "last_error": (last_error or "")[:2000],
        "payload": _aman_json(payload), "status": "pending",
        "updated_at": _iso(_now()),
    }
    try:
        return (_svc().table("dead_letter_queue").upsert(
            row, on_conflict="execution_id,step_id").execute()).data[0]
    except Exception as exc:  # noqa: BLE001 - DLQ tidak boleh jatuhkan alur
        print(f"[dlq] GAGAL menyimpan step={step_id}: "
              f"{type(exc).__name__}: {exc}")
        return None


def list_dlq(user_id: str, status: Optional[str] = None,
             limit: int = 50) -> list[dict]:
    q = (_svc().table("dead_letter_queue").select("*")
         .eq("user_id", str(user_id)).order("created_at", desc=True))
    if status:
        q = q.eq("status", status)
    return q.limit(max(1, min(int(limit), 200))).execute().data or []


def dlq_item(dlq_id: str, user_id: str) -> Optional[dict]:
    """Ambil satu item DLQ — WAJIB milik user tersebut."""
    rows = (_svc().table("dead_letter_queue").select("*")
            .eq("id", dlq_id).eq("user_id", str(user_id))
            .limit(1).execute()).data or []
    return rows[0] if rows else None


def claim_dlq(dlq_id: str, user_id: str) -> Optional[dict]:
    """Klaim item DLQ untuk dijalankan ulang (atomik, anti dobel).

    PENTING (BUG keamanan 8 Okt): RPC mengembalikan jsonb dan PostgREST
    membungkusnya. Saat TIDAK ada baris yang cocok (mis. user_id bukan
    pemilik), PostgREST lama mengembalikan dict berisi NULL semua — dan
    `dict` itu TRUTHY di Python, sehingga user asing seolah berhasil
    mengklaim. Jadi kita WAJIB memvalidasi bahwa hasilnya benar-benar
    berisi id, bukan sekadar "tidak None".
    """
    try:
        res = _svc().rpc("claim_dlq_item", {
            "p_id": dlq_id, "p_user_id": str(user_id)}).execute()
        data = res.data
        if isinstance(data, list):
            data = data[0] if data else None
        if not isinstance(data, dict):
            return None
        if not data.get("id") or not data.get("user_id"):
            return None               # baris kosong -> anggap gagal klaim
        return data
    except Exception as exc:  # noqa: BLE001
        print(f"[dlq] claim gagal: {type(exc).__name__}: {exc}")
        return None


def discard_dlq(dlq_id: str, user_id: str) -> bool:
    res = (_svc().table("dead_letter_queue")
           .update({"status": "discarded", "updated_at": _iso(_now())})
           .eq("id", dlq_id).eq("user_id", str(user_id))
           .eq("status", "pending").execute())
    return bool(res.data)


def dlq_stats(user_id: str) -> dict[str, int]:
    """Statistik DLQ per user.

    Sama seperti claim_dlq: hasil RPC divalidasi, karena PostgREST bisa
    mengembalikan baris berisi NULL semua saat tidak ada data.
    """
    try:
        res = _svc().rpc("dlq_stats", {"p_user_id": str(user_id)}).execute()
        data = res.data
        if isinstance(data, dict):
            data = [data] if data.get("status") else []
        out: dict[str, int] = {}
        for r in (data or []):
            if not isinstance(r, dict):
                continue
            st = r.get("status")
            jml = r.get("jumlah")
            if st is None or jml is None:
                continue
            out[str(st)] = int(jml)
        if out:
            return out
    except Exception as exc:  # noqa: BLE001
        print(f"[dlq] stats RPC dilewati: {type(exc).__name__}: {exc}")
    # fallback hitung langsung
    rows = list_dlq(user_id, limit=200)
    out2: dict[str, int] = {}
    for r in rows:
        st = r.get("status") or "pending"
        out2[st] = out2.get(st, 0) + 1
    return out2


# ---------------------------------------------------------------------------
# 5. Jalankan node dengan SELURUH proteksi (retry + sirkuit + DLQ)
# ---------------------------------------------------------------------------

def run_protected(fn: Callable[[], Any], *, execution_id: Optional[str] = None,
                  workflow_id: Optional[str] = None, user_id: str,
                  step_id: str, node_type: str = "",
                  breaker: Optional[str] = None,
                  max_attempts: int = MAX_ATTEMPTS,
                  sleep: Callable[[float], None] = time.sleep,
                  payload: Any = None) -> dict:
    """Jalankan satu node dengan proteksi lengkap.

    Urutan:
      1. Sirkuit terbuka? -> fail fast, TIDAK memanggil fn, langsung DLQ.
      2. Retry + backoff (hanya error yang layak).
      3. Gagal habis -> DLQ + buka sirkuit.
    """
    nama_cb = breaker or f"node:{node_type or step_id}"

    if not circuit_allows(nama_cb):
        pesan = f"CircuitBreakerError: sirkuit '{nama_cb}' terbuka"
        push_dlq(execution_id=execution_id, workflow_id=workflow_id,
                 user_id=user_id, step_id=step_id, node_type=node_type,
                 attempts=0, last_error=pesan, payload=payload)
        return {"ok": False, "result": None, "error": pesan,
                "attempts": 0, "circuit": "open", "dlq": True}

    ok, hasil, err, percobaan = with_retry(
        fn, step_id=step_id, max_attempts=max_attempts, sleep=sleep)

    if ok:
        circuit_success(nama_cb)
        return {"ok": True, "result": hasil, "error": None,
                "attempts": percobaan, "circuit": "closed", "dlq": False}

    state = circuit_failure(nama_cb, err or "")
    push_dlq(execution_id=execution_id, workflow_id=workflow_id,
             user_id=user_id, step_id=step_id, node_type=node_type,
             attempts=percobaan, last_error=err or "", payload=payload)
    return {"ok": False, "result": None, "error": err,
            "attempts": percobaan, "circuit": state, "dlq": True}
