"""TASK 2 — Batch executor FASE 3 untuk eksekusi connector dalam batch.

Tujuan
------
Menjalankan aktivasi/verifikasi connector **dalam batch berukuran tetap (20)**
dengan **gerbang 100% PASS per batch**: batch yang gagal tidak boleh dilewati
begitu saja, harus diperbaiki dan diuji ulang, dan tidak boleh ada regresi pada
batch sebelumnya.

Hubungan dengan modul yang SUDAH ADA (tidak menduplikasi):

| Konsep | Pemiliknya | Peran di sini |
|--------|-----------|---------------|
| Gerbang per-batch | `connector_manifest.BatchGate` | dipakai apa adanya (`BatchGate`) |
| Aktivasi connector | `connector_activator.bulk_activate` / `persist` | mesin eksekusi batch |
| Katalog | `mcp_registry.load_cached` | sumber entri |
| Kosakata manifest | `connector_manifest` | validasi entri |
| Progres lintas-batch | **modul ini** (`BatchExecutor` / `BatchLedger`) | baru |

Brief meminta: 20 connector/batch · gate 100% PASS · progress tracking ·
12 hard test. Modul ini menyediakan kerangka itu tanpa menyentuh mesin
eksekusi yang sudah terbukti di TASK 1.

Desain
------
1. `BatchExecutor` memecah entri menjadi batch `size` (default 20) secara
   deterministik & stabil (urut berdasarkan `id`), sehingga menjalankan ulang
   memberi partisi yang sama.
2. Setiap batch dinilai dengan `BatchGate` (kontrak yang sudah ada): ukuran
   tepat, tidak ada tes gagal, dan **executable bertambah**. Batch yang gagal
   dapat diulang (`retry`) sampai `max_attempts`, dan pemanggil boleh
   menyuntikkan `repair` hook.
3. Progres lintas-batch disimpan di `BatchLedger` (persistable JSON) sehingga
   eksekusi bisa dilanjutkan (resume) setelah berhenti.
4. Semua keputusan **murni/offline** secara default. Jaringan hanya bila
   `verify_network=True` dan disuntikkan lewat `connector_activator`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from connector_manifest import BatchGate

DEFAULT_BATCH_SIZE = 20
LEDGER_PATH = Path(__file__).with_name("connector_batch_progress.json")


class BatchError(ValueError):
    """Batch tidak dapat dijalankan / gagal gate."""


def _entry_id(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("id") or entry.get("slug") or entry.get("name") or "")
    return str(entry)


def chunk_entries(entries: Iterable[Any], size: int = DEFAULT_BATCH_SIZE,
                  ) -> list[list[Any]]:
    """Bagi entri menjadi batch berukuran `size`, urut & deterministik.

    Urutan dilakukan pada `id` supaya menjalankan ulang memberi partisi yang
    identik — penting untuk resume dan untuk membuktikan tidak ada entri yang
    terlewat atau terhitung dua kali.
    """
    if size <= 0:
        raise BatchError("ukuran batch harus > 0")
    rows = sorted(entries, key=_entry_id)
    return [rows[i:i + size] for i in range(0, len(rows), size)]


# ---------------------------------------------------------------------------
# Mesin eksekusi (default: murni/offline lewat connector_activator)
# ---------------------------------------------------------------------------


def default_runner(batch: list[dict], *, verify_network: bool = False,
                   timeout: float = 8.0, max_verify: int = 0,
                   resolver: Callable[[str], bool] | None = None,
                   ) -> tuple[Any, dict]:
    """Jalankan satu batch dengan mesin aktivasi TASK 1.

    Mengembalikan `(ledger, report)` seperti `connector_activator.bulk_activate`.
    """
    import connector_activator as act

    return act.bulk_activate(
        batch, verify_network=verify_network, timeout=timeout,
        max_verify=max_verify, resolver=resolver,
    )


# ---------------------------------------------------------------------------
# Ledger progres lintas-batch
# ---------------------------------------------------------------------------


@dataclass
class BatchLedger:
    """Progres lintas-batch yang dapat dipersist & dilanjutkan (resume).

    `completed` menyimpan id batch yang LULUS gate. `failed` menyimpan yang
    masih gagal. Karena partisi bersifat deterministik, `completed` cukup
    dipakai untuk melewati batch yang sudah lulus saat resume.
    """

    size: int = DEFAULT_BATCH_SIZE
    completed: dict[int, dict] = field(default_factory=dict)
    failed: dict[int, dict] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)

    # -- mutasi -----------------------------------------------------------

    def record(self, batch_no: int, gate: dict, *, attempt: int = 1,
               connector_ids: list[str] | None = None) -> None:
        row = {"batch": int(batch_no), "attempt": int(attempt), **dict(gate)}
        if connector_ids is not None:
            # Simpan id yang benar-benar lulus di batch ini supaya progres bisa
            # diaudit per-connector (bukan cuma agregat "20 selesai").
            row["connector_ids"] = [str(c) for c in connector_ids]
        self.history.append(row)
        if gate.get("verdict") == "PASS":
            self.completed[int(batch_no)] = row
            self.failed.pop(int(batch_no), None)
        else:
            self.failed[int(batch_no)] = row

    def is_done(self, batch_no: int) -> bool:
        return int(batch_no) in self.completed

    # -- ringkasan --------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        return {
            "size": self.size,
            "batches_completed": len(self.completed),
            "batches_failed": len(self.failed),
            "connectors_completed": len(self.completed) * self.size,
            "attempts": len(self.history),
            "passed": sorted(self.completed),
            "failed": sorted(self.failed),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "size": self.size,
            "completed": {str(k): v for k, v in sorted(self.completed.items())},
            "failed": {str(k): v for k, v in sorted(self.failed.items())},
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BatchLedger":
        led = cls(size=int(data.get("size") or DEFAULT_BATCH_SIZE))
        for k, v in (data.get("completed") or {}).items():
            led.completed[int(k)] = v
        for k, v in (data.get("failed") or {}).items():
            led.failed[int(k)] = v
        led.history = list(data.get("history") or [])
        return led


def save_ledger(ledger: BatchLedger, path: str | Path | None = None) -> dict:
    """Tulis ledger progres ke disk secara atomik."""
    p = Path(path) if path else LEDGER_PATH
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger.as_dict(), ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(p)
    return {"path": str(p), "batches_completed": len(ledger.completed)}


def load_ledger(path: str | Path | None = None) -> BatchLedger:
    """Muat ledger progres; bila tidak ada, kembalikan ledger kosong."""
    p = Path(path) if path else LEDGER_PATH
    if not p.exists():
        return BatchLedger()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return BatchLedger()
    if not isinstance(data, dict):
        return BatchLedger()
    return BatchLedger.from_dict(data)


# ---------------------------------------------------------------------------
# Eksekutor batch
# ---------------------------------------------------------------------------


@dataclass
class BatchExecutor:
    """Jalankan banyak batch dengan gerbang 100% PASS + retry + resume.

    Parameter
    ---------
    size
        Ukuran batch (brief: 20).
    max_attempts
        Berapa kali satu batch boleh diulang sebelum dinyatakan gagal.
    runner
        Fungsi eksekusi batch. Dapat disuntikkan untuk pengujian tanpa jaringan.
    repair
        Hook opsional `repair(batch, attempt, gate) -> batch` yang boleh
        memperbaiki entri sebelum diulang. Bila mengembalikan None, batch asli
        dipakai lagi.
    stop_on_fail
        Bila True (default), berhenti pada batch pertama yang gagal setelah
        semua percobaan habis — brief melarang melanjutkan dengan gate gagal.
    """

    size: int = DEFAULT_BATCH_SIZE
    max_attempts: int = 3
    runner: Callable[..., tuple[Any, dict]] = default_runner
    repair: Callable[[list[dict], int, dict], list[dict] | None] | None = None
    stop_on_fail: bool = True
    verify_network: bool = False
    timeout: float = 8.0
    max_verify: int = 0
    resolver: Callable[[str], bool] | None = None
    ledger: BatchLedger = field(default_factory=BatchLedger)

    def __post_init__(self) -> None:
        if self.size <= 0:
            raise BatchError("ukuran batch harus > 0")
        if self.max_attempts <= 0:
            raise BatchError("max_attempts harus > 0")
        if self.ledger.size != self.size:
            self.ledger.size = self.size

    # -- internal ---------------------------------------------------------

    def _gate_for(self, batch: list[dict], report: dict,
                  batch_no: int) -> BatchGate:
        """Bangun `BatchGate` dari laporan runner.

        Aturan gate berasal dari `connector_manifest.BatchGate` (kontrak yang
        sudah ada), jadi batch yang hanya menaikkan jumlah katalog tanpa
        menambah yang benar-benar executable tetap DITOLAK.
        """
        gate = BatchGate(batch_no=batch_no, size=self.size)
        stats = (report or {}).get("stats") or {}
        activated = int(stats.get("activated") or 0)
        skipped = int(stats.get("skipped") or 0)

        ledger = (report or {}).get("_ledger")
        for e in batch:
            cid = _entry_id(e)
            is_exec = bool(ledger and getattr(ledger, "is_active", lambda _x: False)(cid))
            gate.add(cid, passed=1 if is_exec else 0,
                     failed=0 if is_exec else 1, executable=is_exec)

        # Bila runner tidak menyertakan ledger, jatuh ke agregat:
        # `activated` sebagai pass, `skipped` sebagai fail (per batch).
        if ledger is None:
            gate.results = [{
                "id": _entry_id(e),
                "passed": 0,
                "failed": 0,
                "executable": False,
            } for e in batch]
            # Ringkas: perlakukan activated/skipped sebagai tes batch-level.
            gate.results[0]["passed"] = activated
            gate.results[0]["failed"] = skipped
            gate.results[0]["executable"] = activated > 0
        return gate

    def _verdict(self, gate: BatchGate, batch: list[dict]) -> dict:
        v = gate.verdict()
        # `BatchGate.verdict` menuntut len(results)==size. Bila batch terakhir
        # lebih kecil dari `size` (sisa pembagian), itu sah — longgarkan
        # khusus untuk batch ekor supaya tidak salah menolak.
        if len(batch) < self.size:
            v["checks"]["size_ok"] = len(gate.results) == len(batch)
            v["verdict"] = "PASS" if all(v["checks"].values()) else "FAIL"
        v["expected"] = len(batch)
        return v

    # -- publik -----------------------------------------------------------

    def run_batch(self, batch: list[dict], batch_no: int) -> dict:
        """Jalankan satu batch dengan retry; kembalikan record gate terakhir."""
        current = batch
        last: dict = {}
        for attempt in range(1, self.max_attempts + 1):
            ledger, report = self.runner(
                current, verify_network=self.verify_network,
                timeout=self.timeout, max_verify=self.max_verify,
                resolver=self.resolver,
            )
            report = dict(report or {})
            report["_ledger"] = ledger
            gate = self._gate_for(current, report, batch_no)
            last = self._verdict(gate, current)
            last["attempt"] = attempt
            last["duration_s"] = report.get("duration_s")
            if last["verdict"] == "PASS":
                self.ledger.record(batch_no, last, attempt=attempt,
                                   connector_ids=[_entry_id(e) for e in current])
                return last
            if self.repair and attempt < self.max_attempts:
                fixed = self.repair(current, attempt, last)
                if fixed:
                    current = list(fixed)
            self.ledger.record(batch_no, last, attempt=attempt,
                               connector_ids=[_entry_id(e) for e in current])
        return last

    def run(self, entries: list[Any],
            *, resume: bool = True) -> dict:
        """Jalankan seluruh entri. Berhenti pada gate gagal (default brief)."""
        batches = chunk_entries(entries, self.size)
        t0 = time.perf_counter()
        executed = 0
        for i, batch in enumerate(batches, start=1):
            if resume and self.ledger.is_done(i):
                continue
            res = self.run_batch(batch, i)
            executed += 1
            if res["verdict"] != "PASS" and self.stop_on_fail:
                break

        total = len(batches)
        done = len(self.ledger.completed)
        return {
            "batches_total": total,
            "batches_executed": executed,
            "batches_completed": done,
            "batches_failed": len(self.ledger.failed),
            "connectors_total": len(list(entries)),
            "connectors_completed": done * self.size,
            "gate": "PASS" if done == total and not self.ledger.failed else "HALTED",
            "stopped_at": sorted(self.ledger.failed)[:1] or None,
            "duration_s": round(time.perf_counter() - t0, 3),
            "stats": self.ledger.stats(),
        }


def run_batches(entries: list[Any], *, size: int = DEFAULT_BATCH_SIZE,
                runner: Callable[..., tuple[Any, dict]] | None = None,
                verify_network: bool = False,
                resume: bool = False,
                ledger: BatchLedger | None = None,
                **kw) -> dict:
    """Helper fungsional: jalankan semua batch dan kembalikan laporan."""
    ex = BatchExecutor(
        size=size,
        runner=runner or default_runner,
        verify_network=verify_network,
        ledger=ledger or BatchLedger(size=size),
        **kw,
    )
    return ex.run(entries, resume=resume)


def describe() -> dict[str, Any]:
    return {
        "default_batch_size": DEFAULT_BATCH_SIZE,
        "gate": "connector_manifest.BatchGate (100% PASS: size_ok, all_tests_pass, executable_increased)",
        "features": [
            "partisi deterministik (urut id) -> resume aman",
            "retry sampai max_attempts + hook repair",
            "ledger progres dapat dipersist (connector_batch_progress.json)",
            "berhenti pada batch gagal (stop_on_fail) sesuai brief",
            "murni/offline default; jaringan hanya bila verify_network=True",
        ],
        "executor": "connector_activator.bulk_activate (TASK 1)",
    }
