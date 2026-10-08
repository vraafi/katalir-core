# scheduler_manager.py — Scheduled Trigger (cron) untuk workflow Katalir
# ======================================================================
# Opsi B in-house (keputusan riset 8 Okt 2026, terdokumentasi di
# docs/implementation-log-2026-10-08.md):
#   - fastscheduler 0.2.x  -> TERLALU MUDA untuk production (5 rilis, v0.2.x,
#     kriteria yang sama dipakai untuk menolak APScheduler v4 pre-release).
#   - APScheduler 3.11.x   -> matang tapi butuh SQLAlchemy jobstore + tabel
#     sendiri + event broker; integrasi berat jelang launch.
#   - dbos 3.2.0           -> butuh integrasi runtime penuh (decorator).
#   - Opsi ini             -> loop asyncio tipis + croniter (pure-python,
#     stable) + tabel workflow_schedules (Supabase). Nol framework baru.
#
# Desain:
#   - State di DB (workflow_schedules) -> TAHAN RESTART (Railway redeploy
#     tidak menghilangkan jadwal; recovery dihitung ulang saat startup).
#   - Claim optimistis (UPDATE kondisional next_fire_at) -> aman bila
#     Railway di-scale jadi multi-replica: hanya replica yang berhasil
#     meng-claim baris yang menembak, TIDAK ADA double-fire.
#   - Timezone per-jadwal (IANA via zoneinfo) -> "0 22 * * *" berarti
#     22:00 WIB, bukan UTC. Tidak ada hardcode timezone.
#   - Missed-run policy: jadwal yang terlewat <= 24 jam ditembak SEKALI lalu
#     maju; > 24 jam di-skip (tidak burst), next_fire_at dihitung maju.
#
# Kill-switch: env SCHEDULER_ENABLED=0 mematikan loop (dipakai test suite
# via tests/conftest.py supaya tick tidak berlomba dengan test).
# ======================================================================

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from croniter import croniter

import database as db

_log = logging.getLogger("scheduler")

TICK_SECONDS = int(os.getenv("SCHEDULER_TICK_SECONDS", "20"))
MISSED_RUN_MAX_AGE_H = 24
MAX_DUE_PER_TICK = 25


# ---------------------------------------------------------------------------
# Validasi (dipakai endpoint + test)
# ---------------------------------------------------------------------------

def is_valid_cron(expr: str) -> bool:
    """Validasi cron 5-field standar (minute hour dom month dow).

    croniter >= 6 juga menerima 6-field (dengan detik) — sengaja DITOLAK di
    sini supaya API hanya menerima cron standar 5-field (konsisten dengan
    UI dan dokumen user).
    """
    if not expr or not isinstance(expr, str):
        return False
    expr = expr.strip()
    if len(expr.split()) != 5:
        return False
    try:
        return bool(croniter.is_valid(expr))
    except Exception:  # noqa: BLE001
        return False


def is_valid_timezone(tz_name: str) -> bool:
    """Harus IANA (mis. 'Asia/Jakarta'); 'WIB' bukan IANA -> ditolak."""
    if not tz_name or not isinstance(tz_name, str):
        return False
    try:
        ZoneInfo(tz_name.strip())
        return True
    except Exception:  # noqa: BLE001
        return False


def next_fire_utc(cron_expr: str, tz_name: str, base: Optional[datetime] = None) -> datetime:
    """Waktu tembak berikutnya (cron) dalam timezone jadwal, dikembalikan UTC-aware.

    PENTING (bug fix 8 Okt 2026): `base` HARUS dikonversi ke timezone jadwal
    SEBELUM diserahkan ke croniter. Kalau `base` tetap UTC-aware, croniter
    menghitung cron pada dinding jam UTC -> timezone jadwal DIABAIKAN dan
    semua jadwal jatuh di jam UTC yang sama.

    Contoh bug lama: base=10:00Z, "0 22 * * *"
      - Asia/Jakarta     -> salah: 22:00Z (harusnya 15:00Z / 22:00 WIB)
      - America/New_York -> salah: 22:00Z (harusnya 02:00Z besok)
      Keduanya menghasilkan instant UTC identik = timezone tidak berpengaruh.

    Perbaikan: b.astimezone(tz) dulu, sehingga croniter menghitung pada
    dinding jam lokal jadwal, lalu hasilnya dikembalikan ke UTC.
    """
    tz = ZoneInfo(tz_name.strip())
    if base is None:
        b = datetime.now(tz)
    elif base.tzinfo is None:
        # Naive dianggap sudah waktu lokal jadwal (pemanggil yang eksplisit).
        b = base.replace(tzinfo=tz)
    else:
        # tz-aware (umumnya UTC) -> geser ke dinding jam jadwal.
        b = base.astimezone(tz)
    it = croniter(cron_expr.strip(), b)
    nxt = it.get_next(datetime)
    return nxt.astimezone(dt_timezone.utc)


# ---------------------------------------------------------------------------
# Akses DB (service client -> bypass RLS; endpoint tetap cek ownership)
# ---------------------------------------------------------------------------

def _svc():
    """Write client (service_role, bypass RLS). Loop scheduler = trusted."""
    return db.get_write_client()


def utc_now() -> datetime:
    return datetime.now(dt_timezone.utc)


def iso_utc(dt: datetime) -> str:
    """ISO-8601 UTC-aware (untuk kolom timestamptz via PostgREST)."""
    return _iso(dt)


def _iso(dt: datetime) -> str:
    return dt.astimezone(dt_timezone.utc).isoformat()


def fetch_due_schedules(now_utc: datetime,
                        user_id: Optional[str] = None) -> list[dict]:
    """Jadwal yang due.

    `user_id` (opsional) membatasi pemindaian ke satu owner. Dipakai test
    untuk isolasi: `tick()` memindai SEMUA user, sehingga dua test yang
    sama-sama menembak akan saling mencuri jadwal. Runtime produksi tidak
    mengirim user_id -> perilaku tidak berubah.
    """
    # lte terhadap timestamptz otomatis mengecualikan NULL (SQL semantics),
    # jadi tidak perlu filter not-null terpisah.
    q = (
        _svc()
        .table("workflow_schedules")
        .select("*")
        .eq("enabled", True)
        .lte("next_fire_at", _iso(now_utc))
    )
    if user_id:
        q = q.eq("user_id", str(user_id))
    res = q.limit(MAX_DUE_PER_TICK).execute()
    return res.data or []


def claim_schedule(schedule: dict, now_utc: datetime) -> Optional[str]:
    """Claim optimistis: update next_fire_at DENGAN syarat nilai lama masih sama.

    Return next_fire_at baru bila claim sukses, None bila replica lain sudah
    lebih dulu meng-claim (0 baris ter-update).
    """
    expected = schedule["next_fire_at"]
    new_next = next_fire_utc(schedule["cron_expression"], schedule["timezone"], base=now_utc)
    res = (
        _svc()
        .table("workflow_schedules")
        .update({
            "next_fire_at": _iso(new_next),
            "last_fired_at": _iso(now_utc),
            "updated_at": _iso(now_utc),
        })
        .eq("id", schedule["id"])
        .eq("next_fire_at", expected)
        .execute()
    )
    if res.data:
        return _iso(new_next)
    return None


def recover_on_startup() -> int:
    """Normalisasi next_fire_at saat startup:
      - NULL           -> dibuat DUE (now - 1s) supaya ditembak sekali pada
                          tick pertama (kasus jadwal baru di-enable).
      - overdue > 24h  -> di-majukan ke jadwal berikutnya TANPA menembak
                          (anti-burst; jadwal yang tertinggal lama tidak
                          ditembak massal).
      - overdue <= 24h -> TIDAK disentuh (jalur normal tick akan menembak).
    Return jumlah baris yang diperbaiki."""
    now = datetime.now(dt_timezone.utc)
    cutoff = now - timedelta(hours=MISSED_RUN_MAX_AGE_H)
    fixed = 0
    res = (
        _svc()
        .table("workflow_schedules")
        .select("id, cron_expression, timezone, next_fire_at")
        .eq("enabled", True)
        .execute()
    )
    for row in res.data or []:
        nfa = row.get("next_fire_at")
        if nfa:
            try:
                past = datetime.fromisoformat(str(nfa).replace("Z", "+00:00"))
                if past.tzinfo is None:
                    past = past.replace(tzinfo=dt_timezone.utc)
                if past >= cutoff:
                    continue  # sehat / overdue <= 24h: biarkan tick yang menangani
            except ValueError:
                pass  # format rusak -> jatuh ke perbaikan di bawah
        try:
            new_next = next_fire_utc(row["cron_expression"], row["timezone"], base=now)
        except Exception as exc:  # noqa: BLE001 - cron rusak: jangan matikan loop
            _log.warning("[scheduler] recovery cron invalid id=%s: %s", row["id"], exc)
            continue
        due_now = nfa is None  # NULL = jadwal baru/enable -> tembak sekali
        (
            _svc()
            .table("workflow_schedules")
            .update({
                "next_fire_at": _iso(now - timedelta(seconds=1)) if due_now
                else _iso(new_next),
                "updated_at": _iso(now),
            })
            .eq("id", row["id"])
            .execute()
        )
        fixed += 1
    if fixed:
        _log.info("[scheduler] recovery: %d jadwal diperbaiki", fixed)
    return fixed


# ---------------------------------------------------------------------------
# Eksekusi
# ---------------------------------------------------------------------------

def _owner_email(user_id: str) -> str:
    try:
        res = (
            _svc()
            .table("users")
            .select("email")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return (rows[0].get("email") or "") if rows else ""
    except Exception:  # noqa: BLE001
        return ""


async def _fire(schedule: dict) -> None:
    """Eksekusi satu jadwal yang sudah di-claim. Tidak pernah raise."""
    workflow_id = str(schedule["workflow_id"])
    user_id = str(schedule["user_id"])
    schedule_id = str(schedule["id"])
    execution_id = ""
    try:
        flow = db.get_workflow(workflow_id, user_id)
        if not flow:
            _log.warning("[scheduler] workflow %s hilang, matikan jadwal", workflow_id)
            _svc().table("workflow_schedules").update(
                {"enabled": False, "updated_at": _iso(datetime.now(dt_timezone.utc))}
            ).eq("id", schedule_id).execute()
            return
        owner_email = _owner_email(user_id)
        execution_id = engine_launch(
            workflow_id,
            flow.get("flow_data") or {},
            {"trigger": "cron", "schedule_id": schedule_id},
            owner_email,
        )
        _log.info(
            "[scheduler] CRON FIRED schedule=%s workflow=%s tz=%s execution=%s",
            schedule_id, workflow_id, schedule.get("timezone"), execution_id,
        )
        _svc().table("workflow_schedules").update(
            {"last_execution_id": execution_id or None,
             "updated_at": _iso(datetime.now(dt_timezone.utc))}
        ).eq("id", schedule_id).execute()
    except Exception as exc:  # noqa: BLE001
        _log.error("[scheduler] gagal menembak schedule=%s: %s: %s",
                   schedule_id, type(exc).__name__, exc)


# Indirection supaya test bisa monkeypatch tanpa menyentuh engine sungguhan.
def engine_launch(workflow_id: str, flow_data: dict, trigger_input: dict,
                  owner_email: str) -> str:
    import execution_engine as engine  # import lambat: hindari siklus impor
    return engine.launch_execution(workflow_id, flow_data, trigger_input,
                                   owner_email=owner_email)


async def tick(user_id: Optional[str] = None) -> int:
    """Satu siklus: ambil jadwal due -> claim -> tembak. Return jumlah tembakan.

    `user_id` opsional hanya untuk isolasi test (lihat fetch_due_schedules).
    Produksi memanggil tick() tanpa argumen -> semua owner.
    """
    now = datetime.now(dt_timezone.utc)
    cutoff = now - timedelta(hours=MISSED_RUN_MAX_AGE_H)
    fired = 0
    for sched in fetch_due_schedules(now, user_id=user_id):
        try:
            nfa = sched.get("next_fire_at") or ""
            past = datetime.fromisoformat(nfa.replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            continue
        if past < cutoff:
            # terlewat terlalu lama: skip tanpa menembak, maju saja
            new_next = next_fire_utc(sched["cron_expression"], sched["timezone"], base=now)
            _svc().table("workflow_schedules").update(
                {"next_fire_at": _iso(new_next), "updated_at": _iso(now)}
            ).eq("id", sched["id"]).execute()
            _log.warning("[scheduler] skip missed >24h schedule=%s", sched["id"])
            continue
        if not claim_schedule(sched, now):
            continue  # replica lain yang menang
        fired += 1
        await _fire(sched)
    return fired


async def scheduler_loop(stop_event: asyncio.Event) -> None:
    """Loop utama — di-start dari _lifespan api_server."""
    try:
        recover_on_startup()
    except Exception as exc:  # noqa: BLE001 - recovery gagal tidak boleh matikan loop
        _log.error("[scheduler] recovery gagal: %s: %s", type(exc).__name__, exc)
    _log.info("[scheduler] loop aktif, tick tiap %ds", TICK_SECONDS)
    while not stop_event.is_set():
        try:
            await tick()
        except Exception as exc:  # noqa: BLE001
            _log.error("[scheduler] tick error: %s: %s", type(exc).__name__, exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=TICK_SECONDS)
        except asyncio.TimeoutError:
            pass
    _log.info("[scheduler] loop berhenti")


def scheduler_enabled() -> bool:
    return os.getenv("SCHEDULER_ENABLED", "1").strip().lower() not in ("0", "false", "no")
