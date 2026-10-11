#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""3-Tier Agent Testing Pyramid (Metode 2).

  TIER 1 — UNIT untuk tools
      Setiap tool yang didaftarkan harus punya nama unik, skema valid, dan
      deskripsi; `execute_tool` harus menolak nama tak dikenal dengan rapi
      (bukan KeyError mentah). Murah dan deterministik.

  TIER 2 — COGNITIVE EVALS (LLM-as-a-Judge)
      Menilai kualitas semantik output agent. Memakai `tests/judge_harness.py`.
      SKIP jujur kalau gateway tidak tersedia.

  TIER 3 — MULTI-AGENT SIMULATION
      Beberapa agent berbagi satu `queue_mode.MemoryQueueBackend` (modul NYATA
      dari repo). Diuji: semua tugas selesai, TIDAK deadlock (inflight kosong),
      dan konteks tidak hilang antar agent.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

try:  # dipakai sebagai paket (`tests.three_tier_harness`)
    from tests.judge_harness import LLMJudge, deterministic_check
except ImportError:  # dipakai datar (`three_tier_harness`, saat tests/ ada di sys.path)
    from judge_harness import LLMJudge, deterministic_check  # type: ignore


# --------------------------------------------------------------------------
# TIER 1
# --------------------------------------------------------------------------


def tier1_tools(declarations: Optional[list] = None,
                execute_tool: Optional[Callable] = None,
                openai_schemas: Optional[list] = None) -> dict:
    """Unit-check seluruh registry tool. Tidak butuh jaringan."""
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail[:200]})

    if declarations is None:
        try:
            import tools as _t
            declarations = getattr(_t, "TOOL_DECLARATIONS", None)
            openai_schemas = openai_schemas if openai_schemas is not None else getattr(
                _t, "TOOL_SCHEMAS_OPENAI", None)
            execute_tool = execute_tool or getattr(_t, "execute_tool", None)
        except Exception as e:  # noqa: BLE001
            return {"tier": 1, "ok": False, "detail": f"import tools gagal: {e}",
                    "checks": []}

    if not declarations:
        return {"tier": 1, "ok": False, "detail": "TOOL_DECLARATIONS kosong", "checks": []}

    names: list[str] = []
    for i, d in enumerate(declarations):
        nm = _tool_name(d)
        names.append(nm)
        add(f"tool[{i}] punya nama", bool(nm), f"name={nm!r}")
        add(f"tool[{i}] punya deskripsi", bool(_tool_desc(d)),
            f"desc={str(_tool_desc(d))[:60]!r}")
        add(f"tool[{i}] punya parameter/skema", bool(_tool_params(d)),
            f"params={type(_tool_params(d)).__name__}")

    dupes = {n for n in names if n and names.count(n) > 1}
    add("nama tool unik", not dupes, f"duplikat={sorted(dupes)}")

    if openai_schemas:
        ok_shape = all(isinstance(s, dict) and s.get("type") == "function"
                       and isinstance(s.get("function"), dict) for s in openai_schemas)
        add("skema OpenAI berbentuk function-calling", ok_shape,
            f"{len(openai_schemas)} skema")
        same = {s["function"].get("name") for s in openai_schemas if isinstance(s.get("function"), dict)}
        add("skema & deklarasi sinkron",
            bool(same & set(names)),
            f"irisan={len(same & set(names))}")
    else:
        add("skema OpenAI tersedia", False, "TOOL_SCHEMAS_OPENAI kosong")

    if execute_tool:
        try:
            res = execute_tool("__tool_yang_tidak_ada__", {}, "t@test.dev")
            blob = str(res).lower()
            ok = any(w in blob for w in ("tidak dikenal", "unknown", "not found", "tidak ada"))
            add("execute_tool menolak nama tak dikenal dengan pesan", ok, str(res)[:150])
        except KeyError as e:
            add("execute_tool menolak nama tak dikenal dengan pesan", False,
                f"KeyError mentah: {e}")
        except Exception as e:  # noqa: BLE001
            add("execute_tool menolak nama tak dikenal dengan pesan", True,
                f"melempar {type(e).__name__} (dapat diterima): {str(e)[:100]}")
    else:
        add("execute_tool tersedia", False, "tidak ditemukan")

    bad = [c for c in checks if not c["ok"]]
    return {"tier": 1, "ok": not bad, "n_checks": len(checks),
            "n_fail": len(bad), "detail": f"{len(checks) - len(bad)}/{len(checks)} lulus",
            "checks": checks}


def _tool_name(d: Any) -> str:
    if isinstance(d, dict):
        return d.get("name") or (d.get("function") or {}).get("name") or ""
    return getattr(d, "name", "") or ""


def _tool_desc(d: Any) -> str:
    if isinstance(d, dict):
        return d.get("description") or (d.get("function") or {}).get("description") or ""
    return getattr(d, "description", "") or ""


def _tool_params(d: Any) -> Any:
    if isinstance(d, dict):
        return d.get("parameters") or (d.get("function") or {}).get("parameters")
    return getattr(d, "parameters", None)


# --------------------------------------------------------------------------
# TIER 2
# --------------------------------------------------------------------------


def tier2_cognitive(task: str, output: Any, *, judge: Optional[LLMJudge] = None,
                    threshold: float = 0.8, rules: Optional[list] = None) -> dict:
    judge = judge or LLMJudge()
    det = deterministic_check(output, rules or [])
    jr = judge.score(task, output, threshold=threshold)
    if not det["ok"]:
        ok: Optional[bool] = False
    else:
        ok = jr.ok
    return {"tier": 2, "ok": ok, "deterministic": det,
            "judge": {"ok": jr.ok, "scores": jr.scores, "detail": jr.detail},
            "model": judge.model if hasattr(judge, "model") else ""}


# --------------------------------------------------------------------------
# TIER 3
# --------------------------------------------------------------------------


@dataclass
class AgentResult:
    agent: str
    handled: int = 0
    errors: list[str] = field(default_factory=list)


def tier3_multi_agent(n_agents: int = 3, n_tasks: int = 12,
                      timeout_s: float = 20.0,
                      work: Optional[Callable[[str, dict], Any]] = None) -> dict:
    """Simulasi multi-agent NYATA di atas `queue_mode.MemoryQueueBackend`."""
    try:
        from queue_mode import Job, MemoryQueueBackend
    except Exception as e:  # noqa: BLE001
        return {"tier": 3, "ok": None, "detail": f"SKIP: queue_mode tidak dapat diimpor: {e}"}

    backend = MemoryQueueBackend()
    if not backend.available():
        return {"tier": 3, "ok": None, "detail": "SKIP: MemoryQueueBackend tidak tersedia"}

    shared_context: dict[str, Any] = {}
    lock = threading.Lock()
    results: dict[str, AgentResult] = {}
    stop = threading.Event()

    def default_work(agent: str, payload: dict) -> Any:
        with lock:
            shared_context.setdefault("order", []).append(payload["i"])
        return {"by": agent, "i": payload["i"]}

    work_fn = work or default_work

    def worker(agent: str) -> None:
        res = AgentResult(agent)
        results[agent] = res
        while not stop.is_set():
            job = backend.get(timeout=0.25)
            if job is None:
                # dependency kosong -> back-off, JANGAN busy-spin
                # (temuan hard test: tanpa sleep, fault-run 'get' rusak
                #  memutar CPU sampai timeout 20 s penuh)
                time.sleep(0.05)
                continue
            try:
                out = work_fn(agent, job.payload)
                backend.ack(job.id, result=out)
                res.handled += 1
            except Exception as e:  # noqa: BLE001
                res.errors.append(f"{type(e).__name__}: {e}")
                backend.requeue(job.id)
                if len(res.errors) > 3:
                    stop.set()
                time.sleep(0.02)

    # enqueue
    try:
        for i in range(n_tasks):
            backend.put(Job(id=f"job-{i}", payload={"i": i, "task": "order"}))
    except Exception as e:  # noqa: BLE001
        return {"tier": 3, "ok": False, "detail": f"enqueue gagal: {type(e).__name__}: {e}"}

    threads = [threading.Thread(target=worker, args=(f"agent-{k}",), daemon=True)
               for k in range(n_agents)]
    for t in threads:
        t.start()

    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if backend.size() == 0 and not backend.inflight():
            break
        time.sleep(0.05)
    drained = backend.size() == 0 and not backend.inflight()
    stop.set()
    for t in threads:
        t.join(timeout=2)

    handled = sum(r.handled for r in results.values())
    errs = [e for r in results.values() for e in r.errors]
    ctx_ok = sorted(shared_context.get("order", [])) == list(range(n_tasks))

    ok = bool(drained and handled == n_tasks and not errs and ctx_ok)
    return {
        "tier": 3, "ok": ok,
        "detail": (f"selesai={handled}/{n_tasks} inflight_sisa={len(backend.inflight())} "
                   f"deadlock={'YA' if not drained else 'tidak'} "
                   f"konteks_utuh={ctx_ok} error={len(errs)}"),
        "per_agent": {k: v.handled for k, v in results.items()},
        "no_deadlock": drained, "context_preserved": ctx_ok,
        "errors": errs[:5],
    }
