# insights.py — Fitur #5: Insights & Analytics (8 Okt 2026)
# ======================================================================
# Menutup gap vs n8n "Insights": success rate, latensi, error rate, time
# saved, ROI, time series 7/30/365 hari, filter workflow/user/tanggal,
# ekspor CSV. Riset Okt 2026 (docs/feature-gap-closure-2026-10-08.md §5):
# dashboard monitoring + "time saved" + ROI (jam diselamatkan × tarif).
#
# SUMBER DATA
#   `executions` (id, workflow_id, status, created_at) — owner-scoped lewat
#   `workflows.user_id`. Latensi TIDAK ada di `executions`, jadi diambil
#   dari `execution_logs` (finished_at - started_at) pada SAMPEL terbatas
#   (dilaporkan jujur lewat `latency_sample_size`), bukan dikarang.
#
# UJI
#   Semua agregasi adalah fungsi MURNI atas daftar event; uji menyuntikkan
#   event sintetis (100k) tanpa menyentuh DB -> cepat & deterministik.
# ======================================================================

from __future__ import annotations

import csv
import io
import json
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import database as db

RETENTION_DAYS = 365
RANGE_PRESETS = (7, 30, 365)
DEFAULT_MINUTES_PER_RUN = 5.0
DEFAULT_HOURLY_RATE = 25.0
LATENCY_SAMPLE_MAX = 500

_STATUS_OK = ("completed", "success", "succeeded")
_STATUS_ERR = ("error", "failed", "failure")


def _parse_dt(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _bucket_key(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def filter_events(events: list[dict], days: int = 30,
                  workflow_id: str = "", now: Optional[datetime] = None
                  ) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(1, int(days)))
    out: list[dict] = []
    for e in events:
        dt = _parse_dt(e.get("created_at"))
        if dt is None or dt < cutoff or dt > now:
            continue
        if workflow_id and str(e.get("workflow_id") or "") != str(workflow_id):
            continue
        out.append(e)
    return out


def compute_metrics(events: list[dict]) -> dict:
    """Ringkasan murni: total, success/error/pending, rate, latensi."""
    total = len(events)
    success = error = pending = 0
    lat: list[float] = []
    for e in events:
        s = str(e.get("status") or "pending").lower()
        if s in _STATUS_OK:
            success += 1
        elif s in _STATUS_ERR:
            error += 1
        else:
            pending += 1
        v = e.get("duration_ms")
        if v is not None:
            try:
                lat.append(float(v))
            except (TypeError, ValueError):
                pass
    return {
        "total": total,
        "success": success,
        "error": error,
        "pending": pending,
        "success_rate": round(success / total, 4) if total else 0.0,
        "error_rate": round(error / total, 4) if total else 0.0,
        "latency_mean_ms": round(statistics.fmean(lat), 2) if lat else None,
        "latency_p50_ms": round(statistics.median(lat), 2) if lat else None,
        "latency_p95_ms": _percentile(lat, 95),
        "latency_sample_size": len(lat),
    }


def _percentile(vals: list[float], p: float) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return round(s[k], 2)


def time_series(events: list[dict], days: int = 30,
                now: Optional[datetime] = None) -> list[dict]:
    """Deret harian (termasuk hari tanpa event, nilai 0) sepanjang `days`."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    days = max(1, int(days))
    buckets: dict[str, dict] = {}
    for i in range(days - 1, -1, -1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        buckets[d] = {"date": d, "total": 0, "success": 0, "error": 0, "pending": 0}
    for e in events:
        dt = _parse_dt(e.get("created_at"))
        if dt is None:
            continue
        key = _bucket_key(dt)
        if key not in buckets:
            continue
        b = buckets[key]
        b["total"] += 1
        s = str(e.get("status") or "pending").lower()
        if s in _STATUS_OK:
            b["success"] += 1
        elif s in _STATUS_ERR:
            b["error"] += 1
        else:
            b["pending"] += 1
    return list(buckets.values())


def time_saved(events: list[dict], minutes_per_run: float = DEFAULT_MINUTES_PER_RUN
               ) -> dict:
    """Waktu yang dihemat = jumlah eksekusi SUKSES × menit manual per run."""
    success = sum(1 for e in events
                  if str(e.get("status") or "").lower() in _STATUS_OK)
    try:
        mpr = float(minutes_per_run)
    except (TypeError, ValueError):
        mpr = DEFAULT_MINUTES_PER_RUN
    minutes = round(success * mpr, 2)
    return {"automated_runs": success, "minutes_per_run": mpr,
            "minutes_saved": minutes, "hours_saved": round(minutes / 60.0, 3)}


def roi(hours_saved: float, hourly_rate: float = DEFAULT_HOURLY_RATE,
        currency: str = "USD") -> dict:
    try:
        h = float(hours_saved)
        r = float(hourly_rate)
    except (TypeError, ValueError):
        h, r = 0.0, DEFAULT_HOURLY_RATE
    return {"hours_saved": round(h, 3), "hourly_rate": r, "currency": currency,
            "money_saved": round(h * r, 2)}


def by_workflow(events: list[dict]) -> list[dict]:
    """Agregasi per workflow (untuk tabel/filter)."""
    agg: dict[str, dict] = {}
    for e in events:
        wid = str(e.get("workflow_id") or "(tanpa workflow)")
        a = agg.setdefault(wid, {"workflow_id": wid, "total": 0,
                                 "success": 0, "error": 0})
        a["total"] += 1
        s = str(e.get("status") or "pending").lower()
        if s in _STATUS_OK:
            a["success"] += 1
        elif s in _STATUS_ERR:
            a["error"] += 1
    for a in agg.values():
        a["success_rate"] = round(a["success"] / a["total"], 4) if a["total"] else 0.0
    return sorted(agg.values(), key=lambda x: x["total"], reverse=True)


def to_csv(rows: list[dict], columns: Optional[list[str]] = None) -> str:
    """Ekspor list[dict] ke CSV (header dari union kolom bila tak diberikan)."""
    if not rows:
        return ""
    cols = columns or list(rows[0].keys())
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({c: (json.dumps(r.get(c)) if isinstance(r.get(c), (dict, list))
                        else r.get(c)) for c in cols})
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Loader (produksi) + Insight
# ---------------------------------------------------------------------------

def load_events(user_id: str, days: int = RETENTION_DAYS,
                workflow_id: str = "") -> list[dict]:
    """Ambil event eksekusi milik user (owner-scoped) dari Supabase."""
    if not db.is_configured():
        return []
    try:
        c = db.get_write_client()
        wfs = (c.table("workflows").select("id,name").eq("user_id", user_id)
               .execute().data or [])
        ids = [str(w.get("id")) for w in wfs if w.get("id")]
        if workflow_id:
            ids = [i for i in ids if i == str(workflow_id)]
        if not ids:
            return []
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
                  ).isoformat()
        ex = (c.table("executions")
              .select("id,workflow_id,status,created_at")
              .in_("workflow_id", ids).gte("created_at", cutoff)
              .order("created_at", desc=True).limit(100000).execute().data or [])
        names = {str(w.get("id")): w.get("name") for w in wfs}
        for row in ex:
            row["workflow_name"] = names.get(str(row.get("workflow_id")))
        return ex
    except Exception as exc:  # noqa: BLE001
        print(f"[insights] load_events gagal: {type(exc).__name__}: {exc}")
        return []


def sample_latency(events: list[dict], max_n: int = LATENCY_SAMPLE_MAX) -> int:
    """Isi `duration_ms` dari execution_logs untuk SAMPEL (in-place).

    Latensi tidak ada di `executions`; diambil dari selisih started_at/
    finished_at per log. Dibatasi `max_n` eksekusi terbaru supaya dashboard
    tetap cepat. Mengembalikan jumlah eksekusi yang berhasil diukur.
    """
    if not db.is_configured() or not events:
        return 0
    try:
        c = db.get_write_client()
        measured = 0
        for row in events[:max_n]:
            logs = (c.table("execution_logs")
                    .select("started_at,finished_at")
                    .eq("execution_id", row.get("id")).execute().data or [])
            total = 0.0
            for lg in logs:
                a = _parse_dt(lg.get("started_at"))
                b = _parse_dt(lg.get("finished_at"))
                if a and b and b >= a:
                    total += (b - a).total_seconds() * 1000
            if total > 0:
                row["duration_ms"] = round(total, 2)
                measured += 1
        return measured
    except Exception as exc:  # noqa: BLE001
        print(f"[insights] sample_latency gagal: {type(exc).__name__}")
        return 0


class Insight:
    """Laporan analitik owner-scoped. `events` bisa disuntik (uji)."""

    def __init__(self, user_id: str, events: Optional[list[dict]] = None,
                 minutes_per_run: float = DEFAULT_MINUTES_PER_RUN,
                 hourly_rate: float = DEFAULT_HOURLY_RATE):
        self.user_id = str(user_id or "")
        self._events = events
        self.minutes_per_run = minutes_per_run
        self.hourly_rate = hourly_rate

    def events(self, days: int, workflow_id: str = "",
               with_latency: bool = False) -> list[dict]:
        if self._events is not None:
            return filter_events(self._events, days, workflow_id)
        ev = load_events(self.user_id, days, workflow_id)
        if with_latency and ev:
            sample_latency(ev)
        return filter_events(ev, days, workflow_id)

    def report(self, days: int = 30, workflow_id: str = "",
               with_latency: bool = False,
               now: Optional[datetime] = None) -> dict:
        days = days if days in RANGE_PRESETS else max(1, min(int(days), RETENTION_DAYS))
        ev = self.events(days, workflow_id, with_latency)
        metrics = compute_metrics(ev)
        saved = time_saved(ev, self.minutes_per_run)
        return {
            "range_days": days,
            "workflow_id": workflow_id or None,
            "metrics": metrics,
            "time_saved": saved,
            "roi": roi(saved["hours_saved"], self.hourly_rate),
            "series": time_series(ev, days, now),
            "by_workflow": by_workflow(ev),
            "retention_days": RETENTION_DAYS,
        }

    def export_csv(self, days: int = 30, workflow_id: str = "") -> str:
        ev = self.events(days, workflow_id)
        rows = [{"date": b["date"], "total": b["total"], "success": b["success"],
                 "error": b["error"], "pending": b["pending"]}
                for b in time_series(ev, days)]
        return to_csv(rows, ["date", "total", "success", "error", "pending"])


__all__ = [
    "RETENTION_DAYS", "RANGE_PRESETS", "DEFAULT_MINUTES_PER_RUN",
    "DEFAULT_HOURLY_RATE", "filter_events", "compute_metrics", "time_series",
    "time_saved", "roi", "by_workflow", "to_csv", "load_events",
    "sample_latency", "Insight",
]
