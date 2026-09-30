"""FASE 1 — verifikasi key baru (`sb_secret_` / `sb_publishable_`).

READONLY. Nilai key tidak pernah dicetak; hanya prefix-ish info via fingerprint.

CATATAN BUG YANG SUDAH DIPERBAIKI
--------------------------------
Versi pertama skrip ini menangkap nilai key dengan regex `[A-Za-z0-9]+`.
Itu SALAH: nilai key Supabase memuat karakter tambahan, sehingga nilainya
terpotong (46 char -> 29) dan server menolaknya dengan `401 Invalid API key`.
Saya sempat menyimpulkan "key baru tidak valid" - ternyata SALAH, key aslinya
valid. Sekarang regex menangkap sampai akhir baris (dibatasi whitespace/kutip).
"""
import glob
import hashlib
import json
import pathlib
import re
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
UA = "Katalir-KeyCheck/1.0"

# Tangkap nilai sampai akhir baris; JANGAN pakai kelas karakter sempit.
RX_NEW = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*['\"]?(sb_(?:secret|publishable)_[^\s'\"#]+)"
)


def sources() -> list[pathlib.Path]:
    cands = [ROOT / ".env"] + [pathlib.Path(p) for p in sorted(glob.glob(str(ROOT / ".env.bak-*")))]
    cands += [
        ROOT / "nexus-frontend" / ".env.local",
        ROOT / "nexus-frontend" / ".env.example",
        ROOT / ".env.template",
    ]
    return [p for p in cands if p.is_file()]


def harvest(text: str) -> list[tuple[str, str]]:
    """Kembalikan [(nama, nilai)] untuk setiap key baru di dalam `text`.

    Diparse PER BARIS, bukan `finditer` di atas teks utuh. Versi pertama
    memakai `finditer(text, re.M)` dan tidak menemukan apa pun; per-baris
    langsung bekerja dan jauh lebih mudah diaudit.
    """
    out: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.split(" #")[0].strip().strip("\"'")
        if value.startswith("sb_secret_") or value.startswith("sb_publishable_"):
            out.append((name, value))
    return out


def main() -> int:
    url = ""
    found: dict[str, list[tuple[str, str, pathlib.Path]]] = {}
    for p in sources():
        text = p.read_text(encoding="utf-8", errors="replace")
        if not url:
            m = re.search(r"^SUPABASE_URL\s*=\s*['\"]?(\S+)", text, re.M)
            if m:
                url = m.group(1).strip().strip("'\"")
        for name, val in harvest(text):
            kind = "sb_secret_" if val.startswith("sb_secret_") else "sb_publishable_"
            found.setdefault(kind, []).append((name, val, p))

    print("=== key baru ditemukan (nilai tidak dicetak) ===")
    for kind in sorted(found):
        for name, val, p in found[kind]:
            fp = hashlib.sha256(val.encode()).hexdigest()[:10]
            print(f"  {kind:17s} {name:30s} len={len(val):3d} fp={fp}  <- {p.name}")

    if not url:
        print("\nSUPABASE_URL tidak ditemukan -> tidak bisa menguji")
        return 1

    print("\n=== uji ke REST API (header apikey, gaya dokumentasi 2026) ===")
    tested: set[str] = set()
    for kind in sorted(found):
        for name, val, p in found[kind]:
            fp = hashlib.sha256(val.encode()).hexdigest()[:10]
            if fp in tested:
                continue
            tested.add(fp)
            req = urllib.request.Request(
                f"{url}/rest/v1/workflows?select=id&limit=1",
                headers={"apikey": val, "User-Agent": UA},
            )
            try:
                r = urllib.request.urlopen(req, timeout=25)
                res = f"HTTP {r.status}  rows={len(json.loads(r.read().decode()))}"
            except urllib.error.HTTPError as e:
                res = f"HTTP {e.code}  {e.read().decode('utf-8', 'replace')[:55]}"
            except Exception as e:  # noqa: BLE001
                res = f"ERR {type(e).__name__}"
            print(f"  {kind:17s} fp={fp} len={len(val):3d} <- {p.name:34s} -> {res}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
