"""Patch semua `load_dotenv()` tanpa path eksplisit -> `load_repo_env()`.

Aturan:
  - `load_dotenv()`                      -> load_repo_env()
  - `load_dotenv(override=True)`         -> load_repo_env(override=True)
  - `load_dotenv(".env", override=True)` -> load_repo_env(override=True)  (relatif CWD, rapuh)
  - `load_dotenv(ROOT / ".env", ...)`    -> TINGGAL (sudah benar)

Import `from dotenv import load_dotenv` diganti jadi `from dotenv_loader import load_repo_env`
kecuali file sudah mengimpor `load_dotenv` itu untuk keperluan lain.

File yang sudah benar (load_dotenv(ROOT / ".env")) TIDAK disentuh.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(r"C:\Users\user\Proyek_AI")

# Pola yang bermasalah -> penggantinya
PATTERNS = [
    (re.compile(r'^(?P<ind>[ \t]*)load_dotenv\(ROOT / "\.env", override=True\)[ \t]*$'),
     None),  # sudah benar, tandai skip
    (re.compile(r'^(?P<ind>[ \t]*)load_dotenv\("\.env", override=True\)[ \t]*$'),
     '{ind}load_repo_env(override=True)'),
    (re.compile(r'^(?P<ind>[ \t]*)load_dotenv\(override=True\)[ \t]*$'),
     '{ind}load_repo_env(override=True)'),
    (re.compile(r'^(?P<ind>[ \t]*)load_dotenv\(\)[ \t]*(#.*)?$'),
     '{ind}load_repo_env()'),
]


def patch(path: pathlib.Path) -> tuple[str, int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    out, n, skipped = [], 0, False

    for line in lines:
        body = line.rstrip("\n").rstrip("\r")
        for rx, repl in PATTERNS:
            m = rx.match(body)
            if not m:
                continue
            if repl is None:
                skipped = True
                out.append(line)
            else:
                comment = m.groupdict().get(2) or m.group(0).split("#", 1)[-1] \
                    if "#" in m.group(0) else ""
                new = repl.format(ind=m.group("ind"))
                if comment and not comment.startswith("#"):
                    comment = "  #" + comment
                out.append(new + comment + line[len(body):])
                n += 1
            break
        else:
            out.append(line)

    if n and not skipped:
        new_text = "".join(out)
        new_text = re.sub(
            r"^from dotenv import load_dotenv$",
            "from dotenv_loader import load_repo_env",
            new_text, flags=re.M,
        )
        path.write_text(new_text, encoding="utf-8", newline="")
    return path.name, n


def main() -> int:
    files = []
    for pat in ("*.py", "scripts/*.py", "scripts/**/*.py", "tests/*.py"):
        files.extend(sorted(ROOT.glob(pat)))
    total, total_n = 0, 0
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if "load_dotenv(" not in text:
            continue
        name, n = patch(f)
        if n:
            total += 1
            total_n += n
            print(f"  {name:28s} {n} call site")
    print(f"FILES_PATCHED={total}  CALLSITES_PATCHED={total_n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
