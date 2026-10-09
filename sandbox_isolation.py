"""sandbox_isolation.py — Fitur #5: isolasi sandbox agen (model task runner n8n).

Padanan n8n "Task Runners" (docs Okt 2026). n8n mengeksekusi kode dari Code
node **di luar** proses utama, melalui tiga komponen:

  * **Task Runner**  — proses yang benar-benar mengeksekusi kode.
  * **Task Broker**  — bagian dari instance n8n/worker; mengoordinasi.
  * **Task Requester** — Code node itu sendiri, yang meminta eksekusi.

Runner terhubung ke broker lewat **WebSocket**; broker menyerahkan tugas ke
runner yang tersedia, runner mengirim hasil kembali ke requester.

Dua mode (docs n8n):
  * `internal` (default) — runner adalah **sub-proses** dari n8n, berbagi
    `uid`/`gid`. n8n menyatakan mode ini **TIDAK disarankan untuk produksi**.
  * `external` — launcher menjalankan runner di **kontainer terpisah**
    (sidecar `n8nio/runners`). Butuh n8n >= 1.111.0 dan versi image harus
    sama. Ini satu-satunya mode yang dianggap siap produksi.

Hardening tambahan yang didokumentasikan n8n:
  * image **distroless** (tanpa shell/package manager)
  * jalankan sebagai user tak-berhak **`nobody` (uid/gid 65532)**
  * **root filesystem read-only** + `emptyDir` kecil di `/tmp`
  * profil **AppArmor** menolak baca `/proc/<pid>/{environ,mounts}`

Batas sumber daya (default n8n, nama env PERSIS):
  `N8N_RUNNERS_MAX_CONCURRENCY=5`, `N8N_RUNNERS_TASK_TIMEOUT=300`,
  `N8N_RUNNERS_HEARTBEAT_INTERVAL=30`, `N8N_RUNNERS_TASK_REQUEST_TIMEOUT=60`,
  `N8N_RUNNERS_MAX_PAYLOAD=1073741824`,
  `N8N_RUNNERS_AUTO_SHUTDOWN_TIMEOUT=15`.

Allowlist modul (docs n8n, **default kosong = semua impor diblokir**):
  * JS: `NODE_FUNCTION_ALLOW_BUILTIN`, `NODE_FUNCTION_ALLOW_EXTERNAL`
  * PY: `N8N_RUNNERS_STDLIB_ALLOW`, `N8N_RUNNERS_EXTERNAL_ALLOW`
  * PY builtins ditolak secara default lewat `N8N_RUNNERS_BUILTINS_DENY`
  * `N8N_BLOCK_RUNNER_ENV_ACCESS=true` (default) memblokir `os.environ`

Konteks keamanan Okt 2026: **CVE-2026-27495 / GHSA-jjpj-p2wh-qf23** —
"Sandbox Escape in JavaScript Task Runner", CVSS v3.1 **9.4**
(`AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H`), CWE-94, diperbaiki di n8n
**1.123.22 / 2.9.3 / 2.10.1**. Pengguna terautentikasi dengan izin
membuat/mengubah workflow dapat mengeksekusi kode di luar batas sandbox;
pada mode **internal** dampaknya adalah **penguasaan penuh host**, pada mode
**external** dampaknya terbatas pada runner (dan tugas lain di runner itu).
Mitigasi sementara menurut advisory: batasi izin edit workflow ke pengguna
yang sepenuhnya tepercaya, dan pakai mode external untuk memperkecil
radius ledakan.

Modul ini TIDAK menjalankan kode. Ia menegakkan **kebijakan** sebelum kode
diserahkan ke mesin eksekusi (`code_sandbox.py`), memodelkan mode &
hardening n8n, dan menolak konfigurasi yang tidak aman secara default.

Env:
    KATALIR_SANDBOX_MODE          "internal" (default) | "external"
    KATALIR_SANDBOX_DISTROLESS    "1"/"0" (default "0")
    KATALIR_SANDBOX_UID           default "1000" (harus 65532 bila distroless)
    KATALIR_SANDBOX_READONLY_ROOT "1"/"0" (default "0")
    KATALIR_SANDBOX_APPARMOR      "1"/"0" (default "0")
    KATALIR_SANDBOX_MAX_CONCURRENCY      default 5
    KATALIR_SANDBOX_TASK_TIMEOUT_S       default 300
    KATALIR_SANDBOX_HEARTBEAT_INTERVAL_S default 30
    KATALIR_SANDBOX_REQUEST_TIMEOUT_S    default 60
    KATALIR_SANDBOX_MAX_PAYLOAD_BYTES    default 1073741824
    KATALIR_SANDBOX_AUTOSHUTDOWN_S       default 15
    KATALIR_SANDBOX_ALLOW_BUILTIN        CSV, default ""
    KATALIR_SANDBOX_ALLOW_EXTERNAL       CSV, default ""
    KATALIR_SANDBOX_ALLOW_STDLIB         CSV, default ""
    KATALIR_SANDBOX_ALLOW_PY_EXTERNAL    CSV, default ""
    KATALIR_SANDBOX_BLOCK_ENV_ACCESS     "1"/"0" (default "1")
    KATALIR_SANDBOX_REQUIRE_PRODUCTION   "1"/"0" (default "0") — bila "1",
                                          konfigurasi internal ditolak
"""
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from typing import Any, Callable, Iterable, Optional

__all__ = [
    "SandboxPolicyError", "UnsafeConfiguration", "ModuleNotAllowed",
    "PayloadTooLarge", "ConcurrencyExceeded", "TaskTimeout",
    "TimeoutError_", "RequestTimeout",
    "MODES", "PRODUCTION_SAFE_MODES", "RUNTIME_TYPES",
    "N8N_RUNNER_DEFAULTS", "PY_BUILTINS_DENY_DEFAULT",
    "DISTROLESS_UID", "DOCKER_RUNNER_IMAGE",
    "SandboxPolicy", "TaskRunner", "TaskBroker", "TaskRequester",
    "policy", "set_policy", "policy_from_env", "describe",
    "is_module_allowed", "check_payload", "harden_report",
]

#: Mode runner n8n. `internal` adalah default n8n tetapi TIDAK siap produksi.
MODES = ("internal", "external")
#: Satu-satunya mode yang dianggap siap produksi oleh dokumentasi n8n.
PRODUCTION_SAFE_MODES = ("external",)
#: Jenis runner yang disediakan image `n8nio/runners`.
RUNTIME_TYPES = ("javascript", "python")

#: Default resmi n8n (docs "Task runner environment variables", Okt 2026).
N8N_RUNNER_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "mode": "internal",
    "broker_port": 5679,
    "broker_listen_address": "127.0.0.1",
    "max_payload": 1_073_741_824,
    "max_concurrency": 5,
    "task_timeout": 300,
    "heartbeat_interval": 30,
    "task_request_timeout": 60,
    "auto_shutdown_timeout": 15,
    "launcher_health_port": 5680,
    "insecure_mode": False,
    "allow_prototype_mutation": False,
    "block_runner_env_access": True,
}

#: Builtin Python yang ditolak secara default (docs n8n, verbatim).
PY_BUILTINS_DENY_DEFAULT: tuple[str, ...] = (
    "eval", "exec", "compile", "open", "input", "breakpoint", "getattr",
    "object", "type", "vars", "setattr", "delattr", "hasattr", "dir",
    "memoryview", "__build_class__", "globals", "locals",
)

#: uid/gid yang diwajibkan n8n untuk runner yang di-hardening.
DISTROLESS_UID = 65532

#: Nama image runner resmi (versinya HARUS sama dengan versi n8n).
DOCKER_RUNNER_IMAGE = "n8nio/runners"

#: CVE yang memotivasi gerbang mode produksi.
KNOWN_CVES: tuple[dict, ...] = (
    {
        "id": "CVE-2026-27495",
        "ghsa": "GHSA-jjpj-p2wh-qf23",
        "title": "Sandbox Escape in JavaScript Task Runner",
        "cvss_v31": 9.4,
        "cvss_v31_vector": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H",
        "cwe": "CWE-94",
        "severity": "critical",
        "affected": "< 1.123.22, >= 2.0.0 < 2.9.3, >= 2.10.0 < 2.10.1",
        "patched": ("1.123.22", "2.9.3", "2.10.1"),
        "internal_mode_impact": "penguasaan penuh host n8n",
        "external_mode_impact": "akses ke / dampak pada tugas lain di runner",
        "requires": "N8N_RUNNERS_ENABLED=true + izin buat/ubah workflow",
    },
)


# ---------------------------------------------------------------------------
# Pengecualian
# ---------------------------------------------------------------------------

class SandboxPolicyError(Exception):
    """Kesalahan kebijakan sandbox yang dapat dilaporkan ke pemanggil."""


class UnsafeConfiguration(SandboxPolicyError):
    """Konfigurasi melanggar aturan keamanan (mis. internal di produksi)."""


class ModuleNotAllowed(SandboxPolicyError):
    """Impor modul tidak ada di allowlist (default: semua ditolak)."""


class PayloadTooLarge(SandboxPolicyError):
    """Payload melebihi `max_payload`."""


class ConcurrencyExceeded(SandboxPolicyError):
    """Jumlah tugas bersamaan melebihi `max_concurrency`."""


class TaskTimeout(SandboxPolicyError):
    """Tugas melewati `task_timeout` -> runner dihentikan dan dijalankan ulang."""


#: Alias bertipe TimeoutError agar pemanggil bisa `except TimeoutError`.
TimeoutError_ = TaskTimeout


class RequestTimeout(SandboxPolicyError):
    """Tidak ada runner tersedia dalam `task_request_timeout`."""


# ---------------------------------------------------------------------------
# Kebijakan
# ---------------------------------------------------------------------------

_CSV_SPLIT = re.compile(r"[,\s]+")


def _env_str(env: dict, name: str, default: str) -> str:
    raw = env.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip()


def _env_int(env: dict, name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or str(raw).strip() == "":
        return int(default)
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return int(default)


def _env_flag(env: dict, name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on", "ya")


def _csv(env: dict, name: str, default: Iterable[str] = ()) -> tuple[str, ...]:
    raw = env.get(name)
    if raw is None or str(raw).strip() == "":
        return tuple(default)
    # `*` berarti "izinkan semua" -> direpresentasikan sebagai ("*",).
    item = str(raw).strip()
    if item == "*":
        return ("*",)
    return tuple(dict.fromkeys(
        p.strip() for p in _CSV_SPLIT.split(item) if p.strip()))


class SandboxPolicy:
    """Kebijakan isolasi sandbox — memodelkan task runner n8n.

    Tidak mengeksekusi kode. Menegakkan: mode, hardening, batas sumber daya,
    allowlist modul, dan gerbang produksi.
    """

    def __init__(
        self,
        *,
        mode: str = "internal",
        distroless: bool = False,
        uid: int = 1000,
        gid: Optional[int] = None,
        read_only_root: bool = False,
        apparmor: bool = False,
        max_concurrency: int = 5,
        task_timeout_s: int = 300,
        heartbeat_interval_s: int = 30,
        request_timeout_s: int = 60,
        max_payload_bytes: int = 1_073_741_824,
        auto_shutdown_s: int = 15,
        broker_port: int = 5679,
        broker_listen_address: str = "127.0.0.1",
        allow_builtin: Iterable[str] = (),
        allow_external: Iterable[str] = (),
        allow_stdlib: Iterable[str] = (),
        allow_py_external: Iterable[str] = (),
        block_env_access: bool = True,
        insecure_mode: bool = False,
        allow_prototype_mutation: bool = False,
        require_production: bool = False,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        m = str(mode).strip().lower()
        if m not in MODES:
            raise SandboxPolicyError(
                f"mode harus salah satu dari {MODES}, dapat {mode!r}")
        self.mode = m
        self.distroless = bool(distroless)
        self.uid = int(uid)
        self.gid = int(gid if gid is not None else self.uid)
        self.read_only_root = bool(read_only_root)
        self.apparmor = bool(apparmor)
        self.broker_port = int(broker_port)
        self.broker_listen_address = str(broker_listen_address)
        self.insecure_mode = bool(insecure_mode)
        self.allow_prototype_mutation = bool(allow_prototype_mutation)
        self.block_env_access = bool(block_env_access)
        self.require_production = bool(require_production)
        self.allow_builtin = tuple(dict.fromkeys(str(x) for x in allow_builtin))
        self.allow_external = tuple(dict.fromkeys(str(x) for x in allow_external))
        self.allow_stdlib = tuple(dict.fromkeys(str(x) for x in allow_stdlib))
        self.allow_py_external = tuple(
            dict.fromkeys(str(x) for x in allow_py_external))
        self._clock = clock or time.time

        # Batas sumber daya — divalidasi (n8n: "harus > 0").
        self.max_concurrency = self._positive(
            max_concurrency, "max_concurrency")
        self.task_timeout_s = self._positive(task_timeout_s, "task_timeout_s")
        self.heartbeat_interval_s = self._positive(
            heartbeat_interval_s, "heartbeat_interval_s")
        self.request_timeout_s = self._positive(
            request_timeout_s, "request_timeout_s")
        self.max_payload_bytes = self._positive(
            max_payload_bytes, "max_payload_bytes")
        self.auto_shutdown_s = max(0, int(auto_shutdown_s))  # 0 = nonaktif

        # Keamanan: heartbeat tidak boleh >= task timeout, kalau tidak runner
        # akan dianggap mati sebelum waktunya (jitter jaringan memicu restart
        # palsu). n8n menyarankan heartbeat jauh lebih kecil dari timeout.
        if self.heartbeat_interval_s >= self.task_timeout_s:
            raise UnsafeConfiguration(
                "heartbeat_interval_s harus < task_timeout_s "
                f"({self.heartbeat_interval_s} >= {self.task_timeout_s})")

        # Gerbang hardening: distroless mewajibkan uid/gid 65532.
        if self.distroless and self.uid != DISTROLESS_UID:
            raise UnsafeConfiguration(
                f"image distroless mewajibkan uid/gid {DISTROLESS_UID}, "
                f"dapat {self.uid}")

        self._validate_mode()

    # -- validasi ---------------------------------------------------------
    @staticmethod
    def _positive(value: Any, name: str) -> int:
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise SandboxPolicyError(f"{name} harus bilangan bulat") from None
        if n <= 0:
            raise SandboxPolicyError(f"{name} harus > 0, dapat {n}")
        return n

    def _validate_mode(self) -> None:
        """Aturan keamanan mode — mencegah konfigurasi yang terbukti rentan."""
        if self.insecure_mode and self.require_production:
            raise UnsafeConfiguration(
                "insecure_mode tidak boleh dipakai dengan require_production")
        if self.require_production and self.mode not in PRODUCTION_SAFE_MODES:
            raise UnsafeConfiguration(
                f"mode {self.mode!r} tidak siap produksi (CVE-2026-27495: "
                "mode internal berbagi uid/gid dengan proses utama sehingga "
                "sandbox escape berarti penguasaan penuh host); "
                f"pakai salah satu dari {PRODUCTION_SAFE_MODES}")

    # -- pertanyaan -----------------------------------------------
    @property
    def production_safe(self) -> bool:
        return self.mode in PRODUCTION_SAFE_MODES and not self.insecure_mode

    @property
    def isolation_boundary(self) -> str:
        """Di mana batas isolasi berada secara nyata."""
        if self.mode == "external":
            if self.distroless and self.read_only_root:
                return "container (distroless + rootfs read-only)"
            return "container (sidecar terpisah)"
        return "sub-proses (uid/gid SAMA dengan n8n)"

    @property
    def hardening_layers(self) -> tuple[str, ...]:
        layers: list[str] = []
        if self.mode == "external":
            layers.append("external-mode")
        if self.distroless:
            layers.append("distroless")
        if self.uid == DISTROLESS_UID:
            layers.append("nobody-65532")
        if self.read_only_root:
            layers.append("readonly-rootfs")
        if self.apparmor:
            layers.append("apparmor-proc-deny")
        if self.block_env_access:
            layers.append("env-access-blocked")
        if not self.insecure_mode:
            layers.append("secure-globals")
        return tuple(layers)

    def module_allowed(self, runtime: str, name: str) -> bool:
        """Apakah `name` boleh diimpor pada `runtime`?

        Default n8n = **semua impor ditolak** (allowlist kosong).
        """
        rt = str(runtime).strip().lower()
        if rt not in RUNTIME_TYPES:
            raise SandboxPolicyError(
                f"runtime harus salah satu dari {RUNTIME_TYPES}, dapat {runtime!r}")
        n = str(name).strip()
        if not n:
            return False
        if rt == "javascript":
            allow = list(self.allow_builtin) + list(self.allow_external)
        else:
            allow = list(self.allow_stdlib) + list(self.allow_py_external)
        if "*" in allow:
            return True
        # Impor bersarang (`fs/promises`, `os.path`) dinilai dari akarnya.
        root = n.split("/")[0].split(".")[0]
        return n in allow or root in allow

    def check_payload(self, size_bytes: int) -> None:
        """Lempar `PayloadTooLarge` bila melebihi `max_payload_bytes`."""
        try:
            n = int(size_bytes)
        except (TypeError, ValueError):
            raise SandboxPolicyError("size_bytes harus bilangan bulat") from None
        if n < 0:
            raise SandboxPolicyError("size_bytes tidak boleh negatif")
        if n > self.max_payload_bytes:
            raise PayloadTooLarge(
                f"payload {n} byte melebihi batas {self.max_payload_bytes} byte")

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "production_safe": self.production_safe,
            "isolation_boundary": self.isolation_boundary,
            "hardening_layers": list(self.hardening_layers),
            "distroless": self.distroless,
            "uid": self.uid,
            "gid": self.gid,
            "read_only_root": self.read_only_root,
            "apparmor": self.apparmor,
            "broker_port": self.broker_port,
            "broker_listen_address": self.broker_listen_address,
            "max_concurrency": self.max_concurrency,
            "task_timeout_s": self.task_timeout_s,
            "heartbeat_interval_s": self.heartbeat_interval_s,
            "request_timeout_s": self.request_timeout_s,
            "max_payload_bytes": self.max_payload_bytes,
            "auto_shutdown_s": self.auto_shutdown_s,
            "allow_builtin": list(self.allow_builtin),
            "allow_external": list(self.allow_external),
            "allow_stdlib": list(self.allow_stdlib),
            "allow_py_external": list(self.allow_py_external),
            "block_env_access": self.block_env_access,
            "insecure_mode": self.insecure_mode,
            "allow_prototype_mutation": self.allow_prototype_mutation,
            "require_production": self.require_production,
            "python_builtins_denied": list(PY_BUILTINS_DENY_DEFAULT),
        }


# ---------------------------------------------------------------------------
# Runner / Broker / Requester
# ---------------------------------------------------------------------------

class TaskRunner:
    """Satu task runner — mengeksekusi tugas yang diberikan broker.

    Menegakkan `max_concurrency`, `task_timeout`, dan allowlist modul
    SEBELUM tugas dijalankan (kode tidak pernah dieksekusi di sini).
    """

    def __init__(self, runtime: str, *, policy: SandboxPolicy,
                 runner_id: str = "",
                 clock: Optional[Callable[[], float]] = None,
                 executor: Optional[Callable[[dict], Any]] = None) -> None:
        rt = str(runtime).strip().lower()
        if rt not in RUNTIME_TYPES:
            raise SandboxPolicyError(
                f"runtime harus salah satu dari {RUNTIME_TYPES}, dapat {runtime!r}")
        self.runtime = rt
        self.policy = policy
        self.runner_id = runner_id or f"{rt}-{uuid.uuid4().hex[:12]}"
        self._clock = clock or policy._clock
        self._executor = executor
        self._lock = threading.RLock()
        self.active: dict[str, dict] = {}
        self.started_at = self._clock()
        self.last_heartbeat = self._clock()
        self.completed = 0
        self.failed = 0
        self.rejected = 0

    # -- siklus hidup ------------------------------------------------------
    def heartbeat(self) -> float:
        with self._lock:
            self.last_heartbeat = self._clock()
            return self.last_heartbeat

    def is_alive(self) -> bool:
        """Runner dianggap hidup bila heartbeat-nya belum kedaluwarsa."""
        with self._lock:
            age = self._clock() - self.last_heartbeat
        # Toleransi 2x interval — jitter jaringan tidak boleh memicu restart.
        return age <= self.policy.heartbeat_interval_s * 2

    @property
    def capacity(self) -> int:
        with self._lock:
            return self.policy.max_concurrency - len(self.active)

    def can_accept(self) -> bool:
        return self.is_alive() and self.capacity > 0

    # -- eksekusi ----------------------------------------------------------
    def submit(self, task: dict, *, now: Optional[float] = None) -> dict:
        """Terima tugas, tegakkan kebijakan, lalu (opsional) jalankan.

        Mengembalikan dict hasil. `task` wajib memuat `id`, `runtime`, `code`,
        dan opsional `imports` (daftar modul yang diimpor).
        """
        t = dict(task)
        tid = str(t.get("id") or uuid.uuid4().hex[:12])
        t["id"] = tid

        rt = str(t.get("runtime", self.runtime)).strip().lower()
        if rt != self.runtime:
            with self._lock:
                self.rejected += 1
            raise SandboxPolicyError(
                f"runner {self.runtime} tidak dapat menjalankan tugas "
                f"runtime {rt}")

        # 1. Modul yang diimpor harus ada di allowlist (default: kosong).
        for mod in t.get("imports") or ():
            if not self.policy.module_allowed(self.runtime, mod):
                with self._lock:
                    self.rejected += 1
                raise ModuleNotAllowed(
                    f"impor {mod!r} tidak diizinkan pada runtime "
                    f"{self.runtime} (allowlist kosong = semua ditolak)")

        # 2. Ukuran payload.
        size = t.get("payload_bytes")
        if size is None:
            code = t.get("code") or ""
            size = len(code.encode("utf-8") if isinstance(code, str)
                       else bytes(code))
        try:
            self.policy.check_payload(int(size))
        except PayloadTooLarge:
            with self._lock:
                self.rejected += 1
            raise

        # 3. Tugas tidak boleh diajukan ke runner yang mati.
        if not self.is_alive():
            with self._lock:
                self.rejected += 1
            raise SandboxPolicyError(
                f"runner {self.runner_id} tidak mengirim heartbeat; "
                "tugas ditolak (runner akan dijalankan ulang)")

        with self._lock:
            if len(self.active) >= self.policy.max_concurrency:
                self.rejected += 1
                raise ConcurrencyExceeded(
                    f"runner {self.runner_id} sudah menjalankan "
                    f"{len(self.active)} tugas (batas "
                    f"{self.policy.max_concurrency})")
            t0 = self._clock() if now is None else float(now)
            self.active[tid] = {"started_at": t0, "task": t}

        try:
            if self._executor is not None:
                out = self._executor(t)
            else:
                out = {"task_id": tid, "runtime": self.runtime,
                       "status": "accepted", "executed": False}
            with self._lock:
                self.completed += 1
            return {"ok": True, "task_id": tid, "result": out}
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.failed += 1
            return {"ok": False, "task_id": tid,
                    "error": f"{type(exc).__name__}: {exc}"}
        finally:
            with self._lock:
                self.active.pop(tid, None)

    def reap_timeouts(self, *, now: Optional[float] = None) -> list[dict]:
        """Hentikan tugas yang melewati `task_timeout` (n8n: runner restart).

        Mengembalikan daftar tugas yang dihentikan paksa.
        """
        t_now = self._clock() if now is None else float(now)
        killed: list[dict] = []
        with self._lock:
            for tid, row in list(self.active.items()):
                if t_now - row["started_at"] > self.policy.task_timeout_s:
                    killed.append({"task_id": tid,
                                   "ran_for_s": t_now - row["started_at"],
                                   "action": "stop-and-restart-runner"})
                    self.active.pop(tid, None)
                    self.failed += 1
        return killed

    def stats(self) -> dict:
        with self._lock:
            return {
                "runner_id": self.runner_id, "runtime": self.runtime,
                "alive": self.is_alive(),
                "active": len(self.active),
                "capacity": self.policy.max_concurrency - len(self.active),
                "completed": self.completed, "failed": self.failed,
                "rejected": self.rejected,
                "uptime_s": self._clock() - self.started_at,
                "last_heartbeat": self.last_heartbeat,
            }


class TaskBroker:
    """Task broker — mengoordinasi runner & requester (peran instance n8n).

    Padanan n8n: broker menjadi bagian dari instance n8n/worker; runner
    terhubung lewat WebSocket dan mengambil tugas dari antrean.
    """

    def __init__(self, *, policy: SandboxPolicy,
                 clock: Optional[Callable[[], float]] = None,
                 auth_token: str = "") -> None:
        self.policy = policy
        self._clock = clock or policy._clock
        self.auth_token = auth_token
        self._lock = threading.RLock()
        self.runners: dict[str, TaskRunner] = {}
        self.queue: list[dict] = []
        self.registered = 0
        self.rejected_registrations = 0
        self.dispatched = 0
        self.request_timeouts = 0

    # -- pendaftaran -------------------------------------------------------
    def register(self, runner: TaskRunner, *, token: str = "") -> dict:
        """Daftarkan runner. Token wajib bila broker punya `auth_token`."""
        if self.auth_token and token != self.auth_token:
            with self._lock:
                self.rejected_registrations += 1
            raise SandboxPolicyError(
                "token runner tidak cocok (N8N_RUNNERS_AUTH_TOKEN)")
        with self._lock:
            self.runners[runner.runner_id] = runner
            self.registered += 1
        return {"registered": True, "runner_id": runner.runner_id,
                "runtime": runner.runtime,
                "concurrency": self.policy.max_concurrency}

    def unregister(self, runner_id: str) -> bool:
        with self._lock:
            return self.runners.pop(str(runner_id), None) is not None

    def alive_runners(self, runtime: str = "") -> list[TaskRunner]:
        rt = str(runtime).strip().lower()
        with self._lock:
            rows = list(self.runners.values())
        return [r for r in rows if r.is_alive() and (not rt or r.runtime == rt)]

    # -- penjadwalan -------------------------------------------------------
    def enqueue(self, task: dict) -> str:
        t = dict(task)
        tid = str(t.get("id") or uuid.uuid4().hex[:12])
        t["id"] = tid
        t["enqueued_at"] = self._clock()
        with self._lock:
            self.queue.append(t)
        return tid

    def dispatch_one(self, *, runtime: str = "",
                     now: Optional[float] = None) -> Optional[dict]:
        """Ambil satu tugas dari antrean dan berikan ke runner yang tersedia."""
        t_now = self._clock() if now is None else float(now)
        with self._lock:
            if not self.queue:
                return None
            # Tugas tertua lebih dulu (FIFO), agar tidak ada kelaparan.
            task = self.queue.pop(0)
        rt = str(runtime or task.get("runtime") or "python").strip().lower()
        candidates = [r for r in self.alive_runners(rt) if r.can_accept()]
        if not candidates:
            with self._lock:
                self.queue.insert(0, task)  # kembalikan ke depan antrean
            return None
        # Pilih runner dengan kapasitas terbesar — menyebar beban merata.
        runner = max(candidates, key=lambda r: r.capacity)
        try:
            out = runner.submit(task, now=t_now)
        except SandboxPolicyError as exc:
            out = {"ok": False, "task_id": task["id"],
                   "error": f"{type(exc).__name__}: {exc}"}
        with self._lock:
            self.dispatched += 1
        return {"runner_id": runner.runner_id, "task_id": task["id"],
                "result": out}

    def drain(self, *, max_tasks: int = 10_000,
              now: Optional[float] = None) -> list[dict]:
        """Kosongkan antrean sebanyak mungkin (dipakai uji & drain shutdown)."""
        out: list[dict] = []
        while len(out) < max_tasks:
            r = self.dispatch_one(now=now)
            if r is None:
                break
            out.append(r)
        return out

    def expire_requests(self, *, now: Optional[float] = None) -> int:
        """Buang tugas yang menunggu melebihi `task_request_timeout` (n8n).

        Mencegah workflow menggantung tanpa batas saat tak ada runner.
        """
        t_now = self._clock() if now is None else float(now)
        keep: list[dict] = []
        expired = 0
        with self._lock:
            for task in self.queue:
                waited = t_now - float(task.get("enqueued_at", t_now))
                if waited > self.policy.request_timeout_s:
                    expired += 1
                else:
                    keep.append(task)
            self.queue = keep
            self.request_timeouts += expired
        return expired

    def heartbeat_sweep(self) -> list[str]:
        """Tandai runner yang heartbeat-nya kedaluwarsa (akan dijalankan ulang)."""
        dead: list[str] = []
        with self._lock:
            rows = list(self.runners.values())
        for r in rows:
            if not r.is_alive():
                dead.append(r.runner_id)
        return dead

    def reap_timeouts(self, *, now: Optional[float] = None) -> list[dict]:
        out: list[dict] = []
        with self._lock:
            rows = list(self.runners.values())
        for r in rows:
            for k in r.reap_timeouts(now=now):
                k["runner_id"] = r.runner_id
                out.append(k)
        return out

    def stats(self) -> dict:
        with self._lock:
            runners = list(self.runners.values())
            qlen = len(self.queue)
        return {
            "runners_total": len(runners),
            "runners_alive": len([r for r in runners if r.is_alive()]),
            "runtimes": sorted({r.runtime for r in runners}),
            "queue_depth": qlen,
            "registered": self.registered,
            "rejected_registrations": self.rejected_registrations,
            "dispatched": self.dispatched,
            "request_timeouts": self.request_timeouts,
            "auth_required": bool(self.auth_token),
            "broker_port": self.policy.broker_port,
            "listen_address": self.policy.broker_listen_address,
        }


class TaskRequester:
    """Task requester — padanan Code node; meminta eksekusi ke broker."""

    def __init__(self, broker: TaskBroker, *, node_name: str = "Code",
                 runtime: str = "python") -> None:
        self.broker = broker
        self.node_name = node_name
        self.runtime = runtime

    def request(self, code: str, *, imports: Iterable[str] = (),
                payload_bytes: Optional[int] = None,
                runtime: Optional[str] = None) -> dict:
        """Kirim permintaan tugas; kembalikan hasil atau status menunggu."""
        task = {
            "node": self.node_name,
            "runtime": runtime or self.runtime,
            "code": code,
            "imports": list(imports),
        }
        if payload_bytes is not None:
            task["payload_bytes"] = int(payload_bytes)
        tid = self.broker.enqueue(task)
        res = self.broker.dispatch_one(runtime=task["runtime"])
        if res is None:
            return {"task_id": tid, "status": "queued",
                    "queue_depth": self.broker.stats()["queue_depth"]}
        return {"task_id": tid, "status": "done", **res}


# ---------------------------------------------------------------------------
# Singleton + factory
# ---------------------------------------------------------------------------

_POLICY: Optional[SandboxPolicy] = None


def policy() -> SandboxPolicy:
    global _POLICY
    if _POLICY is None:
        _POLICY = policy_from_env()
    return _POLICY


def set_policy(new: Optional[SandboxPolicy]) -> None:
    global _POLICY
    _POLICY = new


def policy_from_env(env: Optional[dict] = None) -> SandboxPolicy:
    """Bangun kebijakan dari dict env yang disuntik (BUKAN `os.environ`)."""
    e = env if env is not None else os.environ
    defaults = N8N_RUNNER_DEFAULTS
    return SandboxPolicy(
        mode=_env_str(e, "KATALIR_SANDBOX_MODE", defaults["mode"]),
        distroless=_env_flag(e, "KATALIR_SANDBOX_DISTROLESS", False),
        uid=_env_int(e, "KATALIR_SANDBOX_UID", 1000),
        gid=_env_int(e, "KATALIR_SANDBOX_GID", _env_int(
            e, "KATALIR_SANDBOX_UID", 1000)),
        read_only_root=_env_flag(e, "KATALIR_SANDBOX_READONLY_ROOT", False),
        apparmor=_env_flag(e, "KATALIR_SANDBOX_APPARMOR", False),
        max_concurrency=_env_int(e, "KATALIR_SANDBOX_MAX_CONCURRENCY",
                                 defaults["max_concurrency"]),
        task_timeout_s=_env_int(e, "KATALIR_SANDBOX_TASK_TIMEOUT_S",
                                defaults["task_timeout"]),
        heartbeat_interval_s=_env_int(e, "KATALIR_SANDBOX_HEARTBEAT_INTERVAL_S",
                                      defaults["heartbeat_interval"]),
        request_timeout_s=_env_int(e, "KATALIR_SANDBOX_REQUEST_TIMEOUT_S",
                                   defaults["task_request_timeout"]),
        max_payload_bytes=_env_int(e, "KATALIR_SANDBOX_MAX_PAYLOAD_BYTES",
                                   defaults["max_payload"]),
        auto_shutdown_s=_env_int(e, "KATALIR_SANDBOX_AUTOSHUTDOWN_S",
                                 defaults["auto_shutdown_timeout"]),
        broker_port=_env_int(e, "KATALIR_SANDBOX_BROKER_PORT",
                             defaults["broker_port"]),
        broker_listen_address=_env_str(
            e, "KATALIR_SANDBOX_BROKER_LISTEN_ADDRESS",
            defaults["broker_listen_address"]),
        allow_builtin=_csv(e, "KATALIR_SANDBOX_ALLOW_BUILTIN"),
        allow_external=_csv(e, "KATALIR_SANDBOX_ALLOW_EXTERNAL"),
        allow_stdlib=_csv(e, "KATALIR_SANDBOX_ALLOW_STDLIB"),
        allow_py_external=_csv(e, "KATALIR_SANDBOX_ALLOW_PY_EXTERNAL"),
        block_env_access=_env_flag(e, "KATALIR_SANDBOX_BLOCK_ENV_ACCESS", True),
        insecure_mode=_env_flag(e, "KATALIR_SANDBOX_INSECURE_MODE", False),
        allow_prototype_mutation=_env_flag(
            e, "KATALIR_SANDBOX_ALLOW_PROTOTYPE_MUTATION", False),
        require_production=_env_flag(
            e, "KATALIR_SANDBOX_REQUIRE_PRODUCTION", False),
    )


def is_module_allowed(runtime: str, name: str,
                      env: Optional[dict] = None) -> bool:
    return policy_from_env(env).module_allowed(runtime, name)


def check_payload(size_bytes: int, env: Optional[dict] = None) -> None:
    policy_from_env(env).check_payload(size_bytes)


def harden_report(env: Optional[dict] = None) -> dict:
    """Laporan hardening: lapisan aktif + temuan + CVE yang relevan."""
    p = policy_from_env(env)
    findings: list[dict] = []
    if p.mode == "internal":
        findings.append({
            "severity": "high",
            "issue": "mode internal tidak siap produksi",
            "detail": "runner adalah sub-proses dengan uid/gid SAMA dengan "
                      "n8n; sandbox escape (CVE-2026-27495) berarti "
                      "penguasaan penuh host",
            "recommendation": "KATALIR_SANDBOX_MODE=external",
        })
    if not p.distroless:
        findings.append({
            "severity": "medium",
            "issue": "image bukan distroless",
            "detail": "shell & package manager memperbesar permukaan serangan",
            "recommendation": "KATALIR_SANDBOX_DISTROLESS=1 (uid/gid 65532)",
        })
    if not p.read_only_root:
        findings.append({
            "severity": "medium",
            "issue": "root filesystem tidak read-only",
            "detail": "kode jahat dapat memodifikasi berkas sistem di dalam "
                      "kontainer runner",
            "recommendation": "KATALIR_SANDBOX_READONLY_ROOT=1 + emptyDir /tmp",
        })
    if not p.apparmor:
        findings.append({
            "severity": "medium",
            "issue": "profil AppArmor tidak aktif",
            "detail": "/proc/<pid>/{environ,mounts} dapat dibaca sehingga "
                      "variabel lingkungan (termasuk rahasia) bocor",
            "recommendation": "KATALIR_SANDBOX_APPARMOR=1 + profil deny",
        })
    if not p.block_env_access:
        findings.append({
            "severity": "high",
            "issue": "akses lingkungan runner dibuka",
            "detail": "kode Python dapat membaca os.environ (rahasia instance)",
            "recommendation": "KATALIR_SANDBOX_BLOCK_ENV_ACCESS=1",
        })
    if p.insecure_mode:
        findings.append({
            "severity": "critical",
            "issue": "insecure_mode aktif",
            "detail": "seluruh pengaman sandbox dimatikan (n8n: tidak "
                      "disarankan untuk produksi)",
            "recommendation": "matikan KATALIR_SANDBOX_INSECURE_MODE",
        })
    if p.allow_prototype_mutation:
        findings.append({
            "severity": "medium",
            "issue": "mutasi prototipe diizinkan",
            "detail": "membuka kelas serangan prototype pollution",
            "recommendation": "matikan "
                              "KATALIR_SANDBOX_ALLOW_PROTOTYPE_MUTATION",
        })
    if p.allow_builtin and "*" in p.allow_builtin:
        findings.append({
            "severity": "high",
            "issue": "semua modul bawaan JS diizinkan",
            "detail": "termasuk child_process/fs -> eksekusi perintah sistem",
            "recommendation": "ganti '*' dengan allowlist eksplisit",
        })
    return {
        "policy": p.to_dict(),
        "findings": findings,
        "findings_count": len(findings),
        "critical": len([f for f in findings if f["severity"] == "critical"]),
        "high": len([f for f in findings if f["severity"] == "high"]),
        "hardened": p.mode == "external" and p.distroless
        and p.read_only_root and p.apparmor and not p.insecure_mode,
        "known_cves": [dict(c) for c in KNOWN_CVES],
    }


def describe(env: Optional[dict] = None) -> dict:
    """Ringkasan kebijakan untuk API (tanpa rahasia)."""
    e = env if env is not None else os.environ
    p = policy_from_env(e)
    return {
        "modes": list(MODES),
        "production_safe_modes": list(PRODUCTION_SAFE_MODES),
        "runtime_types": list(RUNTIME_TYPES),
        "defaults": dict(N8N_RUNNER_DEFAULTS),
        "python_builtins_denied": list(PY_BUILTINS_DENY_DEFAULT),
        "distroless_uid": DISTROLESS_UID,
        "runner_image": DOCKER_RUNNER_IMAGE,
        "policy": p.to_dict(),
        "isolation_boundary": p.isolation_boundary,
        "production_safe": p.production_safe,
        "known_cves": [dict(c) for c in KNOWN_CVES],
    }
