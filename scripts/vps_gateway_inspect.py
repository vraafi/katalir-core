"""Read-only VPS inspection for the gateway exposure fix.

Runs ONE diagnostic command set over SSH. Makes no changes.
"""
from __future__ import annotations

import os
import sys

import paramiko

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
from dotenv_loader import load_repo_env  # noqa: E402

load_repo_env()

HOST = os.getenv("VPS_IP", "")
USER = os.getenv("VPS_USERNAME", "root")
PW = os.getenv("VPS_PASSWORD", "")

COMMANDS = [
    "systemctl is-active agentgateway cloudflared",
    "ss -ltnp | grep -E ':(3001|15000)' || true",
    "ls -la /etc/agentgateway/ 2>/dev/null | head -20",
    "grep -rhoE '^(AUTH|BEARER|TOKEN|PASSWORD)[A-Z_]*=' /etc/agentgateway/.env 2>/dev/null | sed 's/=.*/=<redacted>/' || echo 'no-auth-vars'",
    "systemctl cat agentgateway | sed -E 's/(token|secret|password|key)([= ])[^ ]+/\\1\\2<redacted>/Ig' | head -40",
    "ps -o args= -p $(pgrep -f agentgateway | head -1) | sed -E 's/(token|secret|password)[= ][^ ]+/\\1=<redacted>/Ig'",
    "find / -maxdepth 4 -name '*agentgateway*' -not -path '*/proc/*' 2>/dev/null | head -20",
    "/opt/agentgateway/agentgateway --help 2>&1 | head -50",
    "echo '--- config.yaml (secrets redacted) ---'; sed -E 's/((token|secret|password|key|credential)[^:]*:).*/\\1 <redacted>/I' /opt/agentgateway/config.yaml | head -60",
    "systemctl cat cloudflared | sed -E 's/(token|secret|password)([= ])[^ ]+/\\1\\2<redacted>/Ig' | head -30",
]


def main() -> int:
    if not HOST or not PW:
        print("missing VPS_IP/VPS_PASSWORD")
        return 1
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        cli.connect(HOST, username=USER, password=PW, timeout=25, look_for_keys=False, allow_agent=False)
    except Exception as exc:  # noqa: BLE001
        print(f"SSH_CONNECT_FAILED {type(exc).__name__}: {str(exc)[:160]}")
        return 1
    print("SSH_CONNECTED")
    for cmd in COMMANDS:
        print(f"\n$ {cmd}")
        _, out, err = cli.exec_command(cmd, timeout=40)
        o = out.read().decode("utf-8", "replace").strip()
        e = err.read().decode("utf-8", "replace").strip()
        if o:
            print(o)
        if e:
            print(f"[stderr] {e[:300]}")
        if not o and not e:
            print("(empty)")
    cli.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
