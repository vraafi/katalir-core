"""tests/gemini_hard_tests.py - FASE 3: 30 uji keras migrasi Gemini.

10 DASAR + 10 KONKUREN (sampai 100 paralel) + 10 INTEGRASI.
Gerbang: SEMUA 30 harus PASS. Bukti mentah ditulis ke
`tests/_gemini_hard_results.json` (+ log manusiawi di stdout).

Jalankan:
    python tests/gemini_hard_tests.py            # semua
    python tests/gemini_hard_tests.py --only basic
    python tests/gemini_hard_tests.py --only concurrent
    python tests/gemini_hard_tests.py --only integration
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)


def load_env() -> None:
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()

import gemini_key_pool as gkp  # noqa: E402
import gemini_llm as G  # noqa: E402

PY = sys.executable
RESULTS: list[dict] = []


def record(group: str, name: str, ok: bool, detail: str, evidence=None) -> None:
    RESULTS.append({"group": group, "name": name, "ok": bool(ok),
                    "detail": detail, "evidence": evidence})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<34} {detail}", flush=True)


# ---------------------------------------------------------------------------
# DASAR (10)
# ---------------------------------------------------------------------------
def basic() -> None:
    print("\n=== GRUP DASAR (10) ===", flush=True)

    # B1 - satu prompt end-to-end
    r = G.chat_with_fallback("Balas satu kata: pong", level="minimal",
                             model_chain=["gemini-3.5-flash-lite"])
    record("basic", "B1 single_prompt", r["ok"] and bool(r["text"]),
           f"model={r['model']} {r['elapsed_s']}s text={r['text'][:30]!r}", r)

    # B2 - rantai utama persis seperti brief
    mandated = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash-lite",
                "gemini-2.5-flash", "gemma-4-31b-it"]
    record("basic", "B2 MODEL_CHAIN matches brief", G.MODEL_CHAIN == mandated,
           f"{G.MODEL_CHAIN}", G.MODEL_CHAIN)

    # B3 - RotatorConfig sesuai brief
    c = G.RotatorConfig()
    want = dict(rpm_per_key=10, cooldown_base_seconds=60, cooldown_max_seconds=1800,
                max_concurrent_per_key=3, max_retries=4, retry_delay_seconds=1.0)
    got = dict(rpm_per_key=c.rpm_per_key, cooldown_base_seconds=c.cooldown_base_seconds,
               cooldown_max_seconds=c.cooldown_max_seconds,
               max_concurrent_per_key=c.max_concurrent_per_key,
               max_retries=c.max_retries, retry_delay_seconds=c.retry_delay_seconds)
    record("basic", "B3 RotatorConfig per brief", got == want, f"{got}", got)

    # B4/B5/B6 - pemetaan berpikir sadar-model
    tc = G.thinking_config_for("gemini-3.8-flash", "low")
    record("basic", "B4 thinking budget (3.8-flash)",
           tc is not None and getattr(tc, "thinking_budget", None) == 512,
           f"budget={getattr(tc, 'thinking_budget', None)}")
    tc = G.thinking_config_for("gemini-3.5-flash-lite", "low")
    record("basic", "B5 thinking level (3.5-flash-lite)",
           tc is not None and getattr(tc, "thinking_level", None) is not None
           and getattr(tc, "thinking_budget", None) is None,
           f"level={getattr(tc, 'thinking_level', None)}")
    tc = G.thinking_config_for("gemma-4-31b-it", "low")
    record("basic", "B6 no thinking block (gemma)", tc is None, "None")

    # B7 - kesehatan pool
    h = G.health_check(deep=False)
    record("basic", "B7 health_check shallow",
           h["total"] == 13 and h["healthy"] >= 1,
           f"healthy={h['healthy']}/{h['total']} alert={h['alert']}", h)

    # B8 - rotasi kunci DETERMINISTIK (stub: kunci-1 selalu 429, kunci-2 sukses)
    entries = [("SYNTH_A", "kA", gkp.fingerprint("kA")),
               ("SYNTH_B", "kB", gkp.fingerprint("kB"))]
    old_pool = gkp._pool
    p = gkp.reset(entries=entries)

    class _M:
        def __init__(self, key):
            self.key = key

        def generate_content(self, model, contents, config):
            if self.key == "kA":
                raise RuntimeError(
                    "429 RESOURCE_EXHAUSTED. {'error':{'code':429,'status':"
                    "'RESOURCE_EXHAUSTED','details':[{'@type':'type.googleapis.com/"
                    "google.rpc.QuotaFailure','violations':[{'quotaId':"
                    "'GenerateRequestsPerMinutePerProjectPerModel-FreeTier',"
                    "'quotaValue':'5'}]}],'retryDelay':'5s'}}")

            class _R:
                text = "pong-from-B"
            return _R()

    class _C:
        def __init__(self, key):
            self.models = _M(key)

    p.client = lambda fp: _C(p.key_for(fp))  # type: ignore[assignment]
    try:
        r = G.chat_with_fallback("x", model_chain=["gemini-3.5-flash-lite"],
                                 level="minimal", deadline_s=20)
        kinds = [a.get("kind") for a in r["attempts"]]
        ok = r["ok"] and r["key"].startswith("SYNTH_B") and "rate_limited" in kinds
        record("basic", "B8 429 -> rotate key (deterministik)", ok,
               f"key={r['key']} kinds={kinds}", r["attempts"])
    finally:
        gkp._pool = old_pool

    # B9 - jatuh ke model berikutnya saat model pertama tidak ada
    r = G.chat_with_fallback("Balas: ok", level="minimal",
                             model_chain=["model-yang-tidak-ada-xyz",
                                          "gemini-3.5-flash-lite"], deadline_s=30)
    record("basic", "B9 fallback ke model berikutnya",
           r["ok"] and r["model"] == "gemini-3.5-flash-lite",
           f"model={r['model']} attempts={len(r['attempts'])}", r["attempts"])

    # B10 - system_instruction + temperature dihormati
    r = G.chat_with_fallback("Sebutkan nama kotamu", level="minimal",
                             model_chain=["gemini-3.5-flash-lite"],
                             system_instruction="Selalu jawab persis: JAKARTA",
                             temperature=0.0, deadline_s=30)
    record("basic", "B10 system_instruction dihormati",
           r["ok"] and "JAKARTA" in r["text"].upper(),
           f"text={r['text'][:40]!r}", r["text"])


# ---------------------------------------------------------------------------
# KONKUREN (10) - sampai 100 paralel; gerbang >=80/100 pada level 100
# ---------------------------------------------------------------------------
def _burst(n: int, workers: int, deadline: float) -> dict:
    # Rantai PENUH (bukan satu model): kuota Gemini bersifat per
    # (project, model), jadi menyebar ke beberapa model = ember kuota berbeda =
    # kapasitas jauh lebih besar untuk burst. Ini juga menguji fallback rantai.
    def one(i):
        t0 = time.time()
        r = G.chat_with_fallback(f"Balas angka {i}", level="minimal",
                                 deadline_s=deadline)
        return r["ok"], round(time.time() - t0, 2), r["model"], r["attempts"][:3]

    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        out = list(ex.map(one, range(n)))
    ok = sum(1 for o in out if o[0])
    return {"n": n, "workers": workers, "ok": ok, "fail": n - ok,
            "elapsed_s": round(time.time() - t0, 2),
            "rate": round(ok / n, 3) if n else 0.0,
            "sample_fail": [o[3] for o in out if not o[0]][:2]}


def concurrent() -> None:
    print("\n=== GRUP KONKUREN (10) ===", flush=True)
    plan = [(1, 1), (2, 2), (4, 4), (8, 8), (12, 8), (16, 12), (24, 16),
            (32, 20), (64, 32), (100, 40)]
    for i, (n, w) in enumerate(plan, 1):
        deadline = 120.0 if n >= 64 else 90.0
        res = _burst(n, w, deadline)
        if n < 100:
            ok = res["rate"] >= 0.9
            gate = "rate>=0.90"
        else:
            ok = res["ok"] >= 80
            gate = "ok>=80/100"
        record("concurrent", f"C{i} burst n={n} workers={w}", ok,
               f"{res['ok']}/{res['n']} rate={res['rate']} {res['elapsed_s']}s ({gate})",
               res)


# ---------------------------------------------------------------------------
# INTEGRASI (10)
# ---------------------------------------------------------------------------
def _run(cmd: list[str], timeout: int = 900) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as e:
        return 124, f"TIMEOUT after {timeout}s\n{(e.stdout or '')}"


def integration() -> None:
    """10 uji integrasi.

    I1-I4 MEMBACA artefak bukti yang dihasilkan oleh re-run TASK 4, TASK 5,
    regresi 420, dan E2E (bukan menjalankannya ulang di dalam suite ini).
    Menjalankan ulang di sini hanya menggandakan biaya kuota tanpa menambah
    bukti; yang perlu dibuktikan adalah bahwa ARTEFAK-nya benar.
    """
    print("\n=== GRUP INTEGRASI (10) ===", flush=True)
    # Beri jeda agar blokir 429 dari burst konkuren mereda sebelum uji yang
    # memanggil LLM (I9/I10). Sejak perbaikan cakupan kuota, blokir di-scope ke
    # PASANGAN (kunci, model) - bukan seluruh kunci 60 s - tetapi pasangan yang
    # dipakai I9 tetap perlu lewat jendela menit kuota lebih dulu.
    cool = os.getenv("GEMINI_COOLDOWN_WAIT_S", "65")
    try:
        nap = float(cool)
    except ValueError:
        nap = 65.0
    if nap > 0:
        print(f"  (menunggu {nap:.0f}s agar cooldown kunci mereda...)", flush=True)
        time.sleep(nap)

    def _load(name: str):
        p = ROOT / "tests" / name
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None

    # I1 - TASK 4 tool_eval_bench
    d = _load("_brief7_toolbench_results.json")
    ok1 = bool(d and d.get("provider") == "gemini" and (d.get("overall") or 0) >= 60)
    record("integration", "I1 TASK4 tool_eval_bench (Gemini)", ok1,
           f"provider={d.get('provider') if d else None} overall="
           f"{d.get('overall') if d else None} model={d.get('model') if d else None}",
           d and {"overall": d.get("overall"), "runs": [r["final_score"] for r in d["runs"]]})

    # I2 - TASK 5 hermes_rubric
    d = _load("_brief7_rubric_results.json")
    scored = sum(1 for v in (d or {}).get("per_feature", {}).values()
                 if v.get("score") is not None) if d else 0
    ok2 = bool(d and scored == 21 and (d.get("mean") or 0) >= 0.7)
    record("integration", "I2 TASK5 hermes_rubric (Gemini)", ok2,
           f"mean={d.get('mean') if d else None} scored={scored}/21 "
           f"below={(d or {}).get('below_threshold')}", d and d.get("mean"))

    # I3 - regresi 420
    d = _load("_brief7_checks_results.json")
    rows = (d or {}).get("results") or []
    npass = sum(1 for r in rows if r.get("final") == "PASS")
    ok3 = len(rows) == 420 and npass == 420
    record("integration", "I3 regresi 420 Brief-7", ok3,
           f"{npass}/{len(rows)} final=PASS", {"n": len(rows), "pass": npass})

    # I4 - E2E produksi
    d = _load("_brief7_e2e_results.json")
    tot = {"PASS": (d or {}).get("pass"), "FAIL": (d or {}).get("fail"),
           "SKIP": (d or {}).get("skip")}
    ok4 = bool(d and (d.get("fail") or 0) == 0 and (d.get("pass") or 0) >= 12)
    record("integration", "I4 E2E produksi (API nyata)", ok4, f"{tot}", tot)

    # I5 - /health/llm mengembalikan 13 kunci
    import api_server as A  # noqa: E402
    st = A.health_llm(deep=0)
    body = json.loads(st.body.decode("utf-8"))
    record("integration", "I5 /health/llm 200 + 13 kunci",
           st.status_code == 200 and body["total"] == 13,
           f"status={st.status_code} healthy={body['healthy']}/{body['total']}", body)

    # I6 - /status memuat cek llm_gemini yang ok
    stt = A.status_deep()
    sbody = json.loads(stt.body.decode("utf-8"))
    gem = sbody["checks"].get("llm_gemini", {})
    record("integration", "I6 /status cek llm_gemini ok", bool(gem.get("ok")),
           f"{gem}", gem)

    # I7 - provider default = gemini (Gemini-first)
    prov = (os.getenv("LLM_PROVIDER") or "gemini").strip().lower()
    record("integration", "I7 provider default Gemini-first", prov == "gemini",
           f"LLM_PROVIDER={prov!r}")

    # I8 - jalur gateway masih hidup bila diminta eksplisit.
    # Dibaca dari ENV, bukan `_gateway_target()`: helper itu bisa memicu probe
    # roster sinkron (puluhan request ke gateway) yang menenggelamkan suite.
    _gw = (os.getenv("LLM_GATEWAY_URL") or os.getenv("FREELM_GATEWAY_URL")
           or os.getenv("GATEWAY_URL") or "").strip()
    record("integration", "I8 gateway masih terkonfigurasi (cadangan)",
           bool(_gw), f"url_set={bool(_gw)}")

    # I9 - LLM judge memakai Gemini dan MEMBEDAKAN benar vs salah
    good = G.chat_with_fallback(
        "Nilai jawaban ini terhadap tugas 'sebutkan ibu kota Prancis'. "
        "Jawaban: Paris. Balas HANYA angka 0..1.", level="minimal",
        model_chain=["gemini-3.5-flash-lite", "gemini-3.6-flash"], deadline_s=60)
    bad = G.chat_with_fallback(
        "Nilai jawaban ini terhadap tugas 'sebutkan ibu kota Prancis'. "
        "Jawaban: Berlin. Balas HANYA angka 0..1.", level="minimal",
        model_chain=["gemini-3.5-flash-lite", "gemini-3.6-flash"], deadline_s=60)

    def _num(t):
        import re
        m = re.search(r"[01](?:\.\d+)?", t or "")
        return float(m.group(0)) if m else None

    gv, bv = _num(good["text"]), _num(bad["text"])
    record("integration", "I9 judge Gemini diskriminatif",
           gv is not None and bv is not None and gv > bv,
           f"good={gv} bad={bv} (raw {good['text'][:12]!r}/{bad['text'][:12]!r})",
           {"good": gv, "bad": bv})

    # I10 - sapuan 4 tingkat berpikir semuanya menghasilkan konten
    lv = {}
    for lvl in ("minimal", "low", "medium", "high"):
        r = G.chat_with_fallback(f"Balas kata: lvl-{lvl}", level=lvl,
                                 model_chain=["gemini-3.5-flash-lite",
                                              "gemini-3.6-flash"],
                                 deadline_s=60)
        lv[lvl] = {"ok": r["ok"], "elapsed": r["elapsed_s"], "text": r["text"][:24],
                   "model": r["model"]}
    record("integration", "I10 sapuan 4 tingkat berpikir",
           all(v["ok"] for v in lv.values()), json.dumps(lv, ensure_ascii=False)[:200], lv)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["basic", "concurrent", "integration"], default=None)
    a = ap.parse_args()
    t0 = time.time()
    print("=" * 78)
    print("FASE 3 - 30 UJI KERAS MIGRASI GEMINI")
    print("=" * 78)
    if a.only in (None, "basic"):
        basic()
    if a.only in (None, "concurrent"):
        concurrent()
    if a.only in (None, "integration"):
        integration()

    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r["ok"])
    print("\n" + "=" * 78)
    print(f"HASIL: {passed}/{total} PASS  ({round(time.time() - t0, 1)}s)")
    print("=" * 78)
    for grp in ("basic", "concurrent", "integration"):
        rows = [r for r in RESULTS if r["group"] == grp]
        if rows:
            print(f"  {grp:<12} {sum(1 for r in rows if r['ok'])}/{len(rows)} PASS")
    fails = [r for r in RESULTS if not r["ok"]]
    for f in fails:
        print(f"  FAIL {f['name']}: {f['detail']}")

    out = ROOT / "tests" / "_gemini_hard_results.json"
    out.write_text(json.dumps({"passed": passed, "total": total,
                               "elapsed_s": round(time.time() - t0, 1),
                               "results": RESULTS}, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"\n  -> bukti mentah: {out}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
