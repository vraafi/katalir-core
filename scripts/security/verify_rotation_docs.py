"""Verifikasi bahwa 2 dokumen status-rotasi tidak memuat nilai credential.

Yang diperiksa:
  1. pola provider (ghp_/AIza/eyJ/whsec_/AKIA/sk-)
  2. setiap nilai dari .env dan .env.bak-* (len>=12) yang muncul di dokumen
  3. artefak teks korup (karakter CJK, U+FFFD)

Nilai credential TIDAK pernah dicetak - hanya jumlah dan nama file.
"""
import glob
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCS = [
    ROOT / "docs" / "security" / "audit-report.md",
    ROOT / "docs" / "security" / "credential-rotation-list.md",
]
PATTERNS = [
    "ghp_[A-Za-z0-9]{10,}", "github_pat_[A-Za-z0-9_]{10,}",
    "sk_live_[A-Za-z0-9]{10,}", "sk-[A-Za-z0-9]{20,}",
    "whsec_[A-Za-z0-9]{10,}", "AIza[0-9A-Za-z_-]{10,}",
    "AKIA[0-9A-Z]{16}", "xox[baprs]-[A-Za-z0-9-]{10,}",
    "eyJ[A-Za-z0-9_-]{10,}",
]


def main() -> int:
    texts = {p: p.read_text(encoding="utf-8") for p in DOCS}
    print("=== pola provider + artefak teks ===")
    for p, s in texts.items():
        cjk = sorted({c for c in s if "一" <= c <= "鿿"})
        hits = sum(len(re.findall(x, s)) for x in PATTERNS)
        print(f"  {p.name:34s} pola={hits}  U+FFFD={s.count(chr(0xFFFD))}  CJK={''.join(cjk) or 'NONE'}")

    print("=== nilai .env / .env.bak-* yang bocor ke dokumen ===")
    files = [ROOT / ".env"] + [pathlib.Path(f) for f in sorted(glob.glob(str(ROOT / ".env.bak-*")))]
    files += [ROOT / "nexus-frontend" / ".env.local"]
    checked = leaked = 0
    for f in files:
        if not f.is_file():
            continue
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if "=" not in s or s.startswith("#"):
                continue
            v = s.partition("=")[2].split(" #")[0].strip().strip('"').strip("'")
            if len(v) >= 12:
                checked += 1
                for p, text in texts.items():
                    if v in text:
                        leaked += 1
                        print(f"  LEAK: {f.name} -> {p.name}")
    print(f"  nilai diperiksa (len>=12) = {checked}")
    print(f"  LEAKED                    = {leaked}")
    return 1 if leaked else 0


if __name__ == "__main__":
    raise SystemExit(main())
