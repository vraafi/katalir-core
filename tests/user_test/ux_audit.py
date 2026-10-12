"""TASK 2 - UX AUDIT berbasis BUKTI (Katalir, 12 Okt 2026).

Menilai 5 aspek x 10 skenario dengan skala 1..5 (target rata-rata >= 4).
Skor TIDAK diketik tangan: semuanya dihitung dari artefak uji yang nyata
(_user_test_results.json, _mobile_results.json, _recon.json, _shopee_results.json)
memakai rumus yang bisa diaudit ulang.

Aspek:
  1. loading_time   - kecepatan halaman & balasan
  2. clarity        - kejelasan teks/label/bahasa
  3. error_message  - mutu pesan galat (ramah, jujur, bisa ditindak)
  4. responsiveness - tata letak lintas viewport & target sentuh
  5. consistency    - konsistensi rute, bahasa, dan kontrak frontend<->backend

Keluaran: tests/user_test/_ux_audit.json
"""
from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
UT = ROOT / "tests" / "user_test"


def load(name, default=None):
    p = UT / name
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


ut = load("_user_test_results.json", {}) or {}
mob = load("_mobile_results.json", []) or []
recon = load("_recon.json", {}) or {}
shop = load("_shopee_results.json", {}) or {}
_sup = load("_supabase_cfg.json", {}) or {}

results = ut.get("results", [])
by_no = {r.get("no"): r for r in results}


def clamp5(x):
    return max(1, min(5, int(round(x))))


# ------------------------------------------------------------------ 1. LOADING
loads = [m.get("load_s") for m in mob if isinstance(m.get("load_s"), (int, float))]
chat_s = [r.get("seconds") for r in results
          if isinstance(r.get("seconds"), (int, float))]
mean_load = sum(loads) / len(loads) if loads else None
mean_chat = sum(chat_s) / len(chat_s) if chat_s else None


def score_seconds(s):
    if s is None:
        return None
    if s < 2:
        return 5
    if s < 4:
        return 4
    if s < 6:
        return 3
    if s < 10:
        return 2
    return 1


page_s = score_seconds(mean_load)
chat_s_score = score_seconds(mean_chat)
loading = clamp5(sum(x for x in (page_s, chat_s_score) if x) /
                 max(1, sum(1 for x in (page_s, chat_s_score) if x)))

# ------------------------------------------------------------------ 2. CLARITY
# Korpus teks UI NYATA: text_head tiap rute (recon) + body kanvas/chat Shopee.
ID_WORDS = ("kirim", "buat", "workflow", "template", "riwayat", "masuk",
            "coba", "lagi", "kembali", "cari", "pesan", "agent", "kanvas",
            "simpan", "tambah", "atur", "lihat", "insight", "brankas")
route_txt = {}
rts = recon.get("routes") or {}
for path, v in rts.items():
    if isinstance(v, dict) and v.get("text_head"):
        route_txt[path] = v["text_head"]
if shop.get("chat_body"):
    route_txt["/chat (pasca-kirim)"] = shop["chat_body"]
if shop.get("canvas_body"):
    route_txt["/builder (kanvas)"] = shop["canvas_body"]
clarity_hits = 0
clarity_total = 0
for t in route_txt.values():
    clarity_total += 1
    low = t.lower()
    if sum(1 for w in ID_WORDS if w in low) >= 3:
        clarity_hits += 1
clarity_ratio = (clarity_hits / clarity_total) if clarity_total else 0
# hukuman: teks yang MENYESATKAN pengguna (menyalahkan internet padahal CSP)
misleading = sum(1 for t in route_txt.values() if "koneksi lambat" in t.lower())
clarity = clamp5(1 + 4 * clarity_ratio - (1 if misleading else 0))

# ------------------------------------------------------------------ 3. ERROR MSG
s9 = by_no.get(9, {})
err_friendly = "ramah" in str(s9.get("actual", "")).lower() or \
    "tombol_retry=1" in str(s9.get("actual", ""))
err_retry = "tombol_retry=1" in str(s9.get("actual", ""))
# apakah pesan galat JUJUR? "Koneksi lambat. Cek internetmu." menyalahkan
# pengguna padahal penyebabnya blokir CSP ke host mati.
honest = not misleading
error_score = clamp5(1 + (2 if err_friendly else 0) + (1 if err_retry else 0) +
                     (1 if honest else 0))

# ------------------------------------------------------------------ 4. RESPONSIVE
mob_ok = 0
for m in mob:
    good = (m.get("composer_visible") and m.get("composer_clickable")
            and m.get("composer_in_viewport") and (m.get("h_overflow_px") or 0) <= 0)
    if good:
        mob_ok += 1
mob_ratio = mob_ok / len(mob) if mob else 0
touch_ok = all((m.get("buttons_under_44") or 0) == 0
               for m in mob if m.get("w", 999) < 700)
responsiveness = clamp5(1 + 3 * mob_ratio + (1 if touch_ok else 0))

# ------------------------------------------------------------------ 5. CONSISTENCY
rts = recon.get("routes") or {}
route_status = {}
for path, v in rts.items():
    route_status[path] = v.get("http") if isinstance(v, dict) else v
ok_routes = [p for p, s in route_status.items() if s == 200]
bad_routes = [p for p, s in route_status.items() if s not in (200, None)]
route_ratio = len(ok_routes) / len(route_status) if route_status else 0

# kontrak frontend<->backend: host API yang BENAR-BENAR ter-bake di bundle
# (hasil extract_cfg.py) vs connect-src di CSP produksi.
baked = (_sup.get("api_urls") or [None])[0] if isinstance(_sup, dict) else None
csp_allow = set()
hdr = ROOT / "nexus-frontend" / "public" / "_headers"
if hdr.exists():
    for m in re.finditer(r"https://[A-Za-z0-9.\-]+", hdr.read_text(
            encoding="utf-8", errors="replace")):
        csp_allow.add(m.group(0).rstrip("."))
contract_mismatch = bool(baked and baked not in csp_allow)
consistency = clamp5(1 + 3 * route_ratio - (1 if contract_mismatch else 0))

ASPECTS = {
    "loading_time": (loading, f"rata-rata muat halaman {mean_load:.1f}s; "
                              f"rata-rata balasan chat {mean_chat:.1f}s "
                              f"(target balasan <30s)"),
    "clarity": (clarity, f"{clarity_hits}/{clarity_total} layar memakai kosakata "
                         f"Indonesia yang jelas; {misleading} layar memakai teks "
                         f"menyesatkan 'Koneksi lambat. Cek internetmu.'"),
    "error_message": (error_score, f"ramah={err_friendly}, tombol coba-lagi="
                                   f"{err_retry}, jujur={honest} (pesan menyalahkan "
                                   f"internet pengguna, bukan blokir CSP)"),
    "responsiveness": (responsiveness, f"{mob_ok}/{len(mob)} viewport bersih "
                                       f"(composer terlihat+dapat diklik, tanpa "
                                       f"overflow horizontal); target sentuh "
                                       f">=44px di mobile={touch_ok}"),
    "consistency": (consistency, f"{len(ok_routes)}/{len(route_status)} rute 200; "
                                 f"kontrak API_URL frontend tidak cocok dengan CSP "
                                 f"(host lama)"),
}

overall = round(sum(v[0] for v in ASPECTS.values()) / len(ASPECTS), 2)
below = [k for k, v in ASPECTS.items() if v[0] < 4]
out = {"aspects": {k: {"score": v[0], "evidence": v[1]}
                   for k, v in ASPECTS.items()},
       "overall": overall, "target": 4.0,
       "aspects_below_target": below,
       "verdict": "PASS" if overall >= 4 and not below else "FAIL",
       "input_files": ["_user_test_results.json", "_mobile_results.json",
                       "_recon.json", "_shopee_results.json"]}

print("=" * 74)
print("UX AUDIT (skala 1-5, target rata-rata >= 4)")
print("=" * 74)
for k, v in ASPECTS.items():
    mark = "OK " if v[0] >= 4 else "!! "
    print(f"  {mark}{k:<15} {v[0]}/5  - {v[1]}")
print("-" * 74)
print(f"  RATA-RATA       {overall}/5  -> {out['verdict']}")
print(f"  di bawah target : {below or 'tidak ada'}")
print("=" * 74)

(UT / "_ux_audit.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
print(f"bukti -> {UT / '_ux_audit.json'}")
