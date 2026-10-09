"""tracing.py — Fitur #8: Distributed tracing (OpenTelemetry / LangSmith).

Menghasilkan *span* OpenTelemetry asli dan mengekspornya lewat **OTLP/HTTP
dengan encoding Protobuf** (sesuai perilaku n8n), tanpa dependensi SDK
OpenTelemetry — encoder protobuf ditulis tangan di sini supaya citra
produksi tetap ringan dan tes tetap deterministik.

RISET (Okt 2026):
  - n8n 2.19.0 (Preview) memancarkan dua span per eksekusi:
    `workflow.execute` (root) + `node.execute` (anak, satu per node).
    Sejak 2.33.0 ada span agen `gen_ai.*`; sejak 2.42.0 ada span
    eksekusi "crashed". Sumber:
    https://docs.n8n.io/deploy/host-n8n/keep-n8n-running/trace-executions-with-opentelemetry
  - Atribut resource: `service.name` (default `n8n`), `service.version`,
    `n8n.instance.id`, `n8n.instance.role`.
  - Propagasi konteks W3C `traceparent`; endpoint OTLP adalah BASE URL
    (exporter menambahkan `/v1/traces` sendiri).
  - LangSmith menerima OTLP di `https://api.smith.langchain.com/otel`
    dengan header `x-api-key`, dan `Langsmith-Project` untuk menamai
    proyek. Sumber: https://docs.langchain.com/langsmith/trace-with-opentelemetry
  - Format `traceparent`: `00-<32hex trace-id>-<16hex span-id>-<2hex flags>`;
    semua-nol = tidak sah. Sumber: https://www.w3.org/TR/trace-context/

Pola transport DISUNTIK (`Callable[[bytes, dict], tuple[int, str]]`) supaya
test menjalankan pengkodean protobuf nyata tanpa jaringan; produksi memakai
`urllib` (stdlib).
"""

from __future__ import annotations

import json
import os
import random
import re
import struct
import threading
import time
import urllib.request
import uuid
from typing import Any, Callable, Iterable, Optional

# ---------------------------------------------------------------------------
# Konstanta
# ---------------------------------------------------------------------------

#: Nama span sesuai n8n.
SPAN_WORKFLOW = "workflow.execute"
SPAN_NODE = "node.execute"

#: Nilai default resource (menyamai n8n).
DEFAULT_SERVICE_NAME = "n8n"
#: Jenis sinyal/span kind OTLP (3 = SPAN_KIND_CLIENT, 5 = INTERNAL).
SPAN_KIND_INTERNAL = 1
SPAN_KIND_SERVER = 2
SPAN_KIND_CLIENT = 3

#: Kode status OTLP.
STATUS_UNSET = 0
STATUS_OK = 1
STATUS_ERROR = 2

#: Batas ukuran (proteksi memori).
MAX_ATTRIBUTES = 128
MAX_ATTRIBUTE_LEN = 8192
MAX_SPANS_PER_BATCH = 512
MAX_SPOOL = 10_000
DEFAULT_TIMEOUT_SEC = 5.0

#: Rasio sampling default (1.0 = semua trace).
DEFAULT_SAMPLE_RATE = 1.0

#: Protokol ekspor.
DEFAULT_PROTOCOL = "http/protobuf"
SUPPORTED_PROTOCOLS = ("http/protobuf", "grpc")

#: Jalur yang ditambahkan exporter bila `endpoint` adalah base URL.
TRACES_PATH = "/v1/traces"

#: Preset backend (base URL + nama header auth).
BACKEND_PRESETS = {
    "langsmith": {"endpoint": "https://api.smith.langchain.com/otel",
                  "auth_header": "x-api-key",
                  "extra_headers": {"Langsmith-Project": "katalir"}},
    "jaeger": {"endpoint": "http://localhost:4318", "auth_header": ""},
    "grafana": {"endpoint": "http://localhost:4318", "auth_header": ""},
    "honeycomb": {"endpoint": "https://api.honeycomb.io",
                  "auth_header": "x-honeycomb-team"},
    "otlp": {"endpoint": "http://localhost:4318", "auth_header": ""},
}

_TRACEPARENT_RE = re.compile(
    r"^(?P<version>[0-9a-f]{2})-(?P<trace>[0-9a-f]{32})-"
    r"(?P<span>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})(?:-.*)?$")
_ALL_ZERO = re.compile(r"^0+$")


class TracingError(RuntimeError):
    """Konfigurasi tracing tidak sah."""


# ---------------------------------------------------------------------------
# ID + konteks trace (W3C Trace Context)
# ---------------------------------------------------------------------------

def new_trace_id() -> str:
    """32 hex char (16 byte), tidak pernah semua-nol."""
    while True:
        v = uuid.uuid4().hex
        if not _ALL_ZERO.match(v):
            return v


def new_span_id() -> str:
    """16 hex char (8 byte), tidak pernah semua-nol."""
    while True:
        v = os.urandom(8).hex()
        if not _ALL_ZERO.match(v):
            return v


def is_valid_traceparent(value: str) -> bool:
    """True bila `traceparent` sah menurut W3C Trace Context §3.2."""
    if not value or not isinstance(value, str):
        return False
    m = _TRACEPARENT_RE.match(value.strip().lower())
    if not m:
        return False
    if m.group("version") == "ff":            # versi ff dilarang
        return False
    if _ALL_ZERO.match(m.group("trace")):     # trace-id nol tidak sah
        return False
    if _ALL_ZERO.match(m.group("span")):      # parent-id nol tidak sah
        return False
    return True


def parse_traceparent(value: str) -> dict | None:
    """urai `traceparent` menjadi {trace_id, span_id, sampled}; None bila sah-sah saja."""
    if not is_valid_traceparent(value):
        return None
    m = _TRACEPARENT_RE.match(value.strip().lower())
    assert m is not None
    flags = int(m.group("flags"), 16)
    return {"trace_id": m.group("trace"), "span_id": m.group("span"),
            "sampled": bool(flags & 0x01), "flags": flags}


def format_traceparent(trace_id: str, span_id: str, *, sampled: bool = True) -> str:
    """Rakit header `traceparent` versi 00."""
    if not re.fullmatch(r"[0-9a-f]{32}", trace_id or ""):
        raise TracingError(f"trace_id tidak sah: {trace_id!r}")
    if not re.fullmatch(r"[0-9a-f]{16}", span_id or ""):
        raise TracingError(f"span_id tidak sah: {span_id!r}")
    return f"00-{trace_id}-{span_id}-{'01' if sampled else '00'}"


# ---------------------------------------------------------------------------
# Atribut + pengkodean protobuf (OTLP TraceService)
# ---------------------------------------------------------------------------
#
# Protobuf ditulis tangan: hanya field yang dibutuhkan OTLP traces.
# Skema acuan: opentelemetry-proto/opentelemetry/proto/trace/v1/trace.proto
# dan .../common/v1/common.proto, .../resource/v1/resource.proto.

def _varint(n: int) -> bytes:
    """Encode varint protobuf."""
    if n < 0:
        n += 1 << 64
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _tag(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def _len_field(field: int, payload: bytes) -> bytes:
    return _tag(field, 2) + _varint(len(payload)) + payload


def _str_field(field: int, value: str) -> bytes:
    return _len_field(field, value.encode("utf-8"))


def _varint_field(field: int, value: int) -> bytes:
    return _tag(field, 0) + _varint(value)


def _fixed64_field(field: int, value: int) -> bytes:
    return _tag(field, 1) + struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF)


def encode_any_value(value: Any) -> bytes:
    """`opentelemetry.proto.common.v1.AnyValue` (string/bool/int/double/array)."""
    if isinstance(value, bool):
        return _varint_field(2, 1 if value else 0)
    if isinstance(value, int):
        return _varint_field(3, value)
    if isinstance(value, float):
        return _tag(4, 1) + struct.pack("<d", value)
    if isinstance(value, (list, tuple)):
        items = b"".join(_len_field(1, encode_any_value(v)) for v in value)
        return _len_field(5, items)
    text = str(value)
    if len(text) > MAX_ATTRIBUTE_LEN:
        text = text[:MAX_ATTRIBUTE_LEN]
    return _str_field(1, text)


def encode_key_value(key: str, value: Any) -> bytes:
    """`opentelemetry.proto.common.v1.KeyValue`."""
    return _str_field(1, key) + _len_field(2, encode_any_value(value))


def encode_attributes(attrs: dict) -> bytes:
    """Urutkan kunci supaya keluaran stabil/deterministik."""
    out = bytearray()
    for i, (k, v) in enumerate(sorted(attrs.items())):
        if i >= MAX_ATTRIBUTES:
            break
        out += _len_field(11, encode_key_value(str(k), v))
    return bytes(out)


def encode_resource(attrs: dict) -> bytes:
    """`opentelemetry.proto.resource.v1.Resource`."""
    out = bytearray()
    for k, v in sorted(attrs.items()):
        out += _len_field(1, encode_key_value(str(k), v))
    return bytes(out)


def encode_span(span: "Span") -> bytes:
    """`opentelemetry.proto.trace.v1.Span`."""
    out = bytearray()
    out += _len_field(1, bytes.fromhex(span.trace_id))        # trace_id
    out += _len_field(2, bytes.fromhex(span.span_id))         # span_id
    if span.parent_span_id:
        out += _len_field(4, bytes.fromhex(span.parent_span_id))
    if span.name:
        out += _str_field(5, span.name)
    out += _varint_field(6, span.kind)
    out += _fixed64_field(7, int(span.start_ns))              # start_time_unix_nano
    out += _fixed64_field(8, int(span.end_ns))                # end_time_unix_nano
    for k, v in sorted(span.attributes.items()):              # attributes
        out += _len_field(9, encode_key_value(str(k), v))
    for link in span.links:                                   # links
        lk = bytearray()
        lk += _len_field(1, bytes.fromhex(link["trace_id"]))
        lk += _len_field(2, bytes.fromhex(link["span_id"]))
        if link.get("reason"):
            lk += _len_field(4, encode_attributes(
                {"n8n.continuation.reason": link["reason"]}))
        out += _len_field(13, bytes(lk))
    if span.status_code:
        out += _len_field(15, _varint_field(3, span.status_code))
    return bytes(out)


def encode_scope_spans(spans: list["Span"], *, scope_name: str,
                       scope_version: str) -> bytes:
    """`ScopeSpans`."""
    out = bytearray()
    scope = _str_field(1, scope_name) + _str_field(2, scope_version)
    out += _len_field(1, scope)
    for s in spans:
        out += _len_field(2, encode_span(s))
    if spans:
        out += _str_field(3, scope_name)   # schema_url (informatif)
    return bytes(out)


def encode_resource_spans(spans: list["Span"], resource_attrs: dict, *,
                          scope_name: str, scope_version: str) -> bytes:
    """`ResourceSpans`."""
    return (_len_field(1, encode_resource(resource_attrs))
            + _len_field(2, encode_scope_spans(
                spans, scope_name=scope_name, scope_version=scope_version)))


def encode_export_request(spans: list["Span"], resource_attrs: dict, *,
                          scope_name: str = "katalir.tracing",
                          scope_version: str = "1.0.0") -> bytes:
    """`ExportTraceServiceRequest` — payload protobuf OTLP/HTTP.

    Dikelompokkan per resource (biasanya satu) lalu per trace, supaya
    backend dapat merakit trace dengan benar.
    """
    if not spans:
        return b""
    by_trace: dict[str, list["Span"]] = {}
    for s in spans:
        by_trace.setdefault(s.trace_id, []).append(s)
    out = bytearray()
    for _, group in sorted(by_trace.items()):
        out += _len_field(
            1, encode_resource_spans(group, resource_attrs,
                                     scope_name=scope_name,
                                     scope_version=scope_version))
    return bytes(out)


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

class Sampler:
    """Trace-id ratio sampler (keluarga sama => keputusan sama)."""

    def __init__(self, rate: float = DEFAULT_SAMPLE_RATE) -> None:
        try:
            r = float(rate)
        except (TypeError, ValueError):
            raise TracingError(f"sample rate tidak sah: {rate!r}")
        if not 0.0 <= r <= 1.0:
            raise TracingError(f"sample rate di luar 0..1: {r}")
        self.rate = r

    def should_sample(self, trace_id: str) -> bool:
        if self.rate >= 1.0:
            return True
        if self.rate <= 0.0:
            return False
        # Ambil 16 hex pertama (64 bit acak penuh; bit versi/variant UUID ada
        # di tengah string, sehingga awal string tetap seragam).
        frac = int(trace_id[:16], 16) / float(1 << 64)
        return frac < self.rate


DEFAULT_SAMPLER = Sampler()


# ---------------------------------------------------------------------------
# Span
# ---------------------------------------------------------------------------

class Span:
    """Satu span OpenTelemetry (mutable selama belum diakhiri)."""

    __slots__ = ("name", "trace_id", "span_id", "parent_span_id", "kind",
                 "start_ns", "end_ns", "attributes", "links",
                 "status_code", "status_message", "_ended", "events")

    def __init__(self, name: str, *, trace_id: str, span_id: str,
                 parent_span_id: str = "",
                 kind: int = SPAN_KIND_INTERNAL,
                 start_ns: int | None = None) -> None:
        self.name = name
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.kind = kind
        self.start_ns = int(start_ns if start_ns is not None else time.time_ns())
        self.end_ns = 0
        self.attributes: dict[str, Any] = {}
        self.links: list[dict] = []
        self.status_code = STATUS_UNSET
        self.status_message = ""
        self.events: list[dict] = []
        self._ended = False

    # -- builder -----------------------------------------------------------
    def set_attribute(self, key: str, value: Any) -> "Span":
        if len(self.attributes) < MAX_ATTRIBUTES:
            self.attributes[str(key)] = value
        return self

    def set_attributes(self, mapping: dict) -> "Span":
        for k, v in (mapping or {}).items():
            self.set_attribute(k, v)
        return self

    def add_link(self, trace_id: str, span_id: str, reason: str = "") -> "Span":
        self.links.append({"trace_id": trace_id, "span_id": span_id,
                           "reason": reason})
        return self

    def record_exception(self, exc: BaseException) -> "Span":
        """Event exception sesuai konvensi OpenTelemetry."""
        self.attributes.setdefault("exception.type", type(exc).__name__)
        self.attributes.setdefault("exception.message", str(exc))
        self.status_code = STATUS_ERROR
        self.status_message = f"{type(exc).__name__}: {exc}"
        self.events.append({"name": "exception", "type": type(exc).__name__,
                            "message": str(exc)})
        return self

    def set_ok(self) -> "Span":
        if self.status_code != STATUS_ERROR:
            self.status_code = STATUS_OK
        return self

    def end(self, *, end_ns: int | None = None) -> "Span":
        if not self._ended:
            self.end_ns = int(end_ns if end_ns is not None
                              else time.time_ns())
            if self.end_ns < self.start_ns:
                self.end_ns = self.start_ns
            self._ended = True
        return self

    @property
    def ended(self) -> bool:
        return self._ended

    @property
    def duration_ms(self) -> float:
        end = self.end_ns or time.time_ns()
        return max(0.0, (end - self.start_ns) / 1e6)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id or None,
            "kind": self.kind, "start_ns": self.start_ns,
            "end_ns": self.end_ns,
            "duration_ms": round(self.duration_ms, 3),
            "status": self.status_code,
            "status_message": self.status_message,
            "attributes": dict(self.attributes),
            "links": list(self.links),
            "ended": self._ended,
        }


# ---------------------------------------------------------------------------
# Resource (identitas instance)
# ---------------------------------------------------------------------------

def instance_id() -> str:
    """ID instance stabil lintas panggilan (dari env atau digenerate sekali)."""
    global _INSTANCE_ID
    if _INSTANCE_ID is None:
        _INSTANCE_ID = (os.environ.get("KATALIR_INSTANCE_ID") or "").strip() \
            or new_span_id() + new_span_id()
    return _INSTANCE_ID


_INSTANCE_ID: str | None = None


def resource_attributes(*, service_name: str = DEFAULT_SERVICE_NAME,
                        service_version: str = "",
                        instance_role: str = "") -> dict:
    """Atribut resource sesuai n8n (`n8n.instance.id`, `n8n.instance.role`)."""
    return {
        "service.name": service_name or DEFAULT_SERVICE_NAME,
        "service.version": service_version or "unknown",
        "n8n.instance.id": instance_id(),
        "n8n.instance.role": instance_role or "main",
    }


# ---------------------------------------------------------------------------
# Eksportir OTLP
# ---------------------------------------------------------------------------

def build_headers(raw: str) -> dict:
    """Ubah `k1=v1,k2=v2` menjadi dict header."""
    out: dict[str, str] = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise TracingError(f"header OTLP tidak sah (butuh k=v): {part!r}")
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        if k:
            out[k] = v
    return out


def traces_url(endpoint: str, *, path: str = TRACES_PATH) -> str:
    """Rakit URL /v1/traces dari BASE URL (jangan dobel path)."""
    ep = (endpoint or "").strip().rstrip("/")
    if not ep:
        raise TracingError("endpoint OTLP kosong.")
    if not re.match(r"^https?://", ep, re.IGNORECASE):
        raise TracingError(f"endpoint OTLP harus http:// atau https://: {endpoint!r}")
    if ep.endswith(path):
        return ep          # sudah menyertakan path (per-signal endpoint)
    return ep + path


class OTLPExporter:
    """Eksportir OTLP/HTTP (+protobuf). Transport dapat disuntik untuk tes."""

    def __init__(self, endpoint: str = "", *, headers: dict | None = None,
                 protocol: str = DEFAULT_PROTOCOL,
                 timeout: float = DEFAULT_TIMEOUT_SEC,
                 transport: Callable[[str, bytes, dict], tuple[int, str]] | None = None,
                 path: str = TRACES_PATH,
                 service_name: str = DEFAULT_SERVICE_NAME,
                 service_version: str = "",
                 instance_role: str = "") -> None:
        proto = (protocol or DEFAULT_PROTOCOL).strip()
        if proto not in SUPPORTED_PROTOCOLS:
            raise TracingError(
                f"protokol tidak didukung: {proto!r} "
                f"(pilih {', '.join(SUPPORTED_PROTOCOLS)})")
        self.protocol = proto
        self.endpoint = (endpoint or "").strip()
        self.path = path
        self.headers = dict(headers or {})
        self.timeout = float(timeout)
        self.transport = transport
        self.service_name = service_name or DEFAULT_SERVICE_NAME
        self.service_version = service_version or "unknown"
        self.instance_role = instance_role or "main"
        # grpc: n8n mengabaikan Trace path dan mewajibkan port eksplisit.
        self.url = ""
        if self.endpoint:
            if proto == "grpc":
                self.url = self.endpoint.rstrip("/")
            else:
                self.url = traces_url(self.endpoint, path=self.path)
        self.sent = 0
        self.failed = 0
        self.last_error = ""
        self.last_status = 0
        self._lock = threading.Lock()

    def payload(self, spans: list[Span]) -> bytes:
        return encode_export_request(
            spans,
            resource_attributes(service_name=self.service_name,
                                service_version=self.service_version,
                                instance_role=self.instance_role))

    def export(self, spans: Iterable[Span]) -> bool:
        """Kirim span. True bila backend menerima (HTTP 2xx)."""
        batch = [s for s in spans if s.ended][:MAX_SPANS_PER_BATCH]
        if not batch:
            return True
        if not self.url:
            with self._lock:
                self.failed += 1
                self.last_error = "endpoint kosong (tracing tidak dikonfigurasi)"
            return False
        body = self.payload(batch)
        try:
            status, detail = self._send(body)
        except Exception as exc:  # noqa: BLE001 - kegagalan ekspor tidak fatal
            with self._lock:
                self.failed += 1
                self.last_error = f"{type(exc).__name__}: {exc}"
                self.last_status = 0
            return False
        ok = 200 <= int(status) < 300
        with self._lock:
            self.last_status = int(status)
            if ok:
                self.sent += len(batch)
                self.last_error = ""
            else:
                self.failed += len(batch)
                self.last_error = f"HTTP {status}: {str(detail)[:200]}"
        return ok

    def _send(self, body: bytes) -> tuple[int, str]:
        headers = dict(self.headers)
        headers.setdefault("Content-Type", "application/x-protobuf")
        if self.transport is not None:
            return self.transport(self.url, body, headers)
        req = urllib.request.Request(self.url, data=body, headers=headers,
                                     method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            return int(resp.status), resp.read(512).decode("utf-8", "replace")

    def stats(self) -> dict:
        return {"protocol": self.protocol, "endpoint": self.endpoint,
                "url": self.url, "headers": sorted(self.headers.keys()),
                "sent_spans": self.sent, "failed_spans": self.failed,
                "last_status": self.last_status,
                "last_error": self.last_error}


def exporter_from_env(env: dict | None = None, **kw) -> OTLPExporter:
    """Bangun eksportir dari variabel `N8N_OTEL_*` (kompatibel n8n).

    Urutan: `N8N_OTEL_*` lebih diutamakan, lalu `OTEL_EXPORTER_OTLP_*`.
    """
    e = env if env is not None else os.environ
    get = lambda *names: next((str(e[n]).strip() for n in names  # noqa: E731
                               if e.get(n)), "")
    endpoint = get("N8N_OTEL_EXPORTER_OTLP_ENDPOINT",
                   "OTEL_EXPORTER_OTLP_ENDPOINT")
    headers = build_headers(get("N8N_OTEL_EXPORTER_OTLP_HEADERS",
                                "OTEL_EXPORTER_OTLP_HEADERS"))
    protocol = get("N8N_OTEL_EXPORTER_OTLP_PROTOCOL",
                   "OTEL_EXPORTER_OTLP_PROTOCOL") or DEFAULT_PROTOCOL
    path = get("N8N_OTEL_EXPORTER_OTLP_TRACING_PATH",
               "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or TRACES_PATH
    # Per-signal endpoint dipakai apa adanya.
    if e.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") and not \
            e.get("N8N_OTEL_EXPORTER_OTLP_ENDPOINT"):
        endpoint = str(e["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"]).strip()
        return OTLPExporter(endpoint, headers=headers, protocol=protocol,
                            service_name=get("OTEL_SERVICE_NAME",
                                             "N8N_OTEL_SERVICE_NAME")
                            or DEFAULT_SERVICE_NAME,
                            service_version=get("N8N_OTEL_SERVICE_VERSION")
                            or "", instance_role=get("N8N_INSTANCE_ROLE")
                            or "main", path=TRACES_PATH, **kw)
    return OTLPExporter(endpoint, headers=headers, protocol=protocol,
                        path=path,
                        service_name=get("OTEL_SERVICE_NAME",
                                         "N8N_OTEL_SERVICE_NAME")
                        or DEFAULT_SERVICE_NAME,
                        service_version=get("N8N_OTEL_SERVICE_VERSION") or "",
                        instance_role=get("N8N_INSTANCE_ROLE") or "main", **kw)


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------

class Tracer:
    """Pembuat span + pengirim batch. Semua waktu dapat disuntik."""

    def __init__(self, *, exporter: OTLPExporter | None = None,
                 sampler: "Sampler | None" = None,
                 service_name: str = DEFAULT_SERVICE_NAME,
                 service_version: str = "",
                 instance_role: str = "",
                 clock: Callable[[], int] | None = None,
                 auto_flush: bool = True) -> None:
        self.exporter = exporter
        self.sampler = sampler or DEFAULT_SAMPLER
        self.service_name = service_name or DEFAULT_SERVICE_NAME
        self.service_version = service_version or "unknown"
        self.instance_role = instance_role or "main"
        self._clock = clock or time.time_ns
        self.auto_flush = auto_flush
        self._pending: list[Span] = []
        self._lock = threading.Lock()
        self.started = 0
        self.dropped_by_sampler = 0

    # -- pembuatan span ----------------------------------------------------
    def start_span(self, name: str, *, trace_id: str = "",
                   parent_span_id: str = "",
                   kind: int = SPAN_KIND_INTERNAL,
                   attributes: dict | None = None,
                   traceparent: str = "") -> Span:
        """Mulai span; bila `traceparent` sah, ia menjadi induk (propagasi W3C)."""
        sampled = True
        if traceparent:
            ctx = parse_traceparent(traceparent)
            if ctx:
                trace_id = ctx["trace_id"]
                parent_span_id = ctx["span_id"]
                sampled = ctx["sampled"] or True
        if not trace_id:
            trace_id = new_trace_id()
        if not sampled or not self.sampler.should_sample(trace_id):
            self.dropped_by_sampler += 1
        span = Span(name, trace_id=trace_id, span_id=new_span_id(),
                    parent_span_id=parent_span_id, kind=kind,
                    start_ns=self._clock())
        if attributes:
            span.set_attributes(attributes)
        return span

    # -- siklus hidup ------------------------------------------------------
    def finish(self, span: Span, *, export: bool = True) -> Span:
        span.end(end_ns=self._clock())
        if export:
            self.record(span)
        return span

    def record(self, span: Span) -> None:
        with self._lock:
            self._pending.append(span)
            self.started += 1

    def flush(self) -> dict:
        """Kirim semua span tertunda. Aman dipanggil kapan pun."""
        with self._lock:
            batch, self._pending = self._pending, []
        if not batch or self.exporter is None:
            return {"exported": 0, "ok": True, "pending": 0}
        ok = self.exporter.export(batch)
        if not ok:
            # Kembalikan ke antrean (kecuali melebihi batas) agar bisa diulang.
            with self._lock:
                room = max(0, MAX_SPOOL - len(self._pending))
                self._pending = (batch[-room:] if room else []) + self._pending
        return {"exported": len(batch) if ok else 0, "ok": ok,
                "pending": len(self._pending),
                "error": "" if ok else self.exporter.last_error}

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def stats(self) -> dict:
        return {"service_name": self.service_name,
                "service_version": self.service_version,
                "instance_role": self.instance_role,
                "instance_id": instance_id(),
                "sample_rate": self.sampler.rate,
                "auto_flush": self.auto_flush,
                "pending": self.pending_count(),
                "dropped_by_sampler": self.dropped_by_sampler,
                "exporter": self.exporter.stats() if self.exporter else None}


# ---------------------------------------------------------------------------
# Semantik workflow/node (n8n 2.19+)
# ---------------------------------------------------------------------------

#: Nama status eksekusi yang dikenali (menyamai n8n).
EXECUTION_MODES = ("manual", "webhook", "trigger", "retry", "internal",
                   "schedule", "chat", "agent")
EXECUTION_STATUSES = ("success", "error", "crashed", "cancelled", "running",
                      "waiting", "unknown")

#: Detektor crash n8n (2.42.0).
CRASH_DETECTORS = ("stall", "queue-recovery", "startup-recovery",
                   "start-failure", "workflow-deactivation")


def workflow_attributes(*, workflow_id: str = "", workflow_name: str = "",
                        version_id: str = "", node_count: int | None = None,
                        project_id: str = "", execution_id: str = "",
                        mode: str = "manual", status: str = "",
                        is_retry: bool = False, retry_of: str = "",
                        error_type: str = "",
                        custom: dict | None = None) -> dict:
    """Atribut span `workflow.execute` persis seperti tabel n8n."""
    attrs: dict[str, Any] = {}
    if workflow_id:
        attrs["n8n.workflow.id"] = workflow_id
    if workflow_name:
        attrs["n8n.workflow.name"] = workflow_name
    if version_id:
        attrs["n8n.workflow.version_id"] = version_id
    if node_count is not None:
        attrs["n8n.workflow.node_count"] = int(node_count)
    if project_id:
        attrs["n8n.project.id"] = project_id
    if execution_id:
        attrs["n8n.execution.id"] = execution_id
    if mode:
        attrs["n8n.execution.mode"] = mode
    if status:
        attrs["n8n.execution.status"] = status
    if is_retry:
        attrs["n8n.execution.is_retry"] = True
    if retry_of:
        attrs["n8n.execution.retry_of"] = retry_of
    if error_type:
        attrs["n8n.execution.error_type"] = error_type
    for k, v in (custom or {}).items():
        attrs[f"n8n.project.custom.{k}"] = v
    return attrs


def node_attributes(*, node_id: str = "", node_name: str = "",
                    node_type: str = "", type_version: Any = None,
                    items_input: int | None = None,
                    items_output: int | None = None,
                    termination_reason: str = "",
                    custom: dict | None = None,
                    prefix: str = "n8n.node.custom.") -> dict:
    """Atribut span `node.execute` persis seperti tabel n8n."""
    attrs: dict[str, Any] = {}
    if node_id:
        attrs["n8n.node.id"] = node_id
    if node_name:
        attrs["n8n.node.name"] = node_name
    if node_type:
        attrs["n8n.node.type"] = node_type
    if type_version is not None:
        attrs["n8n.node.type_version"] = type_version
    if items_input is not None:
        attrs["n8n.node.items.input"] = int(items_input)
    if items_output is not None:
        attrs["n8n.node.items.output"] = int(items_output)
    if termination_reason:
        attrs["n8n.node.termination_reason"] = termination_reason
    for k, v in (custom or {}).items():
        attrs[f"{prefix}{k}"] = v
    return attrs


def crashed_attributes(*, status: str = "crashed", error_type: str = "",
                       detector: str = "", reconstructed: bool = False,
                       extra: dict | None = None) -> dict:
    """Atribut span eksekusi yang crash (n8n 2.42.0)."""
    attrs = dict(extra or {})
    attrs["n8n.execution.status"] = status
    attrs["n8n.execution.error_type"] = error_type or "WorkflowCrashedError"
    if detector:
        if detector not in CRASH_DETECTORS:
            raise TracingError(
                f"detektor crash tidak dikenal: {detector!r} "
                f"(pilih {', '.join(CRASH_DETECTORS)})")
        attrs["n8n.execution.crash.detector"] = detector
    attrs["n8n.execution.reconstructed"] = bool(reconstructed)
    return attrs


def agent_attributes(*, agent_name: str = "", model: str = "",
                     conversation_id: str = "", agent_id: str = "",
                     project_id: str = "", source: str = "",
                     user_id: str = "", execution_id: str = "",
                     workflow_id: str = "", node_id: str = "",
                     prompt: Any = None, tool_count: int | None = None,
                     tool_catalog: Any = None, tool_name: str = "",
                     tool_call_id: str = "", tool_arguments: Any = None,
                     tool_result: Any = None, streaming: bool = False,
                     operation: str = "") -> dict:
    """Atribut span agen (`gen_ai.*`) / tool (`execute_tool`)."""
    if operation == "execute_tool" or tool_name:
        attrs: dict[str, Any] = {
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": tool_name,
        }
        if tool_call_id:
            attrs["gen_ai.tool.call.id"] = tool_call_id
        if agent_name:
            attrs["gen_ai.agent.name"] = agent_name
        if tool_arguments is not None:
            attrs["gen_ai.tool.call.arguments"] = tool_arguments
        if tool_result is not None:
            attrs["gen_ai.tool.call.result"] = tool_result
        return attrs
    attrs = {"gen_ai.operation.name": "invoke_agent"}
    if agent_name:
        attrs["gen_ai.agent.name"] = agent_name
    if model:
        attrs["gen_ai.request.model"] = model
    if conversation_id:
        attrs["gen_ai.conversation.id"] = conversation_id
    if prompt is not None or tool_count is not None or tool_catalog is not None:
        attrs["gen_ai.prompt"] = json.dumps(
            {"prompt": prompt, "tool_count": tool_count,
             "tool_catalog": tool_catalog}, ensure_ascii=False,
            default=str)[:MAX_ATTRIBUTE_LEN]
    if agent_id:
        attrs["agent_id"] = agent_id
    if project_id:
        attrs["project_id"] = project_id
    if conversation_id:
        attrs["thread_id"] = conversation_id
    if source:
        attrs["source"] = source
    if user_id:
        attrs["user_id"] = user_id
    if model:
        attrs["model_id"] = model
    if execution_id:
        attrs["execution_id"] = execution_id
    if workflow_id:
        attrs["workflow_id"] = workflow_id
    if node_id:
        attrs["node_id"] = node_id
    if operation == "stream" or streaming:
        attrs["_katalir.span_kind"] = "stream"
    return attrs


def agent_span_name(agent_name: str, *, streaming: bool = False) -> str:
    """`<agent name>.generate` atau `<agent name>.stream`."""
    return f"{agent_name}.{'stream' if streaming else 'generate'}"


def tool_span_name(tool_name: str) -> str:
    """`execute_tool <tool name>`."""
    return f"execute_tool {tool_name}"


# ---------------------------------------------------------------------------
# Instrumentasi tingkat-tinggi (orkestrasi eksekusi)
# ---------------------------------------------------------------------------

class ExecutionTrace:
    """Span root `workflow.execute` + span anak `node.execute`.

    Pemakaian:
        tr = start_execution(tracer, workflow_id=..., execution_id=...)
        with tr.node(node_id="n1", node_name="HTTP", node_type="httpRequest"):
            ...
        tr.finish(status="success")
    """

    def __init__(self, tracer: Tracer, *, span: Span,
                 record_inputs: bool = True, record_outputs: bool = True,
                 include_node_spans: bool = True) -> None:
        self.tracer = tracer
        self.span = span
        self.record_inputs = bool(record_inputs)
        self.record_outputs = bool(record_outputs)
        self.include_node_spans = bool(include_node_spans)
        self.node_spans: list[Span] = []
        self._open: list[Span] = []

    # -- root --------------------------------------------------------------
    @property
    def trace_id(self) -> str:
        return self.span.trace_id

    @property
    def traceparent(self) -> str:
        """Header untuk diteruskan ke layanan hilir (propagasi keluar)."""
        return format_traceparent(self.span.trace_id, self.span.span_id,
                                 sampled=self.tracer.sampler.should_sample(
                                     self.span.trace_id))

    def link_previous(self, trace_id: str, span_id: str,
                      reason: str = "wait_resume") -> "ExecutionTrace":
        """Span link saat workflow dilanjutkan setelah `wait` (perilaku n8n)."""
        self.span.add_link(trace_id, span_id, reason)
        return self

    def set_node_count(self, count: int) -> "ExecutionTrace":
        self.span.set_attribute("n8n.workflow.node_count", int(count))
        return self

    # -- node --------------------------------------------------------------
    def start_node(self, *, node_id: str = "", node_name: str = "",
                   node_type: str = "", type_version: Any = None,
                   attributes: dict | None = None,
                   custom: dict | None = None) -> Span:
        attrs = node_attributes(node_id=node_id, node_name=node_name,
                               node_type=node_type, type_version=type_version,
                               custom=custom)
        attrs.update(attributes or {})
        sp = self.tracer.start_span(
            SPAN_NODE, trace_id=self.span.trace_id,
            parent_span_id=self.span.span_id, kind=SPAN_KIND_INTERNAL,
            attributes=attrs)
        self._open.append(sp)
        return sp

    def finish_node(self, span: Span, *, items_input: int | None = None,
                    items_output: int | None = None,
                    termination_reason: str = "",
                    error: BaseException | None = None,
                    export: bool = True) -> Span:
        if items_input is not None:
            span.set_attribute("n8n.node.items.input", int(items_input))
        if items_output is not None:
            span.set_attribute("n8n.node.items.output", int(items_output))
        if termination_reason:
            span.set_attribute("n8n.node.termination_reason",
                               termination_reason)
        if error is not None:
            span.record_exception(error)
        elif termination_reason:
            span.status_code = STATUS_ERROR
        else:
            span.set_ok()
        self.tracer.finish(span, export=export and self.include_node_spans)
        self.node_spans.append(span)
        if span in self._open:
            self._open.remove(span)
        return span

    def node(self, **kw) -> "_NodeCtx":
        """Konteks `with` untuk satu node."""
        return _NodeCtx(self, kw)

    # -- akhir -------------------------------------------------------------
    def finish(self, *, status: str = "success",
               error: BaseException | None = None,
               error_type: str = "",
               termination_reason: str = "") -> Span:
        """Tutup node yang masih terbuka, lalu tutup span root."""
        for sp in list(self._open):
            self.finish_node(sp, termination_reason=termination_reason
                             or "workflow_ended")
        self.span.set_attribute("n8n.execution.status", status)
        if error is not None:
            self.span.record_exception(error)
        elif status in ("error", "crashed"):
            # n8n menulis nama kelas error di span yang gagal; bila pemanggil
            # tidak punya exception, pakai nama yang diberikan (atau default).
            self.span.set_attribute("n8n.execution.error_type",
                                    error_type or "WorkflowExecutionError")
            self.span.status_code = STATUS_ERROR
            self.span.status_message = error_type or "WorkflowExecutionError"
        else:
            self.span.set_ok()
        self.tracer.finish(self.span)
        if self.tracer.auto_flush:
            self.tracer.flush()
        return self.span


class _NodeCtx:
    """Manajer konteks untuk satu span node."""

    def __init__(self, trace: ExecutionTrace, kw: dict) -> None:
        self.trace = trace
        self.kw = dict(kw)
        self.span: Span | None = None

    def __enter__(self) -> Span:
        self.span = self.trace.start_node(**self.kw)
        return self.span

    def __exit__(self, exc_type, exc, tb) -> bool:
        assert self.span is not None
        self.trace.finish_node(
            self.span,
            items_input=self.kw.get("items_input"),
            items_output=self.kw.get("items_output"),
            error=exc if exc is not None else None)
        return False        # jangan telan exception


def start_execution(tracer: Tracer, *, workflow_id: str = "",
                    workflow_name: str = "", node_count: int | None = None,
                    project_id: str = "", execution_id: str = "",
                    mode: str = "manual", version_id: str = "",
                    is_retry: bool = False, retry_of: str = "",
                    traceparent: str = "", custom: dict | None = None,
                    record_inputs: bool = True,
                    record_outputs: bool = True,
                    include_node_spans: bool = True,
                    attributes: dict | None = None) -> ExecutionTrace:
    """Buat span root `workflow.execute` (menghormati `traceparent` masuk)."""
    attrs = workflow_attributes(
        workflow_id=workflow_id, workflow_name=workflow_name,
        version_id=version_id, node_count=node_count, project_id=project_id,
        execution_id=execution_id, mode=mode, is_retry=is_retry,
        retry_of=retry_of, custom=custom)
    attrs.update(attributes or {})
    span = tracer.start_span(SPAN_WORKFLOW, kind=SPAN_KIND_INTERNAL,
                            traceparent=traceparent, attributes=attrs)
    return ExecutionTrace(tracer, span=span, record_inputs=record_inputs,
                          record_outputs=record_outputs,
                          include_node_spans=include_node_spans)


def trace_crashed_execution(tracer: Tracer, *, workflow_id: str = "",
                            workflow_name: str = "", project_id: str = "",
                            execution_id: str = "", mode: str = "manual",
                            detector: str = "stall",
                            reconstructed: bool = False,
                            trace_id: str = "", parent_span_id: str = "",
                            version_id: str = "", is_retry: bool = False,
                            retry_of: str = "",
                            custom: dict | None = None) -> Span:
    """Pancarkan satu span `workflow.execute` untuk eksekusi crash (2.42.0).

    Atribut `n8n.workflow.node_count` sengaja TIDAK diisi bila span
    direkonstruksi (menyamai n8n: span hasil rekonstruksi tidak punya
    node_count dan tidak punya span node).
    """
    attrs = crashed_attributes(detector=detector,
                               reconstructed=reconstructed,
                               extra=workflow_attributes(
                                   workflow_id=workflow_id,
                                   workflow_name=workflow_name,
                                   version_id=version_id,
                                   project_id=project_id,
                                   execution_id=execution_id, mode=mode,
                                   is_retry=is_retry, retry_of=retry_of,
                                   custom=custom))
    span = tracer.start_span(SPAN_WORKFLOW, kind=SPAN_KIND_INTERNAL,
                            trace_id=trace_id, parent_span_id=parent_span_id,
                            attributes=attrs)
    span.status_code = STATUS_ERROR
    span.set_attribute("exception.type", "WorkflowCrashedError")
    span.end(end_ns=tracer._clock())
    tracer.record(span)
    if tracer.auto_flush:
        tracer.flush()
    return span


# ---------------------------------------------------------------------------
# Registry proses (dipakai API)
# ---------------------------------------------------------------------------

_TRACER: Tracer | None = None


def tracer() -> Tracer:
    """Tracer proses-tunggal, dibangun dari env pada pemakaian pertama."""
    global _TRACER
    if _TRACER is None:
        _TRACER = tracer_from_env()
    return _TRACER


def set_tracer(new: Tracer | None) -> None:
    global _TRACER
    _TRACER = new


def tracer_from_env(env: dict | None = None) -> Tracer:
    """Tracer dari env: `N8N_OTEL_ENABLED` sebagai gerbang utama."""
    e = env if env is not None else os.environ
    enabled = str(e.get("N8N_OTEL_ENABLED", "false")).strip().lower() \
        in ("true", "1", "yes")
    rate = e.get("N8N_OTEL_TRACES_SAMPLE_RATE")
    try:
        sampler = Sampler(float(rate)) if rate not in (None, "") else DEFAULT_SAMPLER
    except (TracingError, ValueError):
        sampler = DEFAULT_SAMPLER
    exporter = exporter_from_env(e) if enabled else None
    svc = str(e.get("N8N_OTEL_SERVICE_NAME")
              or e.get("OTEL_SERVICE_NAME") or DEFAULT_SERVICE_NAME)
    return Tracer(exporter=exporter, sampler=sampler,
                  service_name=svc,
                  service_version=str(e.get("N8N_OTEL_SERVICE_VERSION") or
                                      "unknown"),
                  instance_role=str(e.get("N8N_INSTANCE_ROLE") or "main"))


def enabled(env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get("N8N_OTEL_ENABLED", "false")).strip().lower() \
        in ("true", "1", "yes")


def production_only(env: dict | None = None) -> bool:
    """`N8N_OTEL_TRACES_PRODUCTION_ONLY` (default true, seperti n8n)."""
    e = env if env is not None else os.environ
    v = e.get("N8N_OTEL_TRACES_PRODUCTION_ONLY")
    if v is None or str(v).strip() == "":
        return True
    return str(v).strip().lower() not in ("false", "0", "no")


def include_node_spans(env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    v = e.get("N8N_OTEL_TRACES_INCLUDE_NODE_SPANS")
    if v is None or str(v).strip() == "":
        return True
    return str(v).strip().lower() not in ("false", "0", "no")


def inject_traceparent(env: dict | None = None) -> bool:
    """`N8N_OTEL_TRACES_INJECT_TRACEPARENT` (default true)."""
    e = env if env is not None else os.environ
    v = e.get("N8N_OTEL_TRACES_INJECT_TRACEPARENT")
    if v is None or str(v).strip() == "":
        return True
    return str(v).strip().lower() not in ("false", "0", "no")


def agents_tracing_enabled(env: dict | None = None) -> bool:
    """Span agen butuh DUA-duanya: `N8N_OTEL_ENABLED` + `N8N_AGENTS_TRACING_ENABLED`."""
    e = env if env is not None else os.environ
    if not enabled(e):
        return False
    return str(e.get("N8N_AGENTS_TRACING_ENABLED", "false")).strip().lower() \
        in ("true", "1", "yes")


def should_trace_mode(mode: str, env: dict | None = None) -> bool:
    """True bila mode eksekusi ini boleh dipancarkan (default: produksi saja)."""
    if not production_only(env):
        return True
    return str(mode or "").strip().lower() != "manual"


def trace_workflow(env: dict | None = None, **kw) -> ExecutionTrace | None:
    """Jalur cepat: mulai trace bila tracing aktif & mode diizinkan."""
    mode = str(kw.get("mode") or "manual")
    if not enabled(env) or not should_trace_mode(mode, env):
        return None
    include_nodes = include_node_spans(env)
    return start_execution(tracer(), include_node_spans=include_nodes, **kw)


def inject_into_headers(headers: dict, trace: ExecutionTrace | None,
                        env: dict | None = None) -> dict:
    """Sisipkan `traceparent` ke header keluar (propagasi W3C keluar)."""
    out = dict(headers or {})
    if trace is None or not inject_traceparent(env):
        return out
    out.setdefault("traceparent", trace.traceparent)
    return out


def describe(env: dict | None = None) -> dict:
    """Ringkasan konfigurasi (untuk UI/endpoint `/tracing/config`)."""
    e = env if env is not None else os.environ
    t = tracer_from_env(e)
    return {
        "enabled": enabled(e),
        "production_only": production_only(e),
        "include_node_spans": include_node_spans(e),
        "inject_traceparent": inject_traceparent(e),
        "agents_tracing_enabled": agents_tracing_enabled(e),
        "sample_rate": t.sampler.rate,
        "service_name": t.service_name,
        "service_version": t.service_version,
        "instance_role": t.instance_role,
        "instance_id": instance_id(),
        "endpoint": (t.exporter.endpoint if t.exporter else ""),
        "url": (t.exporter.url if t.exporter else ""),
        "protocol": (t.exporter.protocol if t.exporter else DEFAULT_PROTOCOL),
        "headers": (sorted(t.exporter.headers.keys()) if t.exporter else []),
        "backends": sorted(BACKEND_PRESETS.keys()),
        "span_names": {"workflow": SPAN_WORKFLOW, "node": SPAN_NODE},
        "execution_modes": list(EXECUTION_MODES),
        "execution_statuses": list(EXECUTION_STATUSES),
        "crash_detectors": list(CRASH_DETECTORS),
    }


def reset_stats() -> None:
    t = tracer()
    if t.exporter:
        t.exporter.sent = 0
        t.exporter.failed = 0
        t.exporter.last_error = ""
        t.exporter.last_status = 0
    with t._lock:                       # noqa: SLF001 - utilitas internal
        t._pending.clear()
        t.started = 0
        t.dropped_by_sampler = 0


__all__ = [
    "SPAN_WORKFLOW", "SPAN_NODE", "SPAN_KIND_INTERNAL", "SPAN_KIND_SERVER",
    "SPAN_KIND_CLIENT", "STATUS_UNSET", "STATUS_OK", "STATUS_ERROR",
    "DEFAULT_SERVICE_NAME", "DEFAULT_PROTOCOL", "SUPPORTED_PROTOCOLS",
    "TRACES_PATH", "BACKEND_PRESETS", "EXECUTION_MODES", "EXECUTION_STATUSES",
    "CRASH_DETECTORS", "MAX_SPANS_PER_BATCH", "MAX_SPOOL",
    "TracingError", "Sampler", "Span", "Tracer", "OTLPExporter",
    "ExecutionTrace", "new_trace_id", "new_span_id", "is_valid_traceparent",
    "parse_traceparent", "format_traceparent", "encode_any_value",
    "encode_key_value", "encode_attributes", "encode_resource", "encode_span",
    "encode_scope_spans", "encode_resource_spans", "encode_export_request",
    "workflow_attributes", "node_attributes", "crashed_attributes",
    "agent_attributes", "agent_span_name", "tool_span_name",
    "start_execution", "trace_crashed_execution", "resource_attributes",
    "instance_id", "build_headers", "traces_url", "exporter_from_env",
    "tracer", "set_tracer", "tracer_from_env", "enabled", "production_only",
    "include_node_spans", "inject_traceparent", "agents_tracing_enabled",
    "should_trace_mode", "trace_workflow", "inject_into_headers", "describe",
    "reset_stats",
]
