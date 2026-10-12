"""TASK 6 - KEPUASAN PENGGUNA via LLM-as-judge DISKRIMINATIF (Katalir, 12 Okt 2026).

Kenapa "diskriminatif"? Judge LLM punya penyakit bawaan: cenderung memberi nilai
tinggi untuk SEMUA jawaban (rubber-stamp). Supaya tidak jadi stempel karet, judge
di sini WAJIB lulus uji kalibrasi lebih dulu:

  * jangkar GOOD  (jawaban kaya & tepat)  -> HARUS dinilai >= 0.80
  * jangkar BAD   (jawaban menolak/tidak nyambung) -> HARUS dinilai <= 0.30
  * jangkar MID   (jawaban setengah benar) -> HARUS di antara keduanya

Bila judge tidak bisa memisahkan ketiganya, judge dinyatakan INVALID dan
skornya tidak dipakai (bukan diklaim lulus).

Selain judge LLM, ada CROSS-CHECK deterministik (tanpa LLM) yang mengukur
hal yang sama secara terukur: cakupan entitas, penanda langkah, panjang, dll.

Jalur: backend `/chat` LANGSUNG (server-side). Ini disengaja - frontend sedang
rusak (CSP/API_URL lama), jadi kepuasan atas MUTU JAWABAN hanya bisa diukur
lewat backend. Batasan ini dicatat di laporan, bukan disembunyikan.

Keluaran: tests/user_test/_satisfaction_results.json
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import statistics
import sys
import time
import urllib.error
import urllib.request

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
UT = ROOT / "tests" / "user_test"
sys.path.insert(0, str(ROOT))
import gemini_llm  # noqa: E402  (modul LLM proyek = model mentah, tanpa persona)
API = "https://gateway.katalir.de5.net/katalir-api"
UA = "Katalir-SatTest/1.0"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
SESS = json.loads((UT / "_session.json").read_text(encoding="utf-8"))
TOKEN = SESS["session"]["access_token"]

PACE_S = 7.0          # rate limit produksi: 10 pesan / 60 detik / akun
DIMENSIONS = ["helpful", "actionable", "intent", "expectation"]
THRESHOLD = 0.70

# 10 prompt nyata - memetakan skenario TASK 1
PROMPTS = [
    ("S1  onboarding", "Halo, saya baru daftar. Apa yang bisa Katalir lakukan?"),
    ("S2  chat pertama", "Jelaskan singkat cara membuat agent pertama saya."),
    ("S3  build workflow", "Buat workflow: kirim pesan Telegram setiap ada email baru."),
    ("S4  history", "Apa saja yang kita bicarakan sebelumnya?"),
    ("S5  credential", "Bagaimana cara menyimpan API key OpenAI dengan aman?"),
    ("S6  template", "Rekomendasikan template untuk notifikasi order e-commerce."),
    ("S7  edit workflow", "Tambahkan langkah filter ke workflow yang tadi."),
    ("S8  insights", "Bagaimana cara melihat performa agent saya?"),
    ("S9  error handling", "asdkjhasd 9999 %% ?? tolong jelaskan"),
    ("S10 logout/login", "Terima kasih, sampai jumpa."),
]

# jangkar kalibrasi judge (dibuat manual, sengaja ekstrem)
ANCHOR_PROMPT = "Buat workflow: webhook Shopee -> batch order jam 8"
ANCHORS = [
    {"name": "GOOD", "reply": None, "expect": ">= 0.80", "mode": "ge",
     "lo": 0.80, "note": "memakai jawaban NYATA terbaik dari FASE A"},
    {"name": "BAD", "expect": "<= 0.30", "mode": "le", "lo": 0.30,
     "reply": "Maaf, saya tidak mengerti pertanyaan Anda. Silakan coba lagi nanti."},
    {"name": "MID", "expect": "between", "mode": "between", "lo": None,
     "reply": "Bisa. Anda perlu webhook, lalu kirim data. "
              "Silakan atur sendiri di kanvas."},
]


def chat(prompt: str, timeout: int = 180) -> dict:
    body = json.dumps({"message": prompt, "prompt": prompt}).encode()
    req = urllib.request.Request(
        f"{API}/chat", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {TOKEN}", "User-Agent": UA})
    t0 = time.time()
    try:
        with OPENER.open(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
            return {"status": r.status, "ms": round((time.time() - t0) * 1000),
                    "reply": data.get("reply", ""),
                    "model": (data.get("meta") or {}).get("model"),
                    "workflow": (data.get("meta") or {}).get("workflow"),
                    "raw_keys": sorted(data.keys())}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "ms": round((time.time() - t0) * 1000),
                "reply": "", "error": e.read().decode("utf-8", "replace")[:200]}
    except Exception as exc:  # noqa: BLE001
        return {"status": -1, "ms": round((time.time() - t0) * 1000),
                "reply": "", "error": f"{type(exc).__name__}: {exc}"[:200]}


# ---------------------------------------------------------------- cross-check
STEPS_RE = re.compile(r"(^\s*\d+[\.\)]\s)|(^\s*[-*]\s)", re.M)
PLACEHOLDER_RE = re.compile(r"\{\{[^}]+\}\}")


def deterministic(prompt: str, reply: str, workflow: dict | None) -> dict:
    """Cross-check tanpa LLM: mengukur sinyal terukur dari jawaban."""
    low = reply.lower()
    ents = [w for w in ("shopee", "webhook", "order", "whatsapp", "sheets",
                        "telegram", "email", "filter", "template", "agent",
                        "api key", "insight", "performa")
            if w in low or w in prompt.lower()]
    prompt_ents = [w for w in ("shopee", "webhook", "order", "whatsapp", "sheets",
                               "telegram", "email", "filter", "template",
                               "api key", "insight", "performa")
                   if w in prompt.lower()]
    covered = [e for e in prompt_ents if e in low]
    steps = len(STEPS_RE.findall(reply))
    ph = len(PLACEHOLDER_RE.findall(reply))
    nodes = len((workflow or {}).get("nodes", []))
    edges = len((workflow or {}).get("edges", []))
    return {
        "len": len(reply),
        "words": len(reply.split()),
        "steps": steps,
        "placeholders": ph,
        "entities_prompt": prompt_ents,
        "entities_covered": covered,
        "entity_cover_ratio": (round(len(covered) / len(prompt_ents), 3)
                               if prompt_ents else None),
        "nodes": nodes,
        "edges": edges,
        "non_empty": len(reply.strip()) > 40,
    }


# ---------------------------------------------------------------- judge LLM
JUDGE_SYS = (
    "Anda adalah penilai KETAT untuk kualitas jawaban asisten AI bernama Katalir. "
    "Nilailah HANYA berdasarkan rubrik. Jangan bermurah hati: jawaban yang tidak "
    "menjawab pertanyaan, menolak, atau kosong HARUS mendapat nilai rendah. "
    "Balas HANYA dengan JSON valid tanpa penjelasan lain, format: "
    '{"helpful": <0..1>, "actionable": <0..1>, "intent": <0..1>, '
    '"expectation": <0..1>, "alasan": "<maks 20 kata>"}'
)

RUBRIK = (
    "Rubrik (masing-masing 0..1):\n"
    "- helpful   : apakah jawaban benar-benar membantu mencapai tujuan pengguna?\n"
    "- actionable: apakah ada langkah/kode/config konkret yang bisa langsung dipakai?\n"
    "- intent    : apakah maksud pengguna dipahami dengan benar (entitas tidak hilang)?\n"
    "- expectation: apakah memenuhi harapan wajar untuk produk Agent Builder?\n"
    "Panduan: jawaban menolak/off-topic/kosong -> semua <= 0.30. "
    "Jawaban generik tanpa langkah konkret -> sekitar 0.40-0.60. "
    "Jawaban lengkap, tepat, dengan langkah konkret -> >= 0.80."
)


def judge(prompt: str, reply: str) -> dict:
    """Panggil MODEL MENTAH (Gemini) - BUKAN `/chat` produk.

    Pelajaran penting (terdokumentasi di laporan): percobaan pertama memakai
    `/chat` Katalir sebagai judge dan GAGAL kalibrasi (GOOD dinilai 0.0),
    karena endpoint itu menempelkan persona produk ("Katalir Agent Builder")
    yang menabrak instruksi penilai. Judge harus model mentah + system prompt
    sendiri.
    """
    q = (f"{RUBRIK}\n\n"
         f"PERMINTAAN PENGGUNA:\n{prompt}\n\n"
         f"JAWABAN ASISTEN:\n{reply[:4000]}\n\n"
         f"JSON:")
    r = gemini_llm.chat_with_fallback(q, system_instruction=JUDGE_SYS,
                                      temperature=0.0, level="low",
                                      deadline_s=60.0)
    txt = (r.get("text") or "")
    m = re.search(r"\{[^{}]*\}", txt, re.S)
    if not m:
        return {"parse_error": True, "raw": txt[:200], "ok": r.get("ok"),
                "model": r.get("model")}
    try:
        d = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return {"parse_error": True, "raw": m.group(0)[:200]}
    out = {k: (float(d[k]) if k in DIMENSIONS and isinstance(
        d.get(k), (int, float)) else d.get(k)) for k in (*DIMENSIONS, "alasan")}
    out["model"] = r.get("model")
    return out


# ================================================================ RUN
out: dict = {"api": API, "model_path": "backend /chat (FASE A) + model mentah Gemini (judge)",
             "threshold": THRESHOLD, "dimensions": DIMENSIONS,
             "pace_s": PACE_S, "note": (
                 "Frontend rusak (CSP/API_URL lama); mutu jawaban diukur lewat "
                 "backend langsung. Judge dikalibrasi dengan 3 jangkar.")}

print("=" * 74)
print("FASE A - ambil jawaban nyata dari backend /chat")
print("=" * 74)
_CACHE = UT / "_satisfaction_results.json"
transcripts: list[dict] = []
_cached = None
if _CACHE.exists() and "--fresh" not in sys.argv:
    try:
        _c = json.loads(_CACHE.read_text(encoding="utf-8"))
        if len(_c.get("transcripts") or []) == len(PROMPTS):
            _cached = _c
    except Exception:  # noqa: BLE001
        _cached = None

if _cached:
    transcripts = _cached["transcripts"]
    print(f"  [pakai ulang {len(transcripts)} transkrip dari {_CACHE.name} - "
          f"hemat kuota; jalankan dengan --fresh untuk ambil ulang]")
    for t in transcripts:
        d = t["deterministic"]
        print(f"  {t['tag']:<18} status={t['status']} {t['ms']}ms "
              f"len={d['len']:<5} steps={d['steps']:<2} "
              f"cover={d['entity_cover_ratio']} nodes={d['nodes']}")
else:
    for tag, p in PROMPTS:
        r = chat(p)
        det = deterministic(p, r.get("reply", ""), r.get("workflow"))
        transcripts.append({"tag": tag, "prompt": p, "status": r.get("status"),
                            "ms": r.get("ms"), "model": r.get("model"),
                            "reply": r.get("reply", ""),
                            "error": r.get("error"),
                            "workflow_nodes": det["nodes"],
                            "workflow_edges": det["edges"],
                            "deterministic": det})
        print(f"  {tag:<18} status={r.get('status')} {r.get('ms')}ms "
              f"len={det['len']:<5} steps={det['steps']:<2} "
              f"cover={det['entity_cover_ratio']} nodes={det['nodes']}", flush=True)
        time.sleep(PACE_S)

out["transcripts"] = transcripts

print()
print("=" * 74)
print("FASE B - kalibrasi judge dengan jangkar (uji diskriminasi)")
print("=" * 74)
anchor_results: list[dict] = []
# GOOD anchor: jawaban NYATA dari backend untuk prompt Shopee yang SAMA.
# Catatan kejujuran: percobaan sebelumnya memasangkan prompt Shopee dengan
# jawaban Telegram -> judge menilainya 0.05 dan kalibrasi GAGAL. Itu bukan bug
# judge, itu jangkar yang salah pasang. Judge ternyata DISKRIMINATIF (menangkap
# ketidaksesuaian prompt<->jawaban).
_shop_ev = ROOT / "docs" / "evidence" / "user-test" / "shopee-03-backend-workflow.json"
shopee_real = None
if _shop_ev.exists():
    shopee_real = (json.loads(_shop_ev.read_text(encoding="utf-8")).get("reply")
                   or None)
if not shopee_real:
    shopee_real = next((t["reply"] for t in transcripts
                        if t["workflow_nodes"] >= 3), transcripts[2]["reply"])
for a in ANCHORS:
    reply = shopee_real if a["name"] == "GOOD" else a["reply"]
    j = judge(ANCHOR_PROMPT, reply)
    rec = {"anchor": a["name"], "expect": a["expect"],
           "reply_len": len(reply), "judge": j}
    anchor_results.append(rec)
    print(f"  jangkar {a['name']:<5} expect={a['expect']:<12} "
          f"judge={ {k: j.get(k) for k in DIMENSIONS} }", flush=True)
    time.sleep(0.2)

good = anchor_results[0]["judge"]
bad = anchor_results[1]["judge"]
mid = anchor_results[2]["judge"]


def mean_dim(j):
    vals = [j.get(k) for k in DIMENSIONS if isinstance(j.get(k), (int, float))]
    return statistics.mean(vals) if vals else None


g, b, m = mean_dim(good), mean_dim(bad), mean_dim(mid)
calib_ok = bool(g is not None and b is not None and m is not None
                and g >= 0.80 and b <= 0.30 and b < m < g)
out["calibration"] = {"anchors": anchor_results,
                      "mean": {"GOOD": g, "BAD": b, "MID": m},
                      "discriminative": calib_ok,
                      "verdict": ("VALID (judge memisahkan baik/buruk)"
                                  if calib_ok else
                                  "INVALID (judge tidak diskriminatif)")}
print(f"\n  mean jangkar: GOOD={g} BAD={b} MID={m} -> "
      f"{'VALID' if calib_ok else 'INVALID'}")

print()
print("=" * 74)
print("FASE C - nilai 10 jawaban nyata")
print("=" * 74)
scored: list[dict] = []
for t in transcripts:
    if not t["reply"].strip():
        j = {k: 0.0 for k in DIMENSIONS}
        j["note"] = "jawaban kosong (backend error)"
    else:
        j = judge(t["prompt"], t["reply"])
    vals = [j.get(k) for k in DIMENSIONS if isinstance(j.get(k), (int, float))]
    t["judge"] = j
    t["judge_mean"] = round(statistics.mean(vals), 3) if vals else None
    t["pass"] = bool(t["judge_mean"] is not None
                     and t["judge_mean"] >= THRESHOLD)
    scored.append(t)
    print(f"  {t['tag']:<18} mean={t['judge_mean']} "
          f"{'PASS' if t['pass'] else 'FAIL'} "
          f"{ {k: j.get(k) for k in DIMENSIONS} }", flush=True)
    time.sleep(0.2)

means = [t["judge_mean"] for t in scored if t["judge_mean"] is not None]
overall = round(statistics.mean(means), 3) if means else None
per_dim = {d: round(statistics.mean(
    [t["judge"][d] for t in scored
     if isinstance(t["judge"].get(d), (int, float))] or [0]), 3)
    for d in DIMENSIONS}

out["scored"] = scored
out["per_dimension"] = per_dim
out["overall_mean"] = overall
out["pass_count"] = sum(1 for t in scored if t["pass"])
out["gate"] = {"threshold": THRESHOLD, "overall": overall,
               "verdict": ("PASS" if (overall is not None
                                      and overall >= THRESHOLD
                                      and calib_ok) else "FAIL"),
               "reason": None if calib_ok else "judge gagal kalibrasi"}

# cross-check deterministik agregat
dets = [t["deterministic"] for t in transcripts]
out["deterministic_summary"] = {
    "non_empty": sum(1 for d in dets if d["non_empty"]),
    "with_steps": sum(1 for d in dets if d["steps"] > 0),
    "with_placeholders": sum(1 for d in dets if d["placeholders"] > 0),
    "with_workflow_nodes": sum(1 for d in dets if d["nodes"] > 0),
    "mean_entity_cover": round(statistics.mean(
        [d["entity_cover_ratio"] for d in dets
         if d["entity_cover_ratio"] is not None] or [0]), 3),
}

print()
print("=" * 74)
print(f"per-dimensi     : {per_dim}")
print(f"overall mean    : {overall}  (ambang {THRESHOLD})")
print(f"lulus           : {out['pass_count']}/{len(scored)}")
print(f"cross-check det : {out['deterministic_summary']}")
print(f"VERDICT         : {out['gate']['verdict']}")
print("=" * 74)

(UT / "_satisfaction_results.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"bukti -> {UT / '_satisfaction_results.json'}")
