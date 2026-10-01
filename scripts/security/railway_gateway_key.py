"""Set Railway vars whose value comes from the VPS gateway, without echoing it.

Usage:
    python scripts/security/railway_gateway_key.py
"""
from __future__ import annotations

import os
import pathlib
import sys

import paramiko

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dotenv_loader import load_repo_env  # noqa: E402
from scripts.security.railway_vars import set_var  # noqa: E402
from scripts.security.railway_deploy import ids  # noqa: E402
from scripts.security.railway_deploy_status import load_env  # noqa: E402

VARS = ("GATEWAY_API_KEY", "AGENTGATEWAY_TOKEN")


def main() -> int:
    load_repo_env()
    env, _ = load_env()
    host = os.getenv("VPS_IP", "")
    user = os.getenv("VPS_USERNAME", "root")
    pw = os.getenv("VPS_PASSWORD", "")

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(host, username=user, password=pw, timeout=25, look_for_keys=False, allow_agent=False)
    _, o, _ = cli.exec_command("grep KATALIR_GATEWAY_API_KEY /etc/agentgateway/.env | cut -d= -f2", timeout=30)
    key = o.read().decode().strip()
    cli.close()
    if len(key) != 64:
        print(f"unexpected key length {len(key)}")
        return 1
    # Never print the value.
    print(f"fetched key len={len(key)} prefix={key[:6]}... (value withheld)")

    tok = env.get("RAILWAY_API_TOKEN") or env.get("RAILWAY_TOKEN")
    info = ids(tok)
    rc = 0
    for name in VARS:
        rc |= set_var(tok, info, name, key)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())