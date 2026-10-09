"""FASE 2 — prober kesehatan connector (live, deterministik).

Menggabungkan dua sinyal:
  1. **Probe MCP native** (utama) — protokol resmi:
     `initialize` -> `notifications/initialized` -> `tools/list`.
     Ini yang menentukan ALIVE/AUTH/DEAD karena berhasil membaca `tools/list`
     berarti benar-benar menerima data.
  2. **mcp-wringer** (sekunder) — fuzzer sungguhan, dipakai untuk mencatat
     apakah server lolos spec `2025-11-25`. Terlalu ketat untuk dijadikan
     satu-satunya penentu (lihat docs/skills-installed.md §3.1).

Hasil disimpan ke tabel `connector_health` lewat `connector_store`.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Iterable

import httpx

import connector_store as cs

PROTOCOL_VERSION = "2025-06-18"
DEFAULT_TIMEOUT = 12.0
DEFAULT_WORKERS = 12
USER_AGENT = "katalir-connector-prober/1.0"


# --------------------------------------------------------------------------
# protokol MCP
# --------------------------------------------------------------------------

def _parse_body(resp: httpx.Response) -> dict | None:
    """Body bisa JSON murni atau SSE (`data: {...}`). Tangani keduanya."""
    text = resp.text or ""
    ctype = (resp.headers.get("content-type") or "").lower()
    if "text/event-stream" in ctype or text.lstrip().startswith("event:"):
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[5:].strip()
                try:
                    return json.loads(payload)
                except ValueError:
                    continue
        return None
    try:
        return resp.json()
    except ValueError:
        return None


def probe_endpoint(url: str, *, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Probe satu endpoint MCP. Selalu mengembalikan dict, tidak melempar.

    Kunci hasil: http_status, tools_count, verdict, error, latency_ms, raw.
    """
    t0 = time.time()
    result: dict[str, Any] = {
        "endpoint_url": url, "http_status": None, "tools_count": None,
        "error": None, "raw": None, "prober": "catalog-probe",
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": USER_AGENT,
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as cli:
            # 1) initialize
            init = cli.post(url, headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "katalir-prober", "version": "1.0"},
                },
            })
            result["http_status"] = init.status_code
            sid = init.headers.get("mcp-session-id")
            body = _parse_body(init)
            if body and body.get("error"):
                result["error"] = str(body["error"])[:400]

            if init.status_code >= 400:
                result["verdict"] = cs.classify(init.status_code, error=result["error"])
                result["latency_ms"] = int((time.time() - t0) * 1000)
                return result

            h2 = dict(headers)
            if sid:
                h2["mcp-session-id"] = sid

            # 2) notifications/initialized (best effort, tanpa id)
            try:
                cli.post(url, headers=h2, json={
                    "jsonrpc": "2.0", "method": "notifications/initialized"})
            except httpx.HTTPError:
                pass

            # 3) tools/list
            tl = cli.post(url, headers=h2, json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            result["http_status"] = tl.status_code
            tbody = _parse_body(tl)
            if tbody is None:
                result["error"] = (result["error"] or
                                   f"body tidak terbaca (content-type={tl.headers.get('content-type')})")
            elif tbody.get("error"):
                result["error"] = str(tbody["error"])[:400]
            else:
                tools = ((tbody.get("result") or {}).get("tools")) or []
                result["tools_count"] = len(tools)
                result["raw"] = {"tools_sample": [t.get("name") for t in tools[:8]]}
    except httpx.HTTPError as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"[:400]
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"[:400]

    result["verdict"] = cs.classify(result["http_status"],
                                    tools_count=result["tools_count"],
                                    error=result["error"])
    result["latency_ms"] = int((time.time() - t0) * 1000)
    return result


# --------------------------------------------------------------------------
# batch
# --------------------------------------------------------------------------

def targets(limit: int | None = None) -> list[dict]:
    """Ambil kandidat ber-URL (transport streamable_http) dari katalog."""
    import mcp_registry as mr
    out = []
    for cid, e in mr.load_cached().items():
        ic = e.get("install_config") or {}
        if ic.get("transport") != "streamable_http":
            continue
        url = ic.get("package")
        if not (isinstance(url, str) and url.startswith("http")):
            continue
        out.append({"connector_id": cid, "endpoint_url": url})
    if limit:
        out = out[:limit]
    return out


def probe_many(items: Iterable[dict], *, workers: int = DEFAULT_WORKERS,
               timeout: float = DEFAULT_TIMEOUT,
               progress: bool = True) -> list[dict]:
    """Probe banyak endpoint secara paralel. Mengembalikan daftar hasil."""
    items = list(items)
    results: list[dict] = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(probe_endpoint, it["endpoint_url"], timeout=timeout): it
                for it in items}
        for fut in as_completed(futs):
            it = futs[fut]
            try:
                r = fut.result()
            except Exception as exc:  # noqa: BLE001
                r = {"endpoint_url": it["endpoint_url"], "http_status": None,
                     "tools_count": None, "error": f"{type(exc).__name__}: {exc}",
                     "verdict": "UNKNOWN", "latency_ms": None, "raw": None,
                     "prober": "catalog-probe"}
            r["connector_id"] = it["connector_id"]
            results.append(r)
            done += 1
            if progress and done % 25 == 0:
                print(f"  ... {done}/{len(items)}", flush=True)
    return results


def summarize(results: list[dict]) -> dict:
    """Hitung verdict + distribusi HTTP status."""
    out = {"ALIVE": 0, "AUTH": 0, "DEAD": 0, "UNKNOWN": 0, "total": len(results)}
    status: dict[str, int] = {}
    tools_total = 0
    for r in results:
        v = r.get("verdict") or "UNKNOWN"
        out[v] = out.get(v, 0) + 1
        s = r.get("http_status")
        status[str(s)] = status.get(str(s), 0) + 1
        if r.get("tools_count"):
            tools_total += r["tools_count"]
    out["by_http_status"] = dict(sorted(status.items(), key=lambda kv: -kv[1]))
    out["tools_total"] = tools_total
    return out


def to_health_rows(results: list[dict]) -> list[dict]:
    """Ubah hasil probe -> baris tabel connector_health."""
    rows = []
    for r in results:
        rows.append({
            "connector_id": r["connector_id"],
            "endpoint_url": r.get("endpoint_url"),
            "verdict": r.get("verdict") or "UNKNOWN",
            "http_status": r.get("http_status"),
            "tools_count": r.get("tools_count"),
            "latency_ms": r.get("latency_ms"),
            "error": (r.get("error") or None),
            "prober": r.get("prober") or "catalog-probe",
            "raw": r.get("raw"),
        })
    return rows


def persist(results: list[dict]) -> dict:
    """Simpan hasil probe ke `connector_health`."""
    return cs.record_health(to_health_rows(results))


def describe() -> dict:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "timeout_s": DEFAULT_TIMEOUT,
        "workers": DEFAULT_WORKERS,
        "supported_transports": ["streamable_http"],
        "verdicts": list(cs.VERDICTS),
    }
