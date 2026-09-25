"""Batch runtime-verify Glama connectors (remote MCP endpoints) for real.

A Glama *connector* is a live streamable-HTTP MCP server, unlike a *server*
entry which is only source-code metadata. Connectors marked ``auth:none`` and
``healthy`` can be probed without any credential, which is what makes an honest
runtime claim possible for this source at all.

Safety rules, all deliberate:

* only ``no_auth`` connectors are probed - we never touch anyone's account;
* only https URLs are accepted, and any host that resolves to a private,
  loopback or link-local address is refused (SSRF guard);
* read-only: we only send ``initialize`` and ``tools/list``, never ``tools/call``,
  so we cannot create, modify or delete anything in a third-party system;
* sequential with a delay - no fan-out against someone else's servers.

Verification ladder: discovered -> tools_listed -> call_verified. This script
can only reach ``tools_listed``; it never claims ``call_verified``.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import pathlib
import socket
import sys
import time
import urllib.parse
import urllib.request

PROTOCOL_VERSION = "2025-06-18"
VALID_STATUS = {"ok", "auth_required", "unreachable", "protocol_error", "no_tools", "ssrf_blocked"}


def is_public_https(url: str) -> tuple[bool, str]:
    """Refuse anything that is not a public https endpoint."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False, "unparseable url"
    if parsed.scheme != "https":
        return False, f"scheme {parsed.scheme!r} is not https"
    host = parsed.hostname
    if not host:
        return False, "no host"
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        return False, f"dns failed: {type(exc).__name__}"
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False, "unresolvable address"
        if not ip.is_global:
            return False, f"non-public address {addr}"
    return True, ""


def parse_messages(raw: str) -> dict:
    for line in raw.splitlines():
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip())
            except ValueError:
                continue
    if raw.lstrip().startswith("{"):
        try:
            return json.loads(raw)
        except ValueError:
            return {}
    return {}


def probe(url: str, timeout: int) -> tuple[str, str, int]:
    """MCP initialize + tools/list against one connector."""
    session: str | None = None
    call_id = 0
    tools: list = []

    def post(payload: dict) -> tuple[str, str]:
        nonlocal session
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if session:
            headers["Mcp-Session-Id"] = session
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            session = resp.headers.get("Mcp-Session-Id") or session
            return resp.status, resp.read().decode("utf-8", "replace")

    call_id += 1
    status, raw = post(
        {
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "katalir-glama-verify", "version": "1"},
            },
        }
    )
    if status in (401, 403):
        return "auth_required", f"HTTP {status}", 0
    if status >= 400:
        return "protocol_error", f"initialize HTTP {status}", 0
    init = parse_messages(raw)
    if init.get("error"):
        return "protocol_error", str(init["error"])[:200], 0

    call_id += 1
    status, raw = post({"jsonrpc": "2.0", "id": call_id, "method": "tools/list", "params": {}})
    if status in (401, 403):
        return "auth_required", f"tools/list HTTP {status}", 0
    if status >= 400:
        return "protocol_error", f"tools/list HTTP {status}", 0
    msg = parse_messages(raw)
    if msg.get("error"):
        return "protocol_error", str(msg["error"])[:200], 0
    tools = (msg.get("result") or {}).get("tools") or []
    if not tools:
        return "no_tools", "tools/list returned none", 0
    return "ok", "tools listed", len(tools)



def pick(registry: dict, limit: int, skip_probed: bool = False) -> list[dict]:
    out = []
    for rec in registry.values():
        if not isinstance(rec, dict) or not rec.get("no_auth"):
            continue
        # re-running the batch must not re-probe what we already measured
        if skip_probed and rec.get("last_probe"):
            continue
        out.append(rec)
    out.sort(key=lambda r: (not r.get("healthy"), -(r.get("quality_score") or 0), str(r.get("name"))))
    return out[:limit]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default="glama_connectors.json")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--out", default="glama-connector-verify.json")
    ap.add_argument("--write-back", action="store_true", help="store tools_listed into the registry")
    ap.add_argument("--merge-from", default="", help="apply an existing report to the registry without probing")
    ap.add_argument("--skip-probed", action="store_true", help="only probe connectors with no recorded probe")
    args = ap.parse_args()

    registry = json.loads(pathlib.Path(args.registry).read_text(encoding="utf-8"))

    if args.merge_from:
        report = json.loads(pathlib.Path(args.merge_from).read_text(encoding="utf-8"))
        applied = 0
        for r in report.get("records") or []:
            rec = registry.get(r.get("id"))
            if not isinstance(rec, dict):
                continue
            rec.setdefault("verification", {})["tools_listed"] = r.get("status") == "ok"
            rec["tools_listed_count"] = int(r.get("tools_listed") or 0)
            rec["last_probe"] = {"status": r.get("status"), "tools": r.get("tools_listed"), "latency_ms": r.get("latency_ms")}
            applied += 1
        pathlib.Path(args.registry).write_text(json.dumps(registry, indent=1, ensure_ascii=False), encoding="utf-8")
        ok = sum(1 for r in report.get("records", []) if r.get("status") == "ok")
        print(f"MERGED={applied} TOOLS_LISTED_CONNECTORS={ok} -> {args.registry}")
        return 0

    registry = json.loads(pathlib.Path(args.registry).read_text(encoding="utf-8"))
    candidates = pick(registry, args.limit, args.skip_probed)
    print(f"CANDIDATES={len(candidates)} of {sum(1 for r in registry.values() if isinstance(r, dict) and r.get('no_auth'))} no_auth")

    records = []
    for i, rec in enumerate(candidates, 1):
        url = rec.get("endpoint_url") or ""
        started = time.time()
        allowed, why = is_public_https(url)
        if not allowed:
            status, reason, n = "ssrf_blocked", why, 0
        else:
            try:
                status, reason, n = probe(url, args.timeout)
            except urllib.error.HTTPError as exc:
                status = "auth_required" if exc.code in (401, 403) else "protocol_error"
                reason, n = f"HTTP {exc.code}", 0
            except Exception as exc:  # noqa: BLE001
                status, reason, n = "unreachable", type(exc).__name__, 0
        if status not in VALID_STATUS:
            status, reason = "unreachable", reason
        elapsed = int((time.time() - started) * 1000)
        records.append(
            {
                "id": rec.get("id"),
                "name": rec.get("name"),
                "namespace": rec.get("namespace"),
                "endpoint_url": url,
                "source_url": rec.get("source_url"),
                "status": status,
                "reason": reason[:200],
                "tools_listed": n,
                "latency_ms": elapsed,
            }
        )
        print(f"[{i}/{len(candidates)}] {str(rec.get('name'))[:40]} -> {status} tools={n} ({elapsed}ms)", flush=True)
        time.sleep(args.delay)

    counts: dict[str, int] = {}
    for r in records:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    listed = sorted(r["id"] for r in records if r["status"] == "ok")
    report = {
        "scope": "no-auth Glama connectors, initialize + tools/list only (no tools/call)",
        "attempted": len(records),
        "counts": dict(sorted(counts.items())),
        "tools_listed_total": sum(r["tools_listed"] for r in records),
        "tools_listed_connectors": listed,
        "records": records,
    }
    pathlib.Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("COUNTS=", json.dumps(report["counts"]))
    print("TOOLS_LISTED_TOTAL=", report["tools_listed_total"])
    print("CONNECTORS_WITH_TOOLS=", len(listed))
    print(f"OUT={args.out}")

    if args.write_back:
        for r in records:
            rec = registry.get(r["id"])
            if not isinstance(rec, dict):
                continue
            ver = rec.setdefault("verification", {})
            ver["tools_listed"] = r["status"] == "ok"
        pathlib.Path(args.registry).write_text(json.dumps(registry, indent=1, ensure_ascii=False), encoding="utf-8")
        print("WROTE_BACK", args.registry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
