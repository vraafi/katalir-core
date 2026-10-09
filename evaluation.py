# evaluation.py — Fitur #4: Evaluation & Testing built-in (8 Okt 2026)
# ======================================================================
# Menutup gap vs n8n "Evaluations": dataset uji + jalankan workflow +
# bandingkan output vs expected + metrik (accuracy/latency/cost) +
# LLM-as-judge. Riset Okt 2026 (docs/feature-gap-closure-2026-10-08.md §4):
# rubrik terstruktur + LLM-as-judge + regresi vs baseline.
#
# DESAIN (kenapa runner injectable):
#   Evaluasi nyata menjalankan workflow (jaringan/LLM). Supaya logika
#   metrik bisa di-hard-test TANPA jaringan, `Evaluator.run` menerima
#   `runner` (callable) dan `judge` (callable). Produksi menyuntikkan
#   runner workflow sungguhan + judge LLM; uji menyuntikkan stub.
#
# KONTRAK runner
#   runner(case: dict) -> {"output": str, "latency_ms": float,
#                          "tokens_in": int, "tokens_out": int,
#                          "cost_usd": float (opsional), "error": str (opsional)}
#
# METRIK
#   accuracy : fraksi kasus yang LULUS (compare/judge >= threshold)
#   latency  : mean / p50 / p95 (ms)
#   cost     : total + rata-rata (USD), dihitung dari token bila tidak diberi
#   regression: delta accuracy vs baseline (naik/turun)
# ======================================================================

from __future__ import annotations

import csv
import io
import json
import re
import statistics
import time
import uuid
from difflib import SequenceMatcher
from typing import Any, Callable, Optional

import database as db

COMPARE_MODES = ("exact", "contains", "fuzzy", "numeric", "judge")
DEFAULT_THRESHOLD = 0.8
MAX_CASES = 1000

#: Harga per 1.000 token (USD) untuk estimasi biaya bila runner tidak
#: melaporkan `cost_usd`. Default konservatif (kelas Gemini Flash 2026).
DEFAULT_PRICE_IN = 0.0001
DEFAULT_PRICE_OUT = 0.0004

Runner = Callable[[dict], dict]
Judge = Callable[[str, str, str], float]  # (input, output, expected) -> 0..1


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

def _norm_key(k: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(k).strip().lower()).strip("_")


def load_dataset(data: Any, fmt: str = "") -> list[dict]:
    """Muat dataset dari JSON (list/objek) atau CSV (string).

    Kolom yang dikenali (nama bebas, dinormalkan): input/prompt/question,
    expected/output/answer/ground_truth, id. Kolom lain tetap disimpan.
    """
    fmt = (fmt or "").strip().lower()
    rows: list[dict] = []
    if isinstance(data, str):
        text = data.strip()
        if not text:
            return []
        if fmt == "csv" or (not fmt and not text.startswith(("[", "{"))):
            rows = _parse_csv(text)
        else:
            try:
                parsed = json.loads(text)
            except ValueError as exc:
                raise ValueError(f"dataset JSON tidak valid: {exc}") from None
            rows = _from_obj(parsed)
    else:
        rows = _from_obj(data)
    return _normalize_rows(rows)[:MAX_CASES]


def _from_obj(parsed: Any) -> list[dict]:
    if isinstance(parsed, list):
        return [r for r in parsed if isinstance(r, dict)]
    if isinstance(parsed, dict):
        for key in ("cases", "data", "items", "rows", "dataset"):
            if isinstance(parsed.get(key), list):
                return [r for r in parsed[key] if isinstance(r, dict)]
        return [parsed]
    return []


def _parse_csv(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    return [dict(r) for r in reader]


def _normalize_rows(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for i, r in enumerate(rows):
        norm: dict[str, Any] = {"id": str(r.get("id") or f"case-{i + 1}")}
        for k, v in r.items():
            if k is None:
                continue
            norm[_norm_key(k)] = v
        inp = _first(norm, ("input", "prompt", "question", "query", "message"))
        exp = _first(norm, ("expected", "output", "answer", "ground_truth",
                            "reference", "label"))
        norm["input"] = "" if inp is None else str(inp)
        norm["expected"] = "" if exp is None else str(exp)
        out.append(norm)
    return out


def _first(d: dict, keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d and str(d[k]).strip() != "":
            return d[k]
    return None


# ---------------------------------------------------------------------------
# Perbandingan (murni)
# ---------------------------------------------------------------------------

def _num(s: Any) -> Optional[float]:
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(s or ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return None


def compare(expected: str, actual: str, mode: str = "fuzzy") -> float:
    """Skor kecocokan 0..1 antara output dan expected (murni, tanpa LLM)."""
    e, a = str(expected or ""), str(actual or "")
    if mode == "exact":
        return 1.0 if e.strip() == a.strip() else 0.0
    if mode == "contains":
        return 1.0 if e.strip() and e.strip().lower() in a.lower() else 0.0
    if mode == "numeric":
        ne, na = _num(e), _num(a)
        if ne is None or na is None:
            return 0.0
        if ne == na:
            return 1.0
        denom = max(abs(ne), abs(na), 1e-9)
        return max(0.0, 1.0 - abs(ne - na) / denom)
    # fuzzy (default)
    if not e.strip() and not a.strip():
        return 1.0
    return round(SequenceMatcher(None, e.strip().lower(),
                                 a.strip().lower()).ratio(), 4)


def _judge_default(inp: str, out: str, expected: str) -> float:
    """LLM-as-judge fallback: gabungan kemiripan teks + cakupan kata kunci."""
    base = compare(expected, out, "fuzzy")
    kw = [w for w in re.findall(r"[a-z0-9]{4,}", expected.lower())]
    if kw:
        hit = sum(1 for w in kw if w in out.lower()) / len(kw)
        return round(0.5 * base + 0.5 * hit, 4)
    return base


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------

def estimate_cost(tokens_in: Any, tokens_out: Any,
                  price_in: float = DEFAULT_PRICE_IN,
                  price_out: float = DEFAULT_PRICE_OUT) -> float:
    try:
        ti, to = int(tokens_in or 0), int(tokens_out or 0)
    except (TypeError, ValueError):
        ti = to = 0
    return round((ti / 1000.0) * price_in + (to / 1000.0) * price_out, 8)


def _percentile(vals: list[float], p: float) -> float:
    """Percentile nearest-rank (definisi standar: ceil(p/100 * N)).

    Temuan hard test Fitur #7: rumus lama `round(p/100*(N-1))` memberi
    p50=51 pada 1..100 (seharusnya 50) — galat satu langkah pada N genap.
    Rumus nearest-rank memberi hasil yang diharapkan operator.
    """
    if not vals:
        return 0.0
    import math
    s = sorted(vals)
    n = len(s)
    rank = max(1, min(n, int(math.ceil((p / 100.0) * n))))
    return round(s[rank - 1], 3)


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

class Evaluator:
    """Jalankan dataset terhadap `runner`, hitung metrik."""

    def __init__(self, name: str = "eval", threshold: float = DEFAULT_THRESHOLD,
                 price_in: float = DEFAULT_PRICE_IN,
                 price_out: float = DEFAULT_PRICE_OUT):
        self.name = name
        self.threshold = max(0.0, min(1.0, float(threshold)))
        self.price_in = price_in
        self.price_out = price_out

    def run(self, cases: list[dict], runner: Runner,
            judge: Optional[Judge] = None,
            compare_mode: str = "fuzzy",
            baseline_accuracy: Optional[float] = None) -> dict:
        compare_mode = compare_mode if compare_mode in COMPARE_MODES else "fuzzy"
        results: list[dict] = []
        t0 = time.perf_counter()
        for case in cases:
            c0 = time.perf_counter()
            error = ""
            try:
                out = runner(case) or {}
            except Exception as exc:  # noqa: BLE001 - 1 kasus gagal ≠ eval gagal
                out, error = {}, f"{type(exc).__name__}: {exc}"
            actual = str(out.get("output") or "")
            latency = float(out.get("latency_ms")
                            or (time.perf_counter() - c0) * 1000)
            if compare_mode == "judge":
                score = (judge or _judge_default)(
                    case.get("input", ""), actual, case.get("expected", ""))
            else:
                score = compare(case.get("expected", ""), actual, compare_mode)
            cost = out.get("cost_usd")
            if cost is None:
                cost = estimate_cost(out.get("tokens_in"), out.get("tokens_out"),
                                     self.price_in, self.price_out)
            results.append({
                "id": case.get("id"),
                "input": case.get("input", ""),
                "expected": case.get("expected", ""),
                "actual": actual,
                "score": round(float(score), 4),
                "passed": float(score) >= self.threshold and not error,
                "latency_ms": round(latency, 2),
                "cost_usd": float(cost),
                "tokens_in": int(out.get("tokens_in") or 0),
                "tokens_out": int(out.get("tokens_out") or 0),
                "error": error,
            })
        total = len(results)
        passed = sum(1 for r in results if r["passed"])
        accuracy = round(passed / total, 4) if total else 0.0
        lat = [r["latency_ms"] for r in results]
        summary = {
            "name": self.name,
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "accuracy": accuracy,
            "threshold": self.threshold,
            "compare_mode": compare_mode,
            "latency_mean_ms": round(statistics.fmean(lat), 2) if lat else 0.0,
            "latency_p50_ms": _percentile(lat, 50),
            "latency_p95_ms": _percentile(lat, 95),
            "cost_total_usd": round(sum(r["cost_usd"] for r in results), 8),
            "cost_mean_usd": round(statistics.fmean(
                [r["cost_usd"] for r in results]), 8) if results else 0.0,
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        }
        if baseline_accuracy is not None:
            delta = round(accuracy - float(baseline_accuracy), 4)
            summary["baseline_accuracy"] = float(baseline_accuracy)
            summary["regression_delta"] = delta
            summary["regression"] = ("improved" if delta > 0
                                     else "regressed" if delta < 0 else "same")
        return {"summary": summary, "results": results}


# ---------------------------------------------------------------------------
# Persistensi run (Supabase + memori)
# ---------------------------------------------------------------------------

class _MemoryRuns:
    name = "memory"

    def __init__(self):
        self._rows: dict[str, dict] = {}

    def save(self, row: dict) -> None:
        self._rows[row["run_id"]] = json.loads(json.dumps(row))

    def list(self, owner: str, limit: int = 20) -> list[dict]:
        rows = [r for r in self._rows.values() if r.get("owner") == owner]
        rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return [json.loads(json.dumps(r)) for r in rows[:limit]]

    def get(self, run_id: str) -> Optional[dict]:
        r = self._rows.get(run_id)
        return json.loads(json.dumps(r)) if r else None


class _SupabaseRuns:
    name = "supabase"

    def _t(self):
        return db.get_write_client()

    def save(self, row: dict) -> None:
        self._t().table("eval_runs").upsert(row, on_conflict="run_id").execute()

    def list(self, owner: str, limit: int = 20) -> list[dict]:
        res = (self._t().table("eval_runs").select("*").eq("owner", owner)
               .order("created_at", desc=True).limit(limit).execute())
        return res.data or []

    def get(self, run_id: str) -> Optional[dict]:
        res = (self._t().table("eval_runs").select("*")
               .eq("run_id", run_id).limit(1).execute())
        return (res.data or [None])[0]


_RUNS: Any = None


def runs_backend():
    global _RUNS
    if _RUNS is not None:
        return _RUNS
    if db.is_configured():
        try:
            _RUNS = _SupabaseRuns()
            return _RUNS
        except Exception:  # noqa: BLE001
            pass
    _RUNS = _MemoryRuns()
    return _RUNS


def set_runs_backend(backend: Any) -> None:
    global _RUNS
    _RUNS = backend


def save_run(owner: str, summary: dict, results: list[dict],
             dataset_name: str = "", backend: Any = None) -> dict:
    import datetime as _dt
    row = {
        "run_id": str(uuid.uuid4()),
        "owner": owner or "",
        "name": summary.get("name") or "eval",
        "dataset_name": dataset_name or "",
        "accuracy": summary.get("accuracy"),
        "passed": summary.get("passed"),
        "total": summary.get("total"),
        "latency_mean_ms": summary.get("latency_mean_ms"),
        "cost_total_usd": summary.get("cost_total_usd"),
        "summary": summary,
        # Simpan hanya ringkas per-kasus (batasi 1000 baris jsonb).
        "results": results[:MAX_CASES],
        "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    (backend or runs_backend()).save(row)
    return row


def list_runs(owner: str, limit: int = 20, backend: Any = None) -> list[dict]:
    return (backend or runs_backend()).list(owner, limit)


__all__ = [
    "COMPARE_MODES", "DEFAULT_THRESHOLD", "MAX_CASES",
    "load_dataset", "compare", "estimate_cost", "Evaluator",
    "save_run", "list_runs", "runs_backend", "set_runs_backend",
]
