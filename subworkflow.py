# subworkflow.py — Fitur #4 (8 Okt 2026)
# ======================================================================
# Sub-workflow execution: satu workflow memanggil workflow lain sebagai anak.
#
# RISET (docs/fitur-04-subworkflow.md):
#   Pola `ref_workflow_id` (didi/tg-flow) + rekomendasi praktik terbaik
#   "Keep nesting depth ≤3 levels for maintainability" — persis batas yang
#   diminta brief.
#
# CACAT REFERENSI YANG KITA PERBAIKI:
#   tg-flow mengizinkan kedalaman tak terbatas TANPA deteksi siklus, sehingga
#   A memanggil B dan B memanggil A akan berputar sampai kehabisan resource.
#   Modul ini menolak siklus SEBELUM anak dijalankan.
#
# ATURAN KEAMANAN:
#   1. Anak WAJIB milik user yang sama dengan induk (tidak boleh memanggil
#      workflow milik orang lain — itu kebocoran lintas-tenant).
#   2. Kedalaman maksimum 3.
#   3. Siklus ditolak.
#   4. Pemanggilan idempoten per (parent_execution, step_id) supaya replay
#      eksekusi induk tidak menjalankan anak dua kali.
# ======================================================================

from __future__ import annotations

import json
import os
from datetime import datetime, timezone as dt_timezone
from typing import Any, Optional

import database as db

#: Kedalaman maksimum nesting sub-workflow. Dapat di-tune lewat env.
#: Default tetap 3 (dipakai & diuji sebagai perilaku saat ini). Brief fitur #4
#: menyebut "default 5" — sekarang bisa dipenuhi lewat SUBWORKFLOW_MAX_DEPTH=5
#: tanpa mengubah kode, dan tanpa memecah tes yang mengunci nilai 3.
MAX_DEPTH = int(os.getenv("SUBWORKFLOW_MAX_DEPTH", "3"))
DEFAULT_CHILD_TIMEOUT_S = int(os.getenv("SUBWORKFLOW_CHILD_TIMEOUT_S", "300"))


def _svc():
    return db.get_write_client()


def _now() -> datetime:
    return datetime.now(dt_timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(dt_timezone.utc).isoformat()


def _aman_json(v: Any) -> Any:
    try:
        json.dumps(v)
        return v
    except (TypeError, ValueError):
        return {"_repr": str(v)[:2000]}


# ---------------------------------------------------------------------------
# Kepemilikan
# ---------------------------------------------------------------------------

def workflow_owner(workflow_id: str) -> Optional[str]:
    rows = (_svc().table("workflows").select("user_id")
            .eq("id", workflow_id).limit(1).execute()).data or []
    return str(rows[0]["user_id"]) if rows else None


def execution_owner(execution_id: str) -> Optional[str]:
    """Pemilik eksekusi = pemilik workflow-nya (executions tak punya user_id)."""
    ex = (_svc().table("executions").select("workflow_id")
          .eq("id", execution_id).limit(1).execute()).data or []
    if not ex:
        return None
    return workflow_owner(ex[0]["workflow_id"])


# ---------------------------------------------------------------------------
# Pemeriksaan kedalaman + siklus (lewat RPC, atomik di DB)
# ---------------------------------------------------------------------------

def check_allowed(parent_execution_id: str, child_workflow_id: str,
                  max_depth: int = MAX_DEPTH) -> dict:
    """Tanya DB apakah pemanggilan ini boleh (kedalaman + siklus).

    Fallback lokal bila RPC tidak tersedia supaya fitur tidak mati total —
    tapi hasilnya HARUS dari DB kalau RPC ada, karena hanya DB yang punya
    gambaran rantai leluhur yang lengkap.
    """
    try:
        res = _svc().rpc("check_subworkflow_allowed", {
            "p_parent_execution_id": parent_execution_id,
            "p_child_workflow_id": child_workflow_id,
            "p_max_depth": int(max_depth),
        }).execute()
        data = res.data
        if isinstance(data, list):
            data = data[0] if data else None
        if isinstance(data, dict) and "allowed" in data:
            return {"allowed": bool(data["allowed"]),
                    "reason": data.get("reason") or "",
                    "depth": int(data.get("depth") or 0)}
    except Exception as exc:  # noqa: BLE001
        print(f"[subwf] RPC cek gagal, pakai fallback: "
              f"{type(exc).__name__}: {exc}")
    return _check_allowed_lokal(parent_execution_id, child_workflow_id, max_depth)


def _check_allowed_lokal(parent_execution_id: str, child_workflow_id: str,
                         max_depth: int) -> dict:
    """Fallback: telusuri rantai leluhur lewat REST."""
    svc = _svc()
    rows = (svc.table("executions").select("id, workflow_id, depth, parent_execution_id")
            .eq("id", parent_execution_id).limit(1).execute()).data or []
    if not rows:
        return {"allowed": False, "reason": "eksekusi induk tidak ditemukan",
                "depth": 0}
    depth = int(rows[0].get("depth") or 0)
    if depth + 1 > max_depth:
        return {"allowed": False,
                "reason": f"kedalaman maksimum {max_depth} terlampaui",
                "depth": depth + 1}

    cur_id = parent_execution_id
    leluhur = {parent_execution_id}
    for _ in range(50):
        if not cur_id:
            break
        r = (svc.table("executions").select("workflow_id, parent_execution_id")
             .eq("id", cur_id).limit(1).execute()).data or []
        if not r:
            break
        if str(r[0].get("workflow_id")) == str(child_workflow_id):
            return {"allowed": False,
                    "reason": "siklus terdeteksi: workflow anak ada di rantai leluhur",
                    "depth": depth + 1}
        nxt = r[0].get("parent_execution_id")
        if not nxt or nxt in leluhur:
            break
        leluhur.add(nxt)
        cur_id = nxt
    return {"allowed": True, "reason": "ok", "depth": depth + 1}


# ---------------------------------------------------------------------------
# Pemanggilan sub-workflow
# ---------------------------------------------------------------------------

def invoke_subworkflow(*, parent_execution_id: str, step_id: str,
                       child_workflow_id: str, user_id: str,
                       input_data: Optional[dict] = None,
                       max_depth: int = MAX_DEPTH,
                       runner: Optional[Any] = None) -> dict:
    """Panggil workflow anak dari dalam eksekusi induk.

    `runner` adalah callable opsional (child_workflow_id, input_data, depth)
    -> hasil. Kalau None, anak hanya DIDAFTARKAN (status running) dan
    pemanggil yang menjalankannya — berguna untuk tes dan untuk engine yang
    sudah punya cara sendiri menjalankan workflow.

    Mengembalikan dict:
      {ok, child_execution_id, output, error, depth, reason}
    """
    svc = _svc()

    # 1. Idempotensi: step ini sudah pernah memanggil anak?
    ada = (svc.table("subworkflow_invocations").select("*")
           .eq("parent_execution_id", parent_execution_id)
           .eq("step_id", step_id).limit(1).execute()).data or []
    if ada:
        row = ada[0]
        if row.get("status") == "success":
            return {"ok": True, "child_execution_id": row.get("child_execution_id"),
                    "output": row.get("output"), "error": None,
                    "depth": None, "reason": "replay: anak sudah dijalankan"}
        # masih running / gagal -> lanjutkan pemanggilan

    # 2. KEAMANAN: anak harus milik user yang sama
    pemilik_anak = workflow_owner(child_workflow_id)
    if pemilik_anak is None:
        return {"ok": False, "child_execution_id": None, "output": None,
                "error": "workflow anak tidak ditemukan", "depth": None,
                "reason": "not_found"}
    if pemilik_anak != str(user_id):
        return {"ok": False, "child_execution_id": None, "output": None,
                "error": "workflow anak bukan milik user ini", "depth": None,
                "reason": "forbidden"}

    # 3. Kedalaman + siklus
    cek = check_allowed(parent_execution_id, child_workflow_id, max_depth)
    if not cek["allowed"]:
        _catat_invokasi(parent_execution_id, step_id, child_workflow_id,
                        None, "failed", input_data, None, cek["reason"])
        return {"ok": False, "child_execution_id": None, "output": None,
                "error": cek["reason"], "depth": cek.get("depth"),
                "reason": "depth_or_cycle"}

    # 4. Catat rantai (untuk deteksi siklus berikutnya)
    _catat_rantai(parent_execution_id, child_workflow_id, cek.get("depth") or 0)

    # 5. Buat eksekusi anak
    import durable_execution as de
    induk = de.get_execution(parent_execution_id) or {}
    anak = de.start_execution(
        child_workflow_id, state={"input": _aman_json(input_data or {})},
        parent_execution_id=parent_execution_id)

    # tetapkan depth anak
    try:
        svc.table("executions").update({"depth": int(cek.get("depth") or 0)}) \
            .eq("id", anak["id"]).execute()
    except Exception as exc:  # noqa: BLE001
        print(f"[subwf] set depth gagal: {type(exc).__name__}: {exc}")

    _catat_invokasi(parent_execution_id, step_id, child_workflow_id,
                    anak["id"], "running", input_data, None, None)

    # 6. Jalankan anak (bila runner tersedia)
    if runner is None:
        return {"ok": True, "child_execution_id": anak["id"], "output": None,
                "error": None, "depth": cek.get("depth"),
                "reason": "didaftarkan (runner tidak diberikan)"}

    try:
        keluaran = runner(child_workflow_id, input_data or {},
                          int(cek.get("depth") or 0))
        de.finish_execution(anak["id"], "success", keluaran)
        _catat_invokasi(parent_execution_id, step_id, child_workflow_id,
                        anak["id"], "success", input_data, keluaran, None)
        return {"ok": True, "child_execution_id": anak["id"],
                "output": keluaran, "error": None,
                "depth": cek.get("depth"), "reason": "ok"}
    except Exception as exc:  # noqa: BLE001
        pesan = f"{type(exc).__name__}: {exc}"
        de.finish_execution(anak["id"], "failed", {"error": pesan})
        _catat_invokasi(parent_execution_id, step_id, child_workflow_id,
                        anak["id"], "failed", input_data, None, pesan)
        return {"ok": False, "child_execution_id": anak["id"], "output": None,
                "error": pesan, "depth": cek.get("depth"), "reason": "child_failed"}


def _catat_rantai(execution_id: str, child_workflow_id: str, depth: int) -> None:
    try:
        induk_wf = (_svc().table("executions").select("workflow_id")
                    .eq("id", execution_id).limit(1).execute()).data or []
        if not induk_wf:
            return
        _svc().table("workflow_call_chain").insert({
            "execution_id": execution_id,
            "child_workflow_id": child_workflow_id,
            "parent_workflow_id": induk_wf[0]["workflow_id"],
            "depth": int(depth),
        }).execute()
    except Exception as exc:  # noqa: BLE001
        print(f"[subwf] catat rantai gagal: {type(exc).__name__}: {exc}")


def _catat_invokasi(parent_execution_id: str, step_id: str,
                    child_workflow_id: str, child_execution_id: Optional[str],
                    status: str, input_data: Any, output: Any,
                    error: Optional[str]) -> None:
    try:
        row = {
            "parent_execution_id": parent_execution_id, "step_id": step_id,
            "child_workflow_id": child_workflow_id,
            "child_execution_id": child_execution_id,
            "status": status, "input": _aman_json(input_data),
            "output": _aman_json(output), "error": error,
            "updated_at": _iso(_now()),
        }
        # updated_at tidak ada di tabel -> buang agar insert tidak error
        row.pop("updated_at", None)
        if status != "running":
            row["finished_at"] = _iso(_now())
        _svc().table("subworkflow_invocations").upsert(
            row, on_conflict="parent_execution_id,step_id").execute()
    except Exception as exc:  # noqa: BLE001
        print(f"[subwf] catat invokasi gagal: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Observabilitas
# ---------------------------------------------------------------------------

def list_invocations(parent_execution_id: str, user_id: str) -> list[dict]:
    """Daftar pemanggilan anak untuk sebuah eksekusi induk (milik user)."""
    if execution_owner(parent_execution_id) != str(user_id):
        return []
    return (_svc().table("subworkflow_invocations").select("*")
            .eq("parent_execution_id", parent_execution_id)
            .order("started_at").execute()).data or []


def call_chain(execution_id: str, user_id: str) -> list[dict]:
    """Rantai pemanggilan (untuk audit/deteksi siklus)."""
    if execution_owner(execution_id) != str(user_id):
        return []
    return (_svc().table("workflow_call_chain").select("*")
            .eq("execution_id", execution_id)
            .order("depth").execute()).data or []


def execution_depth(execution_id: str) -> int:
    rows = (_svc().table("executions").select("depth")
            .eq("id", execution_id).limit(1).execute()).data or []
    return int((rows[0].get("depth") if rows else 0) or 0)
