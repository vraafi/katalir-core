"""Verifikasi kelengkapan FASE A: scan SETIAP blob yang pernah ada di repo.

Tujuan: membuktikan bahwa 98 temuan gitleaks (yang hanya "scanned" 793 dari
1584 commit) tidak apa-apa遗漏. Commit dengan diff kosong tidak menambah
konten baru, tapi kita buktikan dengan memeriksa setiap blob secara langsung.

Tidak mencetak nilai secret - hanya nama file, sha, dan nomor pola.
"""
import collections
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Pola yang sama dengan scan_secrets.py, ditambah provider yang relevan.
PATTERNS = [
    ("OPENAI", r"\bsk-[A-Za-z0-9]{32,}\b"),
    ("ANTHROPIC", r"\bsk-ant-[A-Za-z0-9_\-]{24,}\b"),
    ("JWT", r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
    ("CLOUDFLARE", r"\bv1\.0-[A-Za-z0-9_\-]{20,}\b"),
    ("SLACK", r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"),
    ("GITHUB", r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    ("GITHUB_FINE", r"\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    ("GOOGLE", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ("AWS", r"\bAKIA[0-9A-Z]{16}\b"),
    ("STRIPE", r"\bsk_live_[A-Za-z0-9]{20,}\b"),
    ("DODO_WEBHOOK", r"\bwhsec_[A-Za-z0-9]{20,}\b"),
    ("IP_PASSWORD", r"password\s*=\s*['\"][^'\"\s]{8,}['\"]"),
]
RX = [(name, re.compile(p)) for name, p in PATTERNS]


def main() -> int:
    objs = subprocess.run(
        ["git", "rev-list", "--objects", "--all"],
        capture_output=True, text=True, errors="replace", cwd=ROOT,
    ).stdout.splitlines()

    # sha -> path (path bisa kosong untuk tree/commit)
    sha_path: dict[str, str] = {}
    for line in objs:
        parts = line.split(" ", 1)
        sha = parts[0]
        sha_path[sha] = parts[1] if len(parts) > 1 else ""

    kinds = subprocess.run(
        ["git", "cat-file", "--batch-check"],
        input="\n".join(sha_path) + "\n",
        capture_output=True, text=True, errors="replace", cwd=ROOT,
    ).stdout.splitlines()

    blobs = []
    for sha, line in zip(sha_path, kinds):
        f = line.split()
        if len(f) >= 2 and f[1] == "blob":
            blobs.append((sha, sha_path[sha]))

    print(f"objects_total={len(sha_path)}")
    print(f"blobs_total={len(blobs)}")

    # Batch-read isi blob.
    proc = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=ROOT,
    )
    payload = ("\n".join(sha for sha, _ in blobs) + "\n").encode()
    out, _ = proc.communicate(payload)

    findings: list[tuple[str, str, int, str]] = []
    pos = 0
    for sha, path in blobs:
        nl = out.find(b"\n", pos)
        if nl < 0:
            break
        header = out[pos:nl].split()
        pos = nl + 1
        if len(header) < 3:
            continue
        size = int(header[2])
        data = out[pos:pos + size]
        pos += size + 1
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, rx in RX:
                if rx.search(line):
                    findings.append((path or "<unnamed>", sha[:10], lineno, name))

    by_file = collections.Counter((f[0], f[3]) for f in findings)
    by_rule = collections.Counter(f[3] for f in findings)
    print(f"blob_findings_total={len(findings)}")
    print("--- by rule ---")
    for k, v in by_rule.most_common():
        print(f"  {k}: {v}")
    print("--- by file (top 20) ---")
    for (path, rule), v in by_file.most_common(20):
        print(f"  {v}  {rule}  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
