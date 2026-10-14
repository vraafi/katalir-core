"""VERIFIKASI PRODUKSI 3 BUG (S2, S5, S9) — 12 Okt 2026.

Membuktikan (bukan mengklaim) perbaikan tiga bug di PRODUKSI:

  S2 — latensi /chat < 30 s (benchmark API N=3, prompt "halo";
       memisahkan total vs meta.latency_ms vs overhead).
  S5 — form kredensial TER-RENDER di /chat saat user minta kirim ke
       Telegram, TANPA menggantikan teks balasan (kartu proaktif).
  S9 — prompt 12.000 karakter: dibatasi di 8.000 oleh frontend (maxLength)
       ATAU ditolak backend dengan pesan yang jelas (422).

Keluaran: tests/user_test/_verify_3bug.json
          docs/evidence/user-test/fix3-*.png
"""
from __future__ import annotations

import json
import os
import pathlib
import time
import urllib.error
import urllib.request

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
UT = ROOT / "tests" / "user_test"
SHOTS = ROOT / "docs" / "evidence" / "user-test"
SHOTS.mkdir(parents=True, exist_ok=True)
FRONTEND = "https://katalir.de5.net"
API = "https://gateway.katalir.de5.net/katalir-api"
SESS = json.loads((UT / "_session.json").read_text(encoding="utf-8"))
TOKEN = SESS["session"]["access_token"]
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

out: dict = {"frontend": FRONTEND, "api": API,
             "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

# ===========================================================================
# S2 — benchmark latensi API (N=3, tanpa browser supaya murni server-side)
# ===========================================================================
print("=" * 74)
print("S2 — BENCHMARK LATENSI /chat (N=3, prompt 'halo', target total < 30 s)")
print("=" * 74)
rows = []
for i in range(3):
    p = "halo" if i == 0 else f"halo (cek latensi {i})"
    body = json.dumps({"prompt": p}).encode()
    req = urllib.request.Request(
        f"{API}/chat", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {TOKEN}",
                 "User-Agent": "Katalir-Fix3Verify/1.0"})
    t0 = time.time()
    try:
        with OPENER.open(req, timeout=280) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        total = round((time.time() - t0) * 1000)
        meta = d.get("meta") or {}
        llm = int(meta.get("latency_ms") or 0)
        row = {"i": i + 1, "total_ms": total, "llm_ms": llm,
               "overhead_ms": max(0, total - llm),
               "model": meta.get("model"), "fallback": meta.get("fallback"),
               "status": d.get("status")}
    except urllib.error.HTTPError as e:
        row = {"i": i + 1, "http_error": e.code, "body": e.read()[:200].decode("utf-8", "replace")}
    rows.append(row)
    print(f"  {row}")
    time.sleep(7)  # pacing: batas rate limit 10 pesan/menit
ok = [r for r in rows if r.get("total_ms", 10**9) < 30000]
out["s2"] = {"rows": rows, "n_pass": len(ok), "n": len(rows),
             "target": "total < 30s",
             "verdict": "PASS" if len(ok) >= 2 else "FAIL"}
print(f"  >>> S2 verdict: {out['s2']['verdict']} ({len(ok)}/{len(rows)} < 30 s)")

# ===========================================================================
# S5 + S9 — browser nyata (Playwright)
# ===========================================================================
from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 1000}, locale="id-ID")
    pg = ctx.new_page()
    pg.goto(f"{FRONTEND}/chat", wait_until="domcontentloaded", timeout=60000)
    pg.evaluate("([k,v]) => { try { localStorage.setItem(k,v); } catch(e){} }",
                [SESS["storage_key"], json.dumps(SESS["session"])])
    pg.reload(wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4000)
    # Tutup onboarding "Selamat datang di Katalir" — modal penuh (z-50)
    # yang MENGINTERSEPSI semua klik; tanpa ini pesan tidak pernah terkirim
    # (penyebab FAIL palsu S5 pada dua run pertama). Skip-nya punya
    # data-testid sendiri; tunggu sampai benar-benar muncul.
    try:
        skip = pg.locator('[data-testid="onboarding-skip"]')
        skip.wait_for(state="visible", timeout=8000)
        skip.click(timeout=5000)
        pg.wait_for_timeout(800)
        print("[onboarding] ditutup via onboarding-skip")
    except Exception:  # noqa: BLE001 - modal tidak muncul, lanjut
        print("[onboarding] tidak muncul (lanjut)")
    for lbl in ("Lewati", "Tutup"):
        try:
            el = pg.get_by_role("button", name=lbl, exact=False)
            if el.count() and el.first.is_visible():
                el.first.click(timeout=3000)
                pg.wait_for_timeout(600)
                break
        except Exception:  # noqa: BLE001
            pass
    ta = pg.locator("textarea").first

    # ------------------------------------------------------------------
    # S9a — ketik/paste 12.000 karakter: harus dibatasi 8.000 (maxLength)
    # ------------------------------------------------------------------
    print("=" * 74)
    print("S9 — BATAS PROMPT (12.000 char -> clamp 8.000 / error jelas)")
    print("=" * 74)
    big = "A" * 12000
    ta.click(timeout=10000)
    ta.fill(big)
    pg.wait_for_timeout(400)
    val_len = pg.evaluate("el => (document.querySelector('textarea')||{}).value?.length || 0")
    out["s9_clamped_len"] = val_len
    if val_len == 8000:
        s9_clamp = "PASS"
    elif val_len > 8000:
        # frontend tidak clamp — coba kirim, backend harus menolak 422 jelas
        ta.press("Enter")
        pg.wait_for_timeout(5000)
        body = pg.inner_text("body")
        s9_clamp = ("PASS_BACKEND" if ("terlalu panjang" in body.lower()
                                       or "8.000" in body or "8,000" in body)
                    else "FAIL")
        pg.screenshot(path=str(SHOTS / "fix3-s9-backend-reject.png"), full_page=True)
    else:
        s9_clamp = f"FAIL(val={val_len})"
    out["s9_clamp_12000"] = s9_clamp
    print(f"  isi 12.000 -> panjang nilai sebenarnya: {val_len} -> {s9_clamp}")

    # S9b — counter: isi ~95% batas -> counter harus terlihat
    ta.fill("B" * 7600)
    pg.wait_for_timeout(400)
    cnt = pg.locator('[data-testid="composer-counter"]')
    out["s9_counter_visible"] = cnt.count() > 0 and cnt.first.is_visible()
    out["s9_counter_text"] = cnt.first.inner_text() if cnt.count() else None
    pg.screenshot(path=str(SHOTS / "fix3-s9-counter.png"), full_page=True)
    print(f"  counter terlihat: {out['s9_counter_visible']} "
          f"(teks: {out['s9_counter_text']!r})")

    # kosongkan sebelum tes S5
    ta.fill("kirim ke telegram saya")
    ta.press("Enter")

    # ------------------------------------------------------------------
    # S5 — kartu kredensial proaktif: teks balasan TETAP ADA + form muncul
    # ------------------------------------------------------------------
    print("=" * 74)
    print("S5 — FORM KREDENSIAL TER-RENDER ('kirim ke telegram saya')")
    print("=" * 74)
    body_before = pg.inner_text("body")
    form = pg.locator('[data-testid^="credential-form-"]').first
    t0 = time.time()
    form_seen = False
    while time.time() - t0 < 100:
        pg.wait_for_timeout(1500)
        if form.count() and form.first.is_visible():
            form_seen = True
            break
    elapsed = round(time.time() - t0, 1)
    body_after = pg.inner_text("body")
    # balasan teks harus lebih panjang dari sebelum balasan (reply terjaga)
    out["s5"] = {
        "form_seen": form_seen,
        "form_testid": form.get_attribute("data-testid") if form_seen else None,
        "wait_s": elapsed,
        "reply_preserved": len(body_after) > len(body_before) + 60,
        "gagal_mengirim": "Gagal mengirim" in body_after,
    }
    out["s5"]["verdict"] = ("PASS" if (form_seen and out["s5"]["reply_preserved"])
                            else ("PARTIAL" if form_seen else "FAIL"))
    pg.screenshot(path=str(SHOTS / "fix3-s5-credential-form.png"), full_page=True)
    print(f"  form terlihat: {form_seen} ({elapsed}s) -> {out['s5']['verdict']}")
    out["body_tail_s5"] = body_after[-600:]
    b.close()

out["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
(UT / "_verify_3bug.json").write_text(json.dumps(out, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
print("=" * 74)
print("RINGKASAN:", json.dumps({k: (v.get('verdict') if isinstance(v, dict) else v)
                              for k, v in out.items() if k.startswith('s')}, indent=1))
print(f"[ok] bukti: {UT / '_verify_3bug.json'}")
