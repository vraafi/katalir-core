"""Runner REAL USER SIMULATION — Katalir.

Pakai:
    python tests/user_test/rus_run.py p1 p2 p3 p4 p5
    python tests/user_test/rus_run.py j1 j2 j3
    python tests/user_test/rus_run.py bug
    python tests/user_test/rus_run.py all

Setiap grup menulis tests/user_test/_rus_<grup>.json + screenshot di
docs/evidence/real-user-2026-10-13/.
"""
from __future__ import annotations

import os
import pathlib
import sys
import time
import traceback

# Browser Playwright ada di D: (hemat C:) — pakai garis miring (Git Bash).
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "D:/caches/playwright")

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import rus_core  # noqa: E402
import rus_extra  # noqa: E402
import rus_personas  # noqa: E402
from rus_core import RESULTS, dump  # noqa: E402

ALL = {
    "p1": rus_personas.p1_impatient,
    "p2": rus_personas.p2_beginner,
    "p3": rus_personas.p3_distracted,
    "p4": rus_personas.p4_slow,
    "p5": rus_personas.p5_critical,
    "j1": rus_extra.j1_new_user,
    "j2": rus_extra.j2_shopee,
    "j3": rus_extra.j3_multi_user,
    "bug": rus_extra.b_bughunt,
}


def main(argv: list[str]) -> int:
    wanted = argv[1:] or ["all"]
    if "all" in wanted:
        wanted = list(ALL.keys())
    groups = [g for g in wanted if g in ALL]
    if not groups:
        print(f"grup tidak dikenal: {wanted}. Pilihan: {list(ALL)}")
        return 2

    print("=" * 72)
    print("REAL USER SIMULATION — Katalir (13 Okt 2026)")
    print(f"akun uji   : {rus_core.EMAIL}")
    print(f"frontend   : {rus_core.FRONTEND}")
    print(f"backend    : {rus_core.BACKEND}")
    print(f"bukti      : {rus_core.EV}")
    print(f"grup       : {groups}")
    print("=" * 72, flush=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        for g in groups:
            RESULTS.clear()
            t0 = time.time()
            print(f"\n{'=' * 72}\n### GRUP {g.upper()}\n{'=' * 72}", flush=True)
            try:
                ALL[g](b)
            except Exception:  # noqa: BLE001
                print(f"[grup {g}] gagal total:\n{traceback.format_exc()}",
                      flush=True)
            dur = round(time.time() - t0, 1)
            n = {"PASS": 0, "FAIL": 0, "BLOCKED": 0, "NOT_RUN": 0}
            for r in RESULTS:
                n[r["state"]] = n.get(r["state"], 0) + 1
            print(f"\n[{g}] {dur}s  ->  PASS={n['PASS']} FAIL={n['FAIL']} "
                  f"BLOCKED={n['BLOCKED']} NOT_RUN={n['NOT_RUN']}", flush=True)
            dump(g)
        b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
