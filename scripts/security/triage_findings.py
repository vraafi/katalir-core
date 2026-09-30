"""Triage manual untuk 7 temuan `ASSIGN::*` dari scan_secrets.

Tidak mencetak nilai. Untuk tiap temuan, ia melaporkan:
  - file, apakah file itu masih ada
  - apakah nilainya placeholder (aman) atau entropy tinggi (mencurigakan)
  - 12 karakter pertama + panjang, CUKUP untuk membedakan
    "ini literal dummy di dalam test" dari "ini key sungguhan".
Nilai penuh TIDAK pernah ditulis ke log atau laporan.
"""
from __future__ import annotations

import math
import pathlib
import re
import subprocess

CHECKS = [
    ("nexus-frontend/tests/repro-integrations.spec.ts", "refresh_token"),
    ("nexus-frontend/tests/screenshot-task-d.spec.ts", "refresh_token"),
    ("scripts/gamedev/verify_gate.py", "api_key"),
    ("scripts/probe_repos.ps1", "token"),
    ("nexus-frontend/tests/landing-cta.spec.ts", "password"),
    ("mcp_gateway/client.py", "TOKEN_ENV"),
    ("mcp_gateway/client.py", "token"),
]

RX = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|API_?KEY|PRIVATE_?KEY|SERVICE_?ROLE|CREDENTIAL)[A-Z0-9_]*)\s*[=:]\s*[\"']?([^\s\"',;]{8,})"
)

PLACEHOLDER_HINTS = ("example", "your-", "your_", "dummy", "fake", "test", "placeholder", "xxxx", "changeme", "redacted", "none", "null", "todo")


def entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = {c: s.count(c) for c in set(s)}
    return -sum((n / len(s)) * math.log2(n / len(s)) for n in counts.values())


def head(value: str, n: int = 12) -> str:
    return value[:n] + ("..." if len(value) > n else "")


def main() -> None:
    root = pathlib.Path(__file__).resolve().parents[2]
    for rel, var in CHECKS:
        p = root / rel
        if not p.is_file():
            print(f"{rel} :: {var} :: FILE_GONE")
            continue
        hit = None
        for lineno, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            m = RX.search(line)
            if m and var.lower() in m.group(1).lower():
                hit = (lineno, m.group(1), m.group(2))
                break
        if not hit:
            print(f"{rel} :: {var} :: NOT_IN_CURRENT_FILE (removed or rewritten)")
            continue
        lineno, name, value = hit
        low = value.lower()
        is_ph = any(h in low for h in PLACEHOLDER_HINTS)
        print(
            f"{rel} :: {name} :: line={lineno} len={len(value)} "
            f"entropy={entropy(value):.2f} placeholder={is_ph} value_head={head(value)!r}"
        )

    # Apakah file-file ini masih ada di HEAD, atau sudah dihapus?
    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, cwd=root
    ).stdout.decode("utf-8", "replace")
    for rel, _ in CHECKS:
        state = "TRACKED" if rel in tracked else "NOT_TRACKED"
        print(f"state[{rel}]={state}")


if __name__ == "__main__":
    main()
