"""Cari file .env mana pun di disk yang berisi project ref Katalir.

Pencarian menyeluruh (bukan hanya repo root) karena `.env` bisa berada di
path lain. Yang dicari adalah ISI: ref `qmukkphwaajzbqjrcvaz`.

Nilai credential tidak pernah dicetak - hanya path file + nama variabel.
"""
import os
import pathlib
import sys

REF = b"qmukkphwaajzbqjrcvaz"
SKIP = {
    "node_modules", ".git", "__pycache__", ".next", ".venv", "venv",
    "site-packages", "AppData", "$Recycle.Bin", "System Volume Information",
    ".reference", "test-results", ".gradle", "dist", "build",
}


def main() -> int:
    roots = [r"C:\Users\user", r"C:\tmp", r"C:\temp-chrome-debug"]
    hits: list[tuple[str, list[str]]] = []
    scanned = 0
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP]
            for fn in filenames:
                if not (fn == ".env" or fn.startswith(".env.")
                        or fn.endswith(".env")):
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    with open(p, "rb") as fh:
                        blob = fh.read()
                except OSError:
                    continue
                scanned += 1
                if REF not in blob:
                    continue
                names = []
                for line in blob.decode("utf-8", "replace").splitlines():
                    s = line.strip()
                    if "=" in s and not s.startswith("#"):
                        k = s.split("=", 1)[0].strip()
                        if "SUPABASE" in k or "RAILWAY" in k:
                            names.append(k)
                hits.append((p, sorted(set(names))))

    print(f"file .env* di-scan : {scanned}")
    print(f"file dengan ref Katalir : {len(hits)}")
    for p, names in hits:
        print(f"  {p}")
        shown = ", ".join(names) if names else "(tidak ada var SUPABASE/RAILWAY)"
        print(f"     vars: {shown}")
    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main())
