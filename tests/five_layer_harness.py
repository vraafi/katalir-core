#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Five-Layer Acceptance Testing harness (Metode 1).

Lima lapis, semuanya menghasilkan BUKTI — bukan sekadar assert:

  L1 INPUT SNAPSHOT      — rekam input persis (repr + sha256) sebelum apa pun jalan
  L2 EXECUTION TRAJECTORY— rekam tiap langkah: node, input, output, latensi, error
  L3 FAULT INJECTION     — rusak dependency secara NYATA lalu pastikan pulih
  L4 PROCESS EVIDENCE    — jejak lengkap: langkah, fault, recovery, timing
  L5 OUTPUT VALIDATION   — invariant pada output akhir (bukan hanya "tidak error")

Catatan kejujuran: L3 hanya boleh disebut PASS kalau fault benar-benar
dipasang (ada `faults_applied`) DAN target benar-benar pulih/melempar error
yang benar. Kalau fault tidak bisa dipasang (API tidak ada), hasilnya SKIP —
bukan PASS palsu.
"""
from __future__ import annotations

import hashlib
import inspect
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

# --------------------------------------------------------------------------
# L2 — langkah jejak eksekusi
# --------------------------------------------------------------------------


@dataclass
class Step:
    node: str
    input: Any
    output: Any
    latency: float
    ok: bool = True
    error: str = ""

    def to_dict(self) -> dict:
        return {"node": self.node, "input": _short(self.input),
                "output": _short(self.output), "latency": round(self.latency, 4),
                "ok": self.ok, "error": self.error[:200]}


def _short(v: Any, n: int = 160) -> str:
    try:
        s = repr(v)
    except Exception:  # noqa: BLE001
        s = f"<{type(v).__name__} unrepresentable>"
    return s if len(s) <= n else s[:n] + f"…(+{len(s) - n})"


def snapshot(value: Any) -> dict:
    """L1: rekam input persis — repr + sha256 + tipe."""
    try:
        r = repr(value)
    except Exception:  # noqa: BLE001
        r = f"<{type(value).__name__} unrepresentable>"
    return {"repr": r, "sha256": hashlib.sha256(r.encode("utf-8", "replace")).hexdigest()[:16],
            "type": type(value).__name__, "len": len(r), "ts": time.time()}


# --------------------------------------------------------------------------
# L3 — fault injection NYATA (monkeypatch + auto-revert)
# --------------------------------------------------------------------------


class FaultInjectionError(RuntimeError):
    pass


class FaultInjector:
    """Memasang gangguan nyata pada objek hidup, lalu mengembalikannya.

    Semua gangguan dicatat; `revert_all()` WAJIB dipanggil (dipakai `finally`)
    supaya satu test tidak meracuni test berikutnya.
    """

    def __init__(self) -> None:
        self._undo: list[Callable[[], None]] = []
        self.applied: list[str] = []

    def _patch(self, obj: Any, attr: str, new: Any, label: str) -> None:
        if not hasattr(obj, attr):
            raise FaultInjectionError(f"{label}: {getattr(obj, '__name__', obj)} tidak punya '{attr}'")
        old = getattr(obj, attr)
        setattr(obj, attr, new)
        self._undo.append(lambda: setattr(obj, attr, old))
        self.applied.append(label)

    def raise_on(self, obj: Any, attr: str, exc: BaseException, label: str = "") -> None:
        """Setiap panggilan melempar `exc`."""
        def boom(*_a, **_k):
            raise exc
        self._patch(obj, attr, boom, label or f"raise:{attr}")

    def corrupt_on(self, obj: Any, attr: str, mutator: Callable[[Any], Any],
                   label: str = "") -> None:
        """Panggil aslinya, lalu rusak bentuk hasilnya (format change)."""
        old = getattr(obj, attr, None)
        if old is None:
            raise FaultInjectionError(f"corrupt: '{attr}' tidak ada")

        def wrapper(*a, **k):
            return mutator(old(*a, **k))
        self._patch(obj, attr, wrapper, label or f"corrupt:{attr}")

    def delay_on(self, obj: Any, attr: str, seconds: float, label: str = "") -> None:
        """Tambahkan latensi (dependency slowness)."""
        old = getattr(obj, attr, None)
        if old is None:
            raise FaultInjectionError(f"delay: '{attr}' tidak ada")

        def wrapper(*a, **k):
            time.sleep(seconds)
            return old(*a, **k)
        self._patch(obj, attr, wrapper, label or f"delay:{attr}")

    def revert_all(self) -> None:
        while self._undo:
            try:
                self._undo.pop()()
            except Exception:  # noqa: BLE001
                pass


# --------------------------------------------------------------------------
# Harness utama
# --------------------------------------------------------------------------


@dataclass
class LayerResult:
    ok: Optional[bool]          # None = SKIP (tidak bisa diuji), bukan gagal
    detail: str
    data: dict = field(default_factory=dict)


@dataclass
class FiveLayerResult:
    name: str
    layers: dict[str, LayerResult]
    evidence: dict

    @property
    def ok(self) -> Optional[bool]:
        vals = [l.ok for l in self.layers.values()]
        if any(v is False for v in vals):
            return False
        if any(v is True for v in vals):
            return True
        return None


class FiveLayerHarness:
    """Jalankan satu task melewati 5 lapis dan kumpulkan buktinya."""

    def __init__(self, name: str) -> None:
        self.name = name

    def run(self, target: Callable[[Callable[[str, Any, Any], None]], Any],
            *,
            input_value: Any = None,
            faults: Optional[Iterable[tuple[str, Callable[[FaultInjector], None]]]] = None,
            invariants: Optional[list[tuple[str, Callable[[Any], bool]]]] = None,
            expect_error: Optional[type] = None) -> FiveLayerResult:
        """`target(on_step)` menjalankan task; memanggil `on_step(node, in, out)`."""
        trajectory: list[Step] = []

        def on_step(node: str, i: Any, o: Any) -> None:
            trajectory.append(Step(node=node, input=i, output=o, latency=0.0))

        # ---- L1 input snapshot ----
        snap = snapshot(input_value)

        # ---- L2 eksekusi bersih (baseline) ----
        l2 = LayerResult(True, "trajectory terekam", {})
        clean_out: Any = None
        clean_err = ""
        t0 = time.perf_counter()
        try:
            clean_out = target(on_step)
            l2.detail = f"{len(trajectory)} langkah, {time.perf_counter() - t0:.3f}s"
        except Exception as e:  # noqa: BLE001
            clean_err = f"{type(e).__name__}: {e}"
            if expect_error and isinstance(e, expect_error):
                l2 = LayerResult(True, f"error yang diharapkan: {clean_err}", {})
            else:
                l2 = LayerResult(False, f"gagal di jalur bersih: {clean_err}", {})
        l2.data = {"steps": [s.to_dict() for s in trajectory],
                   "clean_error": clean_err}

        # ---- L3 fault injection ----
        fault_records: list[dict] = []
        l3_ok: Optional[bool] = None
        l3_detail = "tidak ada fault diminta"
        if faults:
            l3_ok = True
            for fname, installer in faults:
                inj = FaultInjector()
                try:
                    installer(inj)
                    if not inj.applied:
                        fault_records.append({"fault": fname, "result": "SKIP",
                                              "reason": "fault tidak terpasang"})
                        continue
                    traj2: list[Step] = []

                    def on2(node: str, i: Any, o: Any, _t=traj2) -> None:
                        _t.append(Step(node=node, input=i, output=o, latency=0.0))

                    tt = time.perf_counter()
                    try:
                        target(on2)
                        recovered, err = True, ""
                    except Exception as e:  # noqa: BLE001
                        recovered = bool(expect_error and isinstance(e, expect_error))
                        err = f"{type(e).__name__}: {e}"[:200]
                    fault_records.append({
                        "fault": fname, "applied": inj.applied,
                        "recovered": recovered, "error": err,
                        "latency": round(time.perf_counter() - tt, 3),
                        "steps": len(traj2), "result": "PASS" if recovered else "FAIL",
                    })
                    if not recovered:
                        l3_ok = False
                except FaultInjectionError as e:
                    fault_records.append({"fault": fname, "result": "SKIP",
                                          "reason": str(e)[:160]})
                except Exception as e:  # noqa: BLE001
                    fault_records.append({"fault": fname, "result": "FAIL",
                                          "reason": f"{type(e).__name__}: {e}"[:160]})
                    l3_ok = False
                finally:
                    inj.revert_all()
            ran = [r for r in fault_records if r.get("result") in ("PASS", "FAIL")]
            if not ran:
                l3_ok = None
                l3_detail = f"{len(fault_records)} fault, semua SKIP (tidak bisa dipasang)"
            else:
                bad = [r for r in ran if r["result"] == "FAIL"]
                l3_detail = f"{len(ran) - len(bad)}/{len(ran)} fault pulih"
        l3 = LayerResult(l3_ok, l3_detail, {"faults": fault_records})

        # ---- L4 process evidence ----
        l4 = LayerResult(True, "bukti proses terkumpul", {})
        if l2.ok is False:
            l4 = LayerResult(False, "tidak ada proses sehat untuk dibuktikan", {})
        elif not trajectory:
            l4 = LayerResult(False, "trajectory KOSONG — target tidak melaporkan langkah", {})
        else:
            lat = [s.latency for s in trajectory]
            l4.data = {"n_steps": len(trajectory),
                       "nodes": sorted({s.node for s in trajectory})}

        # ---- L5 output validation ----
        l5: LayerResult
        if invariants:
            fails = []
            for iname, pred in invariants:
                try:
                    if not pred(clean_out):
                        fails.append(iname)
                except Exception as e:  # noqa: BLE001
                    fails.append(f"{iname} (predikat error: {type(e).__name__})")
            l5 = LayerResult(not fails,
                             "semua invariant lulus" if not fails else f"invariant gagal: {fails}",
                             {"invariants": [i for i, _ in invariants], "failed": fails})
        else:
            l5 = LayerResult(None, "tidak ada invariant didefinisikan", {})

        evidence = {
            "name": self.name,
            "L1_snapshot": snap,
            "L2_steps": [s.to_dict() for s in trajectory],
            "L3_faults": fault_records,
            "L4_nodes": l4.data.get("nodes", []),
            "L5_output": _short(clean_out, 240),
            "clean_error": clean_err,
            "clean_output_ok": l2.ok,
        }
        return FiveLayerResult(
            self.name,
            {"L1": LayerResult(True, f"sha256={snap['sha256']}", snap),
             "L2": l2, "L3": l3, "L4": l4, "L5": l5},
            evidence)
