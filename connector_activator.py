"""connector_activator.py — materialisasi entri metadata_only menjadi executable.

DIAGNOSIS (dari data, bukan dugaan)
-----------------------------------
`mcp_registry.coverage()` melaporkan total 25.925 dengan hanya 23 executable.
Memeriksa `install_config.transport` pada seluruh katalog memberi distribusi:

    metadata-only        24.415   <- paket tanpa endpoint; perlu runtime sendiri
    composio-remote       1.558   <- toolkit Composio; butuh API key Composio
    mcp-meta-layer        1.554   <- OpenConnector; butuh gateway token
    streamable_http       1.000   <- ENDPOINT MCP NYATA
    None                  1.025   <- Nango provider (bukan MCP tool)
    openapi-generated         6   <- spesifikasi OpenAPI

`executable_servers()` menerima transport di `{'stdio','http','sse'}`. String
`streamable_http` TIDAK ada di himpunan itu, sehingga **1.000 connector yang
punya endpoint nyata + 995 sehat + 17.610 tool dikeluarkan hanya karena nama
transpornya berbeda** — celah penamaan, bukan celah kemampuan.

Itulah target pertama dan paling jujur: 1.000 connector yang sudah terbukti
sehat, bukan 1.000 entri katalog baru.

YANG DIVERIFIKASI SEBELUM AKTIVASI
----------------------------------
Aktivasi di sini berarti "entri ini boleh dieksekusi oleh runtime Katalir".
Supaya tidak menjadi sekadar mengubah label, setiap kandidat diperiksa:

  1. ada `endpoint_url` yang valid https
  2. host TIDAK loopback/privat (guard SSRF yang sama dengan `tools.py`)
  3. transport dapat dieksekusi (`streamable_http`, `http`, `sse`, `stdio`)
  4. `healthy` belum pernah dinyatakan False (kalau ada sinyalnya)

Opsional (kalau pemanggil menyalakan jaringan): endpoint benar-benar di-`HEAD`.

CARA MENJALANKAN (eksekusi nyata, bukan metadata)
-------------------------------------------------
Setiap connector yang diaktivasi dipetakan ke **executor** konkret:

  streamable_http/http/sse -> `_call_mcp_streamable()`  (JSON-RPC `tools/call`
                              ke endpoint MCP via httpx)
  stdio                    -> `_call_stdio()`            (subprocess stdio;
                              HANYA dijalankan bila pemanggil mengizinkan
                              eksekusi kode pihak ketiga)
  metadata-only            -> tidak diaktivasi (butuh runtime/kredensial
                              yang belum ada — dilaporkan, tidak diklaim)

`execute(entry, tool, arguments)` adalah jalur panggilan nyata. Kalau ia tidak
bisa dijalankan, connector TIDAK dihitung executable.

ATURAN YANG TIDAK DILANGGAR
---------------------------
- Aktivasi idempoten: memanggil dua kali tidak menggandakan.
- `call_verified` hanya diberikan setelah panggilan nyata berhasil.
- Connector yang butuh kredensial tetap diaktivasi (jalur runtime ada), tetapi
  `call_verified` tetap False sampai ada kredensial user — dilaporkan apa adanya.
- Bisa di-rollback: `deactivate()` mengembalikan status.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse

# Transport yang benar-benar dapat dieksekusi runtime Katalir.
EXECUTABLE_TRANSPORTS = ("streamable_http", "http", "sse", "stdio")

# Transport yang MEMERLUKAN layanan pihak ketiga (Composio/OpenConnector) dan
# karena itu tidak dapat diaktivasi hanya dengan data katalog.
EXTERNAL_SERVICE_TRANSPORTS = ("composio-remote", "mcp-meta-layer")

# Transport yang tidak menyimpan alamat apa pun; perlu runtime sendiri
# (Docker/package manager) yang belum disediakan.
DEFERRED_TRANSPORTS = ("metadata-only", None)

_HTTPS_RE = re.compile(r"^https://", re.I)

_BLOCKED_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1",
                  "169.254.169.254", "metadata.google.internal")
_BLOCKED_PREFIXES = ("10.", "192.168.", "172.16.", "172.17.", "172.18.",
                     "172.19.", "172.2", "172.30.", "172.31.", "127.")
_PRIVATE_SUFFIX = (".local", ".internal", ".localdomain", ".localhost")


class ActivationError(ValueError):
    """Kandidat tidak dapat diaktivasi. Membawa alasan yang dapat dibaca."""


# ---------------------------------------------------------------------------
# Hasil
# ---------------------------------------------------------------------------


@dataclass
class ActivationResult:
    connector_id: str
    activated: bool
    reason: str = ""
    transport: str = ""
    endpoint_url: str = ""
    auth_type: str = ""
    tools_count: int = 0
    call_verified: bool = False
    verified_by: str = ""
    evidence: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "activated": self.activated,
            "reason": self.reason,
            "transport": self.transport,
            "endpoint_url": self.endpoint_url,
            "auth_type": self.auth_type,
            "tools_count": self.tools_count,
            "call_verified": self.call_verified,
            "verified_by": self.verified_by,
            "evidence": self.evidence,
        }


def host_blocked(host: str) -> bool:
    """Guard SSRF — semantik sama dengan `tools._host_blocked()`.

    Sengaja TIDAK melakukan resolusi DNS di sini (berbeda dari versi penuh di
    `tools.py`): fungsi ini dipanggil untuk ribuan entri, dan resolusi DNS per
    entri akan membuat aktivasi lambat sekaligus membanjiri resolver publik.
    Resolusi dilakukan sekali per host unik oleh pemanggil (`bulk_activate`),
    memakai `_resolve_blocked()` yang identik dengan versi penuh.
    """
    h = (host or "").strip().strip("[]").lower()
    if not h:
        return True
    if h in _BLOCKED_HOSTS:
        return True
    for pfx in _BLOCKED_PREFIXES:
        if h.startswith(pfx):
            return True
    for sfx in _PRIVATE_SUFFIX:
        if h.endswith(sfx):
            return True
    return False


def _resolve_blocked(host: str) -> bool:
    """Versi penuh: periksa SETIAP alamat hasil resolusi (anti DNS-rebinding)."""
    import ipaddress
    import socket

    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:  # noqa: BLE001 - tidak dapat dipastikan -> tolak
        return True
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return True
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True
    return False


def url_activatable(url: str) -> tuple[bool, str]:
    """Periksa apakah endpoint boleh dieksekusi. Mengembalikan (ok, alasan)."""
    if not url:
        return False, "endpoint_url kosong"
    if not _HTTPS_RE.match(url):
        return False, "endpoint bukan https"
    try:
        p = urlparse(url)
    except Exception:  # noqa: BLE001
        return False, "endpoint tidak dapat di-parse"
    if not p.hostname:
        return False, "endpoint tanpa host"
    if host_blocked(p.hostname):
        return False, f"host diblokir SSRF ({p.hostname})"
    return True, ""


# ---------------------------------------------------------------------------
# Keputusan aktivasi
# ---------------------------------------------------------------------------


def activation_plan(entry: dict) -> dict[str, Any]:
    """Tentukan apakah entri dapat diaktivasi, dan mengapa.

    Fungsi ini MURNI (tanpa jaringan) sehingga dapat diuji cepat dan
    deterministik. Hasilnya dipakai `bulk_activate` untuk memutuskan.
    """
    ic = entry.get("install_config") or {}
    transport = str(ic.get("transport") or "")
    url = str(entry.get("endpoint_url") or ic.get("package") or "")
    auth = str(entry.get("auth_type") or "")
    cid = str(entry.get("id") or "")

    if transport in DEFERRED_TRANSPORTS or transport == "":
        # DEFERRED selalu ditolak sebagai "deferred" — bukan "unsupported".
        # Bedanya penting untuk laporan: deferred berarti "katalognya belum
        # membawa endpoint, perlu runtime/registri lain di masa depan",
        # sedangkan unsupported berarti "transpornya memang bukan jalur
        # eksekusi Katalir".
        #
        # Catatan: `"" not in DEFERRED_TRANSPORTS` secara literal (tuple berisi
        # None, bukan ""), jadi pemeriksaan `== ""` ditulis eksplisit. Tanpa itu
        # 1.025 entri Nango ber-transport kosong salah dilaporkan "unsupported".
        if not url:
            reason = ("tanpa transport & tanpa endpoint" if transport == ""
                      else "transport metadata-only tanpa endpoint")
            return {"ok": False, "reason": reason,
                    "kind": "deferred", "transport": transport}
        # transport "metadata-only"/"" TAPI punya endpoint: tetap deferred,
        # karena transport-nya bukan jalur eksekusi yang dikenal. Tidak
        # dipromosikan hanya karena ada URL.
        return {"ok": False,
                "reason": (f"transport '{transport or 'kosong'}' tidak dapat "
                           "dieksekusi meski endpoint ada"),
                "kind": "deferred", "transport": transport}

    if transport in EXTERNAL_SERVICE_TRANSPORTS:
        return {"ok": False,
                "reason": f"butuh layanan pihak ketiga ({transport}); bukan endpoint mandiri",
                "kind": "external", "transport": transport}

    if transport not in EXECUTABLE_TRANSPORTS:
        return {"ok": False, "reason": f"transport tidak dapat dieksekusi: '{transport}'",
                "kind": "unsupported", "transport": transport}

    ok, why = url_activatable(url)
    if not ok and transport != "stdio":
        return {"ok": False, "reason": why, "kind": "bad_endpoint", "transport": transport}

    if entry.get("healthy") is False:
        return {"ok": False, "reason": "sebelumnya ditandai tidak sehat (healthy=false)",
                "kind": "unhealthy", "transport": transport}

    return {"ok": True, "reason": "", "kind": "ready", "transport": transport,
            "endpoint_url": url, "auth_type": auth, "connector_id": cid}


# ---------------------------------------------------------------------------
# Runtime executor — jalur panggilan NYATA
# ---------------------------------------------------------------------------


class UnsupportedTransport(RuntimeError):
    pass


def _call_mcp_streamable(endpoint: str, tool: str,
                         arguments: dict | None = None,
                         headers: dict | None = None,
                         timeout: float = 20.0) -> dict:
    """Panggil tool di endpoint MCP Streamable HTTP (JSON-RPC 2.0 `tools/call`).

    Ini jalur eksekusi sebenarnya untuk connector ber-transport
    `streamable_http` — bukan sekadar penanda status.
    """
    import httpx

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments or {}},
    }
    hdrs = {"Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"}
    if headers:
        hdrs.update(headers)

    with httpx.Client(timeout=timeout) as c:
        r = c.post(endpoint, json=payload, headers=hdrs)

    body: Any
    ctype = r.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        # SSE: ambil muatan JSON terakhir yang berbentuk event data.
        body = None
        for line in r.text.splitlines():
            if line.startswith("data:"):
                try:
                    body = json.loads(line[5:].strip())
                except ValueError:
                    continue
    else:
        try:
            body = r.json()
        except ValueError:
            body = {"raw": r.text[:500]}

    return {"status_code": r.status_code, "body": body,
            "endpoint": endpoint, "tool": tool}


def _call_stdio(command: list[str], tool: str,
                arguments: dict | None = None,
                timeout: float = 20.0) -> dict:
    """Panggil tool via MCP stdio. Dijalankan hanya bila pemanggil mengizinkan."""
    import subprocess

    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                      "params": {"name": tool, "arguments": arguments or {}}})
    proc = subprocess.run(  # noqa: S603 - command berasal dari katalog tepercaya
        command, input=req.encode("utf-8"), capture_output=True, timeout=timeout,
    )
    out = proc.stdout.decode("utf-8", errors="replace")[:2000]
    return {"returncode": proc.returncode, "stdout": out,
            "stderr": proc.stderr.decode("utf-8", errors="replace")[:500]}


def execute(entry: dict, tool: str, arguments: dict | None = None,
            *, timeout: float = 20.0, allow_stdio: bool = False) -> dict:
    """Jalankan satu tool pada connector. Ini eksekusi nyata.

    Raises:
        UnsupportedTransport: transport tidak punya jalur eksekusi.
        ActivationError: endpoint diblokir atau tidak sah.
    """
    ic = entry.get("install_config") or {}
    transport = str(ic.get("transport") or "")
    url = str(entry.get("endpoint_url") or ic.get("package") or "")

    if transport in ("streamable_http", "http", "sse"):
        ok, why = url_activatable(url)
        if not ok:
            raise ActivationError(why)
        return _call_mcp_streamable(url, tool, arguments, timeout=timeout)

    if transport == "stdio":
        if not allow_stdio:
            raise UnsupportedTransport(
                "execusi stdio memerlukan allow_stdio=True (menjalankan kode pihak ketiga)"
            )
        pkg = str(ic.get("package") or "")
        if not pkg:
            raise ActivationError("stdio tanpa package")
        return _call_stdio(pkg.split(), tool, arguments, timeout=timeout)

    raise UnsupportedTransport(f"transport '{transport}' tidak punya executor")


# ---------------------------------------------------------------------------
# Aktivasi massal
# ---------------------------------------------------------------------------


@dataclass
class ActivationLedger:
    """Buku besar aktivasi — dapat di-rollback, idempoten."""

    activated: dict[str, dict] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)

    def activate(self, entry: dict) -> ActivationResult:
        cid = str(entry.get("id") or "")
        plan = activation_plan(entry)
        if not plan["ok"]:
            # Idempoten: yang sudah aktif tidak berubah menjadi skipped.
            if cid in self.activated:
                return ActivationResult(cid, True, "sudah aktif (idempoten)",
                                        transport=plan.get("transport", ""))
            self.skipped[cid] = str(plan["reason"])
            return ActivationResult(
                cid, False, str(plan["reason"]),
                transport=str(plan.get("transport") or ""),
                endpoint_url=str(entry.get("endpoint_url") or ""),
                auth_type=str(entry.get("auth_type") or ""),
            )

        already = cid in self.activated
        rec = {
            "id": cid,
            "transport": plan["transport"],
            "endpoint_url": plan["endpoint_url"],
            "auth_type": plan["auth_type"],
            "tools_count": int(entry.get("tools_count") or 0),
            "activated_at": None if already else time.time(),
            "runtime": "manifest-executor",
        }
        self.activated[cid] = rec
        self.skipped.pop(cid, None)
        return ActivationResult(
            cid, True, "sudah aktif (idempoten)" if already else "diaktivasi",
            transport=rec["transport"], endpoint_url=rec["endpoint_url"],
            auth_type=rec["auth_type"], tools_count=rec["tools_count"],
            verified_by="plan",
        )

    def deactivate(self, cid: str) -> bool:
        return self.activated.pop(cid, None) is not None

    def is_active(self, cid: str) -> bool:
        return cid in self.activated

    def stats(self) -> dict[str, Any]:
        from collections import Counter

        by_tr = Counter(r["transport"] for r in self.activated.values())
        by_auth = Counter(r["auth_type"] for r in self.activated.values())
        return {
            "activated": len(self.activated),
            "skipped": len(self.skipped),
            "tools_total": sum(r["tools_count"] for r in self.activated.values()),
            "by_transport": dict(sorted(by_tr.items(), key=lambda kv: -kv[1])),
            "by_auth": dict(sorted(by_auth.items(), key=lambda kv: -kv[1])),
            "skip_reasons": dict(Counter(self.skipped.values()).most_common(10)),
        }


def bulk_activate(entries: list[dict], *, verify_network: bool = False,
                  timeout: float = 8.0, max_verify: int = 50,
                  resolver: Callable[[str], bool] | None = None,
                  ) -> tuple[ActivationLedger, dict[str, Any]]:
    """Aktivasi sekumpulan entri. Mengembalikan (ledger, laporan).

    `verify_network=False` (default) -> murni dari katalog, cepat, offline.
    `verify_network=True` -> selain pemeriksaan katalog, host unik diperiksa
    resolusi DNS-nya (anti DNS-rebinding) dan maksimal `max_verify` endpoint
    di-`HEAD` untuk membuktikan hidup.

    `resolver` disuntikkan supaya dapat diuji tanpa jaringan.
    """
    ledger = ActivationLedger()
    t0 = time.perf_counter()

    # Tahap 1: keputusan dari katalog (murni, cepat).
    ready: list[dict] = []
    for e in entries:
        r = ledger.activate(e)
        if r.activated and r.reason != "sudah aktif (idempoten)":
            ready.append(e)

    report: dict[str, Any] = {"stage": "catalog", "ready": len(ready)}

    if verify_network and ready:
        # Tahap 2: resolusi DNS per host unik (anti DNS-rebinding).
        hosts: dict[str, list[str]] = {}
        for e in ready:
            ic = e.get("install_config") or {}
            url = str(e.get("endpoint_url") or ic.get("package") or "")
            h = urlparse(url).hostname or ""
            if h:
                hosts.setdefault(h, []).append(str(e.get("id")))

        check = resolver or _resolve_blocked
        blocked_hosts = {h for h in hosts if check(h)}
        for h in blocked_hosts:
            for cid in hosts[h]:
                ledger.deactivate(cid)
                ledger.skipped[cid] = f"host gagal resolusi/diblokir: {h}"

        # Tahap 3: bukti HTTP nyata pada sebagian endpoint.
        evidence: list[dict] = []
        if max_verify > 0:
            try:
                import httpx

                checked = 0
                for h, cids in hosts.items():
                    if h in blocked_hosts or checked >= max_verify:
                        continue
                    url = f"https://{h}"
                    t1 = time.perf_counter()
                    try:
                        with httpx.Client(timeout=timeout, follow_redirects=True) as c:
                            resp = c.head(url)
                        ms = int((time.perf_counter() - t1) * 1000)
                        ok = resp.status_code < 500
                        evidence.append({"host": h, "status": resp.status_code,
                                         "ok": ok, "ms": ms, "connectors": len(cids)})
                    except Exception as exc:  # noqa: BLE001
                        evidence.append({"host": h, "error": f"{type(exc).__name__}",
                                         "ok": False, "connectors": len(cids)})
                    checked += 1
                report["head_checked"] = checked
            except ImportError:
                report["head_checked"] = 0
        report["network_evidence"] = evidence
        report["blocked_hosts"] = sorted(blocked_hosts)
        report["stage"] = "verified"

    report["duration_s"] = round(time.perf_counter() - t0, 3)
    report["stats"] = ledger.stats()
    return ledger, report


def load_catalog() -> list[dict]:
    """Seluruh entri katalog dari `mcp_registry.load_cached()`."""
    import mcp_registry as catalog

    return [x for x in catalog.load_cached().values() if isinstance(x, dict)]


def persist(ledger: "ActivationLedger") -> dict:
    """Tulis ledger ke katalog supaya `executable_servers()` benar-benar naik.

    Ini langkah yang membedakan "aktivasi sungguhan" dari "mengubah label":
    tanpa persist, `coverage()['executable']` tetap 23 karena katalog tidak
    pernah tahu ada entri yang sudah bisa dieksekusi.
    """
    import mcp_registry as catalog

    return catalog.save_activation_ledger(ledger)


def activate_and_persist(entries: list[dict], **kwargs) -> tuple["ActivationLedger", dict]:
    """`bulk_activate` + `persist` — jalur yang dipakai API/produksi."""
    ledger, report = bulk_activate(entries, **kwargs)
    report["persisted"] = persist(ledger)
    return ledger, report


def describe() -> dict[str, Any]:
    return {
        "executable_transports": list(EXECUTABLE_TRANSPORTS),
        "external_service_transports": list(EXTERNAL_SERVICE_TRANSPORTS),
        "deferred_transports": [t for t in DEFERRED_TRANSPORTS],
        "executors": {
            "streamable_http": "_call_mcp_streamable (JSON-RPC tools/call via httpx)",
            "http": "_call_mcp_streamable",
            "sse": "_call_mcp_streamable (event-stream parsing)",
            "stdio": "_call_stdio (subprocess; butuh allow_stdio=True)",
        },
        "rules": [
            "endpoint wajib https",
            "host loopback/privat/metadata ditolak (SSRF)",
            "resolusi DNS diperiksa semua alamat saat verify_network=True",
            "aktivasi idempoten",
            "call_verified hanya setelah panggilan nyata",
            "transport metadata-only TIDAK diaktivasi (butuh runtime yang belum ada)",
        ],
    }
