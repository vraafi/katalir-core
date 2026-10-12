"""TRACE OVERHEAD /chat per komponen — diagnostik S2 (12 Okt 2026).

KONTEKS: benchmark latency_bench.py membuktikan overhead /chat (segalanya
di luar loop LLM) rata-rata 12,9 s (38% dari total) dan sampai 23,7 s
(80% untuk prompt "halo"). `meta.latency_ms` HANYA mulai dihitung di
api_server.py:2086 (`_t0`), jadi yang tidak terukur adalah jalur serial
sebelum LLM:

  1. auth dependency (Supabase)
  2. db.get_or_create_user            (RPC Supabase)
  3. db.find_user_message_by_request  (RPC Supabase - idempotensi)
  4. db.check_quota                   (RPC Supabase)
  5. sesi: own_check / create_session (RPC Supabase)
  6. load_history                     (RPC Supabase)
  7. build_memory_context             (HTTP embedding Gemini + RPC
                                       match_agent_memory + RPC
                                       agent_preferences)  <- PRIMADONA
  8. db.add_message (user)            (RPC Supabase)
  9. pool.acquire + pool.client       (klien baru ~0,86 s bila cache miss)

Skrip ini mengukur komponen 7 + fondasinya secara ISOLATED dari mesin ini
(RTT lokal; urutan besaran sama dengan produksi), supaya perbaikan S2
ditargetkan ke komponen yang benar — bukan ditebak.

Keluaran: tests/user_test/_overhead_trace.json
"""
from __future__ import annotations

import json
import os
import pathlib
import statistics
import sys
import time

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# Muat .env root secara manual (format KEY=VALUE, abaikan komentar/kosong).
env_path = ROOT / ".env"
loaded = 0
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip("'\"")
        if k and k not in os.environ:
            os.environ[k] = v
            loaded += 1
print(f"[env] memuat {loaded} variabel dari {env_path.name}")

rows: dict[str, list[float]] = {}


def timed(name: str, fn, *a, **kw):
    t0 = time.perf_counter()
    out = fn(*a, **kw)
    dt = (time.perf_counter() - t0) * 1000
    rows.setdefault(name, []).append(dt)
    print(f"  {name:38s} {dt:8.1f} ms")
    return out


def stat(name: str) -> dict:
    xs = rows.get(name) or []
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "mean_ms": round(statistics.mean(xs), 1),
            "median_ms": round(statistics.median(xs), 1),
            "max_ms": round(max(xs), 1), "min_ms": round(min(xs), 1)}


print("=" * 74)
print("TRACE KOMPONEN OVERHEAD /chat (lokal -> Supabase/Gemini langsung)")
print("=" * 74)

# --- 0. import + klien DB ------------------------------------------------
t0 = time.perf_counter()
import database as db  # noqa: E402
import gemini_key_pool  # noqa: E402
import memory_manager as mm  # noqa: E402
print(f"  import modul memory/database        {(time.perf_counter()-t0)*1000:8.1f} ms")

t0 = time.perf_counter()
svc = db.get_write_client()
print(f"  db.get_write_client (pertama)       {(time.perf_counter()-t0)*1000:8.1f} ms")

USER_EMAIL = "otonom-t-37df433c4a@katalir-internal.dev"
AGENT = "chat"

# Di /chat asli, build_memory_context menerima user_id UUID (bukan email).
_uid = (svc.table("users").select("id")
        .eq("email", USER_EMAIL).limit(1).execute().data or [{}])[0].get("id")
if not _uid:
    raise SystemExit("uuid user uji tidak ditemukan di tabel users")
print(f"[uid] resolve via tabel users: {_uid[:8]}...")
USER = _uid

# --- 1. RTT dasar Supabase (SELECT 1 baris) ------------------------------
for i in range(3):
    def _rtt():
        return (svc.table("agent_preferences").select("key")
                .limit(1).execute())
    timed(f"baseline_rtt_supabase#{i+1}", _rtt)

# --- 2. discover_keys ----------------------------------------------------
for i in range(3):
    timed(f"gemini_discover_keys#{i+1}", gemini_key_pool.discover_keys)

# --- 3. generate_embedding (HTTP Gemini) ---------------------------------
for i in range(3):
    timed(f"generate_embedding#{i+1}", mm.generate_embedding,
          "halo", task_type="retrieval_query")

# --- 4. recall (embedding + RPC match_agent_memory) ----------------------
_m = mm.MemoryManager(user_id=USER, agent_id=AGENT)
for i in range(3):
    timed(f"MemoryManager.recall#{i+1}", _m.recall, "halo", 5)

# --- 5. list_preferences (RPC agent_preferences) -------------------------
for i in range(3):
    timed(f"list_preferences#{i+1}", _m.list_preferences)

# --- 6. build_memory_context END-TO-END ---------------------------------
for i in range(3):
    timed(f"build_memory_context#{i+1}", mm.build_memory_context,
          USER, AGENT, "halo")

print("=" * 74)
summary = {k: stat(k) for k in rows}
for k, v in summary.items():
    print(f"  {k:38s} n={v.get('n',0)} mean={v.get('mean_ms')}ms "
          f"median={v.get('median_ms')}ms max={v.get('max_ms')}ms")
print("=" * 74)

out = ROOT / "tests" / "user_test" / "_overhead_trace.json"
out.write_text(json.dumps({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                          time.gmtime()),
                           "note": ("pengukuran LOKAL per komponen; RTT lokal "
                                    "~ urutan besaran sama dgn produksi"),
                           "components": summary}, indent=2),
               encoding="utf-8")
print(f"[ok] bukti ditulis: {out}")
