# parallel_fanout.py — Fitur #5 (8 Okt 2026)
# ======================================================================
# Parallel Fan-Out / Fan-In di atas skema Katalir sendiri (Supabase Postgres).
#
# RISET (docs/fitur-05-parallel-fanout.md):
#   Mesin Katalir (StatefulOrchestrator.run) SUDAH menjalankan node selevel
#   dengan `asyncio.gather`, tetapi tiga hal yang diminta brief TIDAK ADA:
#     (a) merge/join barrier — "merge tunggu semua" tidak dijamin eksplisit,
#         kegagalan satu cabang langsung melempar RuntimeError dan cabang
#         lain dibiarkan menggantung;
#     (b) timeout per cabang — satu cabang lambat menahan seluruh gelombang;
#     (c) partial-failure policy — tidak ada pilihan all_settled / quorum.
#
#   Kandidat yang diverifikasi (detail di dok riset):
#     anyio 4.15.1        MIT, Production/Stable, rilis 5 Sep 2026  -> DIPAKAI
#     asyncio.TaskGroup   bawaan 3.11+, tapi semua-atau-tidak-sama-sekali
#                         (sekali gagal -> seluruh grup dibatalkan)
#     mcp-agent Parallel  bagus tapi menyeret framework penuh + LLM
#     pyagent/mcp-agent   pola terdokumentasi, bukan pustaka inti
#     asyncio.gather      primitif yang sudah dipakai; tetap dipakai di sini
#                         tapi dibungkus dengan timeout + kebijakan
#
#   anyio dipilih karena `move_on_after` memberi TIMEOUT PER CABANG tanpa
#   membatalkan saudaranya — tepat untuk (b) — dan `create_task_group`
#   memberi penantian eksplisit untuk (a). Diverifikasi langsung:
#     T2 timeout: {'cepat': 'cepat ok', 'lambat': 'TIMEOUT'}
#     T3 partial: {'satu': 'satu ok', 'dua': 'ERR:dua gagal'}
#
# PRINSIP KEAMANAN (sama seperti scheduler_manager / durable_execution):
#   Setiap fungsi yang menyentuh data user WAJIB menerima user_id dan
#   memfilternya. Tidak ada jalur yang bisa membaca cabang milik user lain.
#
# SEMUA fungsi sinkron yang dipanggil dari endpoint FastAPI sync, KECUALI
# `run_branches` yang async (dipanggil dari konteks async mesin eksekusi).
# ======================================================================

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone as dt_timezone
from typing import Any, Awaitable, Callable, Optional

import anyio

import database as db

# Batas bawaan per cabang (detik). Brief: timeout per branch.
DEFAULT_BRANCH_TIMEOUT_S = 120.0
# Batas jumlah cabang sekali fan-out — penjaga terhadap fan-out tak terbatas.
MAX_BRANCHES = 64
# Kebijakan merge yang dikenal.
POLICIES = ("all_success", "all_settled", "quorum")
# Status yang dianggap "selesai" (tidak akan berubah lagi).
SETTLED = ("success", "failed", "timeout", "skipped", "cancelled")


def _svc():
    return db.get_write_client()


def _now_utc() -> datetime:
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
# 1. FAN-OUT: daftarkan cabang-cabang (idempoten)
# ---------------------------------------------------------------------------

def fan_out(execution_id: str, split_step_id: str,
            branch_keys: list[str],
            merge_step_id: Optional[str] = None,
            inputs: Optional[dict[str, Any]] = None,
            policy: str = "all_success") -> list[dict]:
    """Daftarkan cabang cabang untuk satu node SPLIT.

    Idempoten lewat unique (execution_id, split_step_id, branch_key): cabang
    yang sudah ada TIDAK dibuat ulang. Ini yang membuat resume setelah restart
    tidak menggandakan cabang (dan karenanya tidak menggandakan efek samping).

    Return: daftar baris cabang (semua, termasuk yang sudah ada sebelumnya).
    """
    if policy not in POLICIES:
        raise ValueError(f"policy tidak dikenal: {policy!r} (pilih {POLICIES})")
    keys = [str(k) for k in branch_keys]
    if not keys:
        return []
    if len(keys) > MAX_BRANCHES:
        raise ValueError(
            f"fan-out {len(keys)} cabang melebihi MAX_BRANCHES={MAX_BRANCHES}")
    if len(set(keys)) != len(keys):
        raise ValueError("branch_keys mengandung duplikat")

    svc = _svc()
    ada = (svc.table("execution_branches").select("branch_key")
           .eq("execution_id", execution_id)
           .eq("split_step_id", split_step_id).execute()).data or []
    sudah = {r["branch_key"] for r in ada}

    baris = []
    for k in keys:
        if k in sudah:
            continue
        baris.append({
            "execution_id": execution_id,
            "split_step_id": split_step_id,
            "branch_key": k,
            "merge_step_id": merge_step_id,
            "status": "pending",
            "input": _aman_json((inputs or {}).get(k, {})),
        })
    if baris:
        # Balapan antar replika: unique constraint melempar -> abaikan,
        # baris yang menang tetap diambil di query akhir.
        try:
            svc.table("execution_branches").insert(baris).execute()
        except Exception as exc:  # noqa: BLE001
            print(f"[fanout] insert cabang ada balapan ({type(exc).__name__}), "
                  f"lanjut ambil baris yang menang")

    # Simpan kebijakan merge pada eksekusi (dipakai resume/fan-in).
    try:
        svc.table("executions").update(
            {"parallel_policy": policy,
             "updated_at": _iso(_now_utc())}).eq("id", execution_id).execute()
    except Exception as exc:  # noqa: BLE001
        print(f"[fanout] gagal simpan policy: {type(exc).__name__}: {exc}")

    return list_branches(execution_id, split_step_id=split_step_id)


def list_branches(execution_id: str, split_step_id: Optional[str] = None,
                  user_id: Optional[str] = None) -> list[dict]:
    """Daftar cabang satu eksekusi (opsional difilter node SPLIT).

    Bila user_id diberikan, eksekusi WAJIB milik user itu.
    """
    if user_id is not None and not milik_user(execution_id, user_id):
        return []
    q = (_svc().table("execution_branches").select("*")
         .eq("execution_id", execution_id))
    if split_step_id:
        q = q.eq("split_step_id", split_step_id)
    return q.order("branch_key").execute().data or []


def milik_user(execution_id: str, user_id: str) -> bool:
    """Cek kepemilikan lewat executions -> workflows (executions tanpa user_id)."""
    rows = (_svc().table("executions").select("workflow_id")
            .eq("id", execution_id).limit(1).execute()).data or []
    if not rows:
        return False
    wf = (_svc().table("workflows").select("user_id")
          .eq("id", rows[0]["workflow_id"]).limit(1).execute()).data or []
    return bool(wf) and str(wf[0].get("user_id")) == str(user_id)


# ---------------------------------------------------------------------------
# 2. Status per cabang
# ---------------------------------------------------------------------------

def mark_branch(execution_id: str, split_step_id: str, branch_key: str,
                status: str, output: Any = None, error: Optional[str] = None,
                attempt: int = 1) -> bool:
    """Perbarui satu cabang. Return False bila cabang tidak ada.

    Idempotensi: cabang yang SUDAH settled tidak ditimpa kembali menjadi
    'running' (menjaga hasil akhir saat resume/replay).
    """
    svc = _svc()
    rows = (svc.table("execution_branches").select("id, status")
            .eq("execution_id", execution_id)
            .eq("split_step_id", split_step_id)
            .eq("branch_key", str(branch_key)).limit(1).execute()).data or []
    if not rows:
        return False
    if rows[0].get("status") in SETTLED and status == "running":
        return True                       # jangan hidupkan ulang yang sudah final
    upd: dict[str, Any] = {"status": status, "attempt": attempt}
    if output is not None:
        upd["output"] = _aman_json(output)
    if error is not None:
        upd["error"] = str(error)[:2000]
    if status == "running":
        upd["started_at"] = _iso(_now_utc())
    if status in SETTLED:
        upd["finished_at"] = _iso(_now_utc())
    svc.table("execution_branches").update(upd).eq("id", rows[0]["id"]).execute()
    return True


def branch_summary(execution_id: str) -> dict:
    """Agregat cabang. Pakai RPC; fallback hitung lokal bila RPC tak ada."""
    try:
        res = _svc().rpc("branch_summary", {"p_execution_id": execution_id}).execute()
        data = res.data
        if isinstance(data, list):
            data = data[0] if data else None
        if isinstance(data, dict) and "total" in data:
            return data
    except Exception as exc:  # noqa: BLE001
        print(f"[fanout] branch_summary RPC dilewati: {type(exc).__name__}: {exc}")
    # Fallback lokal
    rows = (_svc().table("execution_branches").select("status")
            .eq("execution_id", execution_id).execute()).data or []
    tally = {s: 0 for s in SETTLED}
    for r in rows:
        tally[r.get("status", "")] = tally.get(r.get("status", ""), 0) + 1
    return {
        "execution_id": execution_id,
        "total": len(rows),
        "success": tally.get("success", 0),
        "failed": tally.get("failed", 0),
        "timeout": tally.get("timeout", 0),
        "skipped": tally.get("skipped", 0),
        "cancelled": tally.get("cancelled", 0),
        "running": tally.get("running", 0) + tally.get("pending", 0),
        "settled": sum(tally.get(s, 0) for s in SETTLED),
    }


def mark_branches_bulk(execution_id: str, split_step_id: str,
                       updates: dict[str, tuple[str, Any, Optional[str]]]
                       ) -> int:
    """Tulis BANYAK cabang dalam SATU panggilan HTTP.

    `updates` = {branch_key: (status, output, error)}.

    Kenapa ini ada (temuan benchmark): satu panggilan PostgREST memakan
    ~110-125 ms. Menulis 8 cabang satu-per-satu = 8 round trip = >0.9 s
    hanya untuk pembukuan, yang membuat fan-out 8x0.1 s selesai dalam ~1.06 s
    (lebih lambat daripada seri!). Satu upsert massal memangkas itu jadi
    satu round trip. Ini bukan mikro-optimasi — tanpa ini "paralel" lebih
    lambat daripada berurutan.

    Return: jumlah baris yang disetel.
    """
    if not updates:
        return 0
    payload = []
    for kunci, (status, output, error) in updates.items():
        item: dict[str, Any] = {"branch_key": str(kunci), "status": status}
        if output is not None:
            item["output"] = _aman_json(output)
        if error is not None:
            item["error"] = str(error)[:2000]
        payload.append(item)
    if not payload:
        return 0
    # Satu RPC = satu round trip. (PostgREST upsert tidak bisa: payload
    # parsial diperlakukan INSERT -> kolom NOT NULL jadi NULL -> 23502.)
    try:
        res = _svc().rpc("bulk_update_branches", {
            "p_execution_id": execution_id,
            "p_split_step_id": split_step_id,
            "p_updates": payload,
        }).execute()
        return int(res.data or 0)
    except Exception as exc:  # noqa: BLE001 - jangan jatuhkan fan-out
        print(f"[fanout] bulk_update gagal ({type(exc).__name__}), "
              f"fallback per-cabang: {exc}")
        n = 0
        for kunci, (status, output, error) in updates.items():
            if mark_branch(execution_id, split_step_id, kunci, status,
                           output, error):
                n += 1
        return n


def all_settled(execution_id: str, merge_step_id: Optional[str] = None) -> bool:
    """True bila SEMUA cabang sudah final (tidak ada running/pending)."""
    s = branch_summary(execution_id)
    if s.get("total", 0) == 0:
        return True
    if merge_step_id:
        rows = (_svc().table("execution_branches").select("status")
                .eq("execution_id", execution_id)
                .eq("merge_step_id", merge_step_id).execute()).data or []
        return bool(rows) and all(r["status"] in SETTLED for r in rows)
    return s.get("running", 0) == 0 and s.get("settled", 0) == s.get("total", 0)


# ---------------------------------------------------------------------------
# 3. FAN-IN: kebijakan merge
# ---------------------------------------------------------------------------

def merge_decision(execution_id: str,
                   policy: str = "all_success") -> dict:
    """Putuskan hasil merge berdasarkan kebijakan.

    all_success : sukses hanya bila SEMUA cabang sukses (classic barrier).
    all_settled : lanjut apa pun hasilnya; yang gagal dilaporkan, bukan fatal.
    quorum      : lanjut bila mayoritas (>= separuh) cabang sukses.

    Return: {ok, policy, summary, outputs, failed_keys, timeout_keys,
             reason}
    """
    if policy not in POLICIES:
        raise ValueError(f"policy tidak dikenal: {policy!r} (pilih {POLICIES})")
    rows = list_branches(execution_id)
    s = branch_summary(execution_id)
    outputs = {r["branch_key"]: r.get("output") for r in rows}
    gagal = [r["branch_key"] for r in rows if r["status"] == "failed"]
    timeout = [r["branch_key"] for r in rows if r["status"] == "timeout"]
    sukses = [r["branch_key"] for r in rows if r["status"] == "success"]

    if s.get("running", 0) > 0:
        return {"ok": False, "policy": policy, "summary": s, "outputs": outputs,
                "failed_keys": gagal, "timeout_keys": timeout,
                "reason": f"masih ada {s['running']} cabang berjalan"}

    total = s.get("total", 0)
    if total == 0:
        return {"ok": True, "policy": policy, "summary": s, "outputs": {},
                "failed_keys": [], "timeout_keys": [],
                "reason": "tidak ada cabang"}

    if policy == "all_success":
        ok = (len(sukses) == total)
        reason = ("semua cabang sukses" if ok else
                  f"{len(gagal)} gagal, {len(timeout)} timeout dari {total}")
    elif policy == "all_settled":
        ok = True
        reason = (f"semua cabang selesai (settled): {len(sukses)} sukses, "
                  f"{len(gagal)} gagal, {len(timeout)} timeout")
    else:  # quorum = MAYORITAS MURNI (lebih dari separuh)
        # Catatan: 2/4 BUKAN mayoritas (tepat separuh). Ambang ini sengaja
        # ketat supaya "quorum" tidak diam-diam menerima hasil seri.
        butuh = (total // 2) + 1
        ok = len(sukses) >= butuh
        reason = (f"quorum: {len(sukses)}/{total} sukses "
                  f"(butuh >= {butuh}, mayoritas murni)")
    return {"ok": ok, "policy": policy, "summary": s, "outputs": outputs,
            "failed_keys": gagal, "timeout_keys": timeout, "reason": reason}


# ---------------------------------------------------------------------------
# 4. EKSEKUTOR: jalankan cabang paralel dengan timeout per cabang
# ---------------------------------------------------------------------------

async def run_branches(execution_id: str, split_step_id: str,
                       pekerja: Callable[[str, Any], Awaitable[Any]],
                       inputs: Optional[dict[str, Any]] = None,
                       timeout_s: float = DEFAULT_BRANCH_TIMEOUT_S,
                       policy: str = "all_success",
                       merge_step_id: Optional[str] = None,
                       per_branch_timeout: Optional[dict[str, float]] = None,
                       ) -> dict:
    """Jalankan pekerja untuk setiap cabang SECARA PARALEL.

    - `pekerja(branch_key, input)` -> coroutine; hasilnya jadi output cabang.
    - Timeout PER CABANG (anyio.move_on_after) tidak membatalkan saudaranya.
    - Semua cabang ditunggu (anyio task group) -> barrier merge sungguhan.
    - Keadaan tiap cabang ditulis ke Postgres, jadi tahan restart.
    - `per_branch_timeout` menimpa timeout cabang tertentu.

    Return: hasil merge_decision() + daftar cabang terbaru.
    """
    baris = list_branches(execution_id, split_step_id=split_step_id)
    if not baris:
        baris = fan_out(execution_id, split_step_id, list((inputs or {}).keys()),
                        merge_step_id=merge_step_id, inputs=inputs, policy=policy)

    # SATU round trip: tandai semua cabang "running" sekaligus.
    # (Sebelum ini: satu panggilan per cabang -> I/O mendominasi dan
    # fan-out justru LEBIH LAMBAT daripada seri. Lihat mark_branches_bulk.)
    await asyncio.to_thread(
        mark_branches_bulk, execution_id, split_step_id,
        {r["branch_key"]: ("running", None, None) for r in baris})

    # Hasil tiap cabang dikumpulkan di memori; ditulis ke DB SEKALI di akhir.
    hasil_per_cabang: dict[str, tuple[str, Any, Optional[str]]] = {}

    async def satu_cabang(row: dict) -> None:
        kunci = row["branch_key"]
        batas = float((per_branch_timeout or {}).get(kunci, timeout_s))
        try:
            with anyio.move_on_after(batas) as scope:
                hasil = await pekerja(kunci, row.get("input") or {})
            if scope.cancelled_caught:
                hasil_per_cabang[kunci] = (
                    "timeout", None, f"timeout setelah {batas:.1f}s")
                return
            hasil_per_cabang[kunci] = ("success", hasil, None)
        except Exception as exc:  # noqa: BLE001 - kegagalan 1 cabang != fatal
            hasil_per_cabang[kunci] = (
                "failed", None, f"{type(exc).__name__}: {exc}")

    # anyio memerlukan backend asyncio/trio. Katalir jalan di asyncio (FastAPI),
    # jadi bila kita sudah di dalam loop asyncio, pakai task group asyncio
    # yang setara — semantiknya sama (barrier + tidak membatalkan saudara).
    try:
        asyncio.get_running_loop()
        async with asyncio.TaskGroup() as tg:
            for row in baris:
                tg.create_task(satu_cabang(row))
    except RuntimeError:
        async with anyio.create_task_group() as tg:
            for row in baris:
                tg.start_soon(satu_cabang, row)

    # SATU round trip lagi: tulis semua hasil akhir sekaligus.
    await asyncio.to_thread(mark_branches_bulk, execution_id, split_step_id,
                            hasil_per_cabang)

    # Ringkasan & daftar cabang juga I/O sinkron -> jangan blokir loop.
    hasil = await asyncio.to_thread(merge_decision, execution_id, policy)
    hasil["branches"] = await asyncio.to_thread(
        list_branches, execution_id, split_step_id)
    return hasil


# ---------------------------------------------------------------------------
# 5. Resume setelah restart: cabang yang belum final dijalankan ulang
# ---------------------------------------------------------------------------

def unfinished_branches(execution_id: str,
                        split_step_id: Optional[str] = None) -> list[dict]:
    """Cabang yang belum final -> kandidat dijalankan ulang saat resume."""
    rows = list_branches(execution_id, split_step_id=split_step_id)
    return [r for r in rows if r.get("status") not in SETTLED]


def seconds_since_start(row: dict) -> Optional[float]:
    """Usia cabang (detik) sejak started_at. None bila belum mulai."""
    ts = row.get("started_at")
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)
        return (_now_utc() - dt.astimezone(dt_timezone.utc)).total_seconds()
    except Exception:  # noqa: BLE001
        return None
