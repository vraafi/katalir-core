"""Push ke GitHub memakai GITHUB_TOKEN dari .env (Metode B, Okt 2026).

Mengapa lewat Python, bukan shell: token dilewatkan sebagai STDIN subprocess,
sehingga TIDAK pernah muncul di argv (`ps`), di shell history, atau di log.
Skrip tidak pernah mencetak nilai token - hanya status dan hash.

Alur (sesuai brief):
  2a. baca GITHUB_TOKEN dari .env
  2b. git credential approve  (helper wincred, eksplisit)
  2c. git push origin main
  2d. git credential reject   (BERSIHKAN - jangan simpan permanen)
  3.  verifikasi ls-remote vs rev-parse HEAD

Helper `-c credential.helper=` (kosong) dipakai untuk MERESET rantai helper,
supaya `git-credential-helper-selector` (yang terbukti menggantung ~29 detik)
tidak pernah dipanggil.
"""
from __future__ import annotations

import glob
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
REPO_URL = "https://github.com/vraafi/katalir-core.git"
BRANCH = "main"


def read_token(name: str = "GITHUB_TOKEN") -> str | None:
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip().lstrip("\ufeff")
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == name:
            return v.strip().strip('"').strip("'").strip() or None
    return None


def find_wincred() -> str | None:
    pats = [
        r"C:/Users/user/AppData/Local/Programs/WorkBuddyAI/resources/vendor/"
        r"PortableGit/mingw64/bin/git-credential-wincred.exe",
        r"C:/Program Files/Git/mingw64/bin/git-credential-wincred.exe",
    ]
    for p in pats:
        if pathlib.Path(p).exists():
            return p
    hits = glob.glob(r"C:/**/git-credential-wincred.exe", recursive=True)
    return hits[0] if hits else None


def run(args: list[str], *, stdin_text: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"   # jangan pernah menunggu prompt interaktif
    env["GIT_ASKPASS"] = "echo"        # askpass kosong -> gagal cepat bila perlu
    return subprocess.run(
        args, cwd=str(ROOT), env=env, input=stdin_text,
        capture_output=True, text=True, timeout=300,
    )


def git(*args: str, helper: str | None = None, stdin_text: str | None = None):
    cmd = ["git"]
    if helper is not None:
        cmd += ["-c", "credential.helper=", "-c", f"credential.helper={helper}"]
    cmd += list(args)
    return run(cmd, stdin_text=stdin_text)


tok = read_token()
if not tok:
    print("GAGAL: GITHUB_TOKEN tidak ada di .env")
    sys.exit(2)

wincred = find_wincred()
print(f"2a. token dibaca dari .env  : ADA ({len(tok)} char, prefix {tok[:4]}****)")
print(f"    helper wincred          : {wincred}")
if not wincred:
    print("GAGAL: git-credential-wincred.exe tidak ditemukan")
    sys.exit(2)

block = (f"protocol=https\nhost=github.com\n"
         f"username=x-access-token\npassword={tok}\n")

print("2b. git credential approve ...", flush=True)
r = git("credential", "approve", helper=wincred, stdin_text=block)
print(f"    exit={r.returncode} (stdout/stderr disembunyikan untuk keamanan)")

print("2c. git push origin main ...", flush=True)
r = git("push", "origin", BRANCH, helper=wincred)
out = (r.stdout or "") + (r.stderr or "")
safe = "\n".join(l for l in out.splitlines() if tok not in l)
print(f"    exit={r.returncode}")
if safe.strip():
    print("    --- keluaran ---")
    for line in safe.splitlines()[-12:]:
        print(f"    {line}")

pushed = r.returncode == 0

print("2d. git credential reject (bersih-bersih) ...", flush=True)
r2 = git("credential", "reject", helper=wincred,
         stdin_text="protocol=https\nhost=github.com\n")
print(f"    exit={r2.returncode} -> kredensial dihapus dari Credential Manager")

print()
print("=" * 70)
print("3. VERIFIKASI")
print("=" * 70)
local = run(["git", "rev-parse", "HEAD"]).stdout.strip()
print(f"3b. lokal  HEAD          : {local}")

env2 = dict(os.environ)
env2["GIT_TERMINAL_PROMPT"] = "0"
lr = subprocess.run(["git", "ls-remote", "origin", f"refs/heads/{BRANCH}"],
                    cwd=str(ROOT), env=env2, capture_output=True, text=True,
                    timeout=120)
remote_line = (lr.stdout or "").strip()
remote = remote_line.split()[0] if remote_line else ""
print(f"3a. remote origin/{BRANCH:<4}    : {remote or '(tidak terbaca)'}")

if remote and remote == local:
    print()
    print("3c. VERDICT: **PUSH SUKSES** - hash remote == hash lokal")
    sys.exit(0)
print()
print(f"3c. VERDICT: PUSH GAGAL (push_exit_ok={pushed}) - hash tidak sama")
sys.exit(1)
