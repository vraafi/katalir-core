"""tools/call phase for no-auth Glama connectors: raise verified from listed.

`batch-verify-glama-connectors.py` deliberately stopped at tools/list because a
call can change state in a third-party system. This script takes that step, but
only under constraints narrow enough to be defensible.

Safety rules, all deliberate:

* only connectors already proven ``no_auth`` + ``tools_listed`` are touched;
* SSRF guard identical to the list phase: public https only;
* **read-only tool filter** - callable only if the tool name matches a read-verb
  allowlist AND no mutating-verb blocklist;
* synthetic arguments only, built from the tool's own JSON schema, with clearly
  fake values (RFC 2606 ``.invalid`` for anything email-shaped);
* sequential with a delay - no fan-out against someone else's servers.

Honesty rules, because this number becomes a marketing claim:

``call_verified``
    tools/call returned a result and the server did not flag ``isError``. The tool
    actually ran. This is the only status that counts toward "verified".
``call_validation_error``
    the server rejected our synthetic arguments. Proves the call path is live, NOT
    that the tool works. Never counted as verified.
``call_failed`` / ``no_readonly_tool``
    the tool errored, or every listed tool was filtered out as unsafe.

Counting a validation error as a pass would turn "the endpoint answered" into
"the integration works" - the Marketing Claim != Runtime Reality failure the
playbook warns about. So it is not counted.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

# Connector names contain non-ASCII (e.g. "404 Dispatcher", "é", CJK). Writing
# them to a cp1252 console raises UnicodeEncodeError and kills the run, losing
# every result so far because the report is only written at the end. Force UTF-8
# with replacement so a weird name can never abort a 25-minute sweep.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001  (older/odd streams)
        pass

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "katalir-readonly-verifier", "version": "1.0.0"}


def _load_list_phase():
    """Reuse the SSRF guard from the list-phase script (hyphenated filename)."""
    here = pathlib.Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location(
        "batch_list", here / "batch-verify-glama-connectors.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.is_public_https


is_public_https = _load_list_phase()

# Callable only if it matches a read verb...
READ_VERBS = (
    "get", "list", "fetch", "read", "search", "query", "find", "lookup",
    "describe", "show", "view", "retrieve", "count", "stats", "info",
    "status", "health", "ping", "echo", "check", "validate", "resolve",
    "browse", "enumerate", "about", "capabilities", "schema", "inspect",
)
# ...and none of these. Checked first, so "getAndDelete" is refused.
MUTATING_VERBS = (
    "create", "update", "delete", "remove", "write", "send", "post", "put",
    "patch", "execute", "exec", "run", "invoke", "mutate", "set", "add",
    "insert", "upsert", "destroy", "drop", "truncate", "enable", "disable",
    "start", "stop", "cancel", "refund", "pay", "charge", "transfer",
    "subscribe", "unsubscribe", "import", "generate", "build", "deploy",
    "publish", "notify", "email", "upload", "commit", "merge", "approve",
    "reject", "install", "register", "signup", "password", "credential",
    "token", "secret", "revoke", "grant", "assign", "move", "rename",
    "replace", "clear", "reset", "close", "archive", "restore", "sync",
)

SAFE_DOMAIN = "example.invalid"  # RFC 2606: can never resolve or be delivered
EMAILISH = re.compile(r"(e-?mail|recipient|^to$|^cc$|^bcc$)", re.I)
IDENTISH = re.compile(r"(id|uuid|key|slug|code|name)$", re.I)


def is_read_only_tool(name: str) -> bool:
    n = (name or "").lower()
    if any(v in n for v in MUTATING_VERBS):
        return False
    return any(v in n for v in READ_VERBS)


def synth_args(schema: dict) -> tuple[dict, int]:
    """Build obviously-fake arguments from a tool's own input schema."""
    props = (schema or {}).get("properties") or {}
    required = (schema or {}).get("required") or []
    args: dict = {}
    for key in required:
        spec = props.get(key) or {}
        kind = spec.get("type")
        if kind in ("integer", "number"):
            args[key] = 0
        elif kind == "boolean":
            args[key] = False
        elif kind == "array":
            args[key] = []
        elif kind == "object":
            args[key] = {}
        elif kind == "string":
            if EMAILISH.search(key) or spec.get("format") in ("email", "idn-email"):
                args[key] = f"katalir-verify@{SAFE_DOMAIN}"
            elif spec.get("format") == "uri" or "url" in key.lower():
                args[key] = f"https://{SAFE_DOMAIN}/verify"
            elif IDENTISH.search(key):
                args[key] = "katalir-verify-nonexistent"
            else:
                args[key] = "katalir-verify"
        else:
            args[key] = "katalir-verify"
    return args, len(required)


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


class Session:
    """One MCP session against a single third-party endpoint."""

    def __init__(self, url: str, timeout: int):
        self.url, self.timeout, self.session_id, self.cid = url, timeout, None, 0

    def post(self, payload: dict) -> tuple[str, int, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode(), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                self.session_id = resp.headers.get("Mcp-Session-Id") or self.session_id
                return "ok", resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return "http", exc.code, exc.read().decode("utf-8", "replace")

    def rpc(self, method: str, params: dict | None = None) -> dict | None:
        self.cid += 1
        payload: dict = {"jsonrpc": "2.0", "id": self.cid, "method": method}
        if params is not None:
            payload["params"] = params
        kind, _status, raw = self.post(payload)
        return parse_messages(raw) if kind == "ok" else None

    def notify(self, method: str, params: dict | None = None) -> None:
        payload: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self.post(payload)


def call_one(url: str, timeout: int) -> dict:
    s = Session(url, timeout)
    init = s.rpc(
        "initialize",
        {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO},
    )
    if not init or "result" not in init:
        return {"status": "reinit_failed", "detail": "no initialize result"}
    s.notify("notifications/initialized")

    listed = s.rpc("tools/list")
    tools = (((listed or {}).get("result") or {}).get("tools")) or []
    if not tools:
        return {"status": "no_tools_now", "detail": "tools/list empty on re-check"}

    safe = [t for t in tools if is_read_only_tool(t.get("name", ""))]
    if not safe:
        return {
            "status": "no_readonly_tool",
            "detail": f"all {len(tools)} tools filtered as unsafe or non-read-only",
        }

    # prefer a tool that needs no arguments at all
    safe.sort(key=lambda t: len(((t.get("inputSchema") or {}).get("required") or [])))

    for tool in safe:
        name = tool.get("name", "")
        args, n_req = synth_args(tool.get("inputSchema") or {})
        started = time.time()
        try:
            resp = s.rpc("tools/call", {"name": name, "arguments": args})
        except Exception as exc:  # noqa: BLE001
            return {"status": "call_failed", "tool": name, "detail": type(exc).__name__}
        elapsed = int((time.time() - started) * 1000)

        if resp is None:
            return {"status": "call_failed", "tool": name, "detail": "no response"}
        if "error" in resp:
            code = (resp.get("error") or {}).get("code")
            msg = str((resp.get("error") or {}).get("message", ""))[:200]
            low = msg.lower()
            if code in (-32602, -32601) or "param" in low or "argument" in low:
                return {
                    "status": "call_validation_error",
                    "tool": name,
                    "detail": msg,
                    "latency_ms": elapsed,
                }
            return {"status": "call_failed", "tool": name, "detail": msg, "latency_ms": elapsed}

        result = resp.get("result") or {}
        if result.get("isError") is True:
            content = result.get("content") or []
            text = str(content[0].get("text", ""))[:200] if content and isinstance(content[0], dict) else ""
            low = text.lower()
            # Servers often return argument problems as isError rather than as a
            # JSON-RPC error. Same meaning as call_validation_error: the call path
            # is live, the tool did not run. Reported separately, never verified.
            if "validation" in low or "invalid argument" in low or "invalid input" in low:
                return {
                    "status": "call_validation_error",
                    "tool": name,
                    "detail": text,
                    "latency_ms": elapsed,
                }
            return {
                "status": "call_failed",
                "tool": name,
                "detail": f"isError: {text}",
                "latency_ms": elapsed,
            }
        return {
            "status": "call_verified",
            "tool": name,
            "required_args": n_req,
            "latency_ms": elapsed,
        }

    return {"status": "no_readonly_tool", "detail": "no safe tool produced a call"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default="glama_connectors.json")
    ap.add_argument("--batch", nargs="+", default=[
        "glama-connector-verify-batch1.json",
        "glama-connector-verify-batch2.json",
    ])
    ap.add_argument("--out", default="glama-connector-call-batch1.json")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--delay", type=float, default=0.7)
    ap.add_argument("--resume", action="store_true", help="skip ids already in --out")
    ap.add_argument("--write-back", action="store_true", help="set verification.call_verified in --registry")
    args = ap.parse_args()

    proven: dict[str, dict] = {}
    for b in args.batch:
        data = json.loads(pathlib.Path(b).read_text(encoding="utf-8"))
        for r in data.get("records", []):
            if r.get("status") == "ok" and r.get("endpoint_url"):
                proven[r["id"]] = r
    registry = json.loads(pathlib.Path(args.registry).read_text(encoding="utf-8"))
    # never touch anything not marked no_auth in the catalogue
    for cid in list(proven):
        rec = registry.get(cid)
        if not isinstance(rec, dict) or rec.get("no_auth") is not True:
            del proven[cid]

    order = list(proven)
    # resume: skip ids already recorded in a previous partial run
    done: dict[str, dict] = {}
    if args.resume and pathlib.Path(args.out).exists():
        prev = json.loads(pathlib.Path(args.out).read_text(encoding="utf-8"))
        done = {r["id"]: r for r in prev.get("records", []) if r.get("id")}
        order = [c for c in order if c not in done]
        print(f"RESUME skipping {len(done)} already-recorded connectors", flush=True)
    if args.start:
        order = order[args.start :]
    if args.limit:
        order = order[: args.limit]
    print(f"CALL_TARGETS={len(order)} (of {len(proven)} proven no_auth listers)", flush=True)

    def save(all_records: list[dict]) -> None:
        c: dict[str, int] = {}
        for r in all_records:
            c[r["status"]] = c.get(r["status"], 0) + 1
        ver = [r["id"] for r in all_records if r["status"] == "call_verified"]
        out = {
            "scope": "no-auth Glama connectors, initialize + tools/list + ONE read-only tools/call",
            "safety": "read-verb allowlist AND no mutating verb; synthetic args; sequential; SSRF-guarded",
            "attempted": len(all_records),
            "counts": dict(sorted(c.items())),
            "call_verified_total": len(ver),
            "call_verified_connectors": ver,
            "records": all_records,
        }
        pathlib.Path(args.out).write_text(
            json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    records: list[dict] = list(done.values())
    for i, cid in enumerate(order, 1):
        rec = proven[cid]
        url = rec["endpoint_url"]
        allowed, why = is_public_https(url)
        if not allowed:
            out = {"status": "ssrf_blocked", "detail": why}
        else:
            try:
                out = call_one(url, args.timeout)
            except urllib.error.HTTPError as exc:
                out = {"status": "call_failed", "detail": f"HTTP {exc.code}"}
            except Exception as exc:  # noqa: BLE001
                out = {"status": "call_failed", "detail": type(exc).__name__}
        row = {
            "id": cid,
            "name": rec.get("name"),
            "endpoint_url": url,
            "tools_listed": rec.get("tools_listed"),
            **out,
        }
        records.append(row)
        print(
            f"[{i}/{len(order)}] {str(rec.get('name'))[:36]:36s} "
            f"{out['status']:23s} {str(out.get('tool', ''))[:24]}",
            flush=True,
        )
        # checkpoint: a crash at 340/351 must not discard 340 results
        if i % 10 == 0 or i == len(order):
            save(records)
        time.sleep(args.delay)

    save(records)
    counts: dict[str, int] = {}
    for r in records:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("COUNTS=", json.dumps(dict(sorted(counts.items()))))
    print("CALL_VERIFIED_TOTAL=", sum(1 for r in records if r["status"] == "call_verified"))
    print("OUT=", args.out)

    if args.write_back:
        # Only a real result counts. call_validation_error and call_failed leave
        # call_verified False/absent so the registry can never overstate itself.
        applied = 0
        for r in records:
            rec = registry.get(r["id"])
            if not isinstance(rec, dict):
                continue
            ver = rec.setdefault("verification", {})
            ver["call_verified"] = r["status"] == "call_verified"
            if r["status"] == "call_verified":
                ver["call_verified_tool"] = r.get("tool")
                ver["call_verified_method"] = "one read-only tools/call, synthetic args"
            elif r["status"] == "call_validation_error":
                ver["call_validation_error"] = True
        pathlib.Path(args.registry).write_text(
            json.dumps(registry, indent=1, ensure_ascii=False), encoding="utf-8"
        )
        marked = sum(1 for r in records if r["status"] == "call_verified")
        print(f"WROTE_BACK {args.registry}: call_verified set on {marked} connectors")
        _ = applied
    return 0


if __name__ == "__main__":
    sys.exit(main())

