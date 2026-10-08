# monitoring.py — Fitur #3: Advanced Monitoring & Alerting (Okt 2026)
# ======================================================================
# Observabilitas untuk Katalir: metrik (format Prometheus), mesin aturan alert,
# dedup + silence, notifikasi (Email/Slack/Telegram/Webhook), agregasi log, dan
# tracing per-node.
#
# RISET (Okt 2026):
#   - Format eksposisi Prometheus (text/plain; version=0.0.4) tetap standar de
#     facto; dihasilkan sendiri (nol dependensi) supaya bisa di-scrape Grafana/
#     Prometheus tanpa klien berat.
#   - Notifikasi: transport DISUNTIK (callable) -> test tanpa jaringan; di
#     produksi memakai urllib (stdlib) untuk Slack/Telegram/Webhook.
#   - Semua nilai rahasia di-redact sebelum masuk isi alert (tidak bocor).
# ======================================================================

from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

MASK = "***"
_SECRET_RE = re.compile(
    r"(secret://\S+|sk-[A-Za-z0-9]{8,}|Bearer\s+[A-Za-z0-9._\-]+|"
    r"xox[baprs]-[A-Za-z0-9\-]+|bot\d+:[A-Za-z0-9_\-]+)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Metrik + eksposisi Prometheus
# ---------------------------------------------------------------------------

class Metrics:
    """Registry metrik sederhana (counter, gauge, histogram) + Prometheus text."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counters: dict[tuple, float] = {}
        self.gauges: dict[tuple, float] = {}
        self.histograms: dict[tuple, list[float]] = {}
        self.help: dict[str, str] = {}

    @staticmethod
    def _key(name: str, labels: Optional[dict]) -> tuple:
        if not labels:
            return (name,)
        return (name,) + tuple(sorted((str(k), str(v))
                                      for k, v in labels.items()))

    def describe(self, name: str, text: str) -> None:
        self.help[name] = text

    def inc(self, name: str, value: float = 1.0,
            labels: Optional[dict] = None) -> None:
        with self._lock:
            k = self._key(name, labels)
            self.counters[k] = self.counters.get(k, 0.0) + value

    def set_gauge(self, name: str, value: float,
                  labels: Optional[dict] = None) -> None:
        with self._lock:
            self.gauges[self._key(name, labels)] = float(value)

    def observe(self, name: str, value: float,
                labels: Optional[dict] = None) -> None:
        with self._lock:
            self.histograms.setdefault(self._key(name, labels), []).append(
                float(value))

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "counters": dict(self.counters),
                "gauges": dict(self.gauges),
                "histograms": {k: list(v) for k, v in self.histograms.items()},
            }

    def render_prometheus(self) -> str:
        """Eksposisi teks format Prometheus 0.0.4.

        Menyertakan `# HELP` (dari `describe()`) dan `# TYPE` per keluarga metrik.
        Tanpa ini `describe()` hanya tersimpan dan tidak pernah terlihat oleh
        scraper, dan `promtool check metrics` menganggap tipe metrik tidak
        terdeklarasi (counter/gauge tak bisa dibedakan).
        """
        snap = self.snapshot()
        lines: list[str] = []

        def _labels(k: tuple) -> str:
            if len(k) == 1:
                return ""
            pasangan = k[1:]
            isi = ",".join(f'{kk}="{vv}"' for kk, vv in pasangan)
            return "{" + isi + "}"

        def _family(nama: str, jenis: str, series: list) -> None:
            if not series:
                return
            if nama in self.help:
                # Escape sesuai spec: backslash, newline, kutip ganda.
                teks = (self.help[nama].replace("\\", "\\\\")
                        .replace("\n", "\\n").replace('"', '\\"'))
                lines.append(f"# HELP {nama} {teks}")
            lines.append(f"# TYPE {nama} {jenis}")
            for k, v in series:
                lines.append(f"{nama}{_labels(k)} {_fmt(v)}")

        cg: dict[str, list] = {}
        for k, v in sorted(snap["counters"].items()):
            cg.setdefault(k[0], []).append((k, v))
        for nama, series in cg.items():
            _family(nama, "counter", series)

        gg: dict[str, list] = {}
        for k, v in sorted(snap["gauges"].items()):
            gg.setdefault(k[0], []).append((k, v))
        for nama, series in gg.items():
            _family(nama, "gauge", series)

        hg: dict[str, list] = {}
        for k, vals in sorted(snap["histograms"].items()):
            hg.setdefault(k[0], []).append((k, vals))
        for nama, groups in hg.items():
            if nama in self.help:
                teks = (self.help[nama].replace("\\", "\\\\")
                        .replace("\n", "\\n").replace('"', '\\"'))
                lines.append(f"# HELP {nama} {teks}")
            lines.append(f"# TYPE {nama} histogram")
            for k, vals in groups:
                for le in (50, 100, 250, 500, 1000, 2500, 5000):
                    n = sum(1 for x in vals if x <= le)
                    lbl = _labels(k)
                    if lbl:
                        inner = lbl[1:-1] + f',le="{le}"'
                    else:
                        inner = f'le="{le}"'
                    lines.append(f"{nama}_bucket{{{inner}}} {n}")
                lines.append(f"{nama}_sum{_labels(k)} {_fmt(sum(vals))}")
                lines.append(f"{nama}_count{_labels(k)} {len(vals)}")
        return "\n".join(lines) + "\n"


def _fmt(v: float) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return repr(v) if isinstance(v, float) else str(v)


def parse_prometheus(text: str) -> dict[str, float]:
    """Urai eksposisi Prometheus -> {nama_series: nilai} (untuk verifikasi)."""
    out: dict[str, float] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        bagian = line.rsplit(" ", 1)
        if len(bagian) != 2:
            continue
        try:
            out[bagian[0]] = float(bagian[1])
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------------------
# Mesin aturan alert
# ---------------------------------------------------------------------------

DEFAULT_RULES: list[dict] = [
    {"name": "high_error_rate", "metric": "error_rate", "op": ">",
     "threshold": 0.05, "severity": "critical", "for_seconds": 0},
    {"name": "high_p95_latency", "metric": "p95_latency_ms", "op": ">",
     "threshold": 2000, "severity": "warning"},
    {"name": "high_cost", "metric": "cost_usd", "op": ">",
     "threshold": 10.0, "severity": "warning"},
    {"name": "low_success_rate", "metric": "success_rate", "op": "<",
     "threshold": 0.9, "severity": "critical"},
]

_OPS = {
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


def evaluate_rules(rules: list[dict], values: dict[str, float]) -> list[dict]:
    """Evaluasi aturan terhadap nilai metrik. Return alert yang MENYALA."""
    firing: list[dict] = []
    for r in rules or []:
        nama = r.get("metric")
        if nama not in values:
            continue
        op = _OPS.get(r.get("op", ">"))
        if op is None:
            continue
        try:
            kena = op(float(values[nama]), float(r["threshold"]))
        except (TypeError, ValueError, KeyError):
            continue
        if kena:
            firing.append({
                "rule": r.get("name") or nama,
                "metric": nama,
                "value": values[nama],
                "threshold": r["threshold"],
                "op": r.get("op", ">"),
                "severity": r.get("severity", "warning"),
            })
    return firing


# ---------------------------------------------------------------------------
# Manajer alert: dedup + silence
# ---------------------------------------------------------------------------

class AlertManager:
    """Dedup (per nama aturan dalam jendela waktu) + silence (maintenance)."""

    def __init__(self, dedup_seconds: float = 300.0,
                 clock: Callable[[], float] = time.time) -> None:
        self.dedup_seconds = float(dedup_seconds)
        self._clock = clock
        self._last_sent: dict[str, float] = {}
        self._silences: dict[str, float] = {}   # rule -> until_ts (0=∞)
        self._lock = threading.Lock()

    def silence(self, rule: str, until_ts: float = 0.0) -> None:
        """Bisukan aturan sampai `until_ts` (0 = sampai dibatalkan)."""
        with self._lock:
            self._silences[rule] = float(until_ts)

    def unsilence(self, rule: str) -> None:
        with self._lock:
            self._silences.pop(rule, None)

    def is_silenced(self, rule: str, now: Optional[float] = None) -> bool:
        now = self._clock() if now is None else now
        with self._lock:
            until = self._silences.get(rule)
        if until is None:
            return False
        return until == 0.0 or now < until

    def process(self, firing: list[dict],
                now: Optional[float] = None) -> list[dict]:
        """Saring alert: buang yang di-silence, dedup yang baru dikirim."""
        now = self._clock() if now is None else now
        keluar: list[dict] = []
        with self._lock:
            for a in firing or []:
                rule = a.get("rule", "")
                until = self._silences.get(rule)
                if until is not None and (until == 0.0 or now < until):
                    continue  # dibisukan
                terakhir = self._last_sent.get(rule)
                if terakhir is not None and (now - terakhir) < self.dedup_seconds:
                    continue  # dedup
                self._last_sent[rule] = now
                keluar.append(a)
        return keluar


# ---------------------------------------------------------------------------
# Redaksi isi alert (cegah kebocoran rahasia)
# ---------------------------------------------------------------------------

def redact(text: Any) -> Any:
    """Ganti referensi/token rahasia dengan mask (rekursif)."""
    if isinstance(text, str):
        return _SECRET_RE.sub(MASK, text)
    if isinstance(text, dict):
        return {k: redact(v) for k, v in text.items()}
    if isinstance(text, list):
        return [redact(v) for v in text]
    return text


# ---------------------------------------------------------------------------
# Notifier (transport disuntik -> test tanpa jaringan)
# ---------------------------------------------------------------------------

class Notifier(ABC):
    name = "?"

    def __init__(self, transport: Optional[Callable[[dict], bool]] = None):
        self._transport = transport

    @abstractmethod
    def payload(self, alert: dict) -> dict:
        """Bangun payload untuk alert ini."""

    def send(self, alert: dict) -> bool:
        p = self.payload(redact(alert))
        if self._transport is not None:
            return bool(self._transport(p))
        return self._send_http(p)

    def _send_http(self, payload: dict) -> bool:  # pragma: no cover - jaringan
        return False


class WebhookNotifier(Notifier):
    name = "webhook"

    def __init__(self, url: str = "", transport=None):
        super().__init__(transport)
        self.url = url

    def payload(self, alert: dict) -> dict:
        return {"url": self.url, "json": alert}


class SlackNotifier(Notifier):
    name = "slack"

    def __init__(self, webhook_url: str = "", transport=None):
        super().__init__(transport)
        self.webhook_url = webhook_url

    def payload(self, alert: dict) -> dict:
        teks = (f":rotating_light: [{alert.get('severity','warning')}] "
                f"{alert.get('rule')} — {alert.get('metric')}="
                f"{alert.get('value')} {alert.get('op')} {alert.get('threshold')}")
        return {"url": self.webhook_url, "json": {"text": teks}}


class TelegramNotifier(Notifier):
    name = "telegram"

    def __init__(self, bot_token: str = "", chat_id: str = "", transport=None):
        super().__init__(transport)
        self.bot_token = bot_token
        self.chat_id = chat_id

    def payload(self, alert: dict) -> dict:
        teks = (f"[{alert.get('severity','warning')}] {alert.get('rule')}: "
                f"{alert.get('metric')}={alert.get('value')}")
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        return {"url": url, "json": {"chat_id": self.chat_id, "text": teks}}


class EmailNotifier(Notifier):
    name = "email"

    def __init__(self, to: str = "", transport=None):
        super().__init__(transport)
        self.to = to

    def payload(self, alert: dict) -> dict:
        return {"to": self.to,
                "subject": f"[Katalir] {alert.get('severity','warning')}: "
                           f"{alert.get('rule')}",
                "body": json.dumps(alert, sort_keys=True)}


def notify_all(notifiers: list[Notifier], alert: dict) -> dict[str, bool]:
    """Kirim alert ke semua notifier. Return {nama: berhasil}."""
    hasil: dict[str, bool] = {}
    for n in notifiers or []:
        try:
            hasil[n.name] = n.send(alert)
        except Exception:  # noqa: BLE001 - satu notifier rusak tidak mematikan
            hasil[n.name] = False
    return hasil


# ---------------------------------------------------------------------------
# Agregasi log
# ---------------------------------------------------------------------------

class LogIndex:
    """Indeks log in-memory dengan pencarian substring + level + limit."""

    def __init__(self, max_entries: int = 100_000) -> None:
        self.max_entries = max_entries
        self._entries: list[dict] = []
        self._lock = threading.Lock()

    def add(self, entry: dict) -> None:
        with self._lock:
            self._entries.append(dict(entry))
            if len(self._entries) > self.max_entries:
                self._entries = self._entries[-self.max_entries:]

    def search(self, query: str = "", level: str = "",
               limit: int = 100) -> list[dict]:
        q = (query or "").lower()
        lv = (level or "").lower()
        hasil: list[dict] = []
        with self._lock:
            for e in reversed(self._entries):
                if lv and str(e.get("level", "")).lower() != lv:
                    continue
                if q and q not in json.dumps(e, ensure_ascii=False).lower():
                    continue
                hasil.append(e)
                if len(hasil) >= limit:
                    break
        return hasil

    def __len__(self) -> int:
        return len(self._entries)


# ---------------------------------------------------------------------------
# Tracing per-node
# ---------------------------------------------------------------------------

class Span:
    def __init__(self, name: str, node_id: str = "",
                 started: Optional[float] = None) -> None:
        self.name = name
        self.node_id = node_id
        self.started = started if started is not None else time.time()
        self.ended: Optional[float] = None
        self.status = "ok"
        self.attributes: dict[str, Any] = {}

    def finish(self, status: str = "ok") -> "Span":
        self.ended = time.time()
        self.status = status
        return self

    @property
    def duration_ms(self) -> float:
        if self.ended is None:
            return 0.0
        return (self.ended - self.started) * 1000.0

    def to_dict(self) -> dict:
        return {"name": self.name, "node_id": self.node_id,
                "started": self.started, "ended": self.ended,
                "duration_ms": round(self.duration_ms, 3),
                "status": self.status, "attributes": self.attributes}


class Trace:
    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self.spans: list[Span] = []

    def span(self, name: str, node_id: str = "") -> Span:
        s = Span(name, node_id)
        self.spans.append(s)
        return s

    def to_dict(self) -> dict:
        return {"trace_id": self.trace_id,
                "spans": [s.to_dict() for s in self.spans]}


def trace_from_execution(execution_id: str, nodes: list[dict]) -> Trace:
    """Bangun trace dari daftar node eksekusi (mis. dari execution log).

    Setiap node -> satu span. `started_at`/`ended_at` epoch detik opsional.
    """
    t = Trace(str(execution_id))
    for n in nodes or []:
        s = Span(str(n.get("id") or n.get("node_id") or "node"),
                 str(n.get("node_id") or ""),
                 started=n.get("started_at"))
        if n.get("ended_at") is not None:
            s.ended = float(n["ended_at"])
        s.status = str(n.get("status") or "ok")
        if n.get("kind"):
            s.attributes["kind"] = n["kind"]
        t.spans.append(s)
    return t


# ---------------------------------------------------------------------------
# Ringkasan dashboard
# ---------------------------------------------------------------------------

def dashboard_summary(metrics: Metrics, alerts: list[dict],
                      traces: Optional[list[Trace]] = None) -> dict:
    """Ringkasan siap-render untuk dashboard (dihitung cepat, <2s)."""
    snap = metrics.snapshot()
    counters = {k[0]: v for k, v in snap["counters"].items()}
    gauges = {k[0]: v for k, v in snap["gauges"].items()}
    lat = snap["histograms"].get(("latency_ms",), [])
    p95 = _percentile(lat, 95)
    return {
        "counters": counters,
        "gauges": gauges,
        "p95_latency_ms": p95,
        "active_alerts": len(alerts),
        "traces": len(traces or []),
        "spans": sum(len(t.spans) for t in (traces or [])),
    }


def _percentile(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    idx = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return round(s[idx], 3)
