"""Batch runtime test for OpenConnector actions through the Katalir MCP gateway.

Safety rules, all deliberate:

* only actions OpenConnector itself marks ``noAuthRunnable`` are considered,
  so we never need a credential and never touch a tenant's data;
* only ``read`` operations are considered, so a test can never create,
  modify or delete anything;
* only actions with an empty input schema are called with ``{}``, so the test
  cannot invent arguments;
* calls are sequential with a fixed delay - no parallel fan-out;
* the gateway is addressed exactly the way a real MCP client would, so a pass
  means the whole federation path works, not just the container.

Writes ``batch-test-openconnector.json`` with one record per attempt. A record
is only ``ok`` when the action really executed.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import time
import urllib.request

PROTOCOL_VERSION = "2025-06-18"
EXECUTE_TOOL = "openconnector_execute_action"
VALID_STATUS = {"ok", "no_connection", "auth_required", "invalid_input", "error"}


class MCPClient:
    def __init__(self, url: str, timeout: int = 90):
        self.url = url
        self.timeout = timeout
        self.session: str | None = None
        self._id = 0
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        self.initialize()

    def _post(self, payload: dict) -> dict:
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, **payload}
        headers = dict(self._headers)
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            self.session = r.headers.get("Mcp-Session-Id") or self.session
            raw = r.read().decode("utf-8", "replace")
        message: dict = {}
        for line in raw.splitlines():
            if line.startswith("data:"):
                try:
                    message = json.loads(line[5:].strip())
                except ValueError:
                    message = {}
        if not message and raw.lstrip().startswith("{"):
            message = json.loads(raw)
        return message

    def initialize(self) -> None:
        self._post(
            {
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "katalir-batch-test", "version": "1"},
                },
            }
        )

    def call(self, name: str, arguments: dict) -> dict:
        return self._post({"method": "tools/call", "params": {"name": name, "arguments": arguments}})



def pick_candidates(registry: dict, limit: int) -> list[dict]:
    """Read-only, no-credential, no-input actions, in a deterministic order."""
    out = []
    for slug, entry in registry.items():
        if not isinstance(entry, dict):
            continue
        for tool in entry.get("tools") or []:
            if not isinstance(tool, dict):
                continue
            if not tool.get("no_auth_runnable") or not tool.get("no_input"):
                continue
            if tool.get("operation_type") != "read":
                continue
            out.append(
                {
                    "action_id": tool.get("id"),
                    "service": slug,
                    "name": tool.get("name"),
                    "description": tool.get("description"),
                }
            )
    out.sort(key=lambda x: str(x["action_id"]))
    return out[:limit]


def classify(message: dict) -> tuple[str, str]:
    """Map an MCP tool result onto a status plus a short human reason."""
    if message.get("error"):
        return "error", str(message["error"].get("message") or message["error"])[:300]
    result = message.get("result") or {}
    text = ""
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = str(block.get("text") or "")
            break
    if not text:
        return "error", "empty tool result"
    try:
        payload = json.loads(text)
    except ValueError:
        payload = None
    if payload is None:
        return ("error", text[:200]) if result.get("isError") else ("ok", text[:200])
    if isinstance(payload, dict):
        if payload.get("ok") is True:
            return "ok", "executed"
        err = payload.get("error") or {}
        msg = str(err.get("message") or err) if isinstance(err, dict) else str(err)
        code = str(err.get("code") or "") if isinstance(err, dict) else ""
        blob = (code + " " + msg).lower()
        if result.get("isError") or code or msg:
            if "connect" in blob or "no connection" in blob or "connection" in blob:
                return "no_connection", msg[:300]
            if "auth" in blob or "credential" in blob or "token" in blob or "unauthorized" in blob:
                return "auth_required", msg[:300]
            if "input" in blob or "argument" in blob or "valid" in blob or "required" in blob:
                return "invalid_input", msg[:300]
            return "error", msg[:300]
        return "ok", "executed"
    return "error", "unexpected payload type " + type(payload).__name__



def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default="openconnector_actions.json")
    ap.add_argument("--gateway-url", default="http://127.0.0.1:3001/mcp")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--out", default="batch-test-openconnector.json")
    args = ap.parse_args()

    registry = json.loads(pathlib.Path(args.registry).read_text(encoding="utf-8"))
    candidates = pick_candidates(registry, args.limit)
    print(f"CANDIDATES={len(candidates)}")
    if not candidates:
        print("NOTHING_TO_TEST")
        return 1

    client = MCPClient(args.gateway_url)
    records = []
    for i, cand in enumerate(candidates, 1):
        started = time.time()
        try:
            message = client.call(EXECUTE_TOOL, {"actionId": cand["action_id"], "input": {}})
            status, reason = classify(message)
        except Exception as exc:  # noqa: BLE001
            status, reason = "error", f"{type(exc).__name__}: {exc}"[:300]
        status = status if status in VALID_STATUS else "error"
        elapsed = int((time.time() - started) * 1000)
        records.append({**cand, "status": status, "reason": reason, "latency_ms": elapsed})
        print(f"[{i}/{len(candidates)}] {cand['action_id']} -> {status} ({elapsed}ms) {reason[:90]}")
        time.sleep(args.delay)

    counts: dict[str, int] = {}
    for r in records:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    report = {
        "gateway_url": args.gateway_url,
        "tool": EXECUTE_TOOL,
        "selection": "read-only + noAuthRunnable + empty input schema",
        "attempted": len(records),
        "counts": dict(sorted(counts.items())),
        "call_verified_actions": [r["action_id"] for r in records if r["status"] == "ok"],
        "records": records,
    }
    pathlib.Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("COUNTS", json.dumps(report["counts"]))
    print("CALL_VERIFIED", len(report["call_verified_actions"]))
    print(f"OUT={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
