# workflow_optimizer.py — Fitur #9: AI Workflow Optimizer (Okt 2026)
# ======================================================================
# Menganalisis DAG workflow -> menemukan inefisiensi -> memberi rekomendasi
# (merge node, paralelisasi, cache, retry) + estimasi biaya & latensi, serta
# dapat MENERAPKAN optimasi berisiko-rendah secara aman.
#
# RISET (Okt 2026): optimasi DAG (paralelisasi independen, dedup panggilan,
# caching) + estimasi biaya/latensi per-model adalah pola standar platform
# orkestrasi. KEPUTUSAN: implementasi in-house murni (deterministik, dapat
# di-hard-test, nol dependensi).
#
# KEAMANAN: hanya menganalisis STRUKTUR (id/kind/config) — tidak pernah
# memuat nilai rahasia ke keluaran analisis.
# ======================================================================

from __future__ import annotations

import json
from typing import Any, Optional

#: Biaya USD per pemanggilan node (default; dapat diganti via `pricing`).
DEFAULT_PRICING: dict[str, float] = {
    "trigger": 0.0, "code": 0.0, "mcp": 0.0005, "agent": 0.01,
    "vector_store": 0.0002, "guardrails": 0.0001, "wait_for_human": 0.0,
}

#: Latensi dasar per jenis node (ms) — dipakai bila node tak punya `latency_ms`.
DEFAULT_LATENCY_MS: dict[str, float] = {
    "trigger": 1.0, "code": 20.0, "mcp": 300.0, "agent": 1500.0,
    "vector_store": 120.0, "guardrails": 15.0, "wait_for_human": 0.0,
}

#: Biaya/latensi per model (multi-model support).
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gemini-3.8-flash": {"cost": 0.004, "latency_ms": 900.0},
    "gemini-3.8-pro": {"cost": 0.02, "latency_ms": 2200.0},
    "gpt-5.1": {"cost": 0.015, "latency_ms": 1800.0},
    "claude-4.5": {"cost": 0.012, "latency_ms": 1600.0},
}

RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


# ---------------------------------------------------------------------------
# Graf
# ---------------------------------------------------------------------------

def _nodes(flow: dict) -> list[dict]:
    return list((flow or {}).get("nodes") or [])


def _edges(flow: dict) -> list[dict]:
    out = []
    for e in (flow or {}).get("edges") or []:
        a = str(e.get("source") or e.get("from") or "")
        b = str(e.get("target") or e.get("to") or "")
        if a and b:
            out.append({"source": a, "target": b,
                        "label": e.get("label", ""),
                        "branch": e.get("branch")})
    return out


def _adjacency(flow: dict) -> tuple[dict[str, set], dict[str, set]]:
    succ: dict[str, set] = {}
    pred: dict[str, set] = {}
    for n in _nodes(flow):
        succ.setdefault(str(n.get("id")), set())
        pred.setdefault(str(n.get("id")), set())
    for e in _edges(flow):
        succ.setdefault(e["source"], set()).add(e["target"])
        pred.setdefault(e["target"], set()).add(e["source"])
    return succ, pred


def _node_by_id(flow: dict) -> dict[str, dict]:
    return {str(n.get("id")): n for n in _nodes(flow)}


# ---------------------------------------------------------------------------
# Deteksi inefisiensi
# ---------------------------------------------------------------------------

def _signature(node: dict) -> str:
    """Tanda tangan node untuk mendeteksi DUPLIKAT (kind + config relevan)."""
    cfg = node.get("config") or {}
    relevan = {k: cfg.get(k) for k in ("action", "target", "url", "method",
                                       "prompt", "model", "query") if cfg.get(k)}
    return json.dumps({"kind": node.get("kind"), **relevan}, sort_keys=True)


def detect_duplicate_calls(flow: dict) -> list[dict]:
    """Node dengan panggilan identik -> kandidat cache/merge."""
    grup: dict[str, list[str]] = {}
    for n in _nodes(flow):
        if n.get("kind") in ("mcp", "agent", "vector_store"):
            grup.setdefault(_signature(n), []).append(str(n.get("id")))
    out = []
    for sig, ids in grup.items():
        if len(ids) > 1:
            out.append({"type": "duplicate_call", "nodes": sorted(ids),
                        "signature": sig, "count": len(ids)})
    return out


def detect_sequential_parallelizable(flow: dict) -> list[dict]:
    """Node yang berbagi pendahulu sama & tidak saling bergantung -> paralel."""
    succ, pred = _adjacency(flow)
    # grup berdasarkan himpunan pendahulu
    grup: dict[frozenset, list[str]] = {}
    for nid, ps in pred.items():
        if not ps:
            continue
        grup.setdefault(frozenset(ps), []).append(nid)
    out = []
    for ps, ids in grup.items():
        if len(ids) < 2:
            continue
        # pastikan tidak ada edge antar-anggota (benar-benar independen)
        independen = all(b not in succ.get(a, set()) for a in ids for b in ids
                         if a != b)
        if independen:
            out.append({"type": "parallelizable", "nodes": sorted(ids),
                        "shared_predecessors": sorted(ps)})
    return out


def detect_missing_cache(flow: dict) -> list[dict]:
    """Node mahal (mcp/agent) tanpa cache -> sarankan cache."""
    out = []
    for n in _nodes(flow):
        cfg = n.get("config") or {}
        if n.get("kind") in ("mcp", "agent", "vector_store") and not cfg.get("cache"):
            out.append({"type": "missing_cache", "nodes": [str(n.get("id"))]})
    return out


def detect_missing_retry(flow: dict) -> list[dict]:
    """Node jaringan (mcp) tanpa retry/on_error -> sarankan retry."""
    out = []
    for n in _nodes(flow):
        cfg = n.get("config") or {}
        if n.get("kind") == "mcp" and not (n.get("on_error") or cfg.get("retry")
                                           or cfg.get("on_error")):
            out.append({"type": "missing_retry", "nodes": [str(n.get("id"))]})
    return out


# ---------------------------------------------------------------------------
# Estimasi biaya & latensi
# ---------------------------------------------------------------------------

def _node_cost(node: dict, pricing: dict) -> float:
    cfg = node.get("config") or {}
    model = cfg.get("model")
    if model and model in MODEL_PRICING:
        return MODEL_PRICING[model]["cost"]
    return float(pricing.get(node.get("kind"), 0.0))


def _node_latency(node: dict, latency: dict) -> float:
    cfg = node.get("config") or {}
    if cfg.get("latency_ms") is not None:
        return float(cfg["latency_ms"])
    model = cfg.get("model")
    if model and model in MODEL_PRICING:
        return MODEL_PRICING[model]["latency_ms"]
    return float(latency.get(node.get("kind"), 0.0))


def estimate_cost(flow: dict, pricing: Optional[dict] = None) -> float:
    p = pricing or DEFAULT_PRICING
    return round(sum(_node_cost(n, p) for n in _nodes(flow)), 6)


def estimate_latency(flow: dict, latency: Optional[dict] = None) -> float:
    """Latensi (ms): jumlah sekuensial, TAPI grup paralel memakai MAX.

    Model sederhana namun benar untuk DAG tanpa cabang bersarang.
    """
    lat = latency or DEFAULT_LATENCY_MS
    ids = [str(n.get("id")) for n in _nodes(flow)]
    if not ids:
        return 0.0
    durasi = {str(n.get("id")): _node_latency(n, lat) for n in _nodes(flow)}
    succ, pred = _adjacency(flow)
    # level topologis
    level: dict[str, int] = {}
    sisa = set(ids)
    while sisa:
        maju = False
        for nid in list(sisa):
            ps = pred.get(nid, set()) & sisa
            if not ps:
                level[nid] = 0
                sisa.discard(nid)
                maju = True
        if not maju:            # siklus -> hentikan
            for nid in sisa:
                level[nid] = 0
            break
    # hitung level berjenjang
    for _ in range(len(ids) + 1):
        berubah = False
        for nid in ids:
            ps = pred.get(nid, set())
            if ps:
                lv = max(level.get(p, 0) for p in ps) + 1
                if level.get(nid, 0) < lv:
                    level[nid] = lv
                    berubah = True
        if not berubah:
            break
    per_level: dict[int, float] = {}
    for nid, lv in level.items():
        per_level[lv] = max(per_level.get(lv, 0.0), durasi.get(nid, 0.0))
    return round(sum(per_level.values()), 3)


# ---------------------------------------------------------------------------
# Analisis lengkap + rekomendasi
# ---------------------------------------------------------------------------

def analyze(flow: dict, pricing: Optional[dict] = None,
            latency: Optional[dict] = None) -> dict:
    """Analisis workflow -> temuan + rekomendasi + estimasi biaya/latensi."""
    temuan: list[dict] = []
    rekomendasi: list[dict] = []

    dup = detect_duplicate_calls(flow)
    for d in dup:
        temuan.append({"type": "duplicate_call", "nodes": d["nodes"],
                       "detail": f"{d['count']} panggilan identik"})
        rekomendasi.append({
            "id": f"cache-{'-'.join(d['nodes'])}", "type": "cache",
            "title": "Cache panggilan duplikat", "nodes": d["nodes"],
            "risk": "low",
            "saving_cost": round(_node_cost(_node_by_id(flow).get(d["nodes"][0],
                                                                  {}), pricing or DEFAULT_PRICING)
                                 * (d["count"] - 1), 6),
            "saving_latency_ms": round(_node_latency(
                _node_by_id(flow).get(d["nodes"][0], {}), latency or DEFAULT_LATENCY_MS)
                * (d["count"] - 1), 3),
        })

    par = detect_sequential_parallelizable(flow)
    for p in par:
        temuan.append({"type": "parallelizable", "nodes": p["nodes"],
                       "detail": "node independen berbagi pendahulu"})
        rekomendasi.append({
            "id": f"parallel-{'-'.join(p['nodes'])}", "type": "parallel",
            "title": "Jalankan node independen secara paralel",
            "nodes": p["nodes"], "risk": "medium",
            "saving_latency_ms": round(sum(
                _node_latency(_node_by_id(flow).get(n, {}),
                              latency or DEFAULT_LATENCY_MS)
                for n in p["nodes"][1:]), 3),
            "saving_cost": 0.0,
        })

    for m in detect_missing_cache(flow):
        if any(m["nodes"][0] in r["nodes"] for r in rekomendasi
               if r["type"] == "cache"):
            continue
        rekomendasi.append({
            "id": f"addcache-{m['nodes'][0]}", "type": "cache",
            "title": "Tambahkan cache pada node mahal", "nodes": m["nodes"],
            "risk": "low", "saving_cost": 0.0, "saving_latency_ms": 0.0})

    for m in detect_missing_retry(flow):
        rekomendasi.append({
            "id": f"retry-{m['nodes'][0]}", "type": "retry",
            "title": "Tambahkan retry pada node jaringan", "nodes": m["nodes"],
            "risk": "low", "saving_cost": 0.0, "saving_latency_ms": 0.0})

    return {
        "node_count": len(_nodes(flow)),
        "edge_count": len(_edges(flow)),
        "findings": temuan,
        "recommendations": rekomendasi,
        "cost_usd": estimate_cost(flow, pricing),
        "latency_ms": estimate_latency(flow, latency),
        "potential_saving_cost": round(sum(r["saving_cost"]
                                           for r in rekomendasi), 6),
        "potential_saving_latency_ms": round(sum(r["saving_latency_ms"]
                                                 for r in rekomendasi), 3),
    }


# ---------------------------------------------------------------------------
# Terapkan optimasi (aman)
# ---------------------------------------------------------------------------

def _copy(flow: dict) -> dict:
    return json.loads(json.dumps(flow))


def apply(flow: dict, recommendations: list[dict],
          accept_ids: Optional[list[str]] = None,
          max_risk: str = "low") -> dict:
    """Terapkan rekomendasi. Default: hanya risiko <= `max_risk` (aman).

    `accept_ids` memaksa menerapkan id tertentu walau risikonya lebih tinggi.
    Return {flow, applied, skipped}.
    """
    terima = set(accept_ids or [])
    batas = RISK_ORDER.get(max_risk, 0)
    baru = _copy(flow)
    by_id = _node_by_id(baru)
    applied: list[str] = []
    skipped: list[dict] = []

    for r in recommendations or []:
        rid = r.get("id", "")
        risk = r.get("risk", "low")
        izin = (rid in terima) or (RISK_ORDER.get(risk, 0) <= batas)
        if not izin:
            skipped.append({"id": rid, "reason": f"risiko {risk} > {max_risk}"})
            continue
        jenis = r.get("type")
        if jenis == "cache":
            for nid in r.get("nodes", []):
                if nid in by_id:
                    by_id[nid].setdefault("config", {})["cache"] = True
            applied.append(rid)
        elif jenis == "retry":
            for nid in r.get("nodes", []):
                if nid in by_id:
                    by_id[nid].setdefault("config", {})["retry"] = True
                    by_id[nid]["on_error"] = "retry"
            applied.append(rid)
        elif jenis == "parallel":
            for nid in r.get("nodes", []):
                if nid in by_id:
                    by_id[nid].setdefault("config", {})["parallel_group"] = rid
            applied.append(rid)
        else:
            skipped.append({"id": rid, "reason": f"jenis tak dikenal: {jenis}"})
    return {"flow": baru, "applied": applied, "skipped": skipped}


def apply_safe(flow: dict, accept_ids: Optional[list[str]] = None) -> dict:
    """Analisis + terapkan otomatis rekomendasi berisiko-rendah."""
    hasil = analyze(flow)
    return apply(flow, hasil["recommendations"], accept_ids=accept_ids,
                 max_risk="low")


# ---------------------------------------------------------------------------
# Loop umpan balik pengguna
# ---------------------------------------------------------------------------

class FeedbackStore:
    """Catat umpan balik pengguna terhadap rekomendasi (untuk perbaikan)."""

    def __init__(self) -> None:
        self._data: list[dict] = []

    def record(self, rec_id: str, accepted: bool, note: str = "") -> dict:
        entry = {"id": rec_id, "accepted": bool(accepted), "note": note}
        self._data.append(entry)
        return entry

    def all(self) -> list[dict]:
        return list(self._data)

    def acceptance_rate(self) -> float:
        if not self._data:
            return 0.0
        return round(sum(1 for e in self._data if e["accepted"])
                     / len(self._data), 4)
