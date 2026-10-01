"""Apply agentgateway NATIVE apiKey auth to the live MCP config (no Cloudflare).

Safety contract:
  1. Backup live config.
  2. Generate the key ON the VPS; never returned to this process or chat.
  3. Insert `policies.apiKey` under the existing `mcp:` block, keeping every
     target byte-for-byte.
  4. `--validate-only` BEFORE any restart; abort untouched if it fails.
  5. Verify naked vs with-key from OUTSIDE the VPS.
"""
from __future__ import annotations

import os
import re
import sys

import httpx
import paramiko

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
from dotenv_loader import load_repo_env  # noqa: E402

load_repo_env()

HOST, USER, PW = os.getenv("VPS_IP", ""), os.getenv("VPS_USERNAME", "root"), os.getenv("VPS_PASSWORD", "")

BASE_TARGETS = """  targets:
    - name: time
      stdio:
        cmd: /root/.local/bin/uvx
        args: ["--with", "mcp<2", "mcp-server-time"]
"""

MCP = "mcp:\n  port: 3001\n" + BASE_TARGETS


def _wrap(keys_yaml: str) -> str:
    """Wrap a `keys:` fragment in the binds/listener/route path (LLM/HTTP mode)."""
    return (
        "binds:\n"
        "  - port: 3001\n"
        "    listeners:\n"
        "      - routes:\n"
        "          - policies:\n"
        "              apiKey:\n"
        "                mode: strict\n"
        f"                {keys_yaml}\n"
    ) + MCP


def _wrap_mcp(keys_yaml: str) -> str:
    """MCP SERVER mode: apiKey policy belongs under mcp.policies.apiKey.

    Field name is `key:` (or `keyHash:`), NOT `value:` — the schema type is the
    untagged enum `LocalAPIKey`, which is why `value:`/`secret:` were rejected.
    """
    return (
        "mcp:\n"
        "  port: 3001\n"
        "  policies:\n"
        "    apiKey:\n"
        "      mode: strict\n"
        f"      {keys_yaml}\n"
        "  targets:\n"
        "    - name: time\n"
        "      stdio:\n"
        "        cmd: /root/.local/bin/uvx\n"
        '        args: ["--with", "mcp<2", "mcp-server-time"]\n'
    )


CFG = "/opt/agentgateway/config.yaml"
KEYFILE = "/etc/agentgateway/.env"
UNIT = "/etc/systemd/system/agentgateway.service"


def run(cli, cmd, timeout=60):
    _, o, e = cli.exec_command(cmd, timeout=timeout)
    return o.read().decode("utf-8", "replace").strip(), e.read().decode("utf-8", "replace").strip()


def build_config(live: str) -> str:
    """Insert policies.apiKey right after the `mcp:` line; targets stay untouched."""
    out, inserted = [], False
    for ln in live.splitlines():
        out.append(ln)
        if not inserted and re.match(r"^mcp:\s*$", ln):
            out += [
                "  policies:",
                "    apiKey:",
                "      mode: strict",
                "      keys:",
                '        - key: "${KATALIR_GATEWAY_API_KEY}"',
                "          metadata:",
                "            user: katalir-client",
                "            role: admin",
            ]
            inserted = True
    if not inserted:
        raise SystemExit("no top-level `mcp:` block found")
    return "\n".join(out) + "\n"


def step(n, msg):
    print(f"\n=== {n} ===\n{msg}", flush=True)


def main() -> int:
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(HOST, username=USER, password=PW, timeout=25, look_for_keys=False, allow_agent=False)
    print("SSH_CONNECTED", flush=True)

    o, e = run(cli, f"cp -v {CFG} /tmp/config-backup-pre-fix.yaml")
    step("1 BACKUP", o or e)

    live, _ = run(cli, f"cat {CFG}")
    step("2 BEFORE (live config)", live)
    print(f"top_level_mcp={'mcp:' in live} top_level_binds={'binds:' in live} targets={live.count('- name:')}", flush=True)

    key, _ = run(cli, "openssl rand -hex 32")
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        raise SystemExit("unexpected key format")
    print(f"\n=== 3 KEY GENERATED (on VPS) ===\nlen={len(key)} prefix={key[:6]}... value NOT shown", flush=True)

    o, _ = run(cli, f"systemctl cat agentgateway | grep -c EnvironmentFile || true")
    if o.strip() in ("", "0"):
        o, e = run(cli, f"cp -v {UNIT} /tmp/agentgateway.service.bak && "
                         f"printf 'EnvironmentFile={KEYFILE}\\n' >> {UNIT}")
        step("4a ADD EnvironmentFile", o or e)
    o, e = run(cli, f"mkdir -p /etc/agentgateway && "
                     f"(grep -q KATALIR_GATEWAY_API_KEY {KEYFILE} 2>/dev/null || "
                     f"printf 'KATALIR_GATEWAY_API_KEY=%s\\n' {key} >> {KEYFILE}); "
                     f"chmod 600 {KEYFILE}; ls -l {KEYFILE}")
    step("4b ENVFILE", o or e)

    new = build_config(live)
    step("5 NEW CONFIG (targets preserved)", new)
    sftp = cli.open_sftp()
    with sftp.file("/tmp/config-new.yaml", "w") as fh:
        fh.write(new)
    sftp.close()

    # Validate with the SAME environment systemd provides. Without this the
    # `${KATALIR_GATEWAY_API_KEY}` expansion fails and --validate-only aborts.
    o, e = run(cli, f"set -a; . {KEYFILE}; set +a; timeout 20 "
                    f"/opt/agentgateway/agentgateway --validate-only -f /tmp/config-new.yaml 2>&1; echo RC=$?")
    step("6 VALIDATE-ONLY (env loaded)", o or e)
    if "Configuration is valid" not in o:
        step("ABORT", "validation failed; live config NOT modified")
        cli.close()
        return 1

    o, e = run(cli, f"cp /tmp/config-new.yaml {CFG} && systemctl daemon-reload && "
                    f"systemctl restart agentgateway && sleep 7 && systemctl is-active agentgateway")
    step("ROLLBACK", "restoring live config + unit from pre-fix backups")
    o, e = run(cli, f"cp -v /tmp/config-backup-pre-fix.yaml {CFG}; cp -v /tmp/agentgateway.service.bak {UNIT}; "
                    f"systemctl daemon-reload && systemctl restart agentgateway && sleep 8 && systemctl is-active agentgateway")
    print(o or e, flush=True)
    o, e = run(cli, "journalctl -u agentgateway -n 5 --no-pager")
    print(o or e, flush=True)
    cli.close()
    raise SystemExit(1)

    with open(os.path.join(REPO_ROOT, ".gateway_api_key"), "w", encoding="utf-8") as fh:
        fh.write(key)
    cli.close()
    verify(key)
    return 0


def verify(key: str) -> None:
    """3a-3d: naked must be denied, with-key must work."""
    url = "https://gateway.katalir.de5.net/mcp"
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "katalir-verify", "version": "1"}}}
    print("\n=== 8 VERIFY FROM OUTSIDE ===", flush=True)
    print("3a NAKED initialize  -> ", end="", flush=True)
    try:
        print(f"HTTP {httpx.post(url, headers=h, json=init, timeout=25).status_code}")
    except Exception as exc:  # noqa: BLE001
        print(f"ERR {type(exc).__name__}")
    ha = dict(h, Authorization=f"Bearer {key}")
    print("3c WITH-KEY initialize -> ", end="", flush=True)
    try:
        r = httpx.post(url, headers=ha, json=init, timeout=25)
        print(f"HTTP {r.status_code}")
        if r.status_code == 200:
            h2 = dict(ha)
            sid = r.headers.get("mcp-session-id")
            if sid:
                h2["mcp-session-id"] = sid
            httpx.post(url, headers=h2, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout=25)
            r2 = httpx.post(url, headers=h2, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, timeout=25)
            print(f"3d WITH-KEY tools/list -> HTTP {r2.status_code} tool_count={r2.text.count(chr(34) + 'name' + chr(34))}")
    except Exception as exc:  # noqa: BLE001
        print(f"ERR {type(exc).__name__}")


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    raise SystemExit(main())
