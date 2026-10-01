"""Non-destructive probe: does agentgateway v1.5.0 accept bearer auth in config?

Uses --validate-only against CANDIDATE configs written to /tmp. Never touches the
running service or the live config file. Purpose: if native auth is supported we
can lock the gateway down without a Cloudflare API token.
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

BASE_TARGETS = """  targets:
    - name: time
      stdio:
        cmd: /root/.local/bin/uvx
        args: ["--with", "mcp<2", "mcp-server-time"]
"""

CANDIDATES = {
    # Reveal ResourceName shape (likely {kind,name} or {group,name}).
    "policy_namedict": """policies:
  - name:
      name: require-token
mcp:
  port: 3001
""" + BASE_TARGETS,
    "policy_kindname": """policies:
  - kind: bearer
    name: require-token
mcp:
  port: 3001
""" + BASE_TARGETS,
    # Reveal what a policy body accepts.
    "policy_bare": """policies:
  - name: require-token
mcp:
  port: 3001
""" + BASE_TARGETS,
    "frontend_policy_bare": """frontendPolicies:
  - name: require-token
mcp:
  port: 3001
""" + BASE_TARGETS,
    "baseline_noauth": "mcp:\n  port: 3001\n" + BASE_TARGETS,
}


def main() -> int:
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(HOST, username=USER, password=PW, timeout=25, look_for_keys=False, allow_agent=False)

    # upload current live config for a faithful baseline
    _, out, _ = cli.exec_command("cat /opt/agentgateway/config.yaml", timeout=30)
    live = out.read().decode("utf-8", "replace")
    sftp = cli.open_sftp()
    sftp.get("/opt/agentgateway/config.yaml", "/tmp/live_config_backup.yaml")
    sftp.close()
    print("backed up live config -> /tmp/live_config_backup.yaml")
    print(f"live_config_targets={live.count('- name:')}")

    for name, body in CANDIDATES.items():
        path = f"/tmp/cand_{name}.yaml"
        sftp = cli.open_sftp()
        with sftp.file(path, "w") as fh:
            fh.write(body)
        sftp.close()
        # `timeout 15` on the VPS guarantees a candidate config can never hang
        # the probe (a bad policy shape can make --validate-only block forever).
        cmd = f"timeout 15 /opt/agentgateway/agentgateway --validate-only -f {path} 2>&1; echo RC=$?"
        _, o, _ = cli.exec_command(cmd, timeout=45)
        out_txt = o.read().decode("utf-8", "replace").strip()
        print(f"\n=== {name} ===\n{out_txt[:700]}", flush=True)
        cli.exec_command(f"rm -f {path}", timeout=20)

    cli.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
