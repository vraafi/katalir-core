"""Unduh chunk JS produksi dari frontend live, lalu scan untuk secret.

`out/` tidak ada di mesin ini (build lokal tidak dijalankan), jadi scanner
tidak bisa membaca bundle secara lokal. Menyentuh host produksi adalah
satu-satunya cara mendapat file yang benar-benar dikirim ke user.

Hanya daftar URL + jumlah temuan yang dicetak. Nilai secret TIDAK pernah
dicetak atau disimpan.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

FRONTEND = "https://katalir.de5.net"
UA = {"User-Agent": "katalir-security-audit"}

# Pola yang TIDAK akan muncul di kode bundel normal. Kunci API asli punya
# prefix vendor yang panjang dan特定; test token lokal sengaja dikecualikan
# lewat allowlist.
PATTERNS: dict[str, re.Pattern[str]] = {
    "SUPABASE_SERVICE_ROLE": re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"),
    "PRIVATE_KEY_BLOCK": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "STRIPE_LIVE": re.compile(r"sk_live_[A-Za-z0-9]{20,}"),
    "OPENROUTER_KEY": re.compile(r"sk-or-v1-[A-Za-z0-9]{32,}"),
    "GITHUB_TOKEN": re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    "AWS_ACCESS_KEY": re.compile(r"AKIA[0-9A-Z]{16}"),
    "SLACK_TOKEN": re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
    "GOOGLE_API_KEY": re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    "GENERIC_ASSIGNMENT": re.compile(
        r"(?i)(?:secret|token|passwd|password|apiKey|api_key|privateKey|service[_-]?role)\s*[:=]\s*[\"'][^\"'\s]{16,}[\"']"
    ),
}

# Nilai yang jelas-jelas fixture lokal, bukan credential produksi.
BENIGN = re.compile(
    r"(?i)^(?:local-tests|test|dummy|example|placeholder|xxx+|your[-_]|changeme|"
    r"eyJhbGciOiJIUzI1NiJ9\.eyJ[A-Za-z0-9_-]{5,})"
)


def fetch(url: str, timeout: float = 15.0) -> bytes | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            return r.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return None


def main() -> int:
    index = fetch(FRONTEND + "/")
    if index is None:
        print("FATAL: tidak bisa mengambil index produksi")
        return 2
    html = index.decode("utf-8", "replace")

    srcs = sorted(set(re.findall(r'src="(/_next/static/[^"]+\.js)"', html)))
    print(f"chunk_directives_found={len(srcs)}")

    total = 0
    scanned = 0
    hits: list[dict] = []
    queue = list(srcs)
    seen: set[str] = set()

    while queue and len(seen) < 400:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        data = fetch(FRONTEND + path)
        if data is None:
            continue
        scanned += 1
        text = data.decode("utf-8", "replace")
        for name, rx in PATTERNS.items():
            for m in rx.finditer(text):
                snippet = m.group(0)
                if BENIGN.match(snippet):
                    continue
                total += 1
                hits.append({"chunk": path, "rule": name})
        # Ikuti chunk yang di-lazy-load dari index modul.
        queue.extend(re.findall(r'"(/_next/static/chunks/[^"]+\.js)"', text))

    print(f"chunks_scanned={scanned}")
    print(f"SECRETS_FOUND_IN_BUNDLE={total}")
    for h in hits:
        print("  HIT", h["rule"], h["chunk"])

    out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"chunks_scanned": scanned, "secrets_found": total, "hits": hits}, indent=2),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
