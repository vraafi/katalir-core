"""Periksa key Supabase yang benar-benar TER-INLINE di bundle frontend produksi.

Kenapa perlu: `NEXT_PUBLIC_*` di-inline Next.js SAAT BUILD. Railway list tidak
pernah menunjukkannya, dan Cloudflare API tidak Always bisa dibaca. Bundle
yang terkirim ke browser adalah bukti terakhir yang tidak bisa dibantah:
kalau `sb_publishable_` ada di sana, browser memakainya; kalau tidak ada,
frontend berjalan tanpa Supabase sama sekali.

Pakai:
    python scripts/security/bundle_key_check.py
"""
import pathlib
import re
import sys
import urllib.request

UA = "Katalir-BundleCheck/1.0"
BASE = "https://katalir.de5.net"

# Hanya nama variabel + prefiks format. Nilai penuh tidak pernah dicetak.
PATTERNS = {
    "sb_publishable_": re.compile(r"sb_publishable_[A-Za-z0-9_\-]{8,}"),
    "sb_secret_": re.compile(r"sb_secret_[A-Za-z0-9_\-]{8,}"),
    "legacy_jwt": re.compile(r"eyJ[A-Za-z0-9_\-]{20,}"),
    "supabase_url": re.compile(r"https://[a-z0-9]{20}\.supabase\.co"),
    "railway_url": re.compile(r"https://[a-z0-9\-]+\.up\.railway\.app"),
    "localhost_leak": re.compile(r"localhost:8000"),
}


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def main() -> int:
    html = get(BASE)
    srcs = sorted(set(re.findall(r'src="(/_next/static/[^"]+\.js)"', html))
                  | set(re.findall(r'href="(/_next/static/[^"]+\.js)"', html)))
    print(f"{BASE}: {len(srcs)} script dari HTML")
    if not srcs:
        print("  tidak ada script _next/static yang bisa diperiksa")
        return 1

    hits = {k: [] for k in PATTERNS}
    scanned = 0
    for s in srcs:
        try:
            body = get(BASE + s)
        except Exception as exc:  # noqa: BLE001
            print(f"  gagal ambil {s}: {type(exc).__name__}")
            continue
        scanned += 1
        for name, rx in PATTERNS.items():
            for m in rx.findall(body):
                hits[name].append((s.split("/")[-1], m))

    print(f"script berhasil di-scan: {scanned}")
    print()
    for name, found in hits.items():
        if not found:
            print(f"  {name:18s} TIDAK DITEMUKAN")
            continue
        uniq = sorted({v for _, v in found})
        files = sorted({f for f, _ in found})
        print(f"  {name:18s} {len(found)} kemunculan, {len(uniq)} nilai unik")
        print(f"      prefix   : {uniq[0][:14]}...")
        print(f"      di file  : {', '.join(files[:3])}")
        if name in ("legacy_jwt", "sb_secret_"):
            print(f"      !!! MASALAH: format {name} ada di bundle publik")
    return 0


if __name__ == "__main__":
    sys.exit(main())