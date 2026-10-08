#!/usr/bin/env python
"""ssh_tunnel.py — port-forward TCP lokal ke layanan di VPS lewat SSH.

Dipakai agar tes HANYA menjangkau Redis/VPS melalui terowongan SSH terenkripsi
(alih-alih mengekspos port 6379 ke internet). Ini praktik yang direkomendasikan
dokumentasi keamanan Redis: bind loopback + requirepass + akses via SSH
(https://redis.io/docs/latest/operate/oss_and_stack/management/security/).

Pakai:
    python scripts/ssh_tunnel.py --local 16379 --remote 127.0.0.1:6379
    python scripts/ssh_tunnel.py --local 16379 --remote 127.0.0.1:6379 --check
"""

from __future__ import annotations

import argparse
import os
import re
import select
import socket
import sys
import threading
import time

import paramiko

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env(path: str | None = None) -> dict:
    p = path or os.path.join(HERE, ".env")
    env: dict[str, str] = {}
    with open(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.lstrip().startswith("#"):
                continue
            m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
            if m:
                env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return env


class SSHTunnel:
    """Forwarder TCP satu-arah sederhana di atas kanal `direct-tcpip` paramiko."""

    def __init__(self, ssh_host: str, ssh_user: str, ssh_pass: str,
                 local_port: int, remote_host: str, remote_port: int,
                 local_host: str = "127.0.0.1"):
        self.remote = (remote_host, remote_port)
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(ssh_host, username=ssh_user, password=ssh_pass,
                            timeout=20, allow_agent=False, look_for_keys=False)
        self.transport = self.client.get_transport()
        assert self.transport is not None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((local_host, local_port))
        self.sock.listen(128)
        self.local_port = self.sock.getsockname()[1]
        self._stop = threading.Event()

    def _pump(self, src: socket.socket, dst: socket.socket) -> None:
        try:
            while not self._stop.is_set():
                r, _, _ = select.select([src], [], [], 1.0)
                if not r:
                    continue
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except Exception:  # noqa: BLE001
            pass
        finally:
            for s in (src, dst):
                try:
                    s.close()
                except Exception:  # noqa: BLE001
                    pass

    def _handle(self, conn: socket.socket) -> None:
        try:
            chan = self.transport.open_channel(
                "direct-tcpip", self.remote, conn.getpeername())
        except Exception:  # noqa: BLE001
            conn.close()
            return
        threading.Thread(target=self._pump, args=(conn, chan), daemon=True).start()
        threading.Thread(target=self._pump, args=(chan, conn), daemon=True).start()

    def serve_forever(self) -> None:
        self.sock.settimeout(1.0)
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def close(self) -> None:
        self._stop.set()
        for s in (self.sock,):
            try:
                s.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            self.client.close()
        except Exception:  # noqa: BLE001
            pass


def open_tunnel(local_port: int = 0, remote: str = "127.0.0.1:6379") -> SSHTunnel:
    env = load_env()
    rh, rp = remote.split(":")
    t = SSHTunnel(env["VPS_IP"], env["VPS_USERNAME"], env["VPS_PASSWORD"],
                  local_port, rh, int(rp))
    threading.Thread(target=t.serve_forever, daemon=True).start()
    return t


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", type=int, default=16379)
    ap.add_argument("--remote", default="127.0.0.1:6379")
    ap.add_argument("--check", action="store_true",
                    help="uji koneksi lalu keluar (tanpa serve terus-menerus)")
    args = ap.parse_args()
    t = open_tunnel(args.local, args.remote)
    print(f"tunnel 127.0.0.1:{t.local_port} -> {args.remote} (via {load_env()['VPS_IP']})",
          flush=True)
    if args.check:
        time.sleep(0.4)
        try:
            s = socket.create_connection(("127.0.0.1", t.local_port), timeout=5)
            s.sendall(b"PING\r\n")
            print("raw:", s.recv(64))
            s.close()
        finally:
            t.close()
        return 0
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        t.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
