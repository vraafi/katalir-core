"""Agregasi hasil REAL USER SIMULATION menjadi digest + tabel markdown.

Pakai:  python tests/user_test/rus_report.py
Keluaran: tests/user_test/_rus_digest.json + _rus_digest.md
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
GROUPS = ["p1", "p2", "p3", "p4", "p5", "j1", "j2", "j3", "bug"]
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "?": 4}

rows: list[dict] = []
per_group: dict[str, dict] = {}

for g in GROUPS:
    f = HERE / f"_rus_{g}.json"
    if not f.exists():
        continue
    d = json.loads(f.read_text(encoding="utf-8"))
    per_group[g] = {"count": d.get("count", 0)}
    for r in d.get("results", []):
        r["group"] = g
        rows.append(r)

# tambahan: hasil skrip reproduksi terarah
for extra, key in ((HERE / "_rus_repro_500.json", "repro_500"),
                   (HERE / "_rus_repro_backend.json", "repro_backend"),
                   (HERE / "_rus_repro_long.json", "repro_long"),
                   (HERE / "_rus_repro_p1_01.json", "repro_p1_01")):
    if extra.exists():
        per_group[key] = json.loads(extra.read_text(encoding="utf-8"))

counts = {"PASS": 0, "FAIL": 0, "BLOCKED": 0, "NOT_RUN": 0}
for r in rows:
    counts[r["state"]] = counts.get(r["state"], 0) + 1

problems = [r for r in rows if r["state"] in ("FAIL", "BLOCKED")]
problems.sort(key=lambda r: (SEV_ORDER.get(r.get("severity"), 9),
                             r.get("id", "")))

digest = {"counts": counts, "total": len(rows), "groups": per_group,
          "problems": problems, "all": rows}
(HERE / "_rus_digest.json").write_text(
    json.dumps(digest, ensure_ascii=False, indent=1), encoding="utf-8")

lines = ["# Digest REAL USER SIMULATION", "",
         f"Total skenario: **{len(rows)}**  ·  PASS={counts['PASS']} "
         f"FAIL={counts['FAIL']} BLOCKED={counts['BLOCKED']} "
         f"NOT_RUN={counts['NOT_RUN']}", "", "## Per grup", ""]
for g, v in per_group.items():
    lines.append(f"- `{g}`: {v}")
lines += ["", "## Masalah (urut severity)", ""]
for r in problems:
    shots = ", ".join(pathlib.Path(s).name for s in r.get("screenshots") or [])
    lines += [
        f"### {r['id']} — {r['title']}  [{r['state']} / {r.get('severity')}]",
        f"- persona: {r.get('persona')} · grup: {r.get('group')}"
        + (f" · {r.get('seconds')}s" if r.get("seconds") else ""),
        f"- aksi: {r.get('action')}",
        f"- harapan: {r.get('expected')}",
        f"- kenyataan: {r.get('actual')}",
    ]
    if r.get("evidence_note"):
        lines.append(f"- catatan bukti: {r['evidence_note']}")
    if shots:
        lines.append(f"- bukti: {shots}")
    if r.get("console_errors"):
        lines.append(f"- console: {json.dumps(r['console_errors'][:3], ensure_ascii=False)[:300]}")
    if r.get("failed_requests"):
        lines.append(f"- request gagal: {json.dumps(r['failed_requests'][:3], ensure_ascii=False)[:300]}")
    lines.append("")
(HERE / "_rus_digest.md").write_text("\n".join(lines), encoding="utf-8")

print(f"total={len(rows)} {counts}")
print(f"masalah={len(problems)}")
for r in problems:
    print(f"  {r['id']:8} {r['state']:8} {str(r.get('severity')):8} "
          f"{r['title'][:60]}")
print(f"\nbukti -> {HERE / '_rus_digest.md'}")
