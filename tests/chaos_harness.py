#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chaos Engineering harness untuk agent (Metode 3).

Prinsip yang diimplementasikan (bukan disimulasikan):
  * **Mulai kecil, naikkan blast radius** — tangga gangguan dari latensi
    ringan sampai dependency mati.
  * **Fault injection nyata** — monkeypatch objek hidup: network putus
    (exception transport), dependency slowness (delay), format change
    (mutasi bentuk hasil).
  * **Auto-revert + monitoring** — setiap rung WAJIB dikembalikan, dan
    pengembaliannya DIVERIFIKASI (kalau tidak, chaos meracuni test lain).

Satu rung hanya dianggap PASS bila:
  (a) fault benar-benar terpasang,
  (b) target pulih ATAU melempar error yang benar (tidak menggantung),
  (c) auto-revert berhasil (objek kembali ke implementasi asli).

Kalau fault tidak bisa dipasang, rung itu SKIP — bukan PASS palsu.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

try:  # dipakai sebagai paket (`tests.chaos_harness`)
    from tests.five_layer_harness import FaultInjector, FaultInjectionError
except ImportError:  # dipakai datar (`chaos_harness`, saat tests/ ada di sys.path)
    from five_layer_harness import FaultInjector, FaultInjectionError  # type: ignore


@dataclass
class Rung:
    name: str
    blast: str          # "ringan" | "sedang" | "berat"
    ok: Optional[bool]
    detail: str
    latency: float = 0.0
    reverted: bool = False


# Bentuk gangguan yang tersedia. `target_attr` diisi pemanggil lewat `plan`.
FAULTS: dict[str, tuple[str, dict]] = {
    "network_delay_100ms": ("ringan", {"kind": "delay", "seconds": 0.1}),
    "network_delay_500ms": ("sedang", {"kind": "delay", "seconds": 0.5}),
    "network_down": ("berat", {"kind": "raise", "exc": "ConnectionError"}),
    "timeout": ("sedang", {"kind": "raise", "exc": "TimeoutError"}),
    "format_change": ("sedang", {"kind": "corrupt"}),
    "malformed_result": ("ringan", {"kind": "corrupt"}),
}

_EXC = {"ConnectionError": ConnectionError, "TimeoutError": TimeoutError,
        "RuntimeError": RuntimeError, "ValueError": ValueError}


def _corruptor(payload: Any) -> Callable[[Any], Any]:
    """Format change: buang kunci / ubah tipe, tergantung bentuk."""
    def mutate(result: Any) -> Any:
        if isinstance(result, dict):
            out = dict(result)
            if out:
                k = next(iter(out))
                out[f"{k}Renamed"] = out.pop(k)          # field rename
                return out
            return {"unexpected": None}
        if isinstance(result, list):
            return [{"_corrupt": True} for _ in result]
        if isinstance(result, str):
            return result.replace(",", ";") if "," in result else ""
        return {"_corrupt": payload}
    return mutate


class ChaosHarness:
    """Jalankan tangga chaos atas satu target, dengan auto-revert terverifikasi."""

    def __init__(self, name: str) -> None:
        self.name = name

    def run_ladder(self, target: Callable[[], Any],
                   *,
                   target_obj: Any,
                   target_attr: str,
                   ladder: Optional[list[str]] = None,
                   expect_error: Optional[type] = None,
                   timeout_s: float = 30.0) -> list[Rung]:
        """`target` dipanggil berkali-kali; `target_obj.target_attr` yang dirusak."""
        original = getattr(target_obj, target_attr, None)
        if original is None:
            return [Rung("(tidak ada)", "-", None,
                         f"SKIP: '{target_attr}' tidak ada pada "
                         f"{getattr(target_obj, '__name__', target_obj)}", reverted=True)]

        names = ladder or ["network_delay_100ms", "network_delay_500ms",
                           "network_down", "timeout", "format_change"]
        rungs: list[Rung] = []

        for fname in names:
            blast, spec = FAULTS[fname]
            inj = FaultInjector()
            ok: Optional[bool]
            detail = ""
            latency = 0.0
            try:
                kind = spec["kind"]
                if kind == "delay":
                    inj.delay_on(target_obj, target_attr, spec["seconds"], fname)
                elif kind == "raise":
                    inj.raise_on(target_obj, target_attr, _EXC[spec["exc"]](fname), fname)
                elif kind == "corrupt":
                    inj.corrupt_on(target_obj, target_attr, _corruptor(fname), fname)
                if not inj.applied:
                    rungs.append(Rung(fname, blast, None, "SKIP: fault tidak terpasang",
                                      reverted=True))
                    continue

                t0 = time.perf_counter()
                try:
                    target()
                    recovered, err = True, ""
                except Exception as e:  # noqa: BLE001
                    recovered = bool(expect_error and isinstance(e, expect_error))
                    err = f"{type(e).__name__}: {e}"[:180]
                latency = time.perf_counter() - t0

                hung = latency > timeout_s
                ok = recovered and not hung
                detail = ("pulih" if recovered else f"tidak pulih ({err})")
                if hung:
                    detail += f"; MELAMPAUI timeout {timeout_s}s"
            except FaultInjectionError as e:
                ok, detail = None, f"SKIP: {str(e)[:140]}"
            finally:
                inj.revert_all()

            # Auto-revert terverifikasi: objek HARUS kembali ke fungsi asli.
            restored = getattr(target_obj, target_attr, None) is original
            if not restored:
                ok = False
                detail += "; AUTO-REVERT GAGAL (objek tidak kembali)"
            rungs.append(Rung(fname, blast, ok, detail, round(latency, 3), restored))
        return rungs

    @staticmethod
    def summary(rungs: list[Rung]) -> dict:
        ran = [r for r in rungs if r.ok is not None]
        bad = [r for r in ran if r.ok is False]
        skipped = [r for r in rungs if r.ok is None]
        return {
            "total": len(rungs), "ran": len(ran), "pass": len(ran) - len(bad),
            "fail": len(bad), "skip": len(skipped),
            "worst_blast": max((r.blast for r in ran), default="-"),
            "all_reverted": all(r.reverted for r in rungs),
            "failures": [{"fault": r.name, "detail": r.detail} for r in bad],
        }
