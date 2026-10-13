"""Reproduksi terarah P5-02: prompt 8000 karakter (batas maksimum backend).

Pertanyaan yang harus dijawab: apakah aplikasi MENGGANTUNG (tidak pernah
membalas) atau hanya LAMBAT? `send_measured` punya batas waktu, sehingga
"belum membalas dalam jendela ukur" tidak boleh langsung disebut bug.

Metode: kirim tepat 8000 karakter, lalu pantau tiap 1 detik selama maksimum
150 detik. Catat:
  - panjang teks di dalam [data-testid="msg-list"]
  - apakah penanda sibuk ("Agen sedang berpikir" / "Sedang memproses") terlihat
  - apakah footer balasan (`→ N tok`) sudah muncul
  - apakah kartu galat muncul
Screenshot diambil pada detik ke-5, 20, 45, dan pada akhir pengamatan.

Keluaran: tests/user_test/_rus_repro_long.json
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "D:/caches/playwright")
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from playwright.sync_api import sync_playwright  # noqa: E402

from rus_core import (COMPOSER, MSGLIST, Probe, dismiss_onboarding,  # noqa: E402
                      goto, login, msg_text, new_ctx, shot,
                      assistant_replies, visible_error_card)

N = 8000
PROMPT = ("tolong ringkas teks berikut menjadi satu kalimat. " + "a" * N)[:N]

timeline: list[dict] = []
out: dict = {"n_karakter": N, "timeline": timeline}

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = new_ctx(b)
    pg = ctx.new_page()
    pr = Probe(pg, "long")
    login(pg)
    goto(pg, "/chat", ms=3000)
    dismiss_onboarding(pg)

    ta = pg.locator(COMPOSER).first
    ta.click(timeout=15000)
    ta.fill("")
    ta.fill(PROMPT)
    eff = len(ta.input_value())
    out["panjang_efektif"] = eff
    print(f"panjang efektif di composer: {eff}", flush=True)

    base_replies = assistant_replies(pg)
    t0 = time.time()
    ta.press("Enter")

    shot_at = {5, 20, 45}
    shot_done: set[int] = set()
    replied_at = None
    status = "timeout"
    while time.time() - t0 < 150:
        pg.wait_for_timeout(1000)
        el = time.time() - t0
        body = msg_text(pg)
        low = body.lower()
        busy = any(w in low for w in ("agen sedang berpikir", "sedang memproses",
                                      "sedang berpikir"))
        rep = assistant_replies(pg)
        err = visible_error_card(pg)
        row = {"t": round(el, 1), "len": len(body), "replies": rep,
               "busy": busy, "error_card": err}
        timeline.append(row)
        print(f"  t={row['t']:6.1f}s  len={row['len']:5}  replies={rep}  "
              f"busy={busy}  err={err}", flush=True)
        for s in shot_at:
            if s not in shot_done and el >= s:
                shot(pg, f"repro-long-t{s}s")
                shot_done.add(s)
        if rep > base_replies:
            replied_at = round(el, 1)
            status = "replied"
            break
        if err:
            status = "error"
            break

    shot(pg, "repro-long-akhir")
    out["status"] = status
    out["replied_pada_detik"] = replied_at
    out["panjang_teks_akhir"] = len(msg_text(pg))
    out["reply_tail"] = msg_text(pg)[-400:]
    out["console_errors"] = pr.errs()[:8]
    out["failed_requests"] = pr.netfail[:8]
    out["jumlah_POST_chat"] = len(pr.chat_posts)
    print(f"\nHASIL: status={status} replied_pada={replied_at}s "
          f"POST_chat={len(pr.chat_posts)}", flush=True)

    (HERE / "_rus_repro_long.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"bukti -> {HERE / '_rus_repro_long.json'}", flush=True)
    ctx.close()
    b.close()
