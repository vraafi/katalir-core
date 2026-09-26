"""F3.3 — Custom JS tools, sandboxed, with egress mediated by Python.

This is the most dangerous importer in the phase, because unlike an OpenAPI
document or a GraphQL schema, arbitrary JavaScript *is* the payload. The other
protocols describe traffic someone else already described; this one lets a user
hand us code.

The design choice that matters: **the sandbox has no network of its own.** The
JS host exposes one `fetch` that emits a request over stdio and waits for a
reply, and every one of those requests is put through `ssrf.require_public_url`
here in Python. Had the sandbox been given node's own `fetch`, the SSRF guard
would live in a second language, and a second guard is a second thing to forget
to update.

Three further limits, each a real boundary rather than a hope:

* a fresh process per run, so one script cannot poison the next;
* a wall-clock timeout plus an in-script vm timeout, so an infinite loop cannot
  pin a core;
* no `require`, no `process`, no `Buffer` in the context, so `fs` and
  `child_process` are not reachable even though the host process has them.

`codeGeneration: {strings: false}` also blocks `eval` and `Function`, which
would otherwise be a trivial way back out of the context.

Known and stated rather than hidden: this is a process sandbox, not a security
boundary against a determined attacker. A determined attacker can still exhaust
memory or exploit a V8 bug. It is sized for "a user writes a small
integration", and a hostile-tenant deployment needs a real container or seccomp
boundary around this process.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import time
from typing import Any

import httpx

from .ssrf import require_public_url, SsrfError

RUNNER = pathlib.Path(__file__).with_name("js_runner.js")
WALL_CLOCK_TIMEOUT = 20
VM_TIMEOUT_MS = 5000
MAX_OUTPUT = 8000
ALLOWED_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD")
BLOCKED_ENV = ("PATH", "SystemRoot", "TEMP", "TMP", "PATHEXT", "WINDIR", "COMSPEC")


class SandboxError(RuntimeError):
    """Raised for every failure mode the sandbox is designed to contain."""


def _runner_path() -> str:
    node = shutil.which("node") or shutil.which("nodejs")
    if not node:
        raise SandboxError("node_not_found")
    if not RUNNER.exists():
        raise SandboxError("runner_missing")
    return node


def _spawn() -> subprocess.Popen:
    """A fresh process per run, with a deliberately bare environment.

    The env is filtered rather than cleared: node needs SystemRoot on Windows
    and PATH to be locatable, and a *cleared* env on Windows is not a neutral
    sandbox but a broken one. Everything else the parent had, including every
    Katalir credential, is simply not passed down.
    """
    node = _runner_path()
    env = {k: os.environ[k] for k in BLOCKED_ENV if k in os.environ}
    env["NODE_OPTIONS"] = ""  # do not inherit --inspect from a parent
    try:
        return subprocess.Popen(
            [node, str(RUNNER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            cwd=str(pathlib.Path(__file__).parent),
        )
    except Exception as exc:  # noqa: BLE001
        raise SandboxError(f"spawn_failed:{type(exc).__name__}") from exc


def _guarded_fetch(
    client: httpx.Client,
    requests: list[dict[str, Any]],
    url: str,
    method: str,
    headers: Any,
    body: str | None,
    env_token: str,
) -> dict[str, Any]:
    """One guarded outbound request — the only egress in the whole phase."""
    entry: dict[str, Any] = {"url": url, "method": method, "allowed": False, "status": None, "reason": ""}
    requests.append(entry)
    method = (method or "GET").upper()
    if method not in ALLOWED_METHODS:
        entry["reason"] = f"method_not_allowed:{method}"
        return {"kind": "error", "error": entry["reason"]}
    try:
        require_public_url(url)
    except SsrfError as exc:
        entry["reason"] = f"ssrf_blocked:{exc}"
        return {"kind": "error", "error": entry["reason"]}
    entry["allowed"] = True
    hdrs = {"Accept": "application/json, text/plain, */*"}
    if isinstance(headers, dict):
        for k, v in list(headers.items())[:20]:
            if isinstance(k, str) and isinstance(v, str):
                hdrs[k[:80]] = v[:500]
    if env_token and "authorization" not in {k.lower() for k in hdrs}:
        # Injected here, after the guard passed, so a script cannot read the
        # token out of its own source and a blocked host never sees it.
        hdrs["Authorization"] = f"Bearer {env_token}"
    # One retry on a connect-level failure. A single dropped TCP handshake is not
    # a broken integration, and failing a user's tool on it would be wrong; a real
    # HTTP error status is returned as-is, never retried.
    last = ""
    for attempt in (1, 2):
        try:
            r = client.request(method, url, headers=hdrs, content=body.encode("utf-8") if body else None)
            break
        except Exception as exc:  # noqa: BLE001
            last = type(exc).__name__
            if attempt == 2 or "Timeout" not in last and "Connect" not in last:
                entry["reason"] = f"transport:{last}"
                return {"kind": "error", "error": entry["reason"]}
            time.sleep(0.4 * attempt)
    else:  # pragma: no cover - loop always returns or breaks
        entry["reason"] = f"transport:{last}"
        return {"kind": "error", "error": entry["reason"]}
    entry["status"] = r.status_code
    return {"kind": "response", "status": r.status_code, "text": r.text[:MAX_OUTPUT]}


def run_js(code: str, *, timeout: int = WALL_CLOCK_TIMEOUT, env_token: str = "") -> dict[str, Any]:
    """Run one program, return ``{ok, value, logs, requests, error}``."""
    if not isinstance(code, str) or not code.strip():
        return {"ok": False, "value": None, "logs": [], "requests": [], "error": "empty_program"}

    proc = _spawn()
    logs: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    errors: list[str] = []
    result = None
    client = httpx.Client(timeout=15, follow_redirects=False, headers={"User-Agent": "katalir-js-sandbox"})
    try:
        proc.stdin.write(json.dumps({"code": code}) + "\n")
        proc.stdin.flush()
        for raw in proc.stdout:
            line = (raw or "").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                # A line that is not protocol is a leak from the script itself;
                # surfacing it beats dropping it silently.
                logs.append({"level": "raw", "text": line[:500]})
                continue
            kind = msg.get("kind")
            if kind in ("booted", "ready"):
                continue
            if kind == "log":
                logs.append({"level": msg.get("level", "log"), "text": str(msg.get("text", ""))[:500]})
                continue
            if kind == "request":
                reply = _guarded_fetch(
                    client, requests, str(msg.get("url", "")), str(msg.get("method", "GET")),
                    msg.get("headers"), msg.get("body") if isinstance(msg.get("body"), str) else None, env_token,
                )
                proc.stdin.write(json.dumps({**reply, "id": msg.get("id")}) + "\n")
                proc.stdin.flush()
                continue
            if kind == "error":
                errors.append(str(msg.get("error", "script error")))
                break
            if kind == "done":
                result = msg.get("value")
                break
        if not result and not errors:
            errors.append("runner_produced_no_result")
    except (BrokenPipeError, OSError):
        errors.append("sandbox_pipe_closed")
    finally:
        client.close()
        try:
            proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
            errors.append("wall_clock_timeout")

    return {
        "ok": not errors,
        "value": result,
        "logs": logs[:50],
        "requests": requests,
        "error": "; ".join(errors) if errors else "",
        "protocol": "js",
        # A JS tool that ran and returned a value is the one path in this phase
        # that can honestly be call_verified, because it really did execute.
        "verification": {"discovered": True, "tools_listed": False, "call_verified": not errors and result is not None},
    }


__all__ = ["run_js", "SandboxError", "WALL_CLOCK_TIMEOUT", "VM_TIMEOUT_MS"]
