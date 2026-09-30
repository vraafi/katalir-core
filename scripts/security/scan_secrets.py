"""Secret-leak scanner untuk repo Katalir.

Kenapa skrip sendiri, bukan gitleaks/detect-secrets:
`gitleaks` tidak ada sebagai paket pip, dan `detect-secrets` gagal install
di environment ini (offline). Skrip ini justru lebih sempit - hanya mengenali
provider yang benar-benar dipakai Katalir, sehingga tidak membanjirkan false
positive seperti scanner generik.

Nilai secret TIDAK PERNAH dicetak: hanya nama file, nomor baris, dan nama
variabel. Laporan aman untuk di-commit.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("OPENAI", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("ANTHROPIC", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{24,}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    ("CLOUDFLARE_API_TOKEN", re.compile(r"\bv1\.0-[A-Za-z0-9_\-]{20,}\b")),
    ("SLACK_TOKEN", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    ("GITHUB_TOKEN", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("GOOGLE_API_KEY", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("AWS_ACCESS_KEY_ID", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("STRIPE_SECRET", re.compile(r"\bsk_live_[A-Za-z0-9]{20,}\b")),
    ("UUID", re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")),
]

ASSIGN_HINTS = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|API_?KEY|PRIVATE_?KEY|SERVICE_?ROLE|CREDENTIAL)[A-Z0-9_]*)\s*[=:]\s*[\"']?([^\s\"',;]{16,})"
)

FALSE_POSITIVE_VALUES = {
    "your_token_here", "changeme", "changethis", "xxxxxxxx", "your_api_key",
    "example", "placeholder", "none", "null", "todo", "your_value_here",
    "test_key_123", "dummy_key_123", "sk-xxxxxxxx", "sk-your-key-here",
    "not_a_real_key", "replace_me", "your_key_here", "redacted",
}


def looks_like_placeholder(value: str) -> bool:
    v = value.strip().strip("\"'").lower()
    if not v or v in FALSE_POSITIVE_VALUES:
        return True
    if "example" in v or "your-" in v or "your_" in v or "xxxx" in v:
        return True
    if set(v) <= set("xX*-_=.<>{}"):
        return True
    return False


def scan_text(text: str) -> list[tuple[str, int, str]]:
    """Balik [(provider, line, var_hint)] - tanpa menyertakan nilai."""
    out: list[tuple[str, int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for provider, rx in PATTERNS:
            if rx.search(line):
                out.append((provider, lineno, ""))
        m = ASSIGN_HINTS.search(line)
        if m:
            name, value = m.group(1), m.group(2)
            if not looks_like_placeholder(value):
                out.append((f"ASSIGN::{name}", lineno, name))
    return out



def repo_root() -> pathlib.Path:
    """Akar repo.

    Skrip ini ada di `scripts/security/`, jadi akar repo adalah DUA level ke
    atas dari direktori skrip. `Path(__file__).parent.parent` hanya sampai
    `scripts/` - dan itu membuat scan melaporkan "0 temuan" karena tidak ada
    file yang terbaca sama sekali.
    """
    return pathlib.Path(__file__).resolve().parents[2]


def _git(*args: str, cwd: pathlib.Path | None = None) -> str:
    """Jalankan git dan decode sebagai UTF-8.

    Default `text=True` di Windows memakai cp1252, dan output `git log -p`
    untuk repo ini mengandung byte non-ASCII (nama file/author) yang membuat
    UnicodeDecodeError sehingga `res.stdout` jadi None. `errors="replace"`
    menjaga scan tetap jalan meski ada byte aneh.
    """
    res = subprocess.run(
        list(args), capture_output=True, check=False, cwd=cwd,
    )
    return res.stdout.decode("utf-8", errors="replace")


def git_tracked_files() -> list[str]:
    return [f for f in _git("git", "ls-files", "-z").split("\0") if f]


def scan_working_tree(root: pathlib.Path) -> list[dict]:
    findings: list[dict] = []
    for rel in git_tracked_files():
        p = root / rel
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for provider, lineno, hint in scan_text(text):
            findings.append({"scope": "working_tree", "file": rel, "line": lineno, "provider": provider, "hint": hint})
    return findings


def scan_git_history(root: pathlib.Path, max_commits: int = 500) -> list[dict]:
    """Scan seluruh history lewat `git log -p`. Nilai tidak disimpan."""
    out = _git("git", "log", "--all", "-p", f"-n{max_commits}", "--no-color", cwd=root)
    findings: list[dict] = []
    cur_file = ""
    for line in out.splitlines():
        if line.startswith("+++ b/"):
            cur_file = line[6:]
            continue
        if line.startswith("+") and not line.startswith("+++"):
            for provider, _ln, hint in scan_text(line[1:]):
                findings.append({"scope": "git_history", "file": cur_file, "line": 0, "provider": provider, "hint": hint})
    return findings


def scan_bundle(root: pathlib.Path, bundle_dir: str = "nexus-frontend/out/_next/static") -> list[dict]:
    """Scan bundle produksi yang ter-deploy ke Cloudflare."""
    base = root / bundle_dir
    findings: list[dict] = []
    if not base.is_dir():
        return [{"scope": "bundle", "file": bundle_dir, "line": 0, "provider": "BUNDLE_MISSING", "hint": ""}]
    for p in base.rglob("*.js"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for provider, _ln, hint in scan_text(text):
            findings.append({"scope": "bundle", "file": str(p.relative_to(root)), "line": 0, "provider": provider, "hint": hint})
    return findings


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent.parent
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    out_path = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else None

    report: dict = {"scanned_at_commit": _git("git", "rev-parse", "HEAD", cwd=root).strip()}
    if mode in ("all", "tree"):
        report["working_tree"] = scan_working_tree(root)
    if mode in ("all", "history"):
        report["git_history"] = scan_git_history(root)
    if mode in ("all", "bundle"):
        report["production_bundle"] = scan_bundle(root)

    report["summary"] = {k: len(v) for k, v in report.items() if isinstance(v, list)}
    blob = json.dumps(report, indent=2, ensure_ascii=False)
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(blob, encoding="utf-8")
    print(f"SUMMARY {json.dumps(report['summary'])}")
    for scope in ("working_tree", "git_history", "production_bundle"):
        for f in report.get(scope, [])[:25]:
            print(f"  {scope} {f['provider']} {f['file']}:{f['line']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
