"""subworkflow_batch.py — pola fan-out sub-workflow: `mode: all|each` +
fire-and-forget (dengan pelacakan selesai + batas waktu).

Referensi (skill-first, brief 11 Okt 2026):
  `SUBWORKFLOW_PATTERNS.md` — dari `czlonkowski/n8n-skills`
  (`skills/n8n-subworkflows/SUBWORKFLOW_PATTERNS.md`), diindeks oleh
  `sickn33/agentic-awesome-skills` (`skills_index.json` -> `n8n-subworkflows`).

Dua pola yang belum ada di `subworkflow.py` (yang sudah menegakkan kedalaman
maksimum 3 + siklus):

  1. **`mode: all` vs `each`** — `all` = satu run dengan SEMUA item; `each` =
     N run, satu item per run. Bedanya penting ketika body sub-workflow
     mengasumsikan "saya melihat tepat SATU item" (agregasi per-run, tulis
     sekali per input).
  2. **Fire-and-forget** (`mode: each` + `waitForSubWorkflow: false`) — satu-
     satunya cara mendapat eksekusi sub-workflow yang benar-benar paralel.
     Jebakannya: pemanggil tidak tahu kapan/ apakah anak selesai, jadi WAJIB
     ada mekanisme pelacakan selesai + **batas waktu** supaya job yang mati
     tidak menggantung loop selamanya.

Modul ini MURNI (tanpa I/O) supaya bisa diuji tanpa DB/jaringan: ia hanya
menyusun rencana dispatch dan mengevaluasi status. Eksekusi nyata tetap di
`subworkflow.invoke_subworkflow`.
"""
from __future__ import annotations

from typing import Any

#: Mode dispatch yang sah (mengikuti `Execute Workflow` di n8n).
MODES = ("all", "each")

#: Status yang dianggap SELESAI (tidak akan berubah lagi).
TERMINAL_STATUSES = frozenset(
    {"success", "error", "failed", "timeout", "cancelled", "skipped"}
)

#: Batas jumlah job agar fan-out tidak jadi permukaan DoS.
MAX_JOBS = 1000

#: Batas waktu bawaan (detik) sebelum job yang masih `inProgress` di-timeout.
DEFAULT_RUNTIME_CAP_SEC = 900


class BatchPlanError(ValueError):
    """Rencana dispatch tidak valid (pesan menyebut penyebabnya)."""


def _order_key(r: dict) -> tuple[int, int, str]:
    """Kunci urut job yang TAHAN id berangka.

    Kenapa bukan sekadar `sorted(job_id)`: urutan string menaruh "run:10"
    SEBELUM "run:2" (leksikografis), sehingga agregasi jadi salah urut.
    Ini ditemukan oleh hard test (test_15). Utamakan field `index` bila ada,
    kalau tidak parsing sufiks angka pada job_id.
    """
    idx = r.get("index")
    if isinstance(idx, int):
        return (0, idx, "")
    jid = str(r.get("job_id") or "")
    tail = jid.rsplit(":", 1)[-1]
    if tail.isdigit():
        return (0, int(tail), "")
    return (1, 0, jid)


def plan_dispatch(
    items: list[Any],
    *,
    mode: str = "all",
    wait_for: bool = True,
    run_id: str = "run",
    max_jobs: int = MAX_JOBS,
) -> dict:
    """Susun rencana dispatch untuk `items`.

    Return:
      {
        "mode": "all"|"each",
        "run_id": str,
        "parallel": bool,          # mode=each DAN wait_for=False
        "runs": [[item, ...], ...],# item per run
        "jobs": [{job_id, index, item}, ...],
        "count": int,              # jumlah run
      }

    `mode="all"` -> 1 run berisi semua item (0 run bila item kosong).
    `mode="each"` -> N run, satu item per run.
    """
    if mode not in MODES:
        raise BatchPlanError(
            f"mode tidak dikenal: {mode!r} (sah: {', '.join(MODES)}).")
    if not isinstance(items, list):
        raise BatchPlanError("items harus berupa daftar.")

    if mode == "all":
        runs = [list(items)] if items else []
        jobs = ([{"job_id": f"{run_id}:0", "index": 0, "item": items}]
                if items else [])
    else:  # each
        runs = [[it] for it in items]
        jobs = [
            {"job_id": f"{run_id}:{i}", "index": i, "item": it}
            for i, it in enumerate(items)
        ]

    if len(jobs) > max_jobs:
        raise BatchPlanError(
            f"terlalu banyak job: {len(jobs)} > batas {max_jobs}.")

    return {
        "mode": mode,
        "run_id": run_id,
        "parallel": bool(mode == "each" and not wait_for),
        "runs": runs,
        "jobs": jobs,
        "count": len(runs),
    }


def evaluate_completion(
    rows: list[dict],
    *,
    run_id: str | None = None,
    elapsed_sec: float = 0.0,
    runtime_cap_sec: float = DEFAULT_RUNTIME_CAP_SEC,
    poll_interval_sec: int = 5,
) -> dict:
    """Evaluasi status kumpulan job (pola poll fire-and-forget).

    `rows` = baris pelacakan selesai, tiap baris minimal
    `{"run_id": str, "job_id": str, "status": str, "output": Any}`.

    Return:
      {
        "state": "done" | "waiting" | "timed_out",
        "terminal": int, "pending": int,
        "timed_out_jobs": [job_id, ...],
        "aggregate": [output, ...],   # hanya saat "done"
        "next_poll_sec": int | None,  # hanya saat "waiting"
      }

    Aturan (persis SUBWORKFLOW_PATTERNS.md):
      * semua terminal            -> done  (agregasi hasil)
      * ada pending & masih < cap -> waiting (poll lagi setelah N detik)
      * ada pending & >= cap      -> timed_out (sisa job ditandai timeout,
                                     jadi job yang mati TIDAK menggantung)
    """
    rel = [r for r in (rows or []) if isinstance(r, dict)
           and (run_id is None or str(r.get("run_id")) == str(run_id))]
    if not rel:
        # Tidak ada job = selesai secara vakum (bukan menggantung).
        return {"state": "done", "terminal": 0, "pending": 0,
                "timed_out_jobs": [], "aggregate": [], "next_poll_sec": None}

    def _st(r: dict) -> str:
        return str(r.get("status") or "").lower()

    pending = [r for r in rel if _st(r) not in TERMINAL_STATUSES]
    terminal = len(rel) - len(pending)

    if not pending:
        ordered = sorted(rel, key=_order_key)
        return {"state": "done", "terminal": terminal, "pending": 0,
                "timed_out_jobs": [], "aggregate": [r.get("output") for r in ordered],
                "next_poll_sec": None}

    if float(elapsed_sec) >= float(runtime_cap_sec):
        timed_out = sorted(str(r.get("job_id") or "") for r in pending)
        return {"state": "timed_out", "terminal": terminal,
                "pending": len(pending), "timed_out_jobs": timed_out,
                "aggregate": [], "next_poll_sec": None}

    return {"state": "waiting", "terminal": terminal, "pending": len(pending),
            "timed_out_jobs": [], "aggregate": [],
            "next_poll_sec": int(poll_interval_sec)}


def describe() -> dict[str, Any]:
    """Deskripsi pola (dipakai katalog agen/MCP + dokumentasi)."""
    return {
        "module": "subworkflow_batch",
        "reference": "SUBWORKFLOW_PATTERNS.md (n8n-subworkflows)",
        "modes": list(MODES),
        "terminal_statuses": sorted(TERMINAL_STATUSES),
        "limits": {"max_jobs": MAX_JOBS,
                   "default_runtime_cap_sec": DEFAULT_RUNTIME_CAP_SEC},
    }
