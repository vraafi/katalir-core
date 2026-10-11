r"""Enumerasi seluruh file .env* di disk: NAMA variabel + panjang + prefix format.

Kenapa skrip ini (bukan Get-ChildItem + Select-String):
  1. `Select-String` pada baris `KEY=eyJ...` akan MENCETAK nilai penuh ke
     terminal/log. Skrip ini hanya mencetak NAMA + panjang + 8 karakter
     pertama sebagai identifikasi format.
  2. `Get-ChildItem -Recurse -Force` di C:\Users\user lambat (>30s) dan
    produced error pada symlink/junction. Os.walk + SKIP jauh lebih cepat.

K-prefix yang dipakai (bukan nilai):
  legacy-jwt  : eyJ...  (JWT era lama, bypass RLS)
  sb-secret   : sb_secret_...
  sb-publish  : sb_publishable_...
  url/jwks/other

Pakai:
    python scripts/security/env_enumerate.py
"""
import json
import os
import pathlib
import sys

REF = b"qmukkphwaajzbqjrcvaz"          # project ref Katalir
SKIP = {
    "node_modules", ".git", "__pycache__", ".next", ".venv", "venv",
    "site-packages", "AppData", "$Recycle.Bin", "System Volume Information",
    "test-results", ".gradle", "dist", "build", ".reference",
}
OUT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(
    r"C:\Users\user\AppData\Local\Temp\env-enum.json")


def classify(val: str) -> str:
    if val.startswith("eyJ"):
        return "legacy-jwt"
    if val.startswith("sb_secret_"):
        return "sb-secret"
    if val.startswith("sb_publishable_"):
        return "sb-publish"
    if val.startswith("http"):
        return "url"
    if val.startswith("{"):
        return "jwks"
    if val == "":
        return "EMPTY"
    return "other"


def parse(path: pathlib.Path) -> tuple[list[dict], bool]:
    text = path.read_text(encoding="utf-8", errors="replace")
    has_ref = REF.decode() in text
    out = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, _, val = s.partition("=")
        key = key.strip()
        if not key or " " in key or not key.replace("_", "").isalnum():
            continue
        val = val.split(" #")[0].strip().strip("\"'")
        out.append({"name": key, "len": len(val), "fmt": classify(val),
                    "prefix": val[:8] if classify(val) not in ("url", "jwks", "other")
                    else ""})
    return out, has_ref


def main() -> int:
    roots = [r"C:\Users\user"]
    files: list[pathlib.Path] = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP]
            for fn in filenames:
                if fn == ".env" or fn.startswith(".env.") or fn.endswith(".env"):
                    files.append(pathlib.Path(dirpath) / fn)

    report = []
    for p in sorted(set(files)):
        try:
            vars_, has_ref = parse(p)
        except OSError:
            continue
        if not vars_ and not has_ref:
            continue
        try:
            mtime = p.stat().st_mtime
            import datetime
            stamp = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            stamp = "?"
        # PENTING: pencocokan TIDAK case-sensitive. Variabel seperti
        # `supabase_akun_token_read` (huruf kecil) akan hilang kalau filter
        # memakai `startswith("SUPABASE")` - dan itu berarti enumerasi
        # sebelumnya bisa saja tidak lengkap.
        sup = [v for v in vars_
               if v["name"].upper().startswith("SUPABASE")
               or v["name"].upper().startswith("NEXT_PUBLIC_SUPABASE")]
        report.append({
            "path": str(p), "mtime": stamp, "is_katalir": has_ref,
            "var_count": len(vars_), "supabase": sup,
        })

    OUT.write_text(json.dumps(report, indent=1), encoding="utf-8")

    # Ringkasan ke terminal - hanya NAMA + panjang + format.
    print(f"file .env* dengan isi: {len(report)}")
    katalir = [r for r in report if r["is_katalir"]]
    print(f"  ...memuat ref Katalir: {len(katalir)}\n")
    for r in report:
        tag = "  [KATALIR]" if r["is_katalir"] else "  [lain]   "
        print(f"{tag} {r['path']}")
        print(f"             mtime={r['mtime']}  total_var={r['var_count']}")
        for v in r["supabase"]:
            print(f"             {v['name']:30s} fmt={v['fmt']:11s} len={v['len']}")
        if not r["supabase"]:
            print("             (tidak ada variabel SUPABASE*)")
        print()
    print(f"laporan lengkap -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())