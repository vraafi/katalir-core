"""recovery.py — Fitur #3: Self-healing persistence & execution recovery.

Menutup celah n8n 2.42.0: eksekusi yang "crash" (instance mati tanpa menulis
hasil, mis. OOM-kill atau eviksi kontainer) harus **terdeteksi** dan
**dipulihkan**, bukan tertinggal menggantung sebagai `running` selamanya.

RISET (Okt 2026):
  * n8n mendeteksi crash lewat 5 cara (`stall`, `queue-recovery`,
    `startup-recovery`, `start-failure`, `workflow-deactivation`) dan
    memancarkan span/sinyal ber-atribut `n8n.execution.status=crashed`,
    `n8n.execution.error_type=WorkflowCrashedError`,
    `n8n.execution.crash.detector=<nilai>`, `n8n.execution.reconstructed`.
    Sumber: https://docs.n8n.io/deploy/host-n8n/keep-n8n-running/trace-executions-with-opentelemetry
  * n8n TIDAK melanjutkan dari titik tengah: worker yang mati -> eksekusi
    ditandai crash/error; bila dijalankan lagi, ia **mulai dari awal**
    (tidak ada checkpoint state memori lintas-proses). Maka sisi efek harus
    **idempoten**. Sumber:
    https://community.n8n.io/t/n8n-queue-mode-what-happens-to-a-job-when-a-worker-crashes-or-restarts/314416
  * Pola produksi: idempotency key + retry backoff + compensating action +
    DLQ + observabilitas. Deteksi "silent stall" butuh heartbeat/timeout,
    karena tidak ada error yang muncul. Sumber:
    https://www.aifloxium.online/blog/self-healing-n8n-workflows

Yang membedakan implementasi ini dari n8n: n8n **mendeteksi lalu berhenti**.
Di sini pemulihan bersifat **self-healing**: setelah diklasifikasi, supervisor
memutuskan aksi (restart idempoten / karantina / tandai crash) dan
melakukannya sendiri, dengan gerbang agar operasi tidak pernah terjadi dua kali.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

# ---------------------------------------------------------------------------
# Konstanta
# ---------------------------------------------------------------------------

#: 5 detektor crash, sama persis dengan n8n 2.42.0.
DETECTORS = ("stall", "queue-recovery", "startup-recovery", "start-failure",
             "workflow-deactivation")

#: Status eksekusi.
PENDING = "pending"
RUNNING = "running"
SUCCESS = "success"
ERROR = "error"
CRASHED = "crashed"
CANCELLED = "cancelled"
WAITING = "waiting"

TERMINAL = (SUCCESS, ERROR, CANCELLED)
NON_TERMINAL = (PENDING, RUNNING, WAITING)

#: Jenis keliru -> aksi pemulihan. Menyesuaikan "7 failure mode" dari riset:
#: 5xx/429/401 transien boleh diulang; 422 (data buruk) JANGAN diulang.
RETRYABLE_KINDS = ("transient", "rate_limit", "auth_expired", "timeout",
                   "network", "lock")
NON_RETRYABLE_KINDS = ("validation", "malformed", "permission", "not_found",
                       "conflict", "unknown")

#: Default waktu.
DEFAULT_HEARTBEAT_INTERVAL_SEC = 5.0
DEFAULT_STALL_TIMEOUT_SEC = 30.0
DEFAULT_VISIBILITY_TIMEOUT_SEC = 60.0
DEFAULT_MAX_ATTEMPTS = 3

#: Backoff eksponensial + full jitter (pola playbook produksi).
DEFAULT_BACKOFF_BASE_MS = 1_000
DEFAULT_BACKOFF_CAP_MS = 60_000


class RecoveryError(RuntimeError):
    """Operasi pemulihan tidak sah."""


# ---------------------------------------------------------------------------
# Pembuatan id deterministik (idempotensi)
# ---------------------------------------------------------------------------

def idempotency_key(*parts: Any) -> str:
    """Kunci SHA-256 deterministik dari bagian-bagian event.

    Dipakai supaya pemulihan (atau webhook ganda) tidak menjalankan efek
    samping dua kali — pola Layer 1 dari playbook produksi.
    """
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def recovery_key(execution_id: str, attempt: int) -> str:
    """Kunci per-eksekusi PER-ATTEMPT (bukan global, supaya retry tetap jalan)."""
    return idempotency_key("recovery", execution_id, attempt)


# ---------------------------------------------------------------------------
# Klasifikasi error
# ---------------------------------------------------------------------------

_STATUS_RX = re.compile(r"\b(4\d\d|5\d\d)\b")
_NETWORK_RX = re.compile(
    r"(connection\s+(refused|reset|aborted)|timed?\s*out|timeout|"
    r"getaddrinfo|name or service not known|temporary failure|"
    r"econn(reset|refused|abort)|etimedout|ssl|tls|unreachable|"
    r"network is unreachable|broken pipe|dns)", re.IGNORECASE)
_AUTH_RX = re.compile(
    r"(401|unauthoriz|invalid[_ ]token|token (expired|invalid)|"
    r"expired credential|authentication fail|access token|oauth)", re.IGNORECASE)
_RATE_RX = re.compile(r"(429|rate[ _-]?limit|too many requests|quota|"
                      r"throttl)", re.IGNORECASE)
_VALIDATION_RX = re.compile(
    r"(422|400|validation|invalid (input|payload|json|field)|"
    r"schema|cannot parse|malformed|unprocessable)", re.IGNORECASE)
_NOT_FOUND_RX = re.compile(r"(404|not found|no such)", re.IGNORECASE)
_PERM_RX = re.compile(r"(403|forbidden|permission denied|not allowed|"
                      r"insufficient scope)", re.IGNORECASE)
_CONFLICT_RX = re.compile(r"(409|conflict|already exists|duplicate)", re.IGNORECASE)
_LOCK_RX = re.compile(r"(deadlock|lock wait timeout|could not obtain lock|"
                      r"serialization failure)", re.IGNORECASE)

#: Pemetaan jenis -> boleh diulang?
KIND_RETRYABLE = {
    "transient": True,
    "timeout": True,
    "network": True,
    "rate_limit": True,
    "auth_expired": True,
    "lock": True,
    "validation": False,
    "malformed": False,
    "permission": False,
    "not_found": False,
    "conflict": False,
    "unknown": False,
}

#: Exponential backoff standar untuk tiap jenis.
KIND_BACKOFF = {
    "transient": (1_000, 60_000),
    "timeout": (2_000, 60_000),
    "network": (1_000, 60_000),
    "rate_limit": (5_000, 300_000),      # hormati jendela rate-limit
    "auth_expired": (250, 5_000),        # refresh token lalu segera ulang
    "lock": (500, 30_000),
}


def classify_error(error: Any, *, status: int | None = None) -> dict:
    """Klasifikasi kegagalan -> {kind, http_status, retryable, reason}.

    Aturan (sesuai riset): 5xx/429/401/408/timeout jaringan BUKAN masalah
    data -> boleh diulang. 422/400/404/403/409 = masalah data/izin ->
    JANGAN diulang, langsung karantina.
    """
    text = "" if error is None else str(error)
    code = status
    if code is None:
        m = _STATUS_RX.search(text)
        if m:
            code = int(m.group(1))

    if _RATE_RX.search(text) or code == 429:
        kind = "rate_limit"
    elif _AUTH_RX.search(text) or code == 401:
        kind = "auth_expired"
    elif _VALIDATION_RX.search(text) or code in (400, 422):
        kind = "malformed" if "parse" in text.lower() else "validation"
    elif _NOT_FOUND_RX.search(text) or code == 404:
        kind = "not_found"
    elif _PERM_RX.search(text) or code == 403:
        kind = "permission"
    elif _CONFLICT_RX.search(text) or code == 409:
        kind = "conflict"
    elif _LOCK_RX.search(text):
        kind = "lock"
    elif _NETWORK_RX.search(text):
        kind = "timeout" if re.search(r"timed?\s*out|etimedout", text,
                                     re.IGNORECASE) else "network"
    elif code is not None and 500 <= code <= 599:
        kind = "transient"
    else:
        kind = "unknown"

    # 5xx selalu transien, apa pun teksnya.
    if code is not None and 500 <= code <= 599 and kind == "unknown":
        kind = "transient"

    return {"kind": kind, "http_status": code,
            "retryable": bool(KIND_RETRYABLE.get(kind, False)),
            "reason": text[:400]}


def backoff_delay_ms(attempt: int, *, kind: str = "transient",
                     rng: Callable[[], float] | None = None) -> int:
    """Backoff eksponensial + **full jitter** (playbook produksi 2026).

    `attempt` berbasis 1. Hasil selalu berada pada [0, min(base*2^attempt, cap)],
    dan tidak pernah 0 untuk attempt >= 1 supaya retry tidak spin.
    """
    if attempt < 1:
        raise RecoveryError(f"attempt harus >= 1, dapat {attempt}")
    base, cap = KIND_BACKOFF.get(kind, (DEFAULT_BACKOFF_BASE_MS,
                                        DEFAULT_BACKOFF_CAP_MS))
    expo = min(cap, base * (2 ** attempt))
    r = rng() if rng is not None else _default_rng()
    # Full jitter: [expo/2, expo] -> tetap menghindari thundering herd,
    # tetapi tidak pernah menunggu nyaris nol.
    lo = expo / 2.0
    return int(lo + r * (expo - lo))


def _default_rng() -> float:
    import random
    return random.random()


# ---------------------------------------------------------------------------
# Catatan eksekusi + heartbeat
# ---------------------------------------------------------------------------

@dataclass
class ExecutionRecord:
    """Keadaan eksekusi yang dipantau supervisor."""

    execution_id: str
    workflow_id: str = ""
    status: str = PENDING
    mode: str = "manual"
    attempt: int = 0
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    owner: str = ""
    node_id: str = ""
    idem_key: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    heartbeat_at: Optional[float] = None
    worker_id: str = ""
    detector: str = ""
    error: str = ""
    error_kind: str = ""
    crash_signalled: bool = False
    recovered_by: str = ""
    links: list = field(default_factory=list)

    # -- bantuan ----------------------------------------------------------
    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL

    def age_sec(self, now: float) -> float:
        return max(0.0, now - self.created_at)

    def silent_sec(self, now: float) -> float:
        """Detik sejak sinyal hidup terakhir (heartbeat atau mulai)."""
        last = self.heartbeat_at or self.started_at or self.created_at
        return max(0.0, now - last)

    def to_dict(self) -> dict:
        return {
            "execution_id": self.execution_id, "workflow_id": self.workflow_id,
            "status": self.status, "mode": self.mode, "attempt": self.attempt,
            "max_attempts": self.max_attempts, "owner": self.owner,
            "node_id": self.node_id, "worker_id": self.worker_id,
            "detector": self.detector, "error": self.error,
            "error_kind": self.error_kind,
            "crash_signalled": self.crash_signalled,
            "created_at": self.created_at, "started_at": self.started_at,
            "ended_at": self.ended_at, "heartbeat_at": self.heartbeat_at,
            "links": list(self.links),
        }


class ExecutionSupervisor:
    """Pemantau eksekusi + pemulih otomatis (self-healing).

    Murni in-process dan dapat disuntik jamnya, sehingga seluruh perilaku
    waktu (stall, startup-recovery) dapat diuji secara deterministik.
    """

    def __init__(self, *, heartbeat_interval_sec: float =
                 DEFAULT_HEARTBEAT_INTERVAL_SEC,
                 stall_timeout_sec: float = DEFAULT_STALL_TIMEOUT_SEC,
                 visibility_timeout_sec: float =
                 DEFAULT_VISIBILITY_TIMEOUT_SEC,
                 deactivation_timeout_sec: float | None = None,
                 clock: Callable[[], float] | None = None,
                 on_crash: Callable[[ExecutionRecord, str], None] | None = None,
                 on_recover: Callable[[ExecutionRecord, str], Any] | None = None,
                 instance_id: str = "",
                 rng: Callable[[], float] | None = None,
                 spool_path: str = "") -> None:
        if stall_timeout_sec <= 0:
            raise RecoveryError("stall_timeout_sec harus > 0")
        if visibility_timeout_sec <= 0:
            raise RecoveryError("visibility_timeout_sec harus > 0")
        self.heartbeat_interval_sec = float(heartbeat_interval_sec)
        self.stall_timeout_sec = float(stall_timeout_sec)
        self.visibility_timeout_sec = float(visibility_timeout_sec)
        # Default: 4x visibility (seperti n8n: 4x queue visibility window).
        if deactivation_timeout_sec is None:
            deactivation_timeout_sec = self.visibility_timeout_sec * 4
        if deactivation_timeout_sec <= 0:
            raise RecoveryError("deactivation_timeout_sec harus > 0")
        self.deactivation_timeout_sec = float(deactivation_timeout_sec)
        self._clock = clock or time.time
        self.on_crash = on_crash
        self.on_recover = on_recover
        self.instance_id = instance_id or uuid.uuid4().hex[:12]
        self.rng = rng
        self.spool_path = spool_path
        self._lock = threading.RLock()
        self.records: dict[str, ExecutionRecord] = {}
        self.actions: list[dict] = []
        self.recovered_keys: set[str] = set()
        self._load()

    # -- persistensi ringan ----------------------------------------------
    def _load(self) -> None:
        if not self.spool_path or not os.path.exists(self.spool_path):
            return
        try:
            with open(self.spool_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for raw in data.get("records", []):
                rec = ExecutionRecord(**{
                    k: v for k, v in raw.items()
                    if k in ExecutionRecord.__dataclass_fields__})
                self.records[rec.execution_id] = rec
            self.recovered_keys = set(data.get("recovered_keys", []))
        except Exception as exc:  # noqa: BLE001 - state rusak -> mulai bersih
            print(f"[recovery] spool tidak terbaca: {exc}")

    def _persist(self) -> None:
        if not self.spool_path:
            return
        try:
            tmp = self.spool_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"records": [r.to_dict() for r in
                                       self.records.values()],
                           "recovered_keys": sorted(self.recovered_keys)}, fh)
            os.replace(tmp, self.spool_path)
        except Exception as exc:  # noqa: BLE001
            print(f"[recovery] spool gagal ditulis: {exc}")

    # -- siklus hidup -----------------------------------------------------
    def register(self, execution_id: str, *, workflow_id: str = "",
                 mode: str = "manual", owner: str = "",
                 max_attempts: int = DEFAULT_MAX_ATTEMPTS,
                 idem_key: str = "") -> ExecutionRecord:
        with self._lock:
            rec = ExecutionRecord(
                execution_id=str(execution_id), workflow_id=workflow_id,
                mode=mode, owner=owner, max_attempts=int(max_attempts),
                idem_key=idem_key or idempotency_key(execution_id, 0))
            # Stempel waktu WAJIB dari jam yang disuntik. Bila memakai
            # time.time() bawaan, jam palsu (atau jam proses yang di-mock)
            # membuat age_sec/silent_sec negatif -> detektor buta.
            rec.created_at = self._clock()
            self.records[rec.execution_id] = rec
            self._persist()
            return rec

    def start(self, execution_id: str, *, worker_id: str = "",
              node_id: str = "") -> ExecutionRecord:
        with self._lock:
            rec = self._get(execution_id)
            rec.status = RUNNING
            rec.started_at = self._clock()
            rec.heartbeat_at = rec.started_at
            rec.worker_id = worker_id or self.instance_id
            if node_id:
                rec.node_id = node_id
            rec.attempt += 1
            self._persist()
            return rec

    def heartbeat(self, execution_id: str, *, node_id: str = "") -> bool:
        """Tandai masih hidup. False bila eksekusi sudah terminal/tak dikenal."""
        with self._lock:
            rec = self.records.get(execution_id)
            if rec is None or rec.terminal:
                return False
            rec.heartbeat_at = self._clock()
            if node_id:
                rec.node_id = node_id
            return True

    def finish(self, execution_id: str, *, status: str = SUCCESS,
               error: Any = None) -> ExecutionRecord:
        with self._lock:
            rec = self._get(execution_id)
            rec.status = status
            rec.ended_at = self._clock()
            rec.heartbeat_at = rec.ended_at
            if error is not None:
                info = classify_error(error)
                rec.error = info["reason"]
                rec.error_kind = info["kind"]
            self._persist()
            return rec

    def fail(self, execution_id: str, error: Any, *,
             status: int | None = None) -> ExecutionRecord:
        info = classify_error(error, status=status)
        with self._lock:
            rec = self._get(execution_id)
            rec.status = ERROR
            rec.ended_at = self._clock()
            rec.error = info["reason"]
            rec.error_kind = info["kind"]
            self._persist()
            return rec

    def _get(self, execution_id: str) -> ExecutionRecord:
        rec = self.records.get(str(execution_id))
        if rec is None:
            raise RecoveryError(f"eksekusi tidak dikenal: {execution_id}")
        return rec

    # -- deteksi ----------------------------------------------------------
    def scan(self, *, now: float | None = None) -> list[dict]:
        """Deteksi masalah pada seluruh eksekusi non-terminal.

        Kembalikan daftar temuan: {execution_id, detector, ...}.
        Tidak mengubah state — pemanggil memutuskan lewat `remediate()`.
        """
        t = self._clock() if now is None else now
        found: list[dict] = []
        with self._lock:
            for rec in list(self.records.values()):
                if rec.terminal:
                    continue
                if rec.status == RUNNING:
                    if rec.silent_sec(t) >= self.stall_timeout_sec:
                        found.append({"execution_id": rec.execution_id,
                                      "detector": "stall",
                                      "silent_sec": round(rec.silent_sec(t), 3),
                                      "record": rec})
                elif rec.status == PENDING:
                    if rec.age_sec(t) >= self.visibility_timeout_sec:
                        found.append({"execution_id": rec.execution_id,
                                      "detector": "queue-recovery",
                                      "age_sec": round(rec.age_sec(t), 3),
                                      "record": rec})
                elif rec.status == WAITING:
                    # n8n: workflow dinonaktifkan saat masih menunggu.
                    # Ambang = deactivation_timeout_sec (bukan kelipatan
                    # visibility) supaya bisa dikonfigurasi terpisah.
                    if rec.age_sec(t) >= self.deactivation_timeout_sec:
                        found.append({"execution_id": rec.execution_id,
                                      "detector": "workflow-deactivation",
                                      "age_sec": round(rec.age_sec(t), 3),
                                      "record": rec})
                elif rec.status == CRASHED:
                    # Sudah ditandai lewat signal_crash(); jangan scan ulang.
                    continue
                else:
                    # Status tak dikenal (mis. dari versi baru n8n) -> jangan
                    # meledak, cukup dilewati.
                    continue
        return found

    def startup_scan(self, *, known_worker_ids: Iterable[str] | None = None,
                     now: float | None = None) -> list[dict]:
        """Deteksi eksekusi yang menggantung KARENA instance ini baru mulai.

        `startup-recovery`: instance restart dan menemukan eksekusi masih
        `running` di store. Bila `known_worker_ids` diberikan dan worker
        pemiliknya tidak ada di daftar itu, eksekusi pasti yatim.
        """
        t = self._clock() if now is None else now
        known = set(known_worker_ids) if known_worker_ids is not None else None
        found: list[dict] = []
        with self._lock:
            for rec in list(self.records.values()):
                if rec.status != RUNNING:
                    continue
                orphan = known is not None and rec.worker_id not in known
                silent = rec.silent_sec(t) >= self.stall_timeout_sec
                if orphan or silent:
                    found.append({"execution_id": rec.execution_id,
                                  "detector": "startup-recovery",
                                  "orphan_worker": bool(orphan),
                                  "silent_sec": round(rec.silent_sec(t), 3),
                                  "record": rec})
        return found

    def mark_start_failure(self, execution_id: str, error: Any) -> dict:
        """Eksekusi yang gagal START sebelum sempat berjalan (n8n: start-failure)."""
        info = classify_error(error)
        with self._lock:
            rec = self._get(execution_id)
            rec.detector = "start-failure"
            rec.error = info["reason"]
            rec.error_kind = info["kind"]
            self._persist()
            return {"execution_id": execution_id, "detector": "start-failure",
                    "kind": info["kind"], "retryable": info["retryable"]}

    # -- signalkan crash (n8n 2.42.0) -------------------------------------
    def signal_crash(self, execution_id: str, detector: str,
                     *, record: ExecutionRecord | None = None) -> dict:
        """Tandai eksekusi CRASH + panggil hook on_crash (idempoten)."""
        if detector not in DETECTORS:
            raise RecoveryError(
                f"detektor tidak dikenal: {detector!r} (pilih {', '.join(DETECTORS)})")
        with self._lock:
            rec = record if record is not None else self._get(execution_id)
            if rec.crash_signalled:
                return {"execution_id": rec.execution_id,
                        "detector": rec.detector, "duplicate": True}
            rec.status = CRASHED
            rec.detector = detector
            rec.error_kind = "crash"
            rec.error = rec.error or "WorkflowCrashedError"
            rec.ended_at = self._clock()
            rec.crash_signalled = True
            self._persist()
            out = {"execution_id": rec.execution_id, "detector": detector,
                   "status": CRASHED, "error_type": "WorkflowCrashedError",
                   "duplicate": False}
        if self.on_crash is not None:
            try:
                self.on_crash(rec, detector)
            except Exception as exc:  # noqa: BLE001 - hook tidak boleh meledak
                print(f"[recovery] on_crash gagal: {exc}")
        return out

    # -- remediasi --------------------------------------------------------
    def decide(self, finding: dict) -> dict:
        """Tentukan aksi untuk sebuah temuan (tanpa menjalankannya)."""
        rec: ExecutionRecord = finding["record"]
        detector = finding["detector"]
        # Eksekusi yang crash: hanya diulang bila masih ada jatah DAN
        # kategorinya boleh diulang. Crash platform = transien.
        retryable = rec.error_kind in ("", "crash", "transient", "timeout",
                                       "network")
        can_retry = retryable and rec.attempt < rec.max_attempts
        if can_retry:
            action = "restart"
        elif retryable:
            action = "quarantine"       # jatah habis -> DLQ
        else:
            action = "quarantine"       # error non-retryable -> DLQ
        return {"execution_id": rec.execution_id, "detector": detector,
                "action": action, "attempt": rec.attempt,
                "max_attempts": rec.max_attempts, "error_kind": rec.error_kind}

    def remediate(self, finding: dict) -> dict:
        """Jalankan aksi pemulihan untuk sebuah temuan. Idempoten."""
        plan = self.decide(finding)
        rec: ExecutionRecord = finding["record"]
        key = recovery_key(rec.execution_id, rec.attempt)

        with self._lock:
            if key in self.recovered_keys:
                return {**plan, "duplicate": True, "applied": False}
            self.recovered_keys.add(key)

        action = plan["action"]
        applied = True
        result: Any = None

        if action == "restart":
            # n8n TIDAK melanjutkan dari tengah; eksekusi baru dari awal.
            # Karena itu kunci idempotensi per-attempt diteruskan agar sisi
            # efek dapat menolak pemrosesan ganda.
            with self._lock:
                rec.status = PENDING
                rec.started_at = None
                rec.heartbeat_at = None
                rec.ended_at = None
                rec.detector = finding["detector"]
                rec.crash_signalled = False
                rec.error = ""
                rec.error_kind = ""
                rec.recovered_by = "restart"
                rec.links.append({"reason": finding["detector"],
                                  "at": self._clock()})
                self._persist()
            if self.on_recover is not None:
                try:
                    result = self.on_recover(rec, "restart")
                except Exception as exc:  # noqa: BLE001
                    applied = False
                    result = f"{type(exc).__name__}: {exc}"
        else:
            with self._lock:
                rec.status = CRASHED if rec.crash_signalled else ERROR
                rec.ended_at = self._clock()
                rec.recovered_by = "quarantine"
                if not rec.error:
                    rec.error = "dikarantina setelah pemulihan gagal/ditolak"
                if not rec.error_kind:
                    rec.error_kind = "crash"
                self._persist()
            if self.on_recover is not None:
                try:
                    result = self.on_recover(rec, "quarantine")
                except Exception as exc:  # noqa: BLE001
                    applied = False
                    result = f"{type(exc).__name__}: {exc}"

        action_row = {**plan, "duplicate": False, "applied": applied,
                      "result": result if isinstance(result, (dict, str, int,
                                                              bool, type(None)))
                      else str(result)}
        self._lock.acquire()
        try:
            self.actions.append(action_row)
            self._persist()
        finally:
            self._lock.release()
        return action_row

    def run_once(self, *, now: float | None = None,
                 include_startup: bool = False) -> dict:
        """Satu putaran pemulihan: deteksi -> putuskan -> jalankan."""
        findings = self.scan(now=now)
        if include_startup:
            seen = {f["execution_id"] for f in findings}
            for f in self.startup_scan(now=now):
                if f["execution_id"] not in seen:
                    findings.append(f)
        acted = [self.remediate(f) for f in findings]
        return {"scanned": len(self.records), "found": len(findings),
                "actions": acted}

    # -- laporan ----------------------------------------------------------
    def stats(self) -> dict:
        with self._lock:
            per: dict[str, int] = {}
            for r in self.records.values():
                per[r.status] = per.get(r.status, 0) + 1
            return {
                "instance_id": self.instance_id,
                "total": len(self.records),
                "by_status": per,
                "crashed": per.get(CRASHED, 0),
                "stalled_now": len(self.scan()),
                "recovered": sum(1 for r in self.records.values()
                                 if r.recovered_by),
                "actions": len(self.actions),
                "stall_timeout_sec": self.stall_timeout_sec,
                "visibility_timeout_sec": self.visibility_timeout_sec,
                "heartbeat_interval_sec": self.heartbeat_interval_sec,
                "detectors": list(DETECTORS),
            }

    def list_records(self, *, status: str = "") -> list[dict]:
        with self._lock:
            out = [r.to_dict() for r in self.records.values()]
        if status:
            out = [r for r in out if r["status"] == status]
        return sorted(out, key=lambda r: r["created_at"], reverse=True)

    def reset(self) -> None:
        with self._lock:
            self.records.clear()
            self.actions.clear()
            self.recovered_keys.clear()
            self._persist()


# ---------------------------------------------------------------------------
# Pemulihan idempoten dengan compensating action
# ---------------------------------------------------------------------------

class IdempotencyGuard:
    """Menyaring pemrosesan ganda + mencatat compensating action.

    Alur:
        if not guard.claim(key): return "sudah diproses"
        try: ...kerja...
        except: guard.compensate(key, undo_fn) -> rollback
        guard.commit(key)
    """

    def __init__(self, *, spool_path: str = "",
                 persist_interval_sec: float = 0.25) -> None:
        self.spool_path = spool_path
        self._lock = threading.RLock()
        self._claims: dict[str, dict] = {}
        self._dirty = False
        self._last_persist = 0.0
        # Tulis spool adalah operasi O(n) (seluruh berkas ditulis ulang).
        # Tanpa penggabungan, klaim beruntun menjadi O(n^2). Jendela ini
        # menggabungkan tulisan; `commit()`/`flush()` tetap memaksa tulis.
        self.persist_interval_sec = float(persist_interval_sec)
        self._load()

    def _load(self) -> None:
        if not self.spool_path or not os.path.exists(self.spool_path):
            return
        try:
            with open(self.spool_path, "r", encoding="utf-8") as fh:
                self._claims = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            print(f"[recovery] guard spool tidak terbaca: {exc}")

    def _persist(self, *, force: bool = False) -> None:
        if not self.spool_path:
            return
        if not force and self.persist_interval_sec > 0:
            now = time.time()
            if now - self._last_persist < self.persist_interval_sec:
                self._dirty = True
                return
        try:
            tmp = self.spool_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._claims, fh)
            os.replace(tmp, self.spool_path)
            self._dirty = False
            self._last_persist = time.time()
        except Exception as exc:  # noqa: BLE001
            print(f"[recovery] guard spool gagal ditulis: {exc}")

    def flush(self) -> bool:
        """Paksa tulis spool (mis. sebelum proses berhenti)."""
        with self._lock:
            if not self._dirty:
                return False
            self._persist(force=True)
            return True

    def claim(self, key: str, *, meta: dict | None = None) -> bool:
        """True bila kunci baru (boleh jalan); False bila duplikat."""
        k = str(key)
        with self._lock:
            if k in self._claims:
                return False
            self._claims[k] = {"state": "claimed", "meta": dict(meta or {}),
                               "at": time.time()}
            self._persist()
            return True

    def seen(self, key: str) -> bool:
        with self._lock:
            return str(key) in self._claims

    def commit(self, key: str, *, result: Any = None) -> None:
        with self._lock:
            row = self._claims.get(str(key))
            if row is None:
                return
            row["state"] = "committed"
            row["result"] = result if isinstance(
                result, (dict, str, int, float, bool, type(None))) else str(result)
            # WAJIB persist paksa: tanpa ini, proses yang restart akan
            # kehilangan tanda "sudah commit" dan bisa menjalankan efek
            # samping dua kali.
            self._persist(force=True)

    def compensate(self, key: str, undo: Callable[[], Any]) -> dict:
        """Jalankan aksi kompensasi (rollback) lalu tandai terkompensasi."""
        k = str(key)
        with self._lock:
            row = self._claims.get(k)
            if row is None:
                return {"key": k, "compensated": False,
                        "reason": "kunci tidak dikenal"}
            if row.get("state") == "compensated":
                return {"key": k, "compensated": True, "duplicate": True}
        try:
            out = undo()
            err = ""
        except Exception as exc:  # noqa: BLE001 - rollback tetap dicatat
            out, err = None, f"{type(exc).__name__}: {exc}"
        with self._lock:
            row = self._claims.setdefault(k, {})
            row["state"] = "compensated"
            row["undo"] = out if isinstance(out, (dict, str, int, bool,
                                                  type(None))) else str(out)
            if err:
                row["undo_error"] = err
            self._persist(force=True)
        return {"key": k, "compensated": not err, "result": out,
                "error": err}

    def release(self, key: str) -> None:
        """Buang klaim (mis. pekerjaan benar-benar tidak jalan) -> boleh diulang."""
        with self._lock:
            self._claims.pop(str(key), None)
            self._persist(force=True)

    def stats(self) -> dict:
        with self._lock:
            per: dict[str, int] = {}
            for r in self._claims.values():
                st = str(r.get("state") or "?")
                per[st] = per.get(st, 0) + 1
            return {"total": len(self._claims), "by_state": per}


# ---------------------------------------------------------------------------
# Registry proses
# ---------------------------------------------------------------------------

_SUPERVISOR: ExecutionSupervisor | None = None
_GUARD: IdempotencyGuard | None = None


def supervisor() -> ExecutionSupervisor:
    global _SUPERVISOR
    if _SUPERVISOR is None:
        _SUPERVISOR = supervisor_from_env()
    return _SUPERVISOR


def set_supervisor(new: ExecutionSupervisor | None) -> None:
    global _SUPERVISOR
    _SUPERVISOR = new


def guard() -> IdempotencyGuard:
    global _GUARD
    if _GUARD is None:
        _GUARD = IdempotencyGuard(
            spool_path=(os.environ.get("KATALIR_RECOVERY_SPOOL") or "").strip())
    return _GUARD


def set_guard(new: IdempotencyGuard | None) -> None:
    global _GUARD
    _GUARD = new


def _env_float(env: dict, name: str, default: float) -> float:
    """Ambil float dari dict env (BUKAN os.environ) agar injectable saat tes."""
    raw = env.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def supervisor_from_env(env: dict | None = None) -> ExecutionSupervisor:
    e = env if env is not None else os.environ
    clock = e.get("_CLOCK") if isinstance(e, dict) else None
    return ExecutionSupervisor(
        heartbeat_interval_sec=_env_float(e, "KATALIR_HEARTBEAT_INTERVAL_SEC",
                                          DEFAULT_HEARTBEAT_INTERVAL_SEC),
        stall_timeout_sec=_env_float(e, "KATALIR_STALL_TIMEOUT_SEC",
                                     DEFAULT_STALL_TIMEOUT_SEC),
        visibility_timeout_sec=_env_float(e, "KATALIR_VISIBILITY_TIMEOUT_SEC",
                                          DEFAULT_VISIBILITY_TIMEOUT_SEC),
        deactivation_timeout_sec=_env_float(
            e, "KATALIR_DEACTIVATION_TIMEOUT_SEC", 0.0) or None,
        instance_id=(str(e.get("KATALIR_INSTANCE_ID") or "").strip()),
        spool_path=(str(e.get("KATALIR_RECOVERY_SPOOL") or "").strip()),
        clock=clock if callable(clock) else None)


def describe(env: dict | None = None) -> dict:
    e = env if env is not None else os.environ
    sup = supervisor_from_env(e)
    g = guard()
    return {
        "detectors": list(DETECTORS),
        "retryable_kinds": [k for k, v in KIND_RETRYABLE.items() if v],
        "non_retryable_kinds": [k for k, v in KIND_RETRYABLE.items() if not v],
        "stall_timeout_sec": sup.stall_timeout_sec,
        "visibility_timeout_sec": sup.visibility_timeout_sec,
        "deactivation_timeout_sec": sup.deactivation_timeout_sec,
        "heartbeat_interval_sec": sup.heartbeat_interval_sec,
        "instance_id": sup.instance_id,
        "spool_path": sup.spool_path,
        "actions": ["restart", "quarantine"],
        "guard": g.stats(),
        "backoff": {k: {"base_ms": v[0], "cap_ms": v[1]}
                    for k, v in KIND_BACKOFF.items()},
        "jitter": "full (uniform pada [expo/2, expo])",
    }


__all__ = [
    "DETECTORS", "PENDING", "RUNNING", "SUCCESS", "ERROR", "CRASHED",
    "CANCELLED", "WAITING", "TERMINAL", "NON_TERMINAL",
    "RETRYABLE_KINDS", "NON_RETRYABLE_KINDS", "KIND_RETRYABLE", "KIND_BACKOFF",
    "DEFAULT_MAX_ATTEMPTS", "DEFAULT_STALL_TIMEOUT_SEC",
    "DEFAULT_VISIBILITY_TIMEOUT_SEC", "RecoveryError", "ExecutionRecord",
    "ExecutionSupervisor", "IdempotencyGuard",
    "idempotency_key", "recovery_key", "classify_error", "backoff_delay_ms",
    "supervisor", "set_supervisor", "guard", "set_guard",
    "supervisor_from_env", "describe",
]
