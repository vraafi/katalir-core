"""VPS lockdown: bind the MCP gateway to loopback + firewall port 3001.

Safety rules encoded here:
  * SSH (22) must be allowed BEFORE any ufw default-deny; we refuse to touch ufw
    if SSH is not already permitted, so we can never lock ourselves out.
  * `cloudflared` runs ON THIS HOST and dials 127.0.0.1:3001, so loopback must
    stay open or the tunnel breaks.
  * Every change is verified with before/after evidence; rollback path included.
"""
from __future__ import annotations

import os
import sys

import paramiko

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
from dotenv_loader import load_repo_env  # noqa: E402

load_repo_env()

HOST, USER, PW = os.getenv("VPS_IP", ""), os.getenv("VPS_USERNAME", "root"), os.getenv("VPS_PASSWORD", "")


def run(cli, cmd, timeout=60):
    _, o, e = cli.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace").strip()
    err = e.read().decode("utf-8", "replace").strip()
    return out, err


def main() -> int:
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(HOST, username=USER, password=PW, timeout=25, look_for_keys=False, allow_agent=False)
    print("SSH_CONNECTED")

    print("\n=== 2.1 BASELINE ===")
    for cmd in [
        "ufw status verbose 2>&1 | head -30 || echo 'ufw not installed'",
        "iptables -S INPUT 2>&1 | head -20",
        "ss -ltnp | grep -E ':(22|3001|15000)'",
        "systemctl is-active cloudflared",
    ]:
        print(f"\n$ {cmd}")
        o, e = run(cli, cmd)
        print(o or e or "(empty)")

    # --- decide whether it is safe to proceed ---
    st, _ = run(cli, "ufw status 2>/dev/null | head -40")
    ssh_ok = ("22/tcp" in st or "OpenSSH" in st or "22 " in st) or ("Status: inactive" in st)
    if not ssh_ok:
        print("\nABORT: ufw active but SSH not explicitly allowed — refusing to modify firewall.")
        cli.close()
        return 1
    print("\nSAFETY_CHECK: SSH reachable / ufw not restrictive -> may proceed")

    # --- backup ---
    print("\n=== 2.3c BACKUP ===")
    o, e = run(cli, "cp -v /opt/agentgateway/config.yaml /tmp/config-backup.yaml && ls -la /tmp/config-backup.yaml")
    print(o or e)

    # --- firewall: allow SSH FIRST, then enforce ---
    print("\n=== 2.2 UFW RULES (SSH allowed BEFORE enabling) ===")
    for cmd in [
        "ufw allow 22/tcp comment 'SSH - never lock out' 2>&1",
        "ufw allow from 127.0.0.1 to any port 3001 proto tcp comment 'cloudflared loopback' 2>&1",
        "ufw deny 3001/tcp comment 'block public MCP gateway' 2>&1",
        "ufw --force enable 2>&1",
        "ufw status verbose 2>&1 | head -30",
    ]:
        print(f"\n$ {cmd}")
        o, e = run(cli, cmd)
        print(o or e or "(empty)")

    print("\n=== SSH STILL ALIVE AFTER ENABLE? ===")
    o, e = run(cli, "echo SSH_STILL_ALIVE && id -un", timeout=30)
    print(o or e)
    cli.close()

    # Reconnect with a FRESH session: proves we did not lock ourselves out.
    print("\n=== FRESH SSH RECONNECT VERIFICATION ===")
    cli2 = paramiko.SSHClient()
    cli2.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        cli2.connect(HOST, username=USER, password=PW, timeout=25, look_for_keys=False, allow_agent=False)
        o, e = run(cli2, "echo RECONNECT_OK; ufw status | head -5", timeout=30)
        print(o or e)
        cli2.close()
    except Exception as exc:  # noqa: BLE001
        print(f"RECONNECT_FAILED {type(exc).__name__}: {str(exc)[:160]}")
        print("ROLLBACK: run on console: ufw disable")
        return 1

    print("\n=== 2.2c LOOPBACK STILL WORKS? ===")
    cli3 = paramiko.SSHClient()
    cli3.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli3.connect(HOST, username=USER, password=PW, timeout=25, look_for_keys=False, allow_agent=False)
    o, e = run(cli3,
               """curl -s -o /dev/null -w 'HTTP=%{http_code}' -X POST http://127.0.0.1:3001/mcp """
               """-H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' """
               """-d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","""
               """"capabilities":{},"clientInfo":{"name":"local","version":"1"}}}'""",
               timeout=40)
    print(f"loopback initialize -> {o or e}")
    o, e = run(cli3, "systemctl is-active cloudflared agentgateway")
    print(f"services -> {o or e}")
    cli3.close()
    return 0


if __name__ == "__main__":
    # Line buffering is essential here: these runs are polled from a redirected
    # file, and block buffering would hide progress until the process exits.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:  # noqa: BLE001
        pass
    raise SystemExit(main())