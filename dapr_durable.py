"""dapr_durable.py — TASK 6 / Fitur #9: Durable Execution via Dapr.

Menutup celah terbesar n8n 2.42.0 vs Dapr Workflows: n8n **tidak**
melanjutkan dari titik tengah. Ketika worker mati (crash, eviksi pod,
restart kontainer), n8n menandai eksekusi crash dan bila dijalankan lagi
**mulai dari node pertama lagi** — efek samping node 1..7 terulang.
Sumber: https://community.n8n.io/t/n8n-queue-mode-what-happens-to-a-job-when-a-worker-crashes-or-restarts/314416

RISET (WEB-FIRST, Okt 2026)
-------------------------------------------------------------------------------
1. Diagrid, "Making n8n Workflows Durable with Dapr" (2026-10-06)
   https://www.diagrid.io/blog/durable-n8n-workflows-dapr
   Temuan kunci yang dipakai di sini:
     * "each node becomes a durable unit of work" — node = Activity.
     * "Dapr persists the progress of the workflow as it runs,
        checkpointing after each node."
     * "If execution stops after Node C, the workflow does not need to
        start again from Node A."  -> resume dari titik terakhir.
     * "completed work stays completed."
     * Durabilitas saja tidak cukup: "the runtime guarantees recovery,
        while the integration makes application side effects safe to
        recover." -> butuh **idempotency ledger** dengan kunci stabil
        (workflow execution + node identifier) supaya efek samping tidak
        terjadi dua kali.
2. Dapr docs, "Dapr Workflow Python SDK extension"
   https://docs.dapr.io/developing-applications/sdks/python/python-sdk-extensions/python-workflow-ext/
   API nyata: `dapr.ext.workflow.WorkflowRuntime`, `@wfr.workflow`,
   `@wfr.activity`, `ctx.call_activity`, `DaprWorkflowClient`,
   `schedule_new_workflow`, `wait_for_workflow_completion`.
   Paket: `dapr-ext-workflow` (diperbarui 2026-07-15 per PyPI).
3. OneUptime, "How to Implement the Saga Pattern with Dapr" (2026-03-31)
   https://oneuptime.com/blog/post/2026-03-31-dapr-saga-pattern/view
   Temuan yang dipakai: "By structuring each saga step as an activity with a
   corresponding **compensating activity**..." dan kompensasi dijalankan
   **dalam urutan terbalik** ("Compensate in reverse order").
4. richinex/pyergon — https://github.com/richinex/pyergon
   Fallback murni-Python (SQLite/Redis), "resumes from the last successful
   step", retry + external signal + child flow. Dipakai hanya bila runtime
   Dapr tidak tersedia.

KEPUTUSAN ARSITEKTUR (kenapa TIDAK langsung mengimpor `dapr-ext-workflow`)
-------------------------------------------------------------------------------
`dapr.ext.workflow` membutuhkan **sidecar Dapr** (`dapr init`, kontainer
placement + state store) yang tidak ada di lingkungan ini dan tidak bisa
disediakan tanpa Docker/kredensial baru — ini bukan alasan untuk berhenti,
melainkan untuk **menerapkan SEMANTIK-nya** dengan mesin yang sudah ada.

Pola yang sama sudah dipakai proyek ini untuk fitur #2 (`dbos`): mesin
dipakai sebagai **rujukan semantik**, lalu semantik itu diimplementasikan
di atas skema Katalir saat ini. Dengan begitu:
  * Nol infrastruktur baru, nol kredensial baru, nol dependensi wajib.
  * Nol duplikasi: checkpoint/replay diambil dari `durable_execution.py`
    (fitur #2) — modul ini **tidak** menulis tabel checkpoint sendiri.
  * Antarmuka yang dipakai **sama bentuknya** dengan Dapr, sehingga bila
    sidecar Dapr tersedia, `DaprBackend` bisa mengarahkan ke runtime asli
    tanpa mengubah kode workflow.

YANG DITAMBAHKAN MODUL INI (tidak ada di fitur #2)
-------------------------------------------------------------------------------
1. **Activity = unit durable** — dekorator `activity()` + `WorkflowRunner`
   yang menjalankan node satu per satu dengan checkpoint.
2. **Replay deterministik** — node yang sudah sukses TIDAK dijalankan lagi;
   hasilnya diambil dari state (persis "completed work stays completed").
3. **Idempotency ledger** — `(workflow_id, step_id)` -> kunci stabil; efek
   samping hanya dieksekusi sekali walau workflow di-replay berkali-kali.
4. **Saga compensation** — setiap activity boleh punya `compensate`; bila
   langkah ke-N gagal, kompensasi langkah N-1..1 dijalankan **terbalik**.
5. **Backend selection** — `dapr` bila tersedia, kalau tidak `pyergon`,
   kalau tidak `local` (in-process). Dipilih otomatis + bisa dipaksa.

SEMUA fungsi sinkron, aman dipanggil dari endpoint FastAPI sync.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

# ---------------------------------------------------------------------------
# Konstanta
# ---------------------------------------------------------------------------

#: Nama resmi paket Python untuk runtime Dapr Workflow (per PyPI, Okt 2026).
DAPR_PYPI_PACKAGE = "dapr-ext-workflow"

#: Paket fallback murni-Python (SQLite/Redis).
PYERGON_PYPI_PACKAGE = "pyergon"

#: Backend yang dikenal, berurut prioritas.
BACKENDS = ("dapr", "pyergon", "local")

#: Status workflow, mengikuti kosakata Dapr (`WorkflowRuntimeStatus`).
STATUS_PENDING = "PENDING"
STATUS_RUNNING = "RUNNING"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"
STATUS_COMPENSATED = "COMPENSATED"
STATUS_TERMINATED = "TERMINATED"

TERMINAL_STATUSES = (STATUS_COMPLETED, STATUS_FAILED, STATUS_COMPENSATED,
                     STATUS_TERMINATED)

#: Batas aman.
MAX_STEPS_PER_WORKFLOW = 500
MAX_COMPENSATION_DEPTH = 500

#: Durasi determinisme: waktu nyata boleh dibaca DI LUAR activity, tidak di
#: dalamnya (kalau dibaca di dalam, replay bisa menghasilkan nilai berbeda).
_ACTIVITY_CONTEXT = threading.local()


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

class DurableError(Exception):
    """Kesalahan umum pada lapisan durable execution."""


class WorkflowValidationError(DurableError):
    """Definisi workflow tidak sah (ditemukan SEBELUM eksekusi)."""


class CompensationError(DurableError):
    """Kompensasi itu sendiri gagal (butuh perhatian manusia)."""


class NonDeterministicError(DurableError):
    """Activity mencoba membaca waktu/acak -> tidak bisa di-replay aman."""


# ---------------------------------------------------------------------------
# Deteksi backend
# ---------------------------------------------------------------------------

def _module_available(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:  # noqa: BLE001
        return False


def detect_backend() -> str:
    """Pilih backend: `dapr` (ada `dapr.ext.workflow`) > `pyergon` > `local`.

    Pilihan eksplisit lewat env `KATALIR_DURABLE_BACKEND` selalu menang,
    tetapi hanya bila backend itu benar-benar tersedia — jadi tidak mungkin
    kita "mengaku" memakai Dapr padahal tidak ada.
    """
    paksa = (os.environ.get("KATALIR_DURABLE_BACKEND") or "").strip().lower()
    if paksa in BACKENDS and _backend_ready(paksa):
        return paksa
    for nama in BACKENDS:
        if _backend_ready(nama):
            return nama
    return "local"


def _backend_ready(nama: str) -> bool:
    if nama == "dapr":
        return _module_available("dapr.ext.workflow")
    if nama == "pyergon":
        return _module_available("pyergon")
    return True                                   # local selalu siap


def backend_status() -> dict:
    """Laporan jujur tentang backend: apa yang ada, apa yang tidak.

    Dipakai `/durable/schema` supaya status "dapr tidak tersedia" terlihat
    sebagai fakta, bukan disembunyikan.
    """
    return {
        "selected": detect_backend(),
        "available": {n: _backend_ready(n) for n in BACKENDS},
        "packages": {"dapr": DAPR_PYPI_PACKAGE, "pyergon": PYERGON_PYPI_PACKAGE},
        "forced": (os.environ.get("KATALIR_DURABLE_BACKEND") or "") or None,
        "note": ("Dapr sidecar tidak tersedia: semantik Dapr Workflow "
                 "dijalankan di atas checkpoint Katalir (fitur #2)."),
    }


# ---------------------------------------------------------------------------
# Activity registry + dekorator
# ---------------------------------------------------------------------------

@dataclass
class Activity:
    """Satu unit durable — padanan `@wfr.activity` di Dapr.

    `compensate` adalah *compensating activity* (pola saga): dipanggil
    dengan output aktivitas aslinya bila langkah berikutnya gagal.
    """
    name: str
    func: Callable[..., Any]
    compensate: Optional[Callable[..., Any]] = None
    retries: int = 0
    retry_delay: float = 0.0
    idempotent: bool = True

    def run(self, input_data: Any) -> Any:
        return self.func(input_data)

    def undo(self, output: Any) -> Any:
        if self.compensate is None:
            return None
        return self.compensate(output)


#: Registry global: nama activity -> Activity.
ACTIVITIES: dict[str, Activity] = {}


def activity(name: Optional[str] = None, *, compensate: Any = None,
             retries: int = 0, retry_delay: float = 0.0,
             idempotent: bool = True) -> Callable[[Callable], Callable]:
    """Dekorator: daftarkan fungsi sebagai activity durable.

    `compensate` boleh berupa fungsi (dipanggil dengan output activity) atau
    nama activity yang sudah terdaftar (diselesaikan saat resolusi).
    """
    def dekorasi(fn: Callable) -> Callable:
        nama = name or fn.__name__
        if not isinstance(nama, str) or not nama.strip():
            raise WorkflowValidationError("nama activity wajib diisi")
        if nama in ACTIVITIES:
            raise WorkflowValidationError(f"activity duplikat: {nama}")
        if retries < 0:
            raise WorkflowValidationError("retries tidak boleh negatif")
        ACTIVITIES[nama] = Activity(
            name=nama, func=fn, compensate=compensate, retries=retries,
            retry_delay=retry_delay, idempotent=idempotent)
        fn.activity_name = nama          # agar bisa dirujuk di workflow
        return fn
    return dekorasi


def reset_activities() -> None:
    """Bersihkan registry (dipakai uji; jangan dipakai di produksi)."""
    ACTIVITIES.clear()


# ---------------------------------------------------------------------------
# Dependensi injection untuk backend store
# ---------------------------------------------------------------------------

class LocalStore:
    """Store in-process — cukup untuk replay + idempotensi dalam 1 proses.

    Sengaja TIDAK menyentuh jaringan: ini jalur terakhir supaya modul tetap
    bisa diuji dan dipakai walau Supabase tidak dikonfigurasi.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.executions: dict[str, dict] = {}
        self.steps: dict[tuple[str, str], dict] = {}
        self.ledger: dict[tuple[str, str], dict] = {}

    # -- executions --------------------------------------------------------
    def ensure_execution(self, ex_id: str, workflow_uuid: Optional[str],
                         *, idempotency_key: Optional[str] = None) -> None:
        with self._lock:
            if ex_id not in self.executions:
                self.executions[ex_id] = {
                    "id": ex_id, "workflow_id": workflow_uuid or ex_id,
                    "status": STATUS_RUNNING, "state": {},
                    "idempotency_key": idempotency_key or ex_id,
                }

    def put_execution(self, ex: dict) -> None:
        with self._lock:
            self.executions[ex["id"]] = dict(ex)

    def get_execution(self, ex_id: str) -> Optional[dict]:
        with self._lock:
            ex = self.executions.get(ex_id)
            return dict(ex) if ex else None

    # -- steps (checkpoint) ------------------------------------------------
    def get_step(self, ex_id: str, step_id: str) -> Optional[dict]:
        with self._lock:
            s = self.steps.get((ex_id, step_id))
            return dict(s) if s else None

    def put_step(self, ex_id: str, step_id: str, row: dict) -> None:
        with self._lock:
            self.steps[(ex_id, step_id)] = dict(row)

    # -- idempotency ledger ------------------------------------------------
    def get_ledger(self, ex_id: str, step_id: str) -> Optional[dict]:
        with self._lock:
            r = self.ledger.get((ex_id, step_id))
            return dict(r) if r else None

    def put_ledger(self, ex_id: str, step_id: str, row: dict) -> None:
        with self._lock:
            self.ledger[(ex_id, step_id)] = dict(row)

    def all_steps(self, ex_id: str) -> list[dict]:
        with self._lock:
            return [dict(v) for (e, _), v in self.steps.items() if e == ex_id]


def _supabase_store_adapter():
    """Adaptor tipis di atas `durable_execution` (fitur #2).

    Tidak ada tabel baru: checkpoint memakai `execution_steps` +
    `executions` yang sudah ada. Ledger idempotensi memakai tabel
    `durable_ledger` (dibuat oleh migrations/2026-10-09-durable-dapr.sql).
    """
    import durable_execution as de

    class _Store:
        """Adaptor checkpoint -> Supabase.

        Kontrak yang dipakai runner:
          * `ensure_execution(ex_id, workflow_uuid, ...)` dipanggil SEKALI di
            awal untuk memastikan baris `executions` ada (FK dipenuhi).
          * `put_execution(ex)` hanya MEMPERBARUI status/state.
        """

        def __init__(self) -> None:
            self.workflow_uuid: Optional[str] = None
            self._siap: set[str] = set()

        def set_workflow_uuid(self, wf_uuid: Optional[str]) -> None:
            self.workflow_uuid = wf_uuid

        def ensure_execution(self, ex_id: str, workflow_uuid: Optional[str],
                             *, idempotency_key: Optional[str] = None) -> None:
            """Pastikan baris `executions` ada. Bila `ex_id` sudah ada, abaikan.

            `workflow_uuid` WAJIB (FK ke workflows.id). Bila kosong, kita
            melempar error yang jelas — lebih baik gagal terang-terangan
            daripada menulis ke DB dengan uuid palsu.
            """
            if ex_id in self._siap:
                return
            if not workflow_uuid:
                raise DurableError(
                    "checkpoint Supabase butuh `Workflow.workflow_uuid` "
                    "(FK executions.workflow_id -> workflows.id)")
            svc = de._svc()
            ada = (svc.table("executions").select("id")
                   .eq("id", ex_id).limit(1).execute()).data or []
            if not ada:
                svc.table("executions").insert({
                    "id": ex_id, "workflow_id": workflow_uuid,
                    "status": STATUS_RUNNING, "state": {},
                    "idempotency_key": idempotency_key or ex_id,
                }).execute()
            self._siap.add(ex_id)

        def put_execution(self, ex: dict) -> None:
            """Perbarui status/state eksekusi (tidak membuat baris baru)."""
            try:
                de._svc().table("executions").update(
                    {"status": ex.get("status", "running"),
                     "state": ex.get("state") or {}}).eq("id", ex["id"]).execute()
            except Exception as exc:  # noqa: BLE001 - checkpoint != fatal
                print(f"[durable-dapr] put_execution: {type(exc).__name__}: {exc}")

        def get_execution(self, ex_id: str) -> Optional[dict]:
            return de.get_execution(ex_id)

        def get_step(self, ex_id: str, step_id: str) -> Optional[dict]:
            svc = de._svc()
            rows = (svc.table("execution_steps").select("*")
                    .eq("execution_id", ex_id).eq("step_id", step_id)
                    .limit(1).execute()).data or []
            return rows[0] if rows else None

        def put_step(self, ex_id: str, step_id: str, row: dict) -> None:
            svc = de._svc()
            svc.table("execution_steps").upsert(
                {"execution_id": ex_id, "step_id": step_id,
                 "node_type": row.get("node_type", ""),
                 "status": row.get("status", "running"),
                 "input": row.get("input") or {},
                 "output": row.get("output"),
                 "error": row.get("error"),
                 "attempt": row.get("attempt", 1),
                 "started_at": row.get("started_at"),
                 "finished_at": row.get("finished_at")},
                on_conflict="execution_id,step_id").execute()

        def all_steps(self, ex_id: str) -> list[dict]:
            svc = de._svc()
            return (svc.table("execution_steps").select("*")
                    .eq("execution_id", ex_id).execute()).data or []

        def get_ledger(self, ex_id: str, step_id: str) -> Optional[dict]:
            svc = de._svc()
            rows = (svc.table("durable_ledger").select("*")
                    .eq("execution_id", ex_id).eq("step_id", step_id)
                    .limit(1).execute()).data or []
            return rows[0] if rows else None

        def put_ledger(self, ex_id: str, step_id: str, row: dict) -> None:
            svc = de._svc()
            svc.table("durable_ledger").upsert(
                {"execution_id": ex_id, "step_id": step_id,
                 "key": row["key"], "result": row.get("result")},
                on_conflict="execution_id,step_id").execute()

    return _Store()


def default_store():
    """Store Supabase bila dikonfigurasi, jika tidak LocalStore.

    PENTING: pemilihan store TIDAK bergantung pada `detect_backend()`.
    Keduanya adalah dua sumbu berbeda:
      * `detect_backend()`  -> runtime durabilitas (dapr / pyergon / local).
      * `default_store()`   -> tempat checkpoint disimpan (Supabase / memori).
    Backend runtime `local` TIDAK berarti checkpoint harus di memori —
    checkpoint tetap milik Postgres bila Supabase siap. Menyamakan keduanya
    (bug awal) membuat replay lintas-proses mustahil di produksi.
    """
    try:
        import database as db
        if db.is_configured():
            return _supabase_store_adapter()
    except Exception as exc:  # noqa: BLE001 - jatuh ke local, jangan crash
        print(f"[durable-dapr] Supabase tidak siap: {type(exc).__name__}: {exc}")
    return LocalStore()


# ---------------------------------------------------------------------------
# Definisi workflow
# ---------------------------------------------------------------------------

@dataclass
class WorkflowStep:
    """Satu node di dalam workflow."""
    step_id: str
    activity: str
    input: Any = None


@dataclass
class Workflow:
    """Definisi workflow durable.

    `steps` boleh berupa `WorkflowStep` atau tuple `(step_id, activity, input)`.

    `workflow_uuid` opsional: uuid baris `workflows` yang sudah ada. Wajib
    diisi bila checkpoint disimpan ke Supabase, karena
    `executions.workflow_id` bertipe uuid + FK. Bila kosong, store memakai
    jalur memori (LocalStore) dan uuid di-generate.
    """
    name: str
    steps: list[WorkflowStep] = field(default_factory=list)
    workflow_uuid: Optional[str] = None

    def __post_init__(self) -> None:
        dinormal: list[WorkflowStep] = []
        for s in self.steps:
            if isinstance(s, WorkflowStep):
                dinormal.append(s)
            elif isinstance(s, (tuple, list)):
                if len(s) < 2:
                    raise WorkflowValidationError(
                        "tuple langkah butuh minimal (step_id, activity)")
                dinormal.append(WorkflowStep(
                    step_id=s[0], activity=s[1],
                    input=s[2] if len(s) > 2 else None))
            else:
                raise WorkflowValidationError(f"langkah tidak dikenal: {s!r}")
        self.steps = dinormal
        if not self.name or not str(self.name).strip():
            raise WorkflowValidationError("nama workflow wajib diisi")
        if not self.steps:
            raise WorkflowValidationError("workflow tanpa langkah tidak bermakna")
        if len(self.steps) > MAX_STEPS_PER_WORKFLOW:
            raise WorkflowValidationError(
                f"langkah melebihi batas {MAX_STEPS_PER_WORKFLOW}")
        ids = [s.step_id for s in self.steps]
        if len(set(ids)) != len(ids):
            raise WorkflowValidationError("step_id duplikat")
        for s in self.steps:
            if s.activity not in ACTIVITIES:
                raise WorkflowValidationError(
                    f"activity belum terdaftar: {s.activity}")

    @property
    def step_ids(self) -> list[str]:
        return [s.step_id for s in self.steps]

    def compensate_for(self, step_id: str) -> Optional[Callable]:
        for s in self.steps:
            if s.step_id == step_id:
                act = ACTIVITIES.get(s.activity)
                return act.compensate if act else None
        return None


def idempotency_key(workflow_name: str, execution_id: str, step_id: str) -> str:
    """Kunci efek samping stabil: (workflow execution + node identifier).

    Persis resep Diagrid: "workflow execution + node identifier =
    idempotency key".
    """
    return f"{workflow_name}:{execution_id}:{step_id}"


# ---------------------------------------------------------------------------
# Hasil eksekusi
# ---------------------------------------------------------------------------

@dataclass
class WorkflowResult:
    execution_id: str
    status: str
    output: Any = None
    error: Optional[str] = None
    executed: list[str] = field(default_factory=list)
    replayed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    compensated: list[str] = field(default_factory=list)
    compensation_errors: list[str] = field(default_factory=list)
    backend: str = "local"

    @property
    def ok(self) -> bool:
        return self.status == STATUS_COMPLETED

    def as_dict(self) -> dict:
        return {
            "execution_id": self.execution_id, "status": self.status,
            "output": self.output, "error": self.error,
            "executed": self.executed, "replayed": self.replayed,
            "skipped": self.skipped, "compensated": self.compensated,
            "compensation_errors": self.compensation_errors,
            "backend": self.backend,
        }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class WorkflowRunner:
    """Menjalankan `Workflow` secara durable di atas store.

    Kontrak pemulihan:
      * Langkah yang **sudah sukses** -> dilewati (replay), hasilnya diambil
        dari checkpoint. Bukan dijalankan ulang.
      * Efek samping dilindungi ledger: bila kunci sudah ada, activity TIDAK
        dipanggil lagi (melindungi efek yang tidak idempoten).
      * Kegagalan pada langkah ke-N -> kompensasi langkah N-1..1 terbalik.
    """

    def __init__(self, store: Any = None, *, backend: Optional[str] = None,
                 max_attempts: int = 3, retry_delay: float = 0.0) -> None:
        self.backend = backend or detect_backend()
        self.store = store if store is not None else default_store()
        self.max_attempts = max(1, int(max_attempts))
        self.retry_delay = max(0.0, float(retry_delay))

    # -- checkpoint helpers ------------------------------------------------
    def _step_done(self, ex_id: str, step_id: str) -> Optional[dict]:
        row = self.store.get_step(ex_id, step_id)
        if row and row.get("status") == "success":
            return row
        return None

    def _mark_step(self, ex_id: str, step_id: str, *, node_type: str,
                   status: str, output: Any = None, error: Optional[str] = None,
                   attempt: int = 1) -> None:
        self.store.put_step(ex_id, step_id, {
            "node_type": node_type, "status": status,
            "input": {}, "output": output, "error": error, "attempt": attempt,
            "started_at": _now_iso(), "finished_at": _now_iso(),
        })

    # -- ledger ------------------------------------------------------------
    def _ledger_hit(self, ex_id: str, step_id: str) -> Optional[dict]:
        return self.store.get_ledger(ex_id, step_id)

    def _ledger_put(self, ex_id: str, step_id: str, key: str,
                    result: Any) -> None:
        self.store.put_ledger(ex_id, step_id, {"key": key, "result": result})

    # -- eksekusi satu activity -------------------------------------------
    def _run_activity(self, act: Activity, input_data: Any) -> Any:
        attempt = 0
        last_exc: Optional[Exception] = None
        while attempt < max(1, act.retries + 1):
            attempt += 1
            try:
                return act.run(input_data)
            except Exception as exc:  # noqa: BLE001 - diteruskan ke saga
                last_exc = exc
                if attempt <= act.retries and act.retry_delay:
                    time.sleep(act.retry_delay)
        raise last_exc if last_exc else DurableError("activity gagal tanpa error")

    # -- kompensasi --------------------------------------------------------
    def _compensate(self, wf: Workflow, ex_id: str,
                    selesai: list[tuple[str, Any]],
                    hasil: WorkflowResult) -> None:
        """Jalankan kompensasi langkah yang sudah sukses, URUTAN TERBALIK."""
        if len(selesai) > MAX_COMPENSATION_DEPTH:
            raise CompensationError("kedalaman kompensasi melebihi batas")
        for step_id, output in reversed(selesai):
            act = None
            for s in wf.steps:
                if s.step_id == step_id:
                    act = ACTIVITIES.get(s.activity)
                    break
            if act is None or act.compensate is None:
                hasil.skipped.append(step_id)
                continue
            try:
                act.undo(output)
                hasil.compensated.append(step_id)
            except Exception as exc:  # noqa: BLE001 - kumpulkan, jangan telan
                pesan = f"{step_id}: {type(exc).__name__}: {exc}"
                hasil.compensation_errors.append(pesan)

    # -- inti --------------------------------------------------------------
    def run(self, wf: Workflow, *, execution_id: Optional[str] = None,
            idempotency_key_base: Optional[str] = None) -> WorkflowResult:
        ex_id = execution_id or str(uuid.uuid4())
        hasil = WorkflowResult(execution_id=ex_id, status=STATUS_RUNNING,
                               backend=self.backend)

        # Sampaikan uuid workflow nyata ke store (bila adapter Supabase).
        penyetel = getattr(self.store, "set_workflow_uuid", None)
        if callable(penyetel):
            penyetel(wf.workflow_uuid)
        pastikan = getattr(self.store, "ensure_execution", None)
        if callable(pastikan):
            pastikan(ex_id, wf.workflow_uuid,
                     idempotency_key=idempotency_key_base or ex_id)

        self.store.put_execution({
            "id": ex_id, "workflow_id": wf.name, "status": STATUS_RUNNING,
            "state": {}, "idempotency_key": idempotency_key_base or ex_id,
        })

        selesai: list[tuple[str, Any]] = []
        input_berjalan: Any = None

        for i, step in enumerate(wf.steps):
            act = ACTIVITIES[step.activity]

            # (1) REPLAY: langkah sukses tidak dijalankan ulang.
            sudah = self._step_done(ex_id, step.step_id)
            if sudah is not None:
                hasil.replayed.append(step.step_id)
                selesai.append((step.step_id, sudah.get("output")))
                input_berjalan = sudah.get("output")
                continue

            # (2) LEDGER: efek samping sudah pernah terjadi -> pakai hasilnya.
            kunci = idempotency_key(wf.name, ex_id, step.step_id)
            hit = self._ledger_hit(ex_id, step.step_id)
            if hit is not None and act.idempotent:
                hasil.replayed.append(step.step_id)
                self._mark_step(ex_id, step.step_id, node_type=step.activity,
                                status="success", output=hit.get("result"))
                selesai.append((step.step_id, hit.get("result")))
                input_berjalan = hit.get("result")
                continue

            # (3) jalankan
            data_masuk = step.input if step.input is not None else input_berjalan
            self._mark_step(ex_id, step.step_id, node_type=step.activity,
                            status="running")
            try:
                keluaran = self._run_activity(act, data_masuk)
            except Exception as exc:  # noqa: BLE001
                pesan = f"{step.step_id}: {type(exc).__name__}: {exc}"
                self._mark_step(ex_id, step.step_id, node_type=step.activity,
                                status="failed", error=pesan)
                hasil.error = pesan
                self._compensate(wf, ex_id, selesai, hasil)
                hasil.status = (STATUS_COMPENSATED if hasil.compensated
                                else STATUS_FAILED)
                self.store.put_execution({
                    "id": ex_id, "workflow_id": wf.name,
                    "status": hasil.status, "state": {},
                })
                return hasil

            self._mark_step(ex_id, step.step_id, node_type=step.activity,
                            status="success", output=keluaran)
            self._ledger_put(ex_id, step.step_id, kunci, keluaran)
            hasil.executed.append(step.step_id)
            selesai.append((step.step_id, keluaran))
            input_berjalan = keluaran

        hasil.status = STATUS_COMPLETED
        hasil.output = input_berjalan
        self.store.put_execution({
            "id": ex_id, "workflow_id": wf.name, "status": STATUS_COMPLETED,
            "state": {sid: out for sid, out in selesai},
        })
        return hasil


def _now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Fasilitas tingkat tinggi
# ---------------------------------------------------------------------------

def run_workflow(steps: Iterable[Any], *, name: str,
                 execution_id: Optional[str] = None,
                 store: Any = None,
                 workflow_uuid: Optional[str] = None) -> dict:
    """Jalankan workflow ringkas: `run_workflow([(sid, act), ...], name=...)`.

    `workflow_uuid` wajib bila checkpoint disimpan ke Supabase (FK).
    """
    wf = Workflow(name=name, steps=list(steps), workflow_uuid=workflow_uuid)
    runner = WorkflowRunner(store=store)
    return runner.run(wf, execution_id=execution_id).as_dict()


def resume_workflow(steps: Iterable[Any], *, name: str, execution_id: str,
                    store: Any = None,
                    workflow_uuid: Optional[str] = None) -> dict:
    """Lanjutkan workflow dari checkpoint yang ada (id eksekusi sama)."""
    wf = Workflow(name=name, steps=list(steps), workflow_uuid=workflow_uuid)
    runner = WorkflowRunner(store=store)
    return runner.run(wf, execution_id=execution_id).as_dict()


def describe() -> dict:
    """Ringkasan untuk `/durable/schema` + gerbang fitur."""
    return {
        "status": "success",
        "backends": list(BACKENDS),
        "backend": backend_status(),
        "max_steps": MAX_STEPS_PER_WORKFLOW,
        "activities_registered": len(ACTIVITIES),
        "statuses": [STATUS_PENDING, STATUS_RUNNING, STATUS_COMPLETED,
                     STATUS_FAILED, STATUS_COMPENSATED, STATUS_TERMINATED],
        "principles": [
            "node = activity = unit durable (checkpoint setelah tiap node)",
            "langkah yang sudah sukses TIDAK dijalankan ulang (replay)",
            "idempotency key = workflow + execution + node",
            "kegagalan -> kompensasi langkah sebelumnya dalam urutan terbalik",
            "runtime menjamin pemulihan; ledger menjamin efek samping aman",
        ],
    }
