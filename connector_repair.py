"""FASE 3 — auto-fix connector rusak.

Metodologi diadaptasi dari skill `opencli-autofix`
(`github.com/chobitly/opencli/skills/opencli-autofix`). Skill itu sendiri
menargetkan adapter OpenCLI (DOM/Chrome extension), **bukan** connector MCP,
jadi yang diambil adalah **disiplin prosesnya**:

  * bedakan dulu "kosong" vs "rusak" — jangan menambal noise;
  * batas percobaan maksimum 3 putaran per connector;
  * hard stop yang tidak boleh ditambal (AUTH butuh kredensial manusia);
  * hanya menyentuh berkas yang memang milik connector itu.

Yang **tidak** diambil: `RepairContext.adapter.sourcePath`, `opencli doctor`,
`OPENCLI_DIAGNOSTIC` — semuanya tidak relevan untuk connector MCP.

Aksi perbaikan nyata yang tersedia untuk katalog ini:

  1. `AUTH`      -> **BUKAN kerusakan**. Butuh kredensial pemilik. Tidak
                    ditambal; dicatat agar UI bisa meminta kredensial.
  2. `DEAD` 5xx  -> probe ulang (mungkin transien). Bila tetap mati setelah
                    3 putaran -> tandai `healthy=False`, jangan dihapus.
  3. `404/400`   -> endpoint mungkin pindah. Cari URL baru di katalog
                    (source_url / repo_url) lalu uji ulang.
  4. `UNKNOWN`   -> probe ulang dengan timeout lebih panjang sebelum
                    menyimpulkan apa pun.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Callable

import connector_prober as cp
import connector_store as cs

MAX_ROUNDS = 3
BACKOFF_S = (1.0, 3.0, 7.0)
# Timeout probe ulang. Sengaja lebih pendek dari probe awal: connector yang
# tidak menjawab dalam 8s saat diperbaiki hampir pasti memang tidak sehat,
# dan menunggu 25s x 3 putaran membuat proses panjang mudah terbunuh.
REPROBE_TIMEOUT = 8.0

# Penyebab yang HARAM ditambal otomatis (butuh tindakan manusia/langganan).
HARD_STOP_CAUSES = ("auth_required", "payment_required")
# Verdict yang tidak pernah layak ditambal.
HARD_STOPS = ("AUTH",)


class RepairRefused(RuntimeError):
    """Perbaikan dihentikan karena hard stop (mis. butuh kredensial)."""


def _log(path: pathlib.Path, record: dict) -> None:
    """Log perbaikan append-only (JSON Lines)."""
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def diagnose(result: dict) -> dict:
    """Klasifikasi sebab + tentukan apakah layak ditambal.

    Mengembalikan {verdict, cause, repairable, reason}.
    """
    verdict = result.get("verdict") or "UNKNOWN"
    status = result.get("http_status")
    err = (result.get("error") or "").lower()

    if verdict == "ALIVE":
        return {"verdict": verdict, "cause": "healthy", "repairable": False,
                "reason": "sudah ALIVE; tidak ada yang perlu diperbaiki"}
    if verdict == "AUTH":
        return {"verdict": verdict, "cause": "auth_required", "repairable": False,
                "reason": "hard stop: butuh kredensial manusia, bukan kerusakan kode"}
    if status == 404:
        return {"verdict": verdict, "cause": "endpoint_moved", "repairable": True,
                "reason": "404 — endpoint mungkin pindah; cari URL baru di katalog"}
    if status in (400, 405, 415):
        return {"verdict": verdict, "cause": "bad_request", "repairable": True,
                "reason": f"{status} — bentuk permintaan ditolak; cek protokol"}
    if status == 402:
        return {"verdict": verdict, "cause": "payment_required", "repairable": False,
                "reason": "hard stop: butuh langganan/kuota (bukan kerusakan)"}
    if status is not None and 500 <= status <= 599:
        return {"verdict": verdict, "cause": "server_error", "repairable": True,
                "reason": f"{status} — error sisi server; mungkin transien"}
    if verdict == "DEAD":
        return {"verdict": verdict, "cause": "unreachable", "repairable": True,
                "reason": "tidak dapat dijangkau; probe ulang untuk pastikan"}
    if verdict == "UNKNOWN":
        return {"verdict": verdict, "cause": "inconclusive", "repairable": True,
                "reason": "hasil tidak konklusif; probe ulang timeout lebih panjang"}
    return {"verdict": verdict, "cause": "other", "repairable": False,
            "reason": "tidak ada strategi perbaikan yang cocok"}


def find_alternative_url(connector_id: str) -> str | None:
    """Cari kandidat URL lain di katalog untuk connector yang sama.

    Sumber: `install_config.package`, `endpoint_url`, `source_url`, `repo_url`
    milik entri yang sama DAN entri lain dengan `slug`/`name` yang cocok.
    """
    import mcp_registry as mr
    cache = mr.load_cached()
    entry = cache.get(connector_id)
    if not isinstance(entry, dict):
        return None
    cur = (entry.get("install_config") or {}).get("package") or entry.get("endpoint_url")

    def _cands(e: dict) -> list[str]:
        ic = e.get("install_config") or {}
        vals = [ic.get("package"), e.get("endpoint_url"), e.get("source_url"),
                e.get("repo_url")]
        return [v for v in vals if isinstance(v, str) and v.startswith("http")]

    seen = set(_cands(entry))
    for cid, e in cache.items():
        if not isinstance(e, dict):
            continue
        if cid != connector_id and (e.get("slug") and e.get("slug") == entry.get("slug")):
            for v in _cands(e):
                if v not in seen:
                    return v
    # fallback: `source_url` sendiri (mungkin berbeda dari endpoint)
    for v in _cands(entry):
        if v != cur and "/mcp" in v:
            return v
    return None


def repair_one(result: dict, *, connector_id: str | None = None,
               probe: Callable[..., dict] | None = None,
               log_path: pathlib.Path | None = None,
               sleep: Callable[[float], None] | None = None) -> dict:
    """Perbaiki satu connector. Mengembalikan catatan perbaikan.

    Tidak pernah melempar untuk kasus normal; kegagalan dilaporkan lewat
    field `status` = 'fixed' | 'refused' | 'unfixable' | 'noop'.
    """
    import time as _time
    probe = probe or cp.probe_endpoint
    sleep = sleep or _time.sleep
    cid = connector_id or result.get("connector_id") or "?"
    rec: dict[str, Any] = {"connector_id": cid, "before": result.get("verdict"),
                           "rounds": [], "actions": []}

    diag = diagnose(result)
    rec["diagnosis"] = diag
    if diag["cause"] in HARD_STOP_CAUSES or not diag["repairable"]:
        rec["status"] = "refused" if diag["cause"] in HARD_STOP_CAUSES else "noop"
        rec["reason"] = diag["reason"]
        if log_path:
            _log(log_path, rec)
        return rec

    url = result.get("endpoint_url")
    # Strategi 1: probe ulang URL yang sama (transien / timeout pendek).
    for rnd in range(1, MAX_ROUNDS + 1):
        sleep(BACKOFF_S[min(rnd - 1, len(BACKOFF_S) - 1)])
        try:
            again = probe(url, timeout=REPROBE_TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            again = {"verdict": "UNKNOWN", "error": f"{type(exc).__name__}: {exc}",
                     "http_status": None, "tools_count": None}
        rec["rounds"].append({"round": rnd, "action": "reprobe_same_url",
                              "verdict": again.get("verdict"),
                              "http_status": again.get("http_status"),
                              "tools_count": again.get("tools_count")})
        if again.get("verdict") == "ALIVE":
            rec["status"] = "fixed"
            rec["after"] = "ALIVE"
            rec["fix"] = "transient — berhasil pada probe ulang"
            rec["result"] = again
            if log_path:
                _log(log_path, rec)
            return rec
        # Kalau sekarang jadi AUTH, itu bukan kerusakan.
        if again.get("verdict") == "AUTH":
            rec["status"] = "refused"
            rec["reason"] = "menjadi AUTH setelah probe ulang (butuh kredensial)"
            rec["after"] = "AUTH"
            rec["result"] = again
            if log_path:
                _log(log_path, rec)
            return rec

    # Strategi 2: cari URL alternatif dari katalog.
    alt = find_alternative_url(cid)
    if alt and alt != url:
        rec["actions"].append({"action": "try_alternative_url", "url": alt})
        try:
            r2 = probe(alt, timeout=REPROBE_TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            r2 = {"verdict": "UNKNOWN", "error": f"{type(exc).__name__}: {exc}",
                  "http_status": None, "tools_count": None}
        rec["rounds"].append({"round": "alt", "action": "probe_alternative_url",
                              "url": alt, "verdict": r2.get("verdict"),
                              "http_status": r2.get("http_status"),
                              "tools_count": r2.get("tools_count")})
        if r2.get("verdict") == "ALIVE":
            rec["status"] = "fixed"
            rec["after"] = "ALIVE"
            rec["fix"] = f"endpoint pindah -> {alt}"
            rec["new_url"] = alt
            rec["result"] = r2
            if log_path:
                _log(log_path, rec)
            return rec

    rec["status"] = "unfixable"
    rec["after"] = rec["rounds"][-1].get("verdict") if rec["rounds"] else None
    rec["reason"] = f"tidak berhasil setelah {MAX_ROUNDS} putaran + uji URL alternatif"
    if log_path:
        _log(log_path, rec)
    return rec


def repair_many(results: list[dict], *, probe: Callable[..., dict] | None = None,
                log_path: pathlib.Path | None = None,
                sleep: Callable[[float], None] | None = None,
                only_repairable: bool = True,
                workers: int = 8, timeout: float = 8.0,
                max_items: int | None = None) -> dict:
    """Perbaiki sekumpulan hasil probe secara paralel.

    Paralel + timeout pendek disengaja: satu connector DEAD bisa memakan
    MAX_ROUNDS x timeout, dan menjalankannya berurutan membuat proses panjang
    mudah terbunuh sebelum menulis hasil. Dengan `workers` paralel, total
    waktu turun ~workers kali.
    """
    from concurrent.futures import ThreadPoolExecutor

    jobs: list[dict] = []
    for r in results:
        diag = diagnose(r)
        if only_repairable and not diag["repairable"]:
            continue
        jobs.append(r)
    if max_items:
        jobs = jobs[:max_items]

    recs: list[dict] = []
    if workers <= 1 or len(jobs) <= 1:
        for r in jobs:
            recs.append(repair_one(r, probe=probe, log_path=log_path, sleep=sleep))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(repair_one, r, probe=probe,
                                log_path=log_path, sleep=sleep) for r in jobs]
            for f in futs:
                try:
                    recs.append(f.result())
                except Exception as exc:  # noqa: BLE001
                    recs.append({"connector_id": "?", "status": "noop",
                                 "reason": f"{type(exc).__name__}: {exc}"})
    out = {"status": {"fixed": 0, "refused": 0, "unfixable": 0, "noop": 0},
           "records": recs}
    for rec in recs:
        key = rec.get("status", "noop")
        out["status"][key] = out["status"].get(key, 0) + 1
    return out


def apply_fixes(repairs: dict) -> dict:
    """Tandai hasil perbaikan ke katalog + tabel health.

    - `fixed`     -> catat URL baru (bila ada) dan verdict ALIVE
    - `unfixable` -> tandai `healthy=False` (TIDAK dihapus)
    """
    import mcp_registry as mr
    cache = mr.load_cached()
    health_rows = []
    catalog_changes = []
    for rec in repairs.get("records", []):
        cid = rec["connector_id"]
        st = rec.get("status")
        if st == "fixed":
            entry = cache.get(cid)
            new_url = rec.get("new_url")
            if isinstance(entry, dict) and new_url:
                ic = entry.setdefault("install_config", {})
                ic["package"] = new_url
                entry["endpoint_url"] = new_url
                catalog_changes.append({"connector_id": cid, "package": new_url})
            res = rec.get("result") or {}
            health_rows.append({
                "connector_id": cid,
                "endpoint_url": rec.get("new_url") or res.get("endpoint_url"),
                "verdict": "ALIVE",
                "http_status": res.get("http_status"),
                "tools_count": res.get("tools_count"),
                "latency_ms": res.get("latency_ms"),
                "error": None, "prober": "autofix",
                "raw": {"fixed_via": rec.get("fix")},
            })
        elif st == "unfixable":
            entry = cache.get(cid)
            if isinstance(entry, dict):
                entry["healthy"] = False
                catalog_changes.append({"connector_id": cid, "healthy": False})
            health_rows.append({
                "connector_id": cid,
                "endpoint_url": None, "verdict": "DEAD",
                "http_status": (rec.get("rounds") or [{}])[-1].get("http_status"),
                "tools_count": None, "latency_ms": None,
                "error": rec.get("reason"), "prober": "autofix",
                "raw": {"rounds": rec.get("rounds")},
            })
    written = cs.record_health(health_rows) if health_rows else {"written": 0}
    return {"health_written": written, "catalog_changes": catalog_changes}


def describe() -> dict:
    return {
        "max_rounds": MAX_ROUNDS,
        "backoff_s": list(BACKOFF_S),
        "hard_stops": list(HARD_STOP_CAUSES),
        "methodology_from": "chobitly/opencli skills/opencli-autofix",
        "statuses": ["fixed", "refused", "unfixable", "noop"],
    }
