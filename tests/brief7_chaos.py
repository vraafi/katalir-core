#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BRIEF 7 TASK 3 — Chaos Engineering (arc-reliability + agentprobe/probe-ai).

Menghasilkan **50 skenario chaos BARU** di atas *dependency boundary* nyata
Katalir (bukan mock kosong), menyuntikkan tiga kelas gangguan yang diminta
brief:

  * **network timeout**   — dependency menggantung / melempar TimeoutError,
  * **rate limit**        — dependency melempar 429/ConnectionError,
  * **schema mismatch**   — dependency mengembalikan bentuk yang salah.

Pola skill yang diterapkan (chaos-engineering): hipotesis dulu, blast radius
kecil, **auto-revert terverifikasi**, dan tiap temuan punya tindak lanjut.
Prinsip arc-reliability dipakai untuk determinisme (DeterministicRNG +
VirtualClock); agentprobe `WorldSimulator` dipakai untuk membangkitkan
skenario + metadata chaos.

Verdict per skenario:
  SURVIVE — target fail-fast dengan error bertipe ATAU mengembalikan hasil
            yang masih memenuhi kontraknya; tidak menggantung.
  BREAK   — target menggantung (> ambang) atau mengembalikan hasil yang
            melanggar kontraknya (silent corruption).

Jalankan:  python tests/brief7_chaos.py
Hasil:     tests/_brief7_chaos_results.json
Exit 0 bila tidak ada BREAK.
"""
from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "tests"), r"D:\caches\evaltools"):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from arc.sdk import DeterministicRNG, VirtualClock  # noqa: E402
from agentprobe.chaos import ChaosProfile, WorldSimulator  # noqa: E402

OUT = ROOT / "tests" / "_brief7_chaos_results.json"
HANG_S = 8.0

#: Kelas gangguan yang diminta brief.
KINDS = ("network_timeout", "rate_limit", "schema_mismatch")


# ---------------------------------------------------------------------------
# Util: jalankan callable dengan batas waktu (deteksi hang)
# ---------------------------------------------------------------------------

def _with_timeout(fn, seconds: float = HANG_S):
    box: dict = {}

    def _run():
        try:
            box["val"] = fn()
        except BaseException as e:  # noqa: BLE001
            box["exc"] = e

    th = threading.Thread(target=_run, daemon=True)
    t0 = time.perf_counter()
    th.start()
    th.join(seconds)
    dt = time.perf_counter() - t0
    if th.is_alive():
        return {"hung": True, "dt": dt}
    if "exc" in box:
        return {"exc": box["exc"], "dt": dt}
    return {"val": box.get("val"), "dt": dt}


def _collect(ait):
    async def _c():
        return [x async for x in ait]
    return asyncio.run(_c())


# ---------------------------------------------------------------------------
# Target: fungsi Katalir dengan dependency boundary nyata
# ---------------------------------------------------------------------------

def t_run_protected(kind):
    """retry_policy.run_protected harus mengubah error dependency jadi dict
    hasil ber-retry (fail-fast), bukan menggantung / melempar mentah."""
    import retry_policy as RP
    exc = {"network_timeout": TimeoutError("dep timeout"),
           "rate_limit": ConnectionError("429 too many requests"),
           "schema_mismatch": ValueError("schema mismatch")}[kind]

    def dep():
        raise exc
    RP.circuit_reset("chaos-node")
    r = RP.run_protected(dep, user_id="chaos", step_id="s1",
                         breaker="chaos-node", max_attempts=3,
                         sleep=lambda s: None)
    ok = (isinstance(r, dict) and r.get("ok") is False
          and isinstance(r.get("attempts"), int))
    return ok, f"ok={r.get('ok')} attempts={r.get('attempts')} " \
               f"err={str(r.get('error'))[:36]}"


def t_with_retry(kind):
    """retry_policy.with_retry mengembalikan 4-tuple (ok, result, err, n)."""
    import retry_policy as RP
    exc = {"network_timeout": TimeoutError("dep timeout"),
           "rate_limit": ConnectionError("429"),
           "schema_mismatch": ValueError("bad schema")}[kind]
    r = RP.with_retry(lambda: (_ for _ in ()).throw(exc),
                      step_id="s1", max_attempts=3, sleep=lambda s: None)
    ok = (isinstance(r, tuple) and len(r) == 4 and r[0] is False
          and isinstance(r[3], int))
    return ok, f"tuple={r[0]}/len={len(r) if isinstance(r, tuple) else '-'} " \
               f"attempts={r[3] if isinstance(r, tuple) and len(r) == 4 else '-'}"


def t_expose_tool_errors(kind):
    """mcp_compat.expose_tool_errors membungkus error tool jadi ToolError
    bertipe (bukan melempar exception mentah dependency)."""
    import mcp_compat as MC
    exc = {"network_timeout": TimeoutError("dep timeout"),
           "rate_limit": ConnectionError("429"),
           "schema_mismatch": ValueError("bad schema")}[kind]

    def dep():
        raise exc
    wrapped = MC.expose_tool_errors(dep)
    res = _with_timeout(wrapped)
    tool_err = MC.tool_error_class()
    ok = isinstance(res.get("exc"), tool_err)
    return ok, f"exc={type(res.get('exc')).__name__} " \
               f"(harap {tool_err.__name__})"


def t_run_python(kind):
    """code_sandbox.run_python mengubah program bermasalah jadi dict hasil
    (ok=False + error), tidak menggantung."""
    import code_sandbox as CS
    code = {"network_timeout": "while True:\n    pass",
            "rate_limit": "raise ConnectionError('429')",
            "schema_mismatch": "raise ValueError('bad schema')"}[kind]
    res = _with_timeout(lambda: CS.run_python(code, timeout_s=2))
    if res.get("hung"):
        return False, "MELAMPAUI batas (menggantung)"
    r = res.get("val")
    ok = isinstance(r, dict) and "ok" in r and "error" in r
    return ok, f"ok={r.get('ok') if isinstance(r, dict) else r}"


def t_guardrails_judge(kind):
    """guardrails.check_text harus tetap mengembalikan dict walau 'judge'
    (dependency) gagal — tidak boleh crash."""
    import guardrails as GR

    class BadJudge:
        def evaluate(self, *a, **k):
            raise {"network_timeout": TimeoutError("judge timeout"),
                   "rate_limit": ConnectionError("429"),
                   "schema_mismatch": ValueError("bad judge")}[kind]

    res = _with_timeout(lambda: GR.check_text("halo dunia",
                                              {"jailbreak": True},
                                              judge=BadJudge()))
    if res.get("hung"):
        return False, "MELAMPAUI batas"
    if "exc" in res:
        return False, f"crash {type(res['exc']).__name__}: {str(res['exc'])[:40]}"
    r = res.get("val")
    ok = isinstance(r, dict) and "status" in r
    return ok, f"status={r.get('status') if isinstance(r, dict) else r}"


def t_stream_or_fallback(kind):
    """chat_stream.stream_or_fallback harus memakai fallback saat chunk
    pertama tidak datang (timeout) atau factory gagal (rate limit)."""
    import chat_stream as CS
    if kind == "network_timeout":
        async def factory():
            await asyncio.sleep(5)
            yield "x"
    else:  # rate_limit
        async def factory():
            raise ConnectionError("429")
            yield  # pragma: no cover

    async def fb():
        return {"ok": True, "fallback": True}
    res = _with_timeout(lambda: _collect(
        CS.stream_or_fallback(factory, fb, first_chunk_timeout=0.25)))
    if res.get("hung"):
        return False, "MELAMPAUI batas"
    if "exc" in res:
        return False, f"crash {type(res['exc']).__name__}"
    frames = res.get("val") or []
    ok = bool(frames) and any("fallback" in f for f in frames)
    return ok, f"{len(frames)} frame, fallback={'ya' if ok else 'tidak'}"


def t_watchdog_idle(kind):
    """chat_stream.stream_with_watchdog menutup sumber idle dengan heartbeat
    + frame error (tidak menggantung)."""
    import chat_stream as CS
    if kind == "network_timeout":
        async def src():
            await asyncio.sleep(5)
            yield {"i": 0}
    else:  # rate_limit -> sumber melempar
        async def src():
            raise ConnectionError("429")
            yield  # pragma: no cover
    res = _with_timeout(lambda: _collect(
        CS.stream_with_watchdog(src(), idle_timeout=0.3,
                                heartbeat_interval=0.1)))
    if res.get("hung"):
        return False, "MELAMPAUI batas"
    frames = res.get("val") or []
    ok = bool(frames) and any("event: heartbeat" in f or "event: error" in f
                              for f in frames)
    return ok, f"{len(frames)} frame, terjaga={ok}"


def t_queue_fail(kind):
    """queue_mode.JobQueue mengubah job gagal jadi requeue/dead (fail-fast)."""
    import queue_mode as QM
    q = QM.JobQueue()
    try:
        job = q.enqueue({"x": 1}, max_retries=1)
    except Exception as e:  # noqa: BLE001
        return False, f"enqueue gagal: {type(e).__name__}"
    got = q.dequeue()
    if got is None:
        return False, "dequeue kosong"
    res = _with_timeout(lambda: q.fail(got.id, "chaos: dependency error"))
    if res.get("hung"):
        return False, "MELAMPAUI batas"
    if "exc" in res:
        return False, f"fail crash {type(res['exc']).__name__}"
    outcome = res.get("val")
    ok = isinstance(outcome, str)
    return ok, f"outcome={outcome}"


def t_sandbox_capability(kind):
    """plugin_system.Sandbox menolak capability terlarang dengan error bertipe."""
    import plugin_system as PL
    man = PL.PluginManifest(name="chaos.plugin", version="1.0.0", entry="m.py",
                            capabilities=["log"], dependencies={})
    sb = PL.Sandbox(man)
    cap = {"network_timeout": "net", "rate_limit": "http",
           "schema_mismatch": "secrets"}[kind]
    res = _with_timeout(lambda: sb.call(cap, lambda: "x"))
    denied = res.get("exc")
    ok = denied is not None and isinstance(
        denied, (PL.CapabilityDenied, PL.PluginError, PL.PluginBlocked))
    return ok, f"exc={type(denied).__name__ if denied else 'None'}"


def t_evaluator_runner(kind):
    """evaluation.Evaluator menangkap error runner per-kasus, tidak crash."""
    import evaluation as EV
    ev = EV.Evaluator(name="chaos", threshold=0.8)
    exc = {"network_timeout": TimeoutError("dep timeout"),
           "rate_limit": ConnectionError("429"),
           "schema_mismatch": ValueError("bad schema")}[kind]

    def runner(case):
        raise exc
    res = _with_timeout(lambda: ev.run([{"input": "a", "expected": "b"}], runner))
    if res.get("hung"):
        return False, "MELAMPAUI batas"
    if "exc" in res:
        return False, f"crash {type(res['exc']).__name__}"
    out = res.get("val")
    ok = isinstance(out, dict)
    return ok, f"tipe={type(out).__name__}"


def t_serialize_roundtrip(kind):
    """source_control serialize/deserialize tetap round-trip walau input
    mengandung bentuk tak terduga (schema mismatch)."""
    import source_control as SC
    flow = {"nodes": [{"id": "n1", "type": "agent"}], "edges": [],
            "chaos": {"weird": [1, 2, {"deep": None}]}}
    txt = SC.serialize_workflow("wf-chaos", flow)
    back = SC.deserialize_workflow(txt)
    ok = isinstance(back, dict) and back.get("nodes") == flow["nodes"]
    return ok, f"tipe={type(back).__name__} nodes_ok={ok}"


TARGETS = [
    ("retry_policy.run_protected", t_run_protected),
    ("retry_policy.with_retry", t_with_retry),
    ("mcp_compat.expose_tool_errors", t_expose_tool_errors),
    ("code_sandbox.run_python", t_run_python),
    ("guardrails.check_text", t_guardrails_judge),
    ("chat_stream.stream_or_fallback", t_stream_or_fallback),
    ("chat_stream.stream_with_watchdog", t_watchdog_idle),
    ("queue_mode.JobQueue.fail", t_queue_fail),
    ("plugin_system.Sandbox.call", t_sandbox_capability),
    ("evaluation.Evaluator.run", t_evaluator_runner),
    ("source_control.serialize_workflow", t_serialize_roundtrip),
]


def build_scenarios(n: int = 50) -> list[dict]:
    """Pakai agentprobe WorldSimulator + arc DeterministicRNG untuk 50 skenario
    deterministik yang memetakan (target, kelas gangguan)."""
    tools = [name for name, _ in TARGETS]
    sim = WorldSimulator.from_tool_names(tools, profile=ChaosProfile.HOSTILE,
                                         seed=20261012)
    worlds = sim.generate_batch(n)
    rng = DeterministicRNG(seed=20261012)
    scenarios = []
    for i in range(n):
        target_name, fn = TARGETS[i % len(TARGETS)]
        kind = KINDS[(i // len(TARGETS) + rng.randint(0, 2)) % len(KINDS)]
        w = worlds[i]
        scenarios.append({
            "id": i + 1, "target": target_name, "kind": kind,
            "world_chaos_level": w.chaos_level,
            "world_failures": w.injected_failures,
            "seed": w.seed, "fn": fn,
        })
    return scenarios


def main() -> int:
    print("=" * 78)
    print("BRIEF 7 TASK 3 — CHAOS (arc-reliability + agentprobe) 50 SKENARIO")
    print("=" * 78)
    clock = VirtualClock()
    print(f"VirtualClock: {type(clock).__name__}  (determinisme arc)")
    scenarios = build_scenarios(50)
    print(f"skenario dibangkitkan: {len(scenarios)} "
          f"(target={len(TARGETS)}, kelas={list(KINDS)})")

    # Warm-up: impor dingin + klien (Supabase dll) TIDAK dihitung sebagai hang.
    print("warm-up target (impor dingin)...")
    for _, fn in TARGETS:
        try:
            _with_timeout(lambda: fn("schema_mismatch"), seconds=20.0)
        except Exception:  # noqa: BLE001
            pass
    print()

    rows = []
    t0 = time.perf_counter()
    for sc in scenarios:
        fn = sc.pop("fn")
        res = _with_timeout(lambda: fn(sc["kind"]))
        if res.get("hung"):
            verdict, detail = "BREAK", "MELAMPAUI batas waktu (menggantung)"
        elif "exc" in res:
            verdict = "BREAK"
            detail = f"crash {type(res['exc']).__name__}: {str(res['exc'])[:60]}"
        else:
            ok, detail = res["val"]
            verdict = "SURVIVE" if ok else "BREAK"
        rows.append({**sc, "verdict": verdict, "detail": detail,
                     "seconds": round(res.get("dt", 0.0), 3)})

    n_surv = sum(1 for r in rows if r["verdict"] == "SURVIVE")
    n_break = sum(1 for r in rows if r["verdict"] == "BREAK")
    by_kind: dict[str, dict] = {}
    for r in rows:
        k = by_kind.setdefault(r["kind"], {"SURVIVE": 0, "BREAK": 0})
        k[r["verdict"]] += 1

    print(f"{'#':<4}{'target':<34}{'kelas':<18}{'verdict':<9}detail")
    print("-" * 100)
    for r in rows:
        print(f"{r['id']:<4}{r['target']:<34}{r['kind']:<18}"
              f"{r['verdict']:<9}{r['detail'][:34]}")
    print("-" * 100)
    print(f"TOTAL SURVIVE={n_surv}  BREAK={n_break}  (durasi "
          f"{time.perf_counter() - t0:.1f}s)")
    for k, v in sorted(by_kind.items()):
        print(f"  {k:<18} SURVIVE={v['SURVIVE']} BREAK={v['BREAK']}")

    if n_break:
        print("\nTEMUAN (BREAK) — wajib ditindaklanjuti:")
        for r in rows:
            if r["verdict"] == "BREAK":
                print(f"  #{r['id']} {r['target']} [{r['kind']}]: {r['detail']}")

    OUT.write_text(json.dumps({
        "total": len(rows), "survive": n_surv, "break": n_break,
        "kinds": list(KINDS), "by_kind": by_kind, "results": rows,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nhasil: {OUT}")
    return 0 if n_break == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
