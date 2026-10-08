# durable_execution.py — Fitur #2 (8 Okt 2026)
# ======================================================================
# Durable execution di atas skema Katalir sendiri (Supabase Postgres).
#
# RISET (docs/fitur-02-durable-execution.md):
#   dbos 3.2.0 (MIT, 524 rilis) TERVERIFIKASI melakukan resume-dari-checkpoint
#   terhadap Postgres Supabase — uji crash os._exit(137): langkah 1 & 2 TIDAK
#   diulang, hanya langkah 3 yang jalan setelah recover. Tetapi memakai
#   runtime DBOS langsung berarti mengganti engine Katalir yang sudah jalan
#   menjelang launch, jadi SEMANTIK-nya yang diterapkan di sini:
#
#     1. Checkpoint per node     -> executions.state + execution_steps
#     2. Replay: node yang sudah sukses TIDAK dijalankan ulang
#     3. Idempotency key         -> unique (workflow_id, idempotency_key)
#     4. External signal         -> executions.waiting_for (+ wake_up_signal)
#     5. Heartbeat               -> deteksi eksekusi macet
#     6. Pemulihan saat startup  -> claim_stuck_executions() (atomic, skip locked)
#
# PRINSIP KEAMANAN (sama seperti scheduler_manager):
#   Setiap fungsi yang menyentuh data user WAJIB menerima user_id dan
#   memfilternya. Tidak ada jalur yang bisa membaca eksekusi milik user lain.
#
# SEMUA fungsi sinkron (dipakai dari endpoint FastAPI sync).
# ======================================================================

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Optional

import database as db

# Eksekusi dianggap macet bila heartbeat terakhir lebih lama dari ini.
STUCK_AFTER_SECONDS = 300          # 5 menit (sesuai brief)
HEARTBEAT_INTERVAL_SECONDS = 60

# Status yang boleh dipulihkan.
RESUMABLE_STATUSES = ("running", "pending", "interrupted")


def _svc():
    return db.get_write_client()


def _now_utc() -> datetime:
    return datetime.now(dt_timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(dt_timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 1. Eksekusi: buat / ambil dengan idempotency key
# ---------------------------------------------------------------------------

def start_execution(workflow_id: str, *, state: Optional[dict] = None,
                    idempotency_key: Optional[str] = None,
                    parent_execution_id: Optional[str] = None) -> dict:
    """Buat eksekusi baru, atau kembalikan yang SUDAH ada bila
    idempotency_key-nya sama (partial unique index uq_executions_idem).

    Idempotency di sini krusial untuk cron: satu jadwal yang terklaim dua
    kali (atau di-retry) tidak boleh menghasilkan dua eksekusi berbeda.
    """
    if idempotency_key:
        ada = (_svc().table("executions")
               .select("*")
               .eq("workflow_id", workflow_id)
               .eq("idempotency_key", idempotency_key)
               .limit(1).execute()).data or []
        if ada:
            return ada[0]

    row: dict[str, Any] = {
        "workflow_id": workflow_id,
        "status": "running",
        "state": state or {},
        "heartbeat_at": _iso(_now_utc()),
        "retry_count": 0,
    }
    if idempotency_key:
        row["idempotency_key"] = idempotency_key
    if parent_execution_id:
        row["parent_execution_id"] = parent_execution_id
    try:
        res = _svc().table("executions").insert(row).execute()
        return (res.data or [{}])[0]
    except Exception:
        # Balapan: replika lain menyisipkan kunci sama lebih dulu.
        # Partial unique index melempar -> ambil baris yang menang.
        if idempotency_key:
            lagi = (_svc().table("executions").select("*")
                    .eq("workflow_id", workflow_id)
                    .eq("idempotency_key", idempotency_key)
                    .limit(1).execute()).data or []
            if lagi:
                return lagi[0]
        raise


def get_execution(execution_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    """Ambil eksekusi. Bila user_id diberikan, WAJIB milik user itu."""
    q = _svc().table("executions").select("*").eq("id", execution_id)
    rows = q.limit(1).execute().data or []
    if not rows:
        return None
    ex = rows[0]
    if user_id is not None and not _milik_user(ex, user_id):
        return None
    return ex


def _milik_user(execution: dict, user_id: str) -> bool:
    """Cek kepemilikan lewat workflow (executions tidak punya user_id)."""
    wf = (_svc().table("workflows").select("user_id")
          .eq("id", execution.get("workflow_id")).limit(1).execute()).data or []
    return bool(wf) and str(wf[0].get("user_id")) == str(user_id)


# ---------------------------------------------------------------------------
# 2. Checkpoint per node (inti replay)
# ---------------------------------------------------------------------------

def begin_step(execution_id: str, step_id: str, node_type: str = "",
               payload: Optional[dict] = None) -> bool:
    """Catat node MULAI. Return False bila node ini sudah sukses -> PEMANGGIL
    HARUS MELEWATI eksekusi node (itulah replay).

    Pakai upsert on_conflict=(execution_id, step_id) supaya aman dijalankan
    ulang; status 'success' TIDAK ditimpa kembali ke 'running'.
    """
    svc = _svc()
    ada = (svc.table("execution_steps").select("status")
           .eq("execution_id", execution_id).eq("step_id", step_id)
           .limit(1).execute()).data or []
    if ada and ada[0].get("status") == "success":
        return False                      # <-- replay: jangan ulangi

    row = {"execution_id": execution_id, "step_id": step_id,
           "node_type": node_type or "", "status": "running",
           "input": payload or {}, "started_at": _iso(_now_utc())}
    svc.table("execution_steps").upsert(
        row, on_conflict="execution_id,step_id").execute()
    # tandai titik lanjut + detak
    svc.table("executions").update(
        {"current_step_id": step_id, "heartbeat_at": _iso(_now_utc()),
         "updated_at": _iso(_now_utc())}).eq("id", execution_id).execute()
    return True


def finish_step(execution_id: str, step_id: str, output: Any = None,
                error: Optional[str] = None,
                attempt: int = 1) -> None:
    """Catat node SELESAI (sukses/gagal) + simpan hasilnya ke checkpoint state."""
    svc = _svc()
    status = "failed" if error else "success"
    svc.table("execution_steps").update({
        "status": status, "output": _aman_json(output), "error": error,
        "attempt": attempt, "finished_at": _iso(_now_utc()),
    }).eq("execution_id", execution_id).eq("step_id", step_id).execute()

    if not error:
        # gabungkan ke state (checkpoint) supaya resume punya konteks
        try:
            cur = (svc.table("executions").select("state")
                   .eq("id", execution_id).limit(1).execute()).data or [{}]
            state = dict(cur[0].get("state") or {})
            state[step_id] = _aman_json(output)
            svc.table("executions").update(
                {"state": state, "heartbeat_at": _iso(_now_utc()),
                 "updated_at": _iso(_now_utc())}).eq("id", execution_id).execute()
        except Exception as exc:  # noqa: BLE001 - checkpoint gagal != fatal
            print(f"[durable] checkpoint gagal: {type(exc).__name__}: {exc}")


def done_steps(execution_id: str) -> set[str]:
    """step_id yang sudah SUKSES -> pemanggil melewatkannya (replay)."""
    rows = (_svc().table("execution_steps").select("step_id")
            .eq("execution_id", execution_id).eq("status", "success")
            .execute()).data or []
    return {r["step_id"] for r in rows}


def _aman_json(v: Any) -> Any:
    """Pastikan nilai bisa disimpan sebagai jsonb (tidak melempar)."""
    try:
        json.dumps(v)
        return v
    except (TypeError, ValueError):
        return {"_repr": str(v)[:2000]}


# ---------------------------------------------------------------------------
# 3. Heartbeat
# ---------------------------------------------------------------------------

def heartbeat(execution_id: str) -> None:
    _svc().table("executions").update(
        {"heartbeat_at": _iso(_now_utc())}).eq("id", execution_id).execute()


def finish_execution(execution_id: str, status: str = "success",
                     result: Any = None) -> None:
    upd: dict[str, Any] = {"status": status, "updated_at": _iso(_now_utc())}
    if result is not None:
        upd["result"] = _aman_json(result)
    _svc().table("executions").update(upd).eq("id", execution_id).execute()


# ---------------------------------------------------------------------------
# 4. External signal (menunggu approval / webhook)
# ---------------------------------------------------------------------------

def wait_for_signal(execution_id: str, signal_name: str) -> None:
    """Tandai eksekusi sedang MENUNGGU sinyal. Eksekusi yang menunggu
    TIDAK akan diambil pemulihan (lihat claim_stuck_executions)."""
    _svc().table("executions").update({
        "waiting_for": signal_name,
        "status": "waiting",
        "heartbeat_at": _iso(_now_utc()),
        "updated_at": _iso(_now_utc()),
    }).eq("id", execution_id).execute()


def wake_up_signal(execution_id: str, signal_name: str, payload: Any = None) -> bool:
    """Kirim sinyal -> eksekusi lanjut. Idempoten: sinyal kedua diabaikan."""
    svc = _svc()
    rows = (svc.table("executions").select("id, waiting_for, status")
            .eq("id", execution_id).limit(1).execute()).data or []
    if not rows:
        return False
    ex = rows[0]
    if ex.get("waiting_for") != signal_name:
        return False                      # sudah bangun / nama beda -> abaikan
    state = {}
    try:
        cur = (svc.table("executions").select("state")
               .eq("id", execution_id).limit(1).execute()).data or [{}]
        state = dict(cur[0].get("state") or {})
    except Exception:  # noqa: BLE001
        pass
    state[f"signal:{signal_name}"] = _aman_json(payload)
    svc.table("executions").update({
        "waiting_for": None, "status": "running", "state": state,
        "heartbeat_at": _iso(_now_utc()), "updated_at": _iso(_now_utc()),
    }).eq("id", execution_id).execute()
    return True


# ---------------------------------------------------------------------------
# 5. Pemulihan eksekusi macet (dipanggil dari _lifespan saat startup)
# ---------------------------------------------------------------------------

def recover_stuck(limit: int = 50,
                  stale_seconds: int = STUCK_AFTER_SECONDS) -> list[dict]:
    """Klaim eksekusi macet secara ATOMIK lewat RPC (for update skip locked)
    lalu kembalikan daftarnya untuk dilanjutkan.

    Atomik penting: dua replika Railway yang start bersamaan tidak boleh
    memulihkan eksekusi yang sama (itu akan menggandakan efek samping).
    """
    try:
        res = _svc().rpc("claim_stuck_executions", {
            "stale_seconds": int(stale_seconds),
            "max_rows": int(limit),
        }).execute()
        return res.data or []
    except Exception as exc:  # noqa: BLE001 - pemulihan tidak boleh jatuhkan app
        print(f"[durable] recover_stuck dilewati: {type(exc).__name__}: {exc}")
        return []


def resume_execution(execution_id: str) -> bool:
    """Lanjutkan eksekusi dari checkpoint: status kembali 'running' dan
    state dipertahankan. Node yang sudah sukses dilewati lewat done_steps()."""
    try:
        svc = _svc()
        svc.table("executions").update({
            "status": "running",
            "resumed_at": _iso(_now_utc()),
            "heartbeat_at": _iso(_now_utc()),
            "updated_at": _iso(_now_utc()),
        }).eq("id", execution_id).execute()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[durable] resume gagal: {type(exc).__name__}: {exc}")
        return False


def stuck_execution_ids(stale_seconds: int = STUCK_AFTER_SECONDS,
                        limit: int = 50) -> list[str]:
    """Lihat (tanpa mengklaim) id eksekusi macet — untuk observabilitas."""
    batas = _iso(_now_utc() - timedelta(seconds=stale_seconds))
    rows = (_svc().table("executions").select("id, status, heartbeat_at")
            .in_("status", list(RESUMABLE_STATUSES))
            .lt("heartbeat_at", batas)
            .is_("waiting_for", "null")
            .limit(limit).execute()).data or []
    return [r["id"] for r in rows]
