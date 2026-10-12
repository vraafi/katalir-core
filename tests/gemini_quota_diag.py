"""Diagnosa kuota Gemini: RPM (jendela menit bergulir) vs RPD (per hari).

Tujuan: membuktikan SECARA MENTAH mengapa burst besar gagal setelah
~1000 panggilan kumulatif hari ini. Kita memanggil SETIAP kunci sekali
(proses baru -> state cooldown bersih) dan mencetak payload 429 ASLI,
khususnya `quotaId` (PerDay vs PerMinute) dan `quotaValue`.

Jalankan: python -u tests/_gem_quota_diag.py [model]
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import gemini_llm as G  # noqa: E402
import gemini_key_pool as gkp  # noqa: E402

MODEL = sys.argv[1] if len(sys.argv) > 1 else "gemini-3.5-flash-lite"

G.ensure_env()
pool = gkp.pool()
entries = list(pool._entries)
print(f"model probe   : {MODEL}")
print(f"kunci terlihat: {pool.size}")
print("=" * 78)

rows = []
for name, _key, fp in entries:
    t0 = time.time()
    row = {"name": name, "fp": fp}
    try:
        client = pool.client(fp)
        resp = client.models.generate_content(
            model=MODEL, contents="Say OK",
            config=G.build_config(MODEL, level="minimal", max_output_tokens=16))
        txt = (getattr(resp, "text", None) or "").strip()
        row.update(status="OK", text=txt[:40], dt=round(time.time() - t0, 2))
    except Exception as exc:  # noqa: BLE001
        raw = str(exc)
        kind, ttl = gkp.classify_error(exc)
        qids = re.findall(r"quotaId['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9_\-]+)", raw)
        qids += re.findall(r"([A-Za-z]+Per(?:Day|Minute|Second)[A-Za-z]*)", raw)
        retry = re.findall(r"retryDelay['\"]?\s*[:=]\s*['\"]?([0-9.]+)s", raw)
        row.update(status="ERR", kind=kind, ttl=ttl, dt=round(time.time() - t0, 2),
                   quota_ids=sorted(set(qids))[:4], retry_s=retry[:2],
                   raw=raw[:400])
    rows.append(row)
    tag = row["status"]
    extra = ""
    if tag == "ERR":
        extra = f" kind={row['kind']} ttl={row['ttl']:.0f}s qid={row.get('quota_ids')}"
    else:
        extra = f" text={row.get('text')!r}"
    print(f"  {name:<16} {tag:<4}{extra}  ({row['dt']}s)")

ok = sum(1 for r in rows if r["status"] == "OK")
print("=" * 78)
print(f"RINGKASAN: OK={ok}/{len(rows)}")

perday = [r["name"] for r in rows if r.get("kind") == "rate_limited"
          and any("perday" in q.lower() for q in r.get("quota_ids", []))]
print(f"PerDay  (RPD habis) : {len(perday)} -> {perday}")
rpm = [r["name"] for r in rows if r.get("kind") == "rate_limited"
       and not any("perday" in q.lower() for q in r.get("quota_ids", []))]
print(f"PerMinute (RPM)     : {len(rpm)} -> {rpm}")

out = pathlib.Path(__file__).resolve().parent / "_gem_quota_diag.json"
out.write_text(json.dumps({"model": MODEL, "ts": time.time(), "rows": rows},
                          indent=2, ensure_ascii=False), encoding="utf-8")
print(f"bukti mentah -> {out}")

# Cetak 1 payload mentah penuh sebagai bukti (tanpa membocorkan kredensial).
for r in rows:
    if r["status"] == "ERR":
        print("\n--- CONTOH PAYLOAD 429 MENTAH (dipotong 400 char) ---")
        print(r["raw"])
        break
