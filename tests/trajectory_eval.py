#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Trajectory-Based Evaluation (Metode 4) — skor 6 dimensi.

Menilai JEJAK, bukan hanya output akhir. Enam dimensi:

  1. tool_selection       — node/tool yang dipakai relevan & tidak berlebihan
  2. argument_extraction  — argumen yang dioper lengkap dan benar tipe
  3. result_utilization   — output satu langkah benar-benar dipakai langkah lain
  4. error_recovery       — error ditangani, bukan ditelan
  5. plan_coherence       — urutan langkah masuk akal (tidak ada lompatan)
  6. task_completion      — langkah terakhir menghasilkan output yang valid

Skor 0..1 per dimensi. Ambang lulus default 0.7 (dapat diubah per pemanggil).

Referensi pendekatan: ACL 2026 "A Survey on Evaluation of LLM-based Agents"
(aclanthology.org/2026.findings-acl.1330.pdf) — evaluasi agent bergeser dari
output akhir ke jejak eksekusi + pemulihan error.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Expectation:
    """Ekspektasi atas sebuah jejak. Semua opsional."""
    expect_tools: list[str] = field(default_factory=list)      # node yang WAJIB muncul
    forbid_tools: list[str] = field(default_factory=list)      # node yang TIDAK boleh muncul
    max_steps: Optional[int] = None                            # cegah langkah berlebihan
    required_args: dict[str, list[str]] = field(default_factory=dict)  # node -> nama arg
    chain: list[tuple[str, str]] = field(default_factory=list)  # (penghasil, pemakai)
    final_keys: list[str] = field(default_factory=list)        # kunci wajib di output akhir
    tolerance: float = 0.7


def _steps_of(trajectory: Any) -> list[dict]:
    """Terima list Step, list dict, atau FiveLayerResult."""
    if trajectory is None:
        return []
    if hasattr(trajectory, "evidence"):                       # FiveLayerResult
        return list(trajectory.evidence.get("L2_steps") or [])
    out = []
    for s in trajectory:
        out.append(s.to_dict() if hasattr(s, "to_dict") else dict(s))
    return out


def _as_text(v: Any) -> str:
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        return repr(v)


# --------------------------------------------------------------------------
# 6 dimensi
# --------------------------------------------------------------------------


def score_tool_selection(steps: list[dict], exp: Expectation) -> float:
    if not steps:
        return 0.0
    names = [s.get("node", "") for s in steps]
    score = 1.0
    if exp.expect_tools:
        hit = sum(1 for t in exp.expect_tools if t in names)
        score *= hit / len(exp.expect_tools)
    if exp.forbid_tools:
        bad = [t for t in exp.forbid_tools if t in names]
        if bad:
            score *= max(0.0, 1.0 - 0.5 * len(bad))
    if exp.max_steps is not None and len(steps) > exp.max_steps:
        # hukuman proporsional, bukan langsung nol
        score *= max(0.0, 1.0 - (len(steps) - exp.max_steps) / max(1, exp.max_steps))
    return round(min(1.0, score), 4)


def score_argument_extraction(steps: list[dict], exp: Expectation) -> float:
    if not steps:
        return 0.0
    if not exp.required_args:
        # Tidak ada spesifikasi: nilai dari "argumen tidak kosong" secara wajar.
        with_input = [s for s in steps if _as_text(s.get("input")).strip() not in ("", "None")]
        return round(len(with_input) / len(steps), 4)
    total = 0
    ok = 0
    by_node = {s.get("node", ""): s for s in steps}
    for node, keys in exp.required_args.items():
        st = by_node.get(node)
        for k in keys:
            total += 1
            if st is None:
                continue
            blob = _as_text(st.get("input"))
            if k in blob:
                ok += 1
    return round(ok / total, 4) if total else 0.0


def score_result_utilization(steps: list[dict], exp: Expectation) -> float:
    if not steps:
        return 0.0
    if not exp.chain:
        # Heuristik: apakah output langkah N muncul di input langkah N+1?
        pairs = 0
        used = 0
        for a, b in zip(steps, steps[1:]):
            pairs += 1
            o = _as_text(a.get("output")).strip()
            if len(o) < 8:
                continue
            token = o[:40].strip("'\"[](){} ")
            if token and token in _as_text(b.get("input")):
                used += 1
        return round(used / pairs, 4) if pairs else 0.0
    hits = 0
    for producer, consumer in exp.chain:
        prod = next((s for s in steps if s.get("node") == producer), None)
        cons = next((s for s in steps if s.get("node") == consumer), None)
        if not prod or not cons:
            continue
        o = _as_text(prod.get("output")).strip()
        token = o[:40].strip("'\"[](){} ")
        if token and token in _as_text(cons.get("input")):
            hits += 1
    return round(hits / len(exp.chain), 4)


def score_error_recovery(steps: list[dict], exp: Expectation) -> float:
    """1.0 bila tidak ada error sama sekali, ATAU semua error ditangani."""
    if not steps:
        return 0.0
    errs = [s for s in steps if s.get("error") or s.get("ok") is False]
    if not errs:
        return 1.0
    handled = 0
    for i, s in enumerate(steps):
        if not (s.get("error") or s.get("ok") is False):
            continue
        later = steps[i + 1:]
        if any((not x.get("error")) and x.get("ok", True) for x in later):
            handled += 1
    return round(handled / len(errs), 4)


def score_plan_coherence(steps: list[dict], exp: Expectation) -> float:
    """Urutan masuk akal: node berulang berurutan tanpa progres = tidak koheren."""
    if not steps:
        return 0.0
    if len(steps) == 1:
        return 1.0
    names = [s.get("node", "") for s in steps]
    # 1) tidak ada duplikat identik beruntun >2
    runs = 1
    worst = 1
    for a, b in zip(names, names[1:]):
        runs = runs + 1 if a == b else 1
        worst = max(worst, runs)
    repeat_penalty = 0.0 if worst <= 2 else min(0.5, (worst - 2) * 0.2)
    # 2) tidak ada langkah yang outputnya kosong padahal tidak error
    empty = sum(1 for s in steps if not s.get("error") and _as_text(s.get("output")).strip() in ("", "None"))
    empty_penalty = min(0.5, empty / len(steps))
    # 3) semua langkah punya node bernama
    unnamed = sum(1 for n in names if not n)
    return round(max(0.0, 1.0 - repeat_penalty - empty_penalty - (0.2 if unnamed else 0.0)), 4)


def score_task_completion(steps: list[dict], exp: Expectation, final_output: Any = None) -> float:
    if not steps:
        return 0.0
    last = steps[-1]
    if last.get("error") or last.get("ok") is False:
        return 0.0
    out = final_output if final_output is not None else last.get("output")
    if out is None:
        return 0.0
    if exp.final_keys:
        blob = _as_text(out)
        hit = sum(1 for k in exp.final_keys if k in blob)
        return round(hit / len(exp.final_keys), 4)
    return 1.0 if _as_text(out).strip() not in ("", "None") else 0.0


DIMENSIONS = ("tool_selection", "argument_extraction", "result_utilization",
              "error_recovery", "plan_coherence", "task_completion")


def evaluate_trajectory(trajectory: Any, exp: Optional[Expectation] = None,
                        final_output: Any = None) -> dict:
    """Kembalikan {'scores': {...}, 'ok': bool, 'failed': [...], 'n_steps': int}."""
    exp = exp or Expectation()
    steps = _steps_of(trajectory)
    scores = {
        "tool_selection": score_tool_selection(steps, exp),
        "argument_extraction": score_argument_extraction(steps, exp),
        "result_utilization": score_result_utilization(steps, exp),
        "error_recovery": score_error_recovery(steps, exp),
        "plan_coherence": score_plan_coherence(steps, exp),
        "task_completion": score_task_completion(steps, exp, final_output),
    }
    failed = [k for k, v in scores.items() if v < exp.tolerance]
    return {"scores": scores, "ok": not failed, "failed": failed,
            "tolerance": exp.tolerance, "n_steps": len(steps)}
