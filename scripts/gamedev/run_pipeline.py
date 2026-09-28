"""Pipeline runner: worker -> verification gate -> retry.

MENGGUNAKAN CLI ASLI Cline yang sudah diuji, bukan asumsi:

  clite --auto-approve true --timeout <sec> -c <dir> "<prompt>"

Tiga koreksi terhadap perintah di rencana awal, ketiganya sudah
dibuktikan dengan menjalankan `clite --help` dan satu sesi nyata:
  1. binary bernama `clite`, bukan `cline`
  2. tidak ada flag `-y`; auto-approve sudah default true
  3. `--timeout <detik>` memang ada (default 0 = tanpa timeout)

Pakai:
    python scripts/gamedev/run_pipeline.py --project projects/gamedev/demo
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "scripts" / "gamedev" / "verify_gate.py"


def find_clite() -> str | None:
    exe = shutil.which("clite")
    if exe:
        return exe
    # npm global prefix tidak selalu ada di PATH untuk sesi non-interaktif.
    for base in (
        os.environ.get("APPDATA", ""),
        os.path.expanduser("~/.npm-global"),
        os.path.expanduser("~/.local"),
    ):
        if not base:
            continue
        cand = Path(base) / "npm" / ("clite.cmd" if os.name == "nt" else "clite")
        if cand.exists():
            return str(cand)
    return None


def run_worker(clite: str, project: Path, prompt: str, timeout: int) -> str:
    cmd = [
        clite,
        "--auto-approve", "true",
        "--timeout", str(timeout),
        "-c", str(project),
        prompt,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 120)
    return (proc.stdout or "") + (proc.stderr or "")


def run_gate(project: Path, output_text: str) -> tuple[bool, str]:
    work = project / "worker-output.log"
    work.write_text(output_text, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(GATE), "--spec", str(project / "GAME_SPEC.md"),
         "--output", str(work)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    line = (proc.stdout or "").strip().splitlines()[-1] if proc.stdout.strip() else "VERDICT: FAIL: gate tidak merespons"
    return proc.returncode == 0, line


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--worker-timeout", type=int, default=3600)
    args = ap.parse_args()

    project = Path(args.project).resolve()
    for required in ("GAME_SPEC.md", "PROGRESS.md"):
        if not (project / required).exists():
            print(f"GATE: FAIL: {required} tidak ada di {project}")
            return 1

    clite = find_clite()
    if not clite:
        print("GATE: FAIL: binary `clite` tidak ditemukan di PATH")
        return 1
    print(f"WORKER: {clite}")

    feedback: list[str] = []
    for attempt in range(1, args.max_attempts + 1):
        prompt = (
            "Baca GAME_SPEC.md dan PROGRESS.md di direktori ini. Kerjakan satu "
            "item checklist berikutnya yang belum [x], lalu update PROGRESS.md "
            "dan tulis bukti di bagian Bukti. Jangan menandai [x] tanpa bukti."
        )
        if feedback:
            prompt += "\n\nFeedback QA dari percobaan sebelumnya:\n- " + "\n- ".join(feedback)

        started = time.time()
        print(f"=== ATTEMPT {attempt}/{args.max_attempts} ===")
        try:
            out = run_worker(clite, project, prompt, args.worker_timeout)
        except subprocess.TimeoutExpired:
            print("WORKER: timeout, diperlakukan sebagai FAIL")
            out = "worker timeout"

        ok, verdict = run_gate(project, out)
        print(f"GATE: {verdict}  ({int(time.time() - started)}s)")

        if ok:
            print("PIPELINE: PASS untuk item ini")
            return 0

        feedback.append(verdict)
        print("PIPELINE: retry dengan feedback QA")

    print("PIPELINE: GAGAL setelah{max} percobaan".format(max=args.max_attempts))
    return 1


if __name__ == "__main__":
    sys.exit(main())
