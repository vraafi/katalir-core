"""FASE 6 — pulse check berkala untuk kesehatan connector.

Menyediakan **satu putaran pulse** yang idempoten dan aman dijalankan ulang,
dirancang untuk dipanggil oleh loop cron yang sudah ada (`scheduler_manager`)
atau oleh cron eksternal setiap 6 jam.

Kenapa bukan APScheduler: proyek ini sengaja tidak memakai APScheduler
(lihat catatan di `scheduler_manager.py` — butuh jobstore SQLAlchemy). Pola
yang dipakai konsisten: **hitung `next_run_at`, simpan, klaim, jalankan**.
Itu juga membuat pulse aman bila ada lebih dari satu instance backend.

Perilaku:
  * probe ulang HANYA connector yang ber-URL (streamable_http);
  * `stale_only=True` (default) melewati yang sudah dicek < `max_age_hours`;
  * verdict disimpan lewat `connector_prober.persist` (tabel connector_health);
  * `regenerate` memicu FASE 4/5 bila jumlah ALIVE turun di bawah ambang.
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib
from typing import Any

import connector_prober as cp
import connector_store as cs

INTERVAL_HOURS = 6
STATE_PATH = pathlib.Path("connector_pulse_state.json")
# Bila ALIVE turun di bawah rasio ini, penemuan ulang dijalankan.
REGEN_ALIVE_RATIO = 0.50


def _now() -> _dt.datetime:
    return _dt.datetime.now(tz=_dt.timezone.utc)


def _iso(dt: _dt.datetime) -> str:
    return dt.isoformat()


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {"last_pulse_at": None, "last_result": None, "pulses": 0}


def save_state(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE_PATH)


def due(*, interval_hours: int = INTERVAL_HOURS,
        now: _dt.datetime | None = None) -> bool:
    """True bila sudah waktunya pulse berikutnya."""
    now = now or _now()
    last = load_state().get("last_pulse_at")
    if not last:
        return True
    try:
        last_dt = _dt.datetime.fromisoformat(last)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=_dt.timezone.utc)
    except ValueError:
        return True
    return (now - last_dt) >= _dt.timedelta(hours=interval_hours)


def next_run_at(*, interval_hours: int = INTERVAL_HOURS) -> str | None:
    last = load_state().get("last_pulse_at")
    if not last:
        return _iso(_now())
    try:
        last_dt = _dt.datetime.fromisoformat(last)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=_dt.timezone.utc)
    except ValueError:
        return _iso(_now())
    return _iso(last_dt + _dt.timedelta(hours=interval_hours))


def _stale_connector_ids(max_age_hours: float) -> set[str]:
    """Id yang terakhir dicek lebih tua dari `max_age_hours` (atau belum ada)."""
    if not cs.available():
        return set()
    cutoff = _now() - _dt.timedelta(hours=max_age_hours)
    try:
        rows = (cs._read_client().table(cs.TABLE_HEALTH)
                .select("connector_id,checked_at").execute())
    except Exception as exc:  # noqa: BLE001
        print(f"[pulse] gagal baca health: {exc}")
        return set()
    stale: set[str] = set()
    seen: set[str] = set()
    for r in (rows.data or []):
        cid = r.get("connector_id")
        seen.add(cid)
        ts = r.get("checked_at")
        try:
            dt = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            stale.add(cid)
            continue
        if dt < cutoff:
            stale.add(cid)
    # target yang belum pernah dicek juga dianggap stale
    for t in cp.targets():
        if t["connector_id"] not in seen:
            stale.add(t["connector_id"])
    return stale


def pulse(*, workers: int = 12, timeout: float = 10.0,
          max_age_hours: float = INTERVAL_HOURS,
          stale_only: bool = True, limit: int | None = None,
          regenerate_below: float = REGEN_ALIVE_RATIO) -> dict:
    """Jalankan satu putaran pulse. Mengembalikan ringkasan + aksi."""
    t0 = _now()
    targets = cp.targets()
    if stale_only:
        stale = _stale_connector_ids(max_age_hours)
        targets = [t for t in targets if t["connector_id"] in stale]
    if limit:
        targets = targets[:limit]

    result: dict[str, Any] = {
        "started_at": _iso(t0),
        "candidates": len(targets),
        "skipped_fresh": None,
    }
    if not targets:
        result["status"] = "nothing-to-do"
        result["summary"] = cs.health_summary()
        _record(result)
        return result

    res = cp.probe_many(targets, workers=workers, timeout=timeout, progress=False)
    summary = cp.summarize(res)
    written = cp.persist(res)

    total = summary.get("total") or 1
    alive_ratio = (summary.get("ALIVE", 0) / total) if total else 0.0
    result.update({
        "status": "ok",
        "probed": len(res),
        "summary": summary,
        "persist": written,
        "alive_ratio": round(alive_ratio, 3),
        "regenerated": False,
    })

    if regenerate_below and alive_ratio < regenerate_below and total >= 20:
        try:
            import openapi_connectors as oc
            rows = oc.discover_guru_specs(limit=25)
            gen = oc.generate(rows, max_per_api=60, progress=False)
            result["regenerated"] = True
            result["regenerated_entries"] = len(gen["entries"])
        except Exception as exc:  # noqa: BLE001
            result["regenerated"] = False
            result["regenerate_error"] = f"{type(exc).__name__}: {exc}"

    result["duration_s"] = round((_now() - t0).total_seconds(), 1)
    _record(result)
    return result


def _record(result: dict) -> None:
    st = load_state()
    st["last_pulse_at"] = result.get("started_at") or _iso(_now())
    st["last_result"] = {k: v for k, v in result.items() if k != "summary"}
    st["last_summary"] = result.get("summary")
    st["pulses"] = int(st.get("pulses") or 0) + 1
    st["next_run_at"] = next_run_at()
    save_state(st)


def describe() -> dict:
    st = load_state()
    return {
        "interval_hours": INTERVAL_HOURS,
        "due": due(),
        "next_run_at": next_run_at(),
        "pulses_run": st.get("pulses", 0),
        "last_pulse_at": st.get("last_pulse_at"),
        "last_summary": st.get("last_summary"),
        "regen_alive_ratio": REGEN_ALIVE_RATIO,
        "health": cs.health_summary(),
        "scheduler_pattern": "next_run_at + klaim (sama seperti scheduler_manager)",
    }
