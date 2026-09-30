"""Cek VPS Katalir lewat paramiko (password auth, tanpa paste di command line).

Membaca kredensial dari .env, TIDAK PERNAH mencetak password. Dipakai
sebagai probe cepat sebelum klaim bahwa VPS "accessible".
"""
import os
import sys

import paramiko
from dotenv_loader import load_repo_env

load_repo_env()

host = (os.getenv("VPS_IP") or "").strip()
user = (os.getenv("VPS_USERNAME") or "").strip()
pw = (os.getenv("VPS_PASSWORD") or "").strip()

if not (host and user and pw):
    print("VPS_CREDS=missing")
    sys.exit(2)

cmd = (
    "echo SSH_OK; "
    "echo '--- listeners ---'; "
    "(ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null) | grep -E ':(3011|8000|8080)' | head -8; "
    "echo '--- agentgateway unit ---'; "
    "(systemctl is-active agentgateway 2>/dev/null || echo no-systemd-unit); "
    "echo '--- docker ---'; "
    "(docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null | head -8 || echo no-docker)"
)

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    c.connect(host, username=user, password=pw, timeout=20, banner_timeout=20, auth_timeout=20)
    _, out, err = c.exec_command(cmd, timeout=40)
    print(out.read().decode("utf-8", "replace"))
    e = err.read().decode("utf-8", "replace").strip()
    if e:
        print("STDERR:", e[:400])
finally:
    c.close()
