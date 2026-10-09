"""log_streaming.py — Fitur #4: Log streaming ke SIEM eksternal.

RISET (Okt 2026) — `docs.n8n.io/administer/observe-and-log/stream-logs-to-external-systems`
dan `n8n.nodejs.cn/log-streaming/` (n8n v2.19.0+ untuk konfigurasi via env):

* **Tiga jenis tujuan**: `webhook`, `syslog` (udp/tcp/tls), `sentry`.
* **Field umum** setiap tujuan: `type`, `label`, `enabled`, `subscribedEvents`
  (nama event ATAU prefiks grup, mis. `n8n.audit`), `anonymizeAuditMessages`,
  `circuitBreaker {maxFailures, failureWindow}`.
* **Grup event**: `n8n.workflow` (started/success/failed/cancelled),
  `n8n.node` (started/finished), `n8n.audit` (±60 event: login, user,
  credentials, workflow, 2FA, eksekusi dihapus/dibuka, variabel, dsb.),
  `n8n.worker`, `n8n.ai`, `n8n.runner`, `n8n.queue`.
* **Daya tahan**: n8n menyimpan SETIAP event ke file log lokal **sebelum**
  diteruskan; file bertahan melewati restart dan event yang belum terkirim
  **diemisikan ulang** (`N8N_EVENTBUS_LOGWRITER_LOGFULLPATH` untuk multi-proses).
* **Circuit breaker**: setelah `maxFailures` kegagalan dalam jendela
  `failureWindow` (ms), pengiriman ke tujuan itu DIHENTIKAN sementara.
* **Webhook options**: `method` (GET/POST/PUT), `sendQuery`/`sendHeaders`
  (keypair|json), `timeout`, `redirect`, `proxy`, `socket`, `allowUnauthorizedCerts`.
* **Syslog**: `host`, `port` (514), `protocol` (`udp`|`tcp`|`tls`), `tlsCa`,
  `facility` (16=local0), `app_name`.

DESAIN DI MODUL INI
-------------------
1. **Transport disuntik** (`transport(payload_dict) -> bool`). Di produksi
   transport default memakai `urllib` (stdlib) atau `socket` untuk syslog;
   di test, transport palsu memungkinkan pengujian deterministik **tanpa
   jaringan** — namun kode format/pemfilteran/rangkaian tetap dieksekusi nyata.
2. **Event bus sinkron + spool durable**. `EventBus.emit()` menulis ke spool
   dulu (`_spool`), baru mencoba kirim. Kegagalan → event tetap di spool dan
   `flush()` akan mencoba lagi (perilaku "re-emit" n8n).
3. **Circuit breaker per tujuan** (sliding window) — tidak memblokir tujuan lain.
4. **Anonimisasi audit** memakai redaktor yang sudah ada
   (`agent_redactor.redact_value`) sehingga token/PII tidak bocor ke SIEM.
5. **Format syslog RFC 5424** dibuat sendiri (tanpa dependensi). Sentry memakai
   protokol Store envelope minimal.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Callable, Iterable, Optional

from agent_redactor import redact_value

# ---------------------------------------------------------------------------
# Grup + nama event (mengikuti penamaan n8n `n8n.<grup>.<aksi>`)
# ---------------------------------------------------------------------------
#: Prefiks grup yang dikenal. `subscribedEvents` boleh berisi nama grup ini
#: (mencakup semua anggotanya) atau nama event penuh.
EVENT_GROUPS = (
    "n8n.workflow",
    "n8n.node",
    "n8n.audit",
    "n8n.worker",
    "n8n.ai",
    "n8n.runner",
    "n8n.queue",
)

#: Nama event lengkap per grup (subset yang relevan untuk Katalir; nama
#: mengikuti daftar resmi n8n agar dashboard SIEM yang sudah ada tetap cocok).
EVENTS: dict[str, tuple[str, ...]] = {
    "n8n.workflow": (
        "n8n.workflow.started", "n8n.workflow.success",
        "n8n.workflow.failed", "n8n.workflow.cancelled",
        "n8n.workflow.waiting", "n8n.workflow.resumed",
        "n8n.workflow.executed", "n8n.workflow.created",
        "n8n.workflow.updated", "n8n.workflow.deleted",
        "n8n.workflow.activated", "n8n.workflow.deactivated",
    ),
    "n8n.node": ("n8n.node.started", "n8n.node.finished"),
    "n8n.audit": (
        "n8n.audit.user.login.success", "n8n.audit.user.login.failed",
        "n8n.audit.user.registered", "n8n.audit.user.updated",
        "n8n.audit.user.deleted", "n8n.audit.user.invited",
        "n8n.audit.user.reinvited",
        "n8n.audit.user.email.failed", "n8n.audit.user.reset.requested",
        "n8n.audit.user.reset", "n8n.audit.user.credentials.created",
        "n8n.audit.user.credentials.shared",
        "n8n.audit.user.credentials.updated",
        "n8n.audit.user.credentials.deleted",
        "n8n.audit.user.api.created", "n8n.audit.user.api.deleted",
        "n8n.audit.user.mfa.enabled", "n8n.audit.user.mfa.disabled",
        "n8n.audit.execution.deleted",
        # Redaksi eksekusi (Fitur #11a memancarkan dua event ini).
        "n8n.audit.execution.data.revealed",
        "n8n.audit.execution.data.reveal_failure",
        "n8n.audit.package.installed", "n8n.audit.package.updated",
        "n8n.audit.package.deleted",
        "n8n.audit.workflow.created", "n8n.audit.workflow.deleted",
        "n8n.audit.workflow.updated", "n8n.audit.workflow.archived",
        "n8n.audit.workflow.unarchived", "n8n.audit.workflow.activated",
        "n8n.audit.workflow.deactivated",
        "n8n.audit.workflow.version.updated",
        "n8n.audit.workflow.executed", "n8n.audit.workflow.waiting",
        "n8n.audit.workflow.resumed",
        "n8n.audit.variable.created", "n8n.audit.variable.updated",
        "n8n.audit.variable.deleted",
        "n8n.audit.secrets.provider.saved",
        "n8n.audit.secrets.provider.reloaded",
        "n8n.audit.secrets.connection.created",
        "n8n.audit.secrets.connection.updated",
        "n8n.audit.secrets.connection.deleted",
        "n8n.audit.secrets.connection.tested",
        "n8n.audit.personal.publishing.restricted.enabled",
        "n8n.audit.personal.publishing.restricted.disabled",
        "n8n.audit.personal.sharing.restricted.enabled",
        "n8n.audit.personal.sharing.restricted.disabled",
        "n8n.audit.twofa.enabled", "n8n.audit.twofa.disabled",
        "n8n.audit.role.mapping.rule.created",
        "n8n.audit.role.mapping.rule.updated",
        "n8n.audit.role.mapping.rule.deleted",
    ),
    "n8n.worker": ("n8n.worker.started", "n8n.worker.stopped"),
    "n8n.ai": (
        "n8n.ai.memory.getMessages", "n8n.ai.memory.addMessages",
        "n8n.ai.outputParser.parsed", "n8n.ai.retriever.getRelevantDocuments",
        "n8n.ai.embeddings.embedded.document",
        "n8n.ai.embeddings.embedded.query",
        "n8n.ai.document.processed", "n8n.ai.textSplitter.split",
        "n8n.ai.tool.name", "n8n.ai.vectorStore.searched",
        "n8n.ai.llm.generated", "n8n.ai.llm.error",
        "n8n.ai.vectorStore.populated", "n8n.ai.vectorStore.updated",
    ),
    "n8n.runner": ("n8n.runner.task.requested", "n8n.runner.response.received"),
    "n8n.queue": (
        "n8n.queue.job.enqueued", "n8n.queue.job.dequeued",
        "n8n.queue.job.completed", "n8n.queue.job.failed",
        "n8n.queue.job.stalled",
    ),
}

#: Level log yang dikenal (n8n memakai level di payload, bukan di nama event).
LOG_LEVELS = ("debug", "info", "warn", "error")


def all_event_names() -> list[str]:
    return sorted({e for group in EVENTS.values() for e in group})


def event_group(name: str) -> str:
    """`n8n.audit.user.login.success` -> `n8n.audit` (grup terpanjang yang cocok)."""
    nm = str(name or "")
    best = ""
    for g in EVENT_GROUPS:
        if nm == g or nm.startswith(g + "."):
            if len(g) > len(best):
                best = g
    return best


def event_matches(event: str, subscribed: Iterable[str] | None) -> bool:
    """True bila `event` tercakup oleh daftar `subscribed`.

    Aturan (dikunci test):
      * daftar kosong/None  -> SEMUA event (perilaku default n8n);
      * entri == nama grup  -> semua event di grup itu;
      * entri == nama event -> hanya event itu;
      * entri berakhiran `*`-> pencocokan awalan (mis. `n8n.audit.user.*`).
    """
    subs = [s for s in (subscribed or []) if s]
    if not subs:
        return True
    nm = str(event or "")
    grp = event_group(nm)
    for s in subs:
        s = str(s).strip()
        if s == nm or s == grp:
            return True
        if s.endswith("*") and nm.startswith(s[:-1].rstrip(".")):
            return True
        if s.endswith(".") and nm.startswith(s):
            return True
    return False


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------
#: Default mengikuti n8n: 5 kegagalan dalam 60 detik -> berhenti sementara.
DEFAULT_MAX_FAILURES = 5
DEFAULT_FAILURE_WINDOW_MS = 60_000
#: Lama berhenti setelah breaker terbuka (dipakai untuk half-open).
DEFAULT_COOLDOWN_MS = 60_000


class CircuitBreaker:
    """Breaker berbasis jendela geser. Kunci test-friendly (waktu disuntik)."""

    def __init__(self, max_failures: int = DEFAULT_MAX_FAILURES,
                 failure_window_ms: int = DEFAULT_FAILURE_WINDOW_MS,
                 cooldown_ms: int = DEFAULT_COOLDOWN_MS,
                 clock: Callable[[], float] | None = None):
        self.max_failures = max(1, int(max_failures))
        self.failure_window_ms = max(100, int(failure_window_ms))
        self.cooldown_ms = max(0, int(cooldown_ms))
        self._clock = clock or time.time
        self._failures: list[float] = []
        self._opened_at: float | None = None
        self.open_count = 0

    def _now_ms(self) -> float:
        return self._clock() * 1000.0

    def _prune(self, now_ms: float) -> None:
        cutoff = now_ms - self.failure_window_ms
        self._failures = [t for t in self._failures if t >= cutoff]

    @property
    def is_open(self) -> bool:
        """True bila pengiriman saat ini DILARANG."""
        if self._opened_at is None:
            return False
        if self.cooldown_ms and (
                self._now_ms() - self._opened_at * 1000.0) >= self.cooldown_ms:
            # Half-open: izinkan satu percobaan lagi (lihat `record_success`).
            return False
        return True

    def allows(self) -> bool:
        return not self.is_open

    def record_failure(self) -> None:
        now_ms = self._now_ms()
        self._prune(now_ms)
        self._failures.append(now_ms)
        if len(self._failures) >= self.max_failures:
            self._opened_at = now_ms / 1000.0
            self.open_count += 1

    def record_success(self) -> None:
        self._failures.clear()
        self._opened_at = None

    def snapshot(self) -> dict:
        self._prune(self._now_ms())
        return {"open": self.is_open, "failures": len(self._failures),
                "max_failures": self.max_failures,
                "failure_window_ms": self.failure_window_ms,
                "open_count": self.open_count}


# ---------------------------------------------------------------------------
# Tujuan (destination)
# ---------------------------------------------------------------------------
class DestinationError(RuntimeError):
    """Konfigurasi tujuan tidak sah."""


class Destination(ABC):
    """Tujuan streaming. `send()` mengembalikan True bila terkirim."""

    type = "?"

    def __init__(self, label: str = "", enabled: bool = True,
                 subscribed_events: Iterable[str] | None = None,
                 anonymize_audit: bool = False,
                 circuit_breaker: dict | None = None,
                 transport: Callable[[dict], bool] | None = None,
                 clock: Callable[[], float] | None = None):
        self.label = label or self.type
        self.enabled = bool(enabled)
        self.subscribed_events = list(subscribed_events or [])
        self.anonymize_audit = bool(anonymize_audit)
        self.transport = transport
        cb = circuit_breaker or {}
        self.breaker = CircuitBreaker(
            max_failures=cb.get("maxFailures", DEFAULT_MAX_FAILURES),
            failure_window_ms=cb.get("failureWindow", DEFAULT_FAILURE_WINDOW_MS),
            cooldown_ms=cb.get("cooldownMs", DEFAULT_COOLDOWN_MS),
            clock=clock)
        self.sent = 0
        self.failed = 0
        self.skipped = 0
        self.last_error = ""

    # -- filter ------------------------------------------------------------
    def accepts(self, event: str) -> bool:
        return self.enabled and event_matches(event, self.subscribed_events)

    # -- transformasi ------------------------------------------------------
    def prepare(self, event: dict) -> dict:
        """Bentuk payload kirim. Anonimisasi audit bila diminta."""
        payload = dict(event)
        if self.anonymize_audit and str(payload.get("event", "")).startswith(
                "n8n.audit"):
            for key in ("data", "payload", "workflow", "user"):
                if key in payload:
                    payload[key] = redact_value(payload[key])
            payload["anonymized"] = True
        return payload

    # -- pengiriman --------------------------------------------------------
    @abstractmethod
    def _deliver(self, payload: dict) -> bool:
        """Kirim payload. Sub-kelas: HTTP, syslog, sentry."""

    def send(self, event: dict) -> bool:
        """Kirim satu event. Menghormati breaker + filter langganan."""
        ev = str(event.get("event", ""))
        if not self.accepts(ev):
            self.skipped += 1
            return False
        if not self.breaker.allows():
            self.skipped += 1
            return False
        payload = self.prepare(event)
        try:
            ok = bool(self._deliver(payload))
        except Exception as exc:  # noqa: BLE001 - kegagalan tujuan tidak boleh meledak
            ok = False
            self.last_error = f"{type(exc).__name__}: {exc}"
        if ok:
            self.sent += 1
            self.breaker.record_success()
        else:
            self.failed += 1
            if not self.last_error:
                self.last_error = "transport mengembalikan False"
            self.breaker.record_failure()
        return ok

    def stats(self) -> dict:
        return {"type": self.type, "label": self.label, "enabled": self.enabled,
                "subscribed_events": list(self.subscribed_events),
                "anonymize_audit_messages": self.anonymize_audit,
                "sent": self.sent, "failed": self.failed,
                "skipped": self.skipped, "last_error": self.last_error,
                "circuit_breaker": self.breaker.snapshot()}


# -- webhook ---------------------------------------------------------------
class WebhookDestination(Destination):
    type = "webhook"

    def __init__(self, url: str = "", method: str = "POST",
                 send_query: bool = False, query_parameters: dict | None = None,
                 send_headers: bool = False,
                 header_parameters: dict | None = None,
                 options: dict | None = None, **kw):
        super().__init__(**kw)
        if not url:
            raise DestinationError("webhook: `url` wajib diisi")
        self.url = str(url)
        self.method = str(method or "POST").upper()
        if self.method not in ("GET", "POST", "PUT"):
            raise DestinationError(
                f"webhook: method tidak didukung: {self.method}")
        self.send_query = bool(send_query)
        self.query_parameters = dict(query_parameters or {})
        self.send_headers = bool(send_headers)
        self.header_parameters = dict(header_parameters or {})
        opts = dict(options or {})
        self.timeout = max(1, int(opts.get("timeout", 5000))) / 1000.0
        self.allow_unauthorized_certs = bool(
            opts.get("allowUnauthorizedCerts", False))

    def config(self) -> dict:
        return {"type": self.type, "label": self.label, "url": self.url,
                "method": self.method, "send_query": self.send_query,
                "send_headers": self.send_headers,
                "timeout_ms": int(self.timeout * 1000)}

    def _deliver(self, payload: dict) -> bool:
        if self.transport is not None:
            return bool(self.transport({
                "url": self.url, "method": self.method, "json": payload,
                "headers": self.header_parameters if self.send_headers else {},
                "query": self.query_parameters if self.send_query else {},
            }))
        return self._http(payload)

    def _http(self, payload: dict) -> bool:  # pragma: no cover - jaringan nyata
        url = self.url
        if self.send_query and self.query_parameters:
            sep = "&" if "?" in url else "?"
            url = url + sep + urllib.parse.urlencode(self.query_parameters)
        data = None
        headers = {"Content-Type": "application/json"}
        if self.send_headers:
            headers.update({str(k): str(v)
                            for k, v in self.header_parameters.items()})
        if self.method in ("POST", "PUT"):
            data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method=self.method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return 200 <= int(resp.status) < 300
        except urllib.error.HTTPError as exc:
            self.last_error = f"HTTP {exc.code}"
            return False
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False


# -- syslog ----------------------------------------------------------------
#: Kode facility yang diizinkan n8n.
SYSLOG_FACILITIES = (0, 1, 3, 13, 14, 16, 17, 18, 19, 20, 21, 22, 23)
#: Severity syslog per level aplikasi.
_SYSLOG_SEVERITY = {"debug": 7, "info": 6, "warn": 4, "warning": 4,
                    "error": 3, "critical": 2}


def format_rfc5424(event: dict, *, facility: int = 16,
                   app_name: str = "katalir",
                   hostname: str | None = None,
                   msg_id: str | None = None) -> str:
    """Bentuk pesan syslog RFC 5424 (tanpa dependensi).

    `<PRI>1 TIMESTAMP HOST APP PROCID MSGID [SD] MSG`
    """
    level = str(event.get("level") or "info").lower()
    severity = _SYSLOG_SEVERITY.get(level, 6)
    pri = int(facility) * 8 + severity
    ts = event.get("ts")
    if isinstance(ts, (int, float)):
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)) + "Z"
    else:
        stamp = str(ts) if ts else "-"
    host = hostname or event.get("host") or "-"
    proc = str(event.get("process") or "-")
    mid = msg_id or str(event.get("event") or "-")
    # Structured data: biarkan kosong (data dikirim di MSG) supaya parser
    # SIEM mana pun tetap bisa membaca JSON-nya.
    msg = json.dumps(event, sort_keys=True, default=str)
    return f"<{pri}>1 {stamp} {host} {app_name} {proc} {mid} - {msg}"


class SyslogDestination(Destination):
    type = "syslog"

    def __init__(self, host: str = "", port: int = 514,
                 protocol: str = "udp", tls_ca: str = "",
                 facility: int = 16, app_name: str = "katalir",
                 transport: Callable[[dict], bool] | None = None, **kw):
        super().__init__(transport=transport, **kw)
        if not host:
            raise DestinationError("syslog: `host` wajib diisi")
        self.host = str(host)
        self.port = int(port or 514)
        self.protocol = str(protocol or "udp").lower()
        if self.protocol not in ("udp", "tcp", "tls"):
            raise DestinationError(
                f"syslog: protocol tidak didukung: {self.protocol}")
        if self.protocol == "tls" and not tls_ca:
            raise DestinationError(
                "syslog: protocol 'tls' memerlukan `tlsCa` (PEM)")
        self.tls_ca = tls_ca
        if int(facility) not in SYSLOG_FACILITIES:
            raise DestinationError(f"syslog: facility tidak sah: {facility}")
        self.facility = int(facility)
        self.app_name = str(app_name or "katalir")
        self.timeout = 5.0

    def config(self) -> dict:
        return {"type": self.type, "label": self.label, "host": self.host,
                "port": self.port, "protocol": self.protocol,
                "facility": self.facility, "app_name": self.app_name}

    def _deliver(self, payload: dict) -> bool:
        frame = format_rfc5424(payload, facility=self.facility,
                               app_name=self.app_name)
        if self.transport is not None:
            return bool(self.transport({
                "host": self.host, "port": self.port,
                "protocol": self.protocol, "frame": frame, "json": payload}))
        return self._socket_send(frame)

    def _socket_send(self, frame: str) -> bool:  # pragma: no cover - jaringan
        data = frame.encode("utf-8")
        try:
            if self.protocol == "udp":
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.settimeout(self.timeout)
                    s.sendto(data, (self.host, self.port))
                return True
            if self.protocol == "tcp":
                with socket.create_connection((self.host, self.port),
                                              timeout=self.timeout) as s:
                    s.sendall(data + b"\n")
                return True
            import ssl
            ctx = ssl.create_default_context(cafile=None)
            ctx.load_verify_locations(cadata=self.tls_ca)
            with socket.create_connection((self.host, self.port),
                                          timeout=self.timeout) as raw:
                with ctx.wrap_socket(raw, server_hostname=self.host) as s:
                    s.sendall(data + b"\n")
            return True
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False


# -- sentry ----------------------------------------------------------------
def sentry_dsn_parts(dsn: str) -> dict:
    """Urai DSN `https://<public>@<host>/<project_id>` tanpa dependensi."""
    raw = str(dsn or "")
    if "://" not in raw:
        raise DestinationError(f"sentry: DSN tidak sah: {dsn!r}")
    scheme, rest = raw.split("://", 1)
    if "@" not in rest:
        raise DestinationError(f"sentry: DSN tanpa public key: {dsn!r}")
    public, hostpart = rest.rsplit("@", 1)
    host, _, project = hostpart.partition("/")
    if not (public and host and project):
        raise DestinationError(f"sentry: DSN tidak lengkap: {dsn!r}")
    return {"scheme": scheme, "public_key": public, "host": host,
            "project_id": project}


class SentryDestination(Destination):
    type = "sentry"

    def __init__(self, dsn: str = "", transport=None, **kw):
        super().__init__(transport=transport, **kw)
        self.dsn = str(dsn or "")
        if not self.dsn:
            raise DestinationError("sentry: `dsn` wajib diisi")
        self.parts = sentry_dsn_parts(self.dsn)

    def config(self) -> dict:
        # DSN memuat public key -> jangan pernah dikembalikan utuh.
        p = dict(self.parts)
        p["public_key"] = "***"
        return {"type": self.type, "label": self.label, **p}

    def envelope(self, payload: dict) -> str:
        """Envelope gaya Sentry: header JSON, item header, lalu event JSON."""
        event_id = str(payload.get("event_id") or "")
        head = {"event_id": event_id or None, "dsn": self.dsn}
        item = {"type": "event", "content_type": "application/json"}
        body = {"level": payload.get("level") or "info",
                "message": payload.get("event") or "katalir.event",
                "platform": "python",
                "extra": payload}
        lines = [json.dumps(head, separators=(",", ":")),
                 json.dumps(item, separators=(",", ":")),
                 json.dumps(body, separators=(",", ":"), default=str)]
        return "\n".join(lines) + "\n"

    def _deliver(self, payload: dict) -> bool:
        env = self.envelope(payload)
        url = (f"{self.parts['scheme']}://{self.parts['host']}"
               f"/api/{self.parts['project_id']}/envelope/")
        if self.transport is not None:
            return bool(self.transport({
                "url": url, "envelope": env, "json": payload,
                "headers": {"X-Sentry-Auth": (
                    f"Sentry sentry_version=7, sentry_client=katalir/1.0, "
                    f"sentry_key={self.parts['public_key']}")}}))
        return self._http(url, env)

    def _http(self, url: str, env: str) -> bool:  # pragma: no cover - jaringan
        req = urllib.request.Request(
            url, data=env.encode(), method="POST",
            headers={"Content-Type": "application/x-sentry-envelope",
                     "X-Sentry-Auth": (
                         f"Sentry sentry_version=7, "
                         f"sentry_client=katalir/1.0, "
                         f"sentry_key={self.parts['public_key']}")})
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return 200 <= int(resp.status) < 300
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False


# ---------------------------------------------------------------------------
# Pabrik tujuan dari konfigurasi (bentuk n8n)
# ---------------------------------------------------------------------------
def build_destination(spec: dict, *,
                      transport: Callable[[dict], bool] | None = None,
                      clock: Callable[[], float] | None = None) -> Destination:
    """Bangun `Destination` dari dict gaya `N8N_LOG_STREAMING_DESTINATIONS`."""
    if not isinstance(spec, dict):
        raise DestinationError(f"tujuan harus objek, bukan {type(spec).__name__}")
    typ = str(spec.get("type") or "").strip().lower()
    common = {
        "label": spec.get("label", ""),
        "enabled": spec.get("enabled", True) is not False,
        "subscribed_events": spec.get("subscribedEvents") or [],
        "anonymize_audit": bool(spec.get("anonymizeAuditMessages", False)),
        "circuit_breaker": spec.get("circuitBreaker") or {},
        "clock": clock,
    }
    if typ == "webhook":
        return WebhookDestination(
            url=spec.get("url", ""), method=spec.get("method", "POST"),
            send_query=bool(spec.get("sendQuery", False)),
            query_parameters=_kv(spec, "queryParameters", "jsonQuery"),
            send_headers=bool(spec.get("sendHeaders", False)),
            header_parameters=_kv(spec, "headerParameters", "jsonHeaders"),
            options=spec.get("options") or {},
            transport=transport, **common)
    if typ == "syslog":
        return SyslogDestination(
            host=spec.get("host", ""), port=spec.get("port", 514),
            protocol=spec.get("protocol", "udp"), tls_ca=spec.get("tlsCa", ""),
            facility=spec.get("facility", 16),
            app_name=spec.get("app_name", spec.get("appName", "katalir")),
            transport=transport, **common)
    if typ == "sentry":
        return SentryDestination(dsn=spec.get("dsn", ""),
                                 transport=transport, **common)
    raise DestinationError(f"tipe tujuan tidak dikenal: {typ!r}")


def _kv(spec: dict, keypair_key: str, json_key: str) -> dict:
    """Ambil parameter keypair ATAU JSON (mengikuti `specifyQuery/Headers`)."""
    kp = spec.get(keypair_key)
    if isinstance(kp, dict):
        items = kp.get("parameters")
        if isinstance(items, list):
            out = {}
            for item in items:
                if isinstance(item, dict) and item.get("name"):
                    out[str(item["name"])] = item.get("value", "")
            return out
        # Bentuk langsung {name: value}.
        return {str(k): v for k, v in kp.items() if k != "parameters"}
    raw = spec.get(json_key)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return {str(k): v for k, v in parsed.items()}
        except Exception:  # noqa: BLE001 - JSON rusak -> tanpa parameter
            return {}
    return {}


def destinations_from_env(
        env: dict | None = None,
        *,
        transport: Callable[[dict], bool] | None = None,
        clock: Callable[[], float] | None = None) -> list[Destination]:
    """Baca `KATALIR_LOG_STREAMING_DESTINATIONS` (pola n8n-MANAGED_BY_ENV).

    Format: JSON array berisi objek tujuan. Bila `MANAGED_BY_ENV` tidak
    `true`, kembalikan daftar kosong (UI/DB yang jadi sumber kebenaran).
    """
    src = env if env is not None else os.environ
    managed = str(src.get("KATALIR_LOG_STREAMING_MANAGED_BY_ENV",
                          "false")).strip().lower()
    if managed not in ("true", "1", "yes"):
        return []
    raw = (src.get("KATALIR_LOG_STREAMING_DESTINATIONS") or "").strip()
    if not raw:
        return []
    try:
        specs = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise DestinationError(f"destinations JSON tidak sah: {exc}") from exc
    if not isinstance(specs, list):
        raise DestinationError("destinations harus JSON array")
    out: list[Destination] = []
    for spec in specs:
        try:
            out.append(build_destination(spec, transport=transport, clock=clock))
        except DestinationError as exc:
            # Satu tujuan cacat tidak boleh membatalkan yang lain.
            print(f"[log_streaming] tujuan dilewati: {exc}")
    return out


# ---------------------------------------------------------------------------
# Event bus + spool durable
# ---------------------------------------------------------------------------
def _default_hostname() -> str:
    """Hostname untuk header syslog (FQDN-ish; fallback "-" bila tak diketahui)."""
    try:
        return socket.gethostname() or "-"
    except Exception:  # noqa: BLE001
        return "-"


def make_event(event: str, *, data: dict | None = None, level: str = "info",
               user_id: str = "", workflow_id: str = "",
               execution_id: str = "", extra: dict | None = None) -> dict:
    """Bangun event terstruktur (bentuk yang dikirim ke tujuan)."""
    lvl = str(level or "info").lower()
    if lvl == "warning":
        lvl = "warn"
    if lvl not in LOG_LEVELS:
        lvl = "info"
    return {
        "event": str(event),
        "group": event_group(event),
        "level": lvl,
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
        "event_id": f"{int(time.time() * 1000)}-{os.urandom(4).hex()}",
        "host": _default_hostname(),
        "user_id": str(user_id or ""),
        "workflow_id": str(workflow_id or ""),
        "execution_id": str(execution_id or ""),
        "data": dict(data or {}),
        **(dict(extra or {})),
    }


class EventBus:
    """Bus event dengan spool durable + fan-out ke semua tujuan.

    Kontrak penting (mengikuti n8n):
      * `emit()` MENCATAT event ke spool **lebih dulu**; pengiriman dilakukan
        setelahnya. Kegagalan tujuan tidak menghilangkan event.
      * `flush()` mencoba mengirim ulang event spool yang belum terkirim —
        inilah "re-emit setelah restart" milik n8n.
      * Spool dibatasi (`max_spool`) supaya tidak tumbuh tanpa batas.
    """

    def __init__(self, destinations: Iterable[Destination] | None = None,
                 spool_path: str = "", max_spool: int = 10_000,
                 clock: Callable[[], float] | None = None):
        self.destinations: list[Destination] = list(destinations or [])
        self.max_spool = max(1, int(max_spool))
        self.spool_path = spool_path or ""
        self._clock = clock or time.time
        self._lock = threading.Lock()
        #: Event yang belum terkirim ke SEMUA tujuan yang berlangganan.
        self._spool: list[dict] = []
        self.emitted = 0
        self.delivered = 0
        if self.spool_path:
            self._load_spool()

    # -- tujuan ------------------------------------------------------------
    def add(self, dest: Destination) -> Destination:
        with self._lock:
            self.destinations.append(dest)
        return dest

    def remove(self, label: str) -> bool:
        with self._lock:
            before = len(self.destinations)
            self.destinations = [d for d in self.destinations
                                 if d.label != label]
            return len(self.destinations) != before

    # -- spool -------------------------------------------------------------
    def _load_spool(self) -> None:
        try:
            with open(self.spool_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        self._spool.append(json.loads(line))
                    except Exception:  # noqa: BLE001 - baris rusak dilewati
                        continue
        except FileNotFoundError:
            pass
        except Exception as exc:  # noqa: BLE001
            print(f"[log_streaming] spool tidak bisa dibaca: {exc}")

    def _append_spool(self, event: dict) -> None:
        self._spool.append(event)
        if len(self._spool) > self.max_spool:
            self._spool = self._spool[-self.max_spool:]
            if self.spool_path:
                self._persist_spool()
        elif self.spool_path:
            try:
                with open(self.spool_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event, default=str) + "\n")
            except Exception as exc:  # noqa: BLE001
                print(f"[log_streaming] spool tidak bisa ditulis: {exc}")

    def _persist_spool(self) -> None:
        if not self.spool_path:
            return
        try:
            with open(self.spool_path, "w", encoding="utf-8") as fh:
                for ev in self._spool:
                    fh.write(json.dumps(ev, default=str) + "\n")
        except Exception as exc:  # noqa: BLE001
            print(f"[log_streaming] spool tidak bisa di-flush: {exc}")

    def spool_size(self) -> int:
        with self._lock:
            return len(self._spool)

    # -- emit --------------------------------------------------------------
    def emit(self, event: dict) -> dict:
        """Catat + teruskan satu event. Return ringkasan per tujuan."""
        with self._lock:
            self.emitted += 1
            if self.destinations:
                self._append_spool(event)
            dests = list(self.destinations)
        hasil: dict[str, bool] = {}
        semua_ok = True
        for d in dests:
            if not d.accepts(str(event.get("event", ""))):
                continue
            ok = d.send(event)
            hasil[d.label] = ok
            semua_ok = semua_ok and ok
            if ok:
                self.delivered += 1
        if semua_ok:
            with self._lock:
                if self._spool and self._spool[-1].get("event_id") == \
                        event.get("event_id"):
                    self._spool.pop()
        return hasil

    def emit_event(self, event: str, **kw) -> dict:
        """Racikan ringkas: bangun lalu `emit`."""
        return self.emit(make_event(event, **kw))

    def flush(self, limit: int = 500) -> dict:
        """Kirim ulang event spool yang gagal (perilaku re-emit n8n)."""
        with self._lock:
            pending = list(self._spool[:max(1, int(limit))])
        terkirim = 0
        sisa: list[dict] = []
        for ev in pending:
            ok_all = True
            ada = False
            for d in self.destinations:
                if not d.accepts(str(ev.get("event", ""))):
                    continue
                ada = True
                if not d.send(ev):
                    ok_all = False
            if ok_all:
                terkirim += 1
            else:
                sisa.append(ev)
        with self._lock:
            failed = pending[len(pending) - len(sisa):] if sisa else []
            self._spool = failed + self._spool[len(pending):]
            if self.spool_path:
                self._persist_spool()
            return {"attempted": len(pending), "delivered": terkirim,
                    "remaining": len(self._spool), "had_destination": bool(
                        self.destinations)}

    # -- observabilitas ----------------------------------------------------
    def stats(self) -> dict:
        with self._lock:
            return {"emitted": self.emitted, "delivered": self.delivered,
                    "spool_size": len(self._spool),
                    "max_spool": self.max_spool,
                    "spool_path": self.spool_path,
                    "destinations": [d.stats() for d in self.destinations]}


#: Bus proses-wide (dipakai aplikasi). Test memakai instans sendiri.
_BUS: EventBus | None = None

#: Bus per-pemilik. Tujuan streaming disimpan per-user di DB, jadi tiap
#: user perlu bus sendiri; bus tunggal proses-wide akan membocorkan
#: event antar-penyewa. Kunci = id pemilik, nilai = (bus, waktu_buat).
_BUS_BY_OWNER: dict[str, tuple[EventBus, float]] = {}

#: Umur maksimum cache bus per-pemilik (detik) sebelum dibangun ulang dari
#: konfigurasi tersimpan — perubahan tujuan langsung terpakai tanpa restart.
OWNER_BUS_TTL = 15.0


def bus() -> EventBus:
    global _BUS
    if _BUS is None:
        _BUS = EventBus(destinations=destinations_from_env())
    return _BUS


def set_bus(new_bus: EventBus | None) -> None:
    global _BUS
    _BUS = new_bus


def owner_bus(owner_id: str, factory, *, ttl: float = OWNER_BUS_TTL,
              now: float | None = None) -> EventBus:
    """Bus milik `owner_id`, dibangun lewat `factory(owner_id)` bila basi.

    `factory` dipanggil HANYA saat cache kosong/kedaluwarsa, jadi
    pembacaan DB tidak terjadi pada tiap event.
    """
    import time as _time
    ts = _time.time() if now is None else now
    hit = _BUS_BY_OWNER.get(str(owner_id))
    if hit is not None and (ts - hit[1]) < ttl:
        return hit[0]
    b = factory(str(owner_id))
    _BUS_BY_OWNER[str(owner_id)] = (b, ts)
    return b


def invalidate_owner_bus(owner_id: str | None = None) -> None:
    """Buang cache bus satu pemilik (atau semua bila None)."""
    if owner_id is None:
        _BUS_BY_OWNER.clear()
    else:
        _BUS_BY_OWNER.pop(str(owner_id), None)


# ---------------------------------------------------------------------------
# Jembatan ke Table/hitl/queue dsb. — pemancar kejadian aplikasi
# ---------------------------------------------------------------------------
#: Nama event Katalir -> nama event n8n (agar SIEM yang sudah ada cocok).
BRIDGE_MAP = {
    "workflow_started": "n8n.workflow.started",
    "workflow_success": "n8n.workflow.success",
    "workflow_failed": "n8n.workflow.failed",
    "workflow_cancelled": "n8n.workflow.cancelled",
    "node_started": "n8n.node.started",
    "node_finished": "n8n.node.finished",
    "user_login_success": "n8n.audit.user.login.success",
    "user_login_failed": "n8n.audit.user.login.failed",
    "credential_created": "n8n.audit.user.credentials.created",
    "credential_updated": "n8n.audit.user.credentials.updated",
    "credential_deleted": "n8n.audit.user.credentials.deleted",
    "mfa_enabled": "n8n.audit.twofa.enabled",
    "mfa_disabled": "n8n.audit.twofa.disabled",
    "execution_deleted": "n8n.audit.execution.deleted",
    "execution_data_revealed": "n8n.audit.execution.data.revealed",
    "execution_data_reveal_failed": "n8n.audit.execution.data.reveal_failure",
    "queue_job_enqueued": "n8n.queue.job.enqueued",
    "queue_job_completed": "n8n.queue.job.completed",
    "queue_job_failed": "n8n.queue.job.failed",
}


def stream(kind: str, *, level: str = "info", **kw) -> dict:
    """Pemancar ramah-pemanggil: `stream("workflow_success", workflow_id=...)`.

    Nama yang tidak ada di `BRIDGE_MAP` dilewatkan apa adanya bila sudah
    berprefiks `n8n.`, selain itu dianggap nama event kustom Katalir.
    """
    name = BRIDGE_MAP.get(kind, kind)
    try:
        return bus().emit_event(name, level=level, **kw)
    except Exception as exc:  # noqa: BLE001 - streaming tidak boleh mematikan app
        print(f"[log_streaming] emit '{kind}' gagal: {exc}")
        return {}


def destination_from_config(spec: dict, **kw) -> Destination:
    """Alias publik untuk `build_destination` (dipakai API)."""
    return build_destination(spec, **kw)


__all__ = [
    "EVENT_GROUPS", "EVENTS", "LOG_LEVELS", "BRIDGE_MAP",
    "DestinationError", "Destination", "WebhookDestination",
    "SyslogDestination", "SentryDestination", "CircuitBreaker", "EventBus",
    "all_event_names", "event_group", "event_matches", "make_event",
    "format_rfc5424", "sentry_dsn_parts", "build_destination",
    "destination_from_config", "destinations_from_env", "bus", "set_bus",
    "owner_bus", "invalidate_owner_bus", "OWNER_BUS_TTL", "stream",
]
