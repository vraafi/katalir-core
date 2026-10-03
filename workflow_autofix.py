# -*- coding: utf-8 -*-
"""Self-correcting generate -> validate -> repair loop (Bagian 2, 2026-10-03).

KENAPA MODUL INI ADA
--------------------
``tools.generate_workflow_json`` hanya memvalidasi SEKALI. Kalau model
mengirim spec cacat, validasi menolak, lalu user dipaksa menebak-pasak
sendiri ("coba ulangi tapi jangan pakai id GHOST").

Dua kegagalan yang berlawanan dan keduanya harus dihindari:

  * Loop TANPA batas  -> "stuck berjam-jam". Persis kelemahan n8n #1.
  * Cap kecil TANPA deteksi progres -> loop berhenti di iterasi ke-2
    padahal error yang muncul masih baru dan bisa diperbaiki.

Maka modul ini pasang KEDUA sisi:

  1. Batas keras (``max_iterations``, ``time_budget_s``) - tidak pernah
     berputar tanpa akhir.
  2. Deteksi tanpa progres (``no_progress_limit``) - kalau error yang
     identik berulang, iterasi berikutnya pasti sia-sia juga, jadi
     BERHENTI dan lapor jujur. Inilah yang membedakan "loop" dari
     "menyerah diam-diam".

ANALISIS AKAR BERKAS INI
-------------------------
Reference n8n saat ini (``MAX_STEPS`` di
packages/@n8n/instance-ai/src/constants/max-steps.ts, commit 8bb6489):

    ORCHESTRATOR : 100
    BROWSER     : 300   (legacy)
    BUILDER     : 60    (legacy)
    EVAL_SETUP  : 30
    RESEARCH    : 25

Angka "5 -> 60" di brief sudah basi; n8n menaikkan ~20x karena
orchestrator butuh banyak putaran tool-calling. Tapi cap besar tanpa deteksi
progres justru patologi: model bisa menghabiskan 100 putaran mengulang spec
yang sama persis, lalu tetap gagal dengan biaya 100x.

Karena itu cap besar WAJIB berpasangan dengan no-progress detection.
Kita memilih cap kecil (10) secara sadar: loop di sini hanya
revalidate + repair spec, yaitu operasi masked yang murah dan cepat -
bukan eksekusi tool panjang seperti n8n. 10 putaran sudah jauh melebihi
kebutuhan nyata;oeslon jika butuh lebih, itu tanda masalahnya elsewhere.

DESIGN: TANPA LLM DI DALAM
--------------------------
Loop ini SENGAJA tidak memanggil LLM. ``generate_fn`` dan ``repair_fn``
disuntikkan pemanggil. Konsekuensinya: seluruh policy (batas, no-progress,
pelaporan, klasifikasi stop) bisa diuji tanpa jaringan dan tanpa API key -
itulah alasan modul ini layak dipercaya sebagai guard, bukan sekadar
harapan. LLM tinggal tinggal swapped di lapisan pemanggil.
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable, Optional

import workflow_spec as _ws

# Batas keras. Loop kita hanya revalidate + repair spec (murah, masked).
MAX_ITERATIONS = 10
TIME_BUDGET_S = 120.0

# Berapa kali error IDENTIK boleh muncul sebelum menyerah.
# 3 memberi model 2 kesempatan (repair #1, repair #2) sebelum kita nyatakan
# bahwa perbaikan otomatis tidak lagi membantu.
NO_PROGRESS_LIMIT = 3


class LoopTimeout(Exception):
    """Loop melewati time_budget_s."""


class LoopExhausted(Exception):
    """Loop mencapai max_iterations tanpa spec valid."""


class NoProgress(Exception):
    """Error identik berulang; repair berikutnya pasti sia-sia."""
# Identifier yang dinormalisasi HANYA yang muncul di dalam tanda kutip, karena
# hanya nama node / ID yang berubah-ubah antar percobaan. Kalau kita
# menokenisasi semua kata, setiap error jadi tanda tangan yang sama dan
# no-progress detection jadi buta.
_QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"")


def error_signature(result: dict[str, Any]) -> str:
    """Kunci stabil untuk mendeteksi error yang berulang.

    WAJIB stabil terhadap variasi kosmetik, karena model sering menulis
    ulang pesan dengan urutan/ejaan berbeda padahal masalahnya identik.
    Kalau tanda tangannya rapuh, no-progress detection tidak pernah
    menyala dan kita kehilangan guard terpenting.

    Urutan normalisasi penting: ganti token BERKUTIP dulu (itulah yang
    dinamis, mis. ``'GHOST'`` vs ``'n1'``), baru lowercase + collapse
    whitespace, lalu sort. Kalau urutan dibalik, semua kata ikut ternormalisasi
    dan setiap error jadi tanda tangan yang sama.
    """
    errs = list(result.get("errors") or [])
    if not errs:
        # Spec valid; tidak ada alasan untuk jadi sinyal stop.
        return ""
    parts = []
    for e in errs:
        t = _QUOTED_RE.sub("X", str(e).strip())
        t = t.replace("'", "").replace('"', "")
        t = " ".join(t.lower().split())
        parts.append(t)
    return " || ".join(sorted(parts))


def describe_errors(errors: list[str]) -> str:
    """Pesan jujur untuk user: apa yang gagal dan apa yang harus dilakukan.

    Prinsip: JANGAN pernah menyatakan workflow sudah jadi bila belum.
    Error harus terbaca dan harus bisa ditindaklanjuti.
    """
    uniq: list[str] = []
    for e in errors:
        if e not in uniq:
            uniq.append(e)
    lines = [
        "Workflow belum bisa diselesaikan otomatis.",
        f"Masalah yang masih tersisa ({len(uniq)}):",
    ]
    lines += [f"  - {e}" for e in uniq]
    lines += [
        "",
        "Cara memperbaiki: benahi masalah di atas lalu minta ulang.",
        "Kalau error yang sama tetap muncul, penyebabnya sudah terisolasi "
        "sehingga lebih mudah diperbaiki manual.",
    ]
    return "\n".join(lines)


class SelfCorrectingLoop:
    """Orkestrator generate -> validate -> repair, dengan batas + no-progress.

    Loop ini tidak memanggil LLM; ``generate_fn`` / ``repair_fn``
    disuntikkan pemanggil. Itu membuat seluruh policy bisa diuji offline.
    """

    def __init__(
        self,
        generate_fn: Callable[[], str],
        repair_fn: Callable[[str, list[str]], str],
        *,
        max_iterations: int = MAX_ITERATIONS,
        time_budget_s: float = TIME_BUDGET_S,
        no_progress_limit: int = NO_PROGRESS_LIMIT,
        clock: Callable[[], float] = time.monotonic,
        progress_cb: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self.generate_fn = generate_fn
        self.repair_fn = repair_fn
        self.max_iterations = max(1, int(max_iterations))
        self.time_budget_s = float(time_budget_s)
        self.no_progress_limit = max(2, int(no_progress_limit))
        self.clock = clock
        self.progress_cb = progress_cb
        self.error_log: list[list[str]] = []
        self.signatures: list[str] = []
        self.iterations = 0

    def _emit(self, event: dict) -> None:
        if self.progress_cb is not None:
            try:
                self.progress_cb(dict(event))
            except Exception:
                pass  # progress callback tidak boleh menjatuhkan loop

    def _signature_count(self, sig: str) -> int:
        return sum(1 for s in self.signatures if s == sig)

    def run(self) -> dict[str, Any]:
        t0 = self.clock()
        current: Optional[str] = None
        last_errors: list[str] = []

        for i in range(1, self.max_iterations + 1):
            elapsed = self.clock() - t0
            if elapsed > self.time_budget_s:
                return self._failed(
                    reason="timeout",
                    elapsed=elapsed,
                    last_errors=last_errors,
                    detail=(f"Melewati batas waktu {self.time_budget_s:.0f} detik "
                            f"setelah {self.iterations} iterasi."),
                )

            try:
                current = (self.generate_fn() if current is None
                           else self.repair_fn(current, last_errors))
            except Exception as exc:  # noqa: BLE001
                # Error generator diperlakukan sebagai DATA, bukan crash:
                # bisa jadi rate-limit sementara atau model gagal parse.
                self.iterations = i
                msg = f"generator error: {exc}"
                self.error_log.append([msg])
                self.signatures.append(msg.lower())
                last_errors = [msg]
                current = None
                self._emit({"event": "generator_error", "iteration": i, "error": str(exc)})
                if self._signature_count(self.signatures[-1]) >= self.no_progress_limit:
                    return self._failed(
                        reason="no_progress",
                        elapsed=self.clock() - t0,
                        last_errors=last_errors,
                        detail="Generator gagal berulang dengan error yang sama.",
                    )
                continue

            self.iterations = i
            result = _ws.validate_spec(current or "")
            self._emit({
                "event": "validated",
                "iteration": i,
                "ok": bool(result.get("ok")),
                "errors": list(result.get("errors") or []),
                "elapsed_s": round(self.clock() - t0, 3),
            })

            if result.get("ok"):
                spec = result.get("spec") or {}
                return {
                    "ok": True,
                    "status": "ok",
                    "spec": spec,
                    "node_count": len(spec.get("nodes", [])),
                    "edge_count": len(spec.get("edges", [])),
                    "iterations": i,
                    "warnings": list(result.get("warnings") or []),
                    "repaired_count": len(self.error_log),
                    "elapsed_s": round(self.clock() - t0, 3),
                }
            last_errors = list(result.get("errors") or [])
            self.error_log.append(last_errors)
            sig = error_signature(result)
            self.signatures.append(sig)
            repeats = self._signature_count(sig)
            self._emit({"event": "invalid", "iteration": i, "repeats": repeats})

            if repeats >= self.no_progress_limit:
                return self._failed(
                    reason="no_progress",
                    elapsed=self.clock() - t0,
                    last_errors=last_errors,
                    detail=(f"Error yang sama muncul {repeats}x berturut-turut; "
                            "perbaikan otomatis tidak mengubah apa pun."),
                )

        return self._failed(
            reason="max_iterations",
            elapsed=self.clock() - t0,
            last_errors=last_errors,
            detail=f"Mencapai batas {self.max_iterations} iterasi tanpa spec valid.",
        )

    def _failed(self, *, reason: str, elapsed: float,
                    last_errors: list[str], detail: str) -> dict[str, Any]:
            seen: list[str] = []
            for batch in self.error_log:
                for e in batch:
                    if e not in seen:
                        seen.append(e)
            return {
                "ok": False,
                "status": "failed",
                "reason": reason,
                "iterations": self.iterations,
                "max_iterations": self.max_iterations,
                "elapsed_s": round(elapsed, 3),
                "errors": seen,
                "error_log": self.error_log,
                "message": describe_errors(seen or last_errors),
                "detail": detail,
                # Ledger alasan stop supaya bisa diaudit, bukan ditebak.
                "no_progress_signature": next(
                    (s for s in self.signatures
                     if s and self._signature_count(s) >= self.no_progress_limit),
                    "",
                ),
            }


def run_self_correcting_loop(
    generate_fn: Callable[[], str],
    repair_fn: Callable[[str, list[str]], str],
    **kw: Any,
) -> dict[str, Any]:
    """Convenience: instantiate lalu run dalam satu panggilan."""
    return SelfCorrectingLoop(generate_fn, repair_fn, **kw).run()
