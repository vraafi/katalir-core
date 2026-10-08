# advanced_scheduling.py — Fitur #2 (Okt 2026)
# ======================================================================
# Penjadwalan lanjutan di atas `scheduler_manager.py` (cron 5-field + zoneinfo).
# SEMUA fungsi di modul ini MURNI (tanpa DB/jaringan) supaya bisa di-hard-test
# deterministik; integrasi ke scheduler_manager memanggil fungsi-fungsi ini.
#
# RISET (Okt 2026):
#   - croniter (pure-python, stabil) tetap dipakai — bukan APScheduler v4
#     (masih pre-release) atau fastscheduler (v0.2.x, terlalu muda).
#   - Kunci DST: hitung cron pada DINDING JAM LOKAL timezone jadwal, lalu
#     konversi hasil ke UTC (pelajaran dari bug scheduler_manager 8 Okt 2026).
#   - Natural language: parser kecil sendiri (EN + ID) — nol dependensi baru;
#     library NL-time (dateparser/parsedatetime) berat & ambigu untuk cron.
# ======================================================================

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from croniter import croniter

#: Timezone IANA yang disediakan UI (validasi: semuanya harus ada di tzdata).
COMMON_TIMEZONES = [
    "UTC", "Asia/Jakarta", "Asia/Makassar", "Asia/Jayapura", "Asia/Singapore",
    "Asia/Kuala_Lumpur", "Asia/Bangkok", "Asia/Manila", "Asia/Ho_Chi_Minh",
    "Asia/Kolkata", "Asia/Dubai", "Asia/Tokyo", "Asia/Seoul", "Asia/Shanghai",
    "Asia/Hong_Kong", "Asia/Taipei", "Australia/Sydney", "Australia/Perth",
    "Pacific/Auckland", "Europe/London", "Europe/Dublin", "Europe/Paris",
    "Europe/Berlin", "Europe/Madrid", "Europe/Rome", "Europe/Amsterdam",
    "Europe/Stockholm", "Europe/Warsaw", "Europe/Moscow", "Europe/Istanbul",
    "Africa/Cairo", "Africa/Lagos", "Africa/Johannesburg", "Africa/Nairobi",
    "America/New_York", "America/Chicago", "America/Denver",
    "America/Los_Angeles", "America/Toronto", "America/Mexico_City",
    "America/Bogota", "America/Sao_Paulo", "America/Argentina/Buenos_Aires",
    "America/Santiago", "America/Lima", "America/Phoenix", "America/Anchorage",
    "Pacific/Honolulu", "Atlantic/Reykjavik", "Asia/Karachi",
]

#: Peta hari (EN + ID) -> indeks cron DOW (0=Minggu .. 6=Sabtu).
_DAYS = {
    "sunday": 0, "sun": 0, "minggu": 0, "ahad": 0,
    "monday": 1, "mon": 1, "senin": 1,
    "tuesday": 2, "tue": 2, "tues": 2, "selasa": 2,
    "wednesday": 3, "wed": 3, "rabu": 3,
    "thursday": 4, "thu": 4, "thur": 4, "thurs": 4, "kamis": 4,
    "friday": 5, "fri": 5, "jumat": 5, "jum'at": 5,
    "saturday": 6, "sat": 6, "sabtu": 6,
}

_MONTHS = {
    "january": 1, "jan": 1, "januari": 1,
    "february": 2, "feb": 2, "februari": 2,
    "march": 3, "mar": 3, "maret": 3,
    "april": 4, "apr": 4,
    "may": 5, "mei": 5,
    "june": 6, "jun": 6, "juni": 6,
    "july": 7, "jul": 7, "juli": 7,
    "august": 8, "aug": 8, "agustus": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "oktober": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12, "desember": 12,
}


class ScheduleError(ValueError):
    """Spesifikasi jadwal tidak valid."""


# ---------------------------------------------------------------------------
# Validasi + builder visual
# ---------------------------------------------------------------------------

def is_valid_cron(expr: str) -> bool:
    """Cron 5-field standar (menit jam dom bulan dow). 6-field DITOLAK."""
    if not expr or not isinstance(expr, str):
        return False
    if len(expr.split()) != 5:
        return False
    try:
        return bool(croniter.is_valid(expr.strip()))
    except Exception:  # noqa: BLE001
        return False


def is_valid_timezone(tz_name: str) -> bool:
    if not tz_name or not isinstance(tz_name, str):
        return False
    try:
        ZoneInfo(tz_name.strip())
        return True
    except Exception:  # noqa: BLE001
        return False


def build_cron(minute: Any = "*", hour: Any = "*", dom: Any = "*",
               month: Any = "*", dow: Any = "*") -> str:
    """Rakit cron dari field terpisah (dipakai builder visual).

    Menerima int, str, atau list (mis. dow=[1,3,5] -> "1,3,5").
    Raises ScheduleError bila hasilnya bukan cron valid.
    """
    def _f(v: Any) -> str:
        if v is None or v == "":
            return "*"
        if isinstance(v, (list, tuple, set)):
            if not v:
                return "*"
            return ",".join(str(int(x)) for x in sorted(v))
        return str(v).strip() or "*"

    expr = " ".join([_f(minute), _f(hour), _f(dom), _f(month), _f(dow)])
    if not is_valid_cron(expr):
        raise ScheduleError(f"cron tidak valid: {expr!r}")
    return expr


def parse_cron(expr: str) -> dict:
    """Urai cron 5-field menjadi dict (untuk ditampilkan di builder)."""
    if not is_valid_cron(expr):
        raise ScheduleError(f"cron tidak valid: {expr!r}")
    menit, jam, dom, bulan, dow = expr.split()
    return {"minute": menit, "hour": jam, "dom": dom, "month": bulan, "dow": dow}


# ---------------------------------------------------------------------------
# Natural language -> cron (EN + ID)
# ---------------------------------------------------------------------------

def _jam_ke_hour(t: str) -> tuple[int, int]:
    """'9am' -> (9,0); '9:30 pm' -> (21,30); '21:00' -> (21,0)."""
    t = t.strip().lower().replace(".", "")
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", t)
    if not m:
        raise ScheduleError(f"jam tidak dikenali: {t!r}")
    h = int(m.group(1))
    mi = int(m.group(2) or 0)
    ampm = m.group(3)
    if ampm == "pm" and h < 12:
        h += 12
    elif ampm == "am" and h == 12:
        h = 0
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        raise ScheduleError(f"jam di luar rentang: {t!r}")
    return h, mi


def natural_to_cron(text: str) -> Optional[str]:
    """Ubah frasa natural (EN/ID) menjadi cron. None bila tak dikenali.

    Didukung:
      every 15 minutes / setiap 15 menit
      every hour / setiap jam
      every day at 9am / setiap hari jam 9
      every Monday at 9:30am / setiap senin jam 9:30
      weekdays at 8am / hari kerja jam 8
      first day of month at midnight / tanggal 1 jam 00:00
      every 1st of January at noon
    """
    if not text or not isinstance(text, str):
        return None
    s = " " + text.strip().lower() + " "
    s = s.replace("pukul", "jam").replace("o'clock", "")
    s = re.sub(r"\s+", " ", s)

    # every N minutes / setiap N menit
    m = re.search(r"(?:every|setiap)\s+(\d{1,3})\s*(?:minutes?|menit)", s)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 59:
            return f"*/{n} * * * *"

    # every minute / setiap menit
    if re.search(r"(?:every|setiap)\s+(?:minute|menit)\b", s):
        return "* * * * *"

    # every hour / setiap jam
    if re.search(r"(?:every|setiap)\s+(?:hour|jam)\b", s) and "jam" not in re.findall(
            r"jam\s+\d", s)[0:1]:
        # hindari salah tangkap "setiap hari jam 9"
        if not re.search(r"(?:day|hari|senin|monday|weekday)", s):
            return "0 * * * *"

    # interval hours: every 2 hours / setiap 2 jam
    m = re.search(r"(?:every|setiap)\s+(\d{1,2})\s*(?:hours?|jam)", s)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 23:
            return f"0 */{n} * * *"

    # waktu (jam) opsional
    hour, minute = 0, 0
    tm = re.search(r"(?:at|jam)\s+([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)", s)
    if not tm:
        tm = re.search(r"(midnight|noon|tengah malam|tengah hari)", s)
        if tm:
            kata = tm.group(1)
            hour = 0 if kata in ("midnight", "tengah malam") else 12
            minute = 0
    else:
        hour, minute = _jam_ke_hour(tm.group(1))

    # hari spesifik
    for nama, idx in _DAYS.items():
        if re.search(rf"\b{re.escape(nama)}\b", s):
            return f"{minute} {hour} * * {idx}"

    # hari kerja
    if re.search(r"(?:weekdays?|hari kerja)", s):
        return f"{minute} {hour} * * 1-5"

    # akhir pekan
    if re.search(r"(?:weekends?|akhir pekan)", s):
        return f"{minute} {hour} * * 0,6"

    # tanggal N setiap bulan: "first day of every month" / "1st of month" /
    # "tanggal 1"
    if re.search(r"(?:first|1st)\s+day\s+of", s):
        return f"{minute} {hour} 1 * *"
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+of\s+(?:every\s+)?(?:month|bulan)",
                  s)
    if m:
        dom = int(m.group(1))
        if 1 <= dom <= 31:
            return f"{minute} {hour} {dom} * *"
    m = re.search(r"tanggal\s+(\d{1,2})", s)
    if m:
        dom = int(m.group(1))
        if 1 <= dom <= 31:
            return f"{minute} {hour} {dom} * *"

    # bulan spesifik + tanggal
    for nama, bulan in _MONTHS.items():
        if re.search(rf"\b{re.escape(nama)}\b", s):
            dm = re.search(r"(\d{1,2})(?:st|nd|rd|th)?", s)
            dom = int(dm.group(1)) if dm else 1
            return f"{minute} {hour} {dom} {bulan} *"

    # harian (default bila ada 'day'/'hari')
    if re.search(r"(?:every\s+day|setiap\s+hari|daily|harian|tiap\s+hari)", s):
        return f"{minute} {hour} * * *"

    # hanya jam yang disebut
    if tm:
        return f"{minute} {hour} * * *"

    return None


# ---------------------------------------------------------------------------
# Hitung waktu tembak (DST-aware)
# ---------------------------------------------------------------------------

def next_fire(expr: str, tz_name: str,
              base: Optional[datetime] = None) -> datetime:
    """Waktu tembak berikutnya (UTC-aware), dihitung pada dinding jam lokal.

    DST-SAFE (temuan hard test Okt 2026): `croniter` yang diberi datetime
    tz-AWARE menghasilkan waktu SPURIOUS pada hari transisi DST — mis.
    "0 9 * * *" di America/New_York ikut menembak 08:00 pada hari
    spring-forward. Perbaikan: iterasi dilakukan pada dinding jam LOKAL
    (naive), baru hasilnya dilokalkan ke timezone (zoneinfo mengurus fold).
    """
    if not is_valid_cron(expr):
        raise ScheduleError(f"cron tidak valid: {expr!r}")
    tz = ZoneInfo(tz_name)
    if base is None:
        wall = datetime.now(tz).replace(tzinfo=None)
    elif base.tzinfo is None:
        wall = base
    else:
        wall = base.astimezone(tz).replace(tzinfo=None)
    nxt_wall = croniter(expr.strip(), wall).get_next(datetime)  # naive lokal
    return nxt_wall.replace(tzinfo=tz).astimezone(dt_timezone.utc)


def next_fires(expr: str, tz_name: str, count: int = 5,
               base: Optional[datetime] = None) -> list[datetime]:
    """`count` waktu tembak berikutnya (UTC-aware)."""
    out: list[datetime] = []
    kursor = base
    for _ in range(max(0, count)):
        nxt = next_fire(expr, tz_name, base=kursor)
        out.append(nxt)
        kursor = nxt
    return out


def local_hour_preserved(expr: str, tz_name: str, expected_hour: int,
                         start: datetime, days: int = 400) -> bool:
    """True bila SEMUA tembakan dalam rentang tetap di jam lokal `expected_hour`.

    Dipakai untuk membuktikan DST-awareness: jadwal "0 9 * * *" di
    America/New_York harus tetap 09:00 lokal setelah spring-forward/fall-back.
    """
    tz = ZoneInfo(tz_name)
    batas = start.astimezone(tz) + timedelta(days=days)
    kursor = start
    for _ in range(1000):
        nxt = next_fire(expr, tz_name, base=kursor)
        if nxt.astimezone(tz) >= batas:
            break
        if nxt.astimezone(tz).hour != expected_hour:
            return False
        kursor = nxt
    return True


# ---------------------------------------------------------------------------
# Spec jadwal: multiple, conditional, dependency
# ---------------------------------------------------------------------------

def validate_spec(spec: dict) -> list[str]:
    """Validasi satu spec jadwal. Return daftar pesan error (kosong = valid)."""
    errs: list[str] = []
    if not isinstance(spec, dict):
        return ["spec harus objek"]
    expr = spec.get("cron")
    if not is_valid_cron(expr or ""):
        errs.append(f"cron tidak valid: {expr!r}")
    tz = spec.get("timezone", "UTC")
    if not is_valid_timezone(tz):
        errs.append(f"timezone tidak valid: {tz!r}")
    if "condition" in spec and spec["condition"] not in (None, ""):
        try:
            evaluate_condition(str(spec["condition"]), {})
        except ScheduleError as exc:
            errs.append(f"condition: {exc}")
    if "after" in spec and spec["after"] is not None:
        if not isinstance(spec["after"], list):
            errs.append("after harus daftar id workflow")
    return errs


#: Operator yang diizinkan pada `condition` (TANPA eval — aman).
_COND_RE = re.compile(
    r"^\s*([A-Za-z_][\w.]*)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*$")


def _coerce(token: str) -> Any:
    t = token.strip().strip("'\"")
    low = t.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "none"):
        return None
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    return t


def evaluate_condition(expr: str, context: dict) -> bool:
    """Evaluasi kondisi sederhana TANPA `eval`.

    Bentuk: "flag == true", "count > 5", "env != prod", atau "flag" (truthy).
    """
    if expr is None or str(expr).strip() == "":
        return True
    m = _COND_RE.match(str(expr))
    if not m:
        # kondisi truthy sederhana: nama kunci
        kunci = str(expr).strip()
        if not re.match(r"^[A-Za-z_][\w.]*$", kunci):
            raise ScheduleError(f"kondisi tidak valid: {expr!r}")
        return bool(context.get(kunci, False))
    kiri, op, kanan = m.group(1), m.group(2), m.group(3)
    a = context.get(kiri)
    b = _coerce(kanan)
    if a is None and kiri not in context:
        return False
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    try:
        if op == ">":
            return a > b
        if op == "<":
            return a < b
        if op == ">=":
            return a >= b
        if op == "<=":
            return a <= b
    except TypeError:
        return False
    return False


def decide(spec: dict, context: Optional[dict] = None,
           deps_done: Optional[dict] = None) -> dict:
    """Putuskan apakah jadwal harus menembak + ALASAN (untuk log).

    Return {fire: bool, reason: str}.
    """
    context = context or {}
    deps_done = deps_done or {}
    if not spec.get("enabled", True):
        return {"fire": False, "reason": "disabled"}
    after = spec.get("after") or []
    for dep in after:
        if not deps_done.get(str(dep), False):
            return {"fire": False, "reason": f"dependency belum selesai: {dep}"}
    cond = spec.get("condition")
    if cond:
        try:
            if not evaluate_condition(str(cond), context):
                return {"fire": False, "reason": f"condition false: {cond}"}
        except ScheduleError as exc:
            return {"fire": False, "reason": f"condition error: {exc}"}
    return {"fire": True, "reason": "ok"}


def build_workflow_schedules(specs: list[dict]) -> list[dict]:
    """Normalisasi daftar spec (multiple schedule per workflow) + validasi.

    Raises ScheduleError bila ADA spec tidak valid (fail-fast untuk UI).
    """
    hasil: list[dict] = []
    for i, spec in enumerate(specs or []):
        errs = validate_spec(spec)
        if errs:
            raise ScheduleError(f"jadwal #{i}: {'; '.join(errs)}")
        hasil.append({
            "cron": spec["cron"].strip(),
            "timezone": spec.get("timezone", "UTC"),
            "enabled": bool(spec.get("enabled", True)),
            "condition": spec.get("condition") or None,
            "after": [str(x) for x in (spec.get("after") or [])],
            "name": spec.get("name") or f"schedule-{i}",
        })
    return hasil
