# tests/test_advanced_scheduling.py — Fitur #2 hard test (12 skenario, Okt 2026)
# Murni & deterministik: tanpa DB/jaringan. DST diuji pada tanggal transisi
# NYATA (America/New_York) memakai zoneinfo.
from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

import advanced_scheduling as sch


# 1. Builder visual -> cron valid (dan menolak yang invalid)
def test_01_visual_builder():
    assert sch.build_cron(minute=0, hour=9) == "0 9 * * *"
    assert sch.build_cron(minute="*/15", hour="*") == "*/15 * * * *"
    assert sch.build_cron(dow=[1, 3, 5], hour=8, minute=30) == "30 8 * * 1,3,5"
    assert sch.build_cron() == "* * * * *"
    with pytest.raises(sch.ScheduleError):
        sch.build_cron(minute=99, hour=99)
    d = sch.parse_cron("30 8 * * 1,3,5")
    assert d["hour"] == "8" and d["dow"] == "1,3,5"


# 2. Natural language EN -> cron
@pytest.mark.parametrize("teks,harap", [
    ("every day at 9am", "0 9 * * *"),
    ("every Monday at 9:30am", "30 9 * * 1"),
    ("every 15 minutes", "*/15 * * * *"),
    ("every hour", "0 * * * *"),
    ("weekdays at 8am", "0 8 * * 1-5"),
    ("every day at midnight", "0 0 * * *"),
    ("every day at noon", "0 12 * * *"),
    ("first day of every month at 6am", "0 6 1 * *"),
])
def test_02_natural_en(teks, harap):
    assert sch.natural_to_cron(teks) == harap


# 3. Natural language ID -> cron
@pytest.mark.parametrize("teks,harap", [
    ("setiap hari jam 9", "0 9 * * *"),
    ("setiap senin jam 09:30", "30 9 * * 1"),
    ("setiap 15 menit", "*/15 * * * *"),
    ("tiap hari jam 6 pagi", "0 6 * * *"),
    ("hari kerja jam 8", "0 8 * * 1-5"),
    ("akhir pekan jam 10", "0 10 * * 0,6"),
])
def test_03_natural_id(teks, harap):
    assert sch.natural_to_cron(teks) == harap


def test_03b_natural_tak_dikenal():
    assert sch.natural_to_cron("bla bla bla") is None


# 4. DST spring-forward: "0 9 * * *" tetap 09:00 lokal (America/New_York)
def test_04_dst_spring():
    mulai = datetime(2026, 3, 1, tzinfo=timezone.utc)
    assert sch.local_hour_preserved("0 9 * * *", "America/New_York", 9,
                                    mulai, days=40) is True
    # bukti offset benar-benar bergeser (EST -5 -> EDT -4)
    sebelum = sch.next_fire("0 9 * * *", "America/New_York",
                            base=datetime(2026, 3, 6, 12, tzinfo=timezone.utc))
    sesudah = sch.next_fire("0 9 * * *", "America/New_York",
                            base=datetime(2026, 3, 9, 12, tzinfo=timezone.utc))
    assert sebelum.astimezone(timezone.utc).hour == 14  # 09:00 EST = 14:00Z
    assert sesudah.astimezone(timezone.utc).hour == 13  # 09:00 EDT = 13:00Z


# 5. DST fall-back: tetap 09:00 lokal
def test_05_dst_fall():
    mulai = datetime(2026, 10, 25, tzinfo=timezone.utc)
    assert sch.local_hour_preserved("0 9 * * *", "America/New_York", 9,
                                    mulai, days=20) is True


# 6. Multiple schedule per workflow
def test_06_multiple_schedules():
    specs = [
        {"cron": "0 9 * * 1-5", "timezone": "Asia/Jakarta", "name": "pagi"},
        {"cron": "0 17 * * 1-5", "timezone": "Asia/Jakarta", "name": "sore"},
        {"cron": "0 10 * * 6", "timezone": "Asia/Jakarta", "name": "sabtu"},
    ]
    out = sch.build_workflow_schedules(specs)
    assert len(out) == 3
    assert {o["name"] for o in out} == {"pagi", "sore", "sabtu"}
    with pytest.raises(sch.ScheduleError):
        sch.build_workflow_schedules([{"cron": "not a cron"}])


# 7. Conditional schedule
def test_07_conditional():
    spec = {"cron": "0 9 * * *", "condition": "flag == true"}
    assert sch.decide(spec, {"flag": True})["fire"] is True
    r = sch.decide(spec, {"flag": False})
    assert r["fire"] is False and "condition" in r["reason"]
    # numerik
    assert sch.decide({"cron": "0 9 * * *", "condition": "count > 5"},
                      {"count": 9})["fire"] is True
    assert sch.decide({"cron": "0 9 * * *", "condition": "count > 5"},
                      {"count": 2})["fire"] is False


# 8. Schedule dependency (A selesai -> B jalan)
def test_08_dependency():
    spec = {"cron": "0 9 * * *", "after": ["wf-A", "wf-B"]}
    r = sch.decide(spec, {}, {"wf-A": True, "wf-B": False})
    assert r["fire"] is False and "dependency" in r["reason"]
    r2 = sch.decide(spec, {}, {"wf-A": True, "wf-B": True})
    assert r2["fire"] is True


# 9. Timezone selector: 50 timezone valid
def test_09_timezones():
    assert len(sch.COMMON_TIMEZONES) >= 50
    for tz in sch.COMMON_TIMEZONES:
        assert sch.is_valid_timezone(tz), tz
    assert sch.is_valid_timezone("WIB") is False
    assert sch.is_valid_timezone("Not/AZone") is False


# 10. Validasi ekspresi
def test_10_validation():
    assert sch.is_valid_cron("*/5 * * * *")
    assert sch.is_valid_cron("0 0 1 1 *")
    assert not sch.is_valid_cron("0 0 * *")          # 4 field
    assert not sch.is_valid_cron("0 0 * * * *")      # 6 field (detik) ditolak
    assert not sch.is_valid_cron("bogus")
    errs = sch.validate_spec({"cron": "bad", "timezone": "WIB"})
    assert len(errs) >= 2


# 11. Performa: hitung 1000 next_fire
def test_11_performance_1000():
    t0 = time.perf_counter()
    for i in range(1000):
        sch.next_fire("*/5 * * * *", "Asia/Jakarta")
    dt = time.perf_counter() - t0
    assert dt < 2.0, f"1000 next_fire terlalu lambat: {dt:.3f}s"


# 12. Alasan fire/skip untuk log
def test_12_reason_logging():
    assert sch.decide({"cron": "0 9 * * *"})["reason"] == "ok"
    assert sch.decide({"cron": "0 9 * * *", "enabled": False})["reason"] == "disabled"


# 13. next_fires mengembalikan deret menaik
def test_13_next_fires_series():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    deret = sch.next_fires("0 9 * * *", "Asia/Jakarta", count=5, base=base)
    assert len(deret) == 5
    assert all(deret[i] < deret[i + 1] for i in range(4))
