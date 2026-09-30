"""Triage advisory pip-audit: mana yang fixable tanpa major upgrade?

`pip-audit` JSON tidak menyediakan field severity, jadi klasifikasi di sini
berdasarkan bentuk upgrade yang dibutuhkan (semver), bukan label severity:

  PATCH/MINOR  -> boleh di-fix (tidak melanggar larangan "major upgrade")
  MAJOR       -> ACCEPTED RISK, dicatat untuk post-launch
  NO FIX      -> tidak ada versi patched, ACCEPTED + lacak upstream

Nilai versi TIDAK pernah dicetak sebagai kredensial; yang dicetak hanya
nama paket + bentuk bump.
"""
import json
import pathlib
import re
import sys
from functools import total_ordering

ROOT = pathlib.Path(__file__).resolve().parents[2]


@total_ordering
class V:
    def __init__(self, s: str):
        m = re.match(r"^(\d+)\.(\d+)\.(\d+)", s or "")
        self.raw = s
        self.ok = bool(m)
        self.t = tuple(int(x) for x in m.groups()) if m else (0, 0, 0)

    def __lt__(self, o):
        return self.t < o.t

    def __eq__(self, o):
        return self.t == o.t

    def __hash__(self):
        return hash(self.t)


def bump_kind(cur: str, target: str) -> str:
    c, t = V(cur), V(target)
    if not c.ok or not t.ok:
        return "UNKNOWN"
    if c == t:
        return "SAME"
    if t < c:
        return "DOWNGRADE"
    if t.t[0] != c.t[0]:
        return "MAJOR"
    if t.t[1] != c.t[1]:
        return "MINOR"
    return "PATCH"


def main() -> int:
    path = ROOT / "docs" / "security" / "pip-audit-req.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    deps = data.get("dependencies", [])

    rows = []
    for dep in deps:
        name, cur = dep["name"], dep.get("version") or ""
        for v in dep.get("vulns") or []:
            fixes = v.get("fix_versions") or []
            best, best_kind = None, None
            order = {"PATCH": 0, "MINOR": 1, "MAJOR": 2,
                     "SAME": 3, "DOWNGRADE": 4, "UNKNOWN": 5, "NO_FIX": 6}
            for f in fixes:
                k = bump_kind(cur, f)
                if best is None or order[k] < order[best_kind]:
                    best, best_kind = f, k
            if best is None:
                kind = "NO_FIX"
            else:
                kind = best_kind
            rows.append({
                "package": name, "current": cur, "advisory": v["id"],
                "best_fix": best, "kind": kind,
            })

    by_kind: dict[str, list] = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(r)

    print(f"TOTAL ADVISORIES = {len(rows)}")
    print("--- klasifikasi bentuk upgrade ---")
    for k in ("PATCH", "MINOR", "MAJOR", "NO_FIX", "SAME", "DOWNGRADE", "UNKNOWN"):
        if k in by_kind:
            print(f"  {k:10s} {len(by_kind[k])}")

    print("\n--- paket yang bisa di-fix tanpa major (PATCH/MINOR) ---")
    seen = set()
    for r in by_kind.get("PATCH", []) + by_kind.get("MINOR", []):
        key = (r["package"], r["best_fix"], r["kind"])
        if key in seen:
            continue
        seen.add(key)
        print(f"  {r['package']:22s} {r['current']:10s} -> {r['best_fix']:10s} [{r['kind']}]")
    n_fixable = len({(r["package"], r["best_fix"]) for r in by_kind.get("PATCH", []) + by_kind.get("MINOR", [])})

    print("\n--- perlu MAJOR (ACCEPTED RISK) ---")
    for p in sorted({r["package"] for r in by_kind.get("MAJOR", [])}):
        print(f"  {p}")

    print("\n--- tanpa fix upstream (lacak) ---")
    for p in sorted({r["package"] for r in by_kind.get("NO_FIX", [])}):
        print(f"  {p}")

    out = ROOT / "docs" / "security" / "pip-triage.json"
    out.write_text(json.dumps(
        {"total": len(rows),
         "by_kind": {k: len(v) for k, v in by_kind.items()},
         "fixable_no_major": sorted(seen),
         "needs_major": sorted({r["package"] for r in by_kind.get("MAJOR", [])}),
         "no_fix": sorted({r["package"] for r in by_kind.get("NO_FIX", [])})},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nFIXABLE_NO_MAJOR = {n_fixable} paket")
    print(f"report: docs/security/pip-triage.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
