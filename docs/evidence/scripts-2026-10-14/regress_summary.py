"""Rekap hasil regresi 73 skenario dari tests/user_test/_rus_<grup>.json.

Skema berkas (dikonfirmasi 14 Okt): {"results": [ {id, title, state, actual,
severity, extra}, ... ]} — BUKAN "name"/"detail" seperti dugaan awal.

Pakai:
    python _regress_summary.py                 # ringkas + daftar non-PASS
    python _regress_summary.py --json out.json # simpan rekap
"""
from __future__ import annotations

import json
import pathlib
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
UT = HERE / "tests" / "user_test"
GROUPS = ["p1", "p2", "p3", "p4", "p5", "j1", "j2", "j3", "bug"]
ORDER = ["PASS", "FAIL", "BLOCKED", "NOT_RUN"]


def main() -> None:
    totals: Counter = Counter()
    per_group: dict[str, Counter] = {}
    bad: list[dict] = []

    for g in GROUPS:
        p = UT / f"_rus_{g}.json"
        if not p.exists():
            print(f"  (lewat) {g}: berkas tidak ada")
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        res = data.get("results", data if isinstance(data, list) else [])
        c = Counter(r.get("state") for r in res)
        per_group[g] = c
        totals.update(c)
        for r in res:
            if r.get("state") != "PASS":
                bad.append({"group": g, "id": r.get("id"), "state": r.get("state"),
                            "severity": r.get("severity"), "title": r.get("title"),
                            "actual": str(r.get("actual"))[:300]})

    print("\n=== per grup ===")
    hdr = "grup   " + "".join(f"{s:>9}" for s in ORDER) + f"{'total':>7}"
    print(hdr)
    for g in GROUPS:
        if g not in per_group:
            continue
        c = per_group[g]
        print(f"{g:<7}" + "".join(f"{c.get(s, 0):>9}" for s in ORDER)
              + f"{sum(c.values()):>7}")
    print("-" * len(hdr))
    print(f"{'TOTAL':<7}" + "".join(f"{totals.get(s, 0):>9}" for s in ORDER)
          + f"{sum(totals.values()):>7}")

    print(f"\n=== non-PASS ({len(bad)}) ===")
    for r in bad:
        print(f"  [{r['state']:<8}] {r['id']:<7} ({r['group']}, {r['severity']}) {r['title']}")
        print(f"      {r['actual']}")

    if "--json" in sys.argv:
        out = pathlib.Path(sys.argv[sys.argv.index("--json") + 1])
        out.write_text(json.dumps(
            {"per_group": {k: dict(v) for k, v in per_group.items()},
             "totals": dict(totals), "non_pass": bad}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"\nrekap -> {out}")


if __name__ == "__main__":
    main()
