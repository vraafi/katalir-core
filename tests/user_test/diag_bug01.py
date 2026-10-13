"""DIAGNOSTIK BUG-01 — instrumentasi batas komponen (systematic-debugging Fase 1.4).

Tujuan: tentukan DI LAPIS MANA alur 8.000 karakter berhenti:
  L1 request dikirim          -> POST terlihat?
  L2 respons diterima         -> status + waktu
  L3 body respons dibaca      -> apakah res.json() selesai? (hipotesis utama)
  L4 state React diperbarui   -> bubble asisten muncul?
  L5 render                   -> teks berubah?

Hipotesis yang diuji (falsifiable):
  H1 perAttemptMs (55s) mematikan fetch -> akan terlihat requestfailed
     "net::ERR_ABORTED" + retry (POST ke-2/ke-3).
  H2 Respons tiba (200) tetapi pembacaan body menggantung -> requestfinished
     TIDAK pernah muncul walaupun respons headers sudah diterima.
  H3 Respons lengkap diterima tetapi render gagal -> body diterima, tetapi DOM
     tidak berubah dan ada error React di console.
  H4 Tidak spesifik panjang: panjang lain juga gagal.

Keluaran: tests/user_test/_diag_bug01.json
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

from rus_core import (COMPOSER, MSGLIST, dismiss_onboarding, goto, login, new_ctx, proxy_backend, shot)  # noqa: E402

PANJANG = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
DURASI = float(sys.argv[2]) if len(sys.argv) > 2 else 200.0

ev: list[dict] = []
out: dict = {"panjang": PANJANG, "durasi": DURASI, "events": ev, "dom": []}

# T0 HARUS ada sebelum handler jaringan/console dipasang: halaman bisa
# memunculkan event sebelum kita sempat menetapkannya (NameError).
T0 = time.time()


def log(kind, **kw):
    row = {"t": round(time.time() - T0, 2), "kind": kind, **kw}
    ev.append(row)
    print(f"  [{row['t']:7.2f}] {kind}: {json.dumps(kw, ensure_ascii=False)[:220]}",
          flush=True)


with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = new_ctx(b)
    # Server lokal (127.0.0.1) ditolak CORS oleh backend produksi -> semua
    # request gagal dan pengujian jadi tidak bermakna. Proksikan lewat Python.
    if "127.0.0.1" in (os.environ.get("RUS_FRONTEND") or ""):
        proxy_backend(ctx, on_call=lambda m, p: log("BACKEND_CALL", m=m, p=p[:80]))
        print("  [info] proksi backend aktif (CORS dilewati untuk uji lokal)",
              flush=True)
    pg = ctx.new_page()

    # ── instrumentasi jaringan (L1–L3) ──────────────────────────────────────
    def _is_chat_post(url: str, method: str) -> bool:
        return "/chat" in url and method == "POST"

    def _on_response(r):
        """Simpan body respons /chat APA ADANYA — inilah `data` yang diparse UI."""
        try:
            if _is_chat_post(r.url, r.request.method):
                log("RES_HEADERS", status=r.status, u=r.url[-60:])
                body = r.text()
                out["body_chat"] = body
                out["body_chat_status"] = r.status
                try:
                    j = json.loads(body)
                    out["body_chat_parsed"] = {
                        "status": j.get("status"),
                        "reply_len": len(j.get("reply") or ""),
                        "reply_head": (j.get("reply") or "")[:120],
                        "session_id": j.get("session_id"),
                        "has_credential_prompt": bool(j.get("credential_prompt")),
                        "meta_keys": sorted((j.get("meta") or {}).keys()),
                        "top_keys": sorted(j.keys()),
                    }
                    log("RES_BODY", **out["body_chat_parsed"])
                except Exception as exc:  # noqa: BLE001
                    log("RES_BODY_NOT_JSON", err=str(exc)[:120], head=body[:200])
            elif "/messages/" in r.url and r.request.method == "GET":
                b = r.text()
                out["body_messages"] = b[:4000]
                log("GET_MESSAGES", status=r.status, len=len(b), head=b[:160])
        except Exception as exc:  # noqa: BLE001
            log("RESP_HANDLER_ERR", err=str(exc)[:160])

    pg.on("request", lambda r: log("REQ", m=r.method, u=r.url[-60:])
          if _is_chat_post(r.url, r.method) else None)
    pg.on("response", _on_response)
    pg.on("requestfinished",
          lambda r: log("REQ_FINISHED", u=r.url[-60:])
          if _is_chat_post(r.url, r.method) else None)
    pg.on("requestfailed",
          lambda r: log("REQ_FAILED", err=r.failure, u=r.url[-60:])
          if "/chat" in r.url else None)
    pg.on("console", lambda m: log("CONSOLE", type=m.type, text=m.text[:300]))
    pg.on("pageerror", lambda e: log("PAGEERROR", text=str(e)[:400]))

    login(pg)
    goto(pg, "/chat", ms=3000)
    dismiss_onboarding(pg)
    # Pastikan composer benar-benar siap sebelum mengetik (server lokal kadang
    # lambat; tanpa ini Enter bisa tidak mengirim apa pun -> run tidak bermakna).
    pg.wait_for_selector(COMPOSER, timeout=30000)
    pg.wait_for_timeout(1500)

    ta = pg.locator(COMPOSER).first
    ta.click(timeout=15000)
    ta.fill("")
    ta.fill("a" * PANJANG)
    out["panjang_efektif"] = len(ta.input_value())

    T0 = time.time()
    log("SEND", panjang=out["panjang_efektif"])
    ta.press("Enter")

    shot_done = set()
    while time.time() - T0 < DURASI:
        pg.wait_for_timeout(2000)
        el = round(time.time() - T0, 1)
        snap = pg.evaluate("""() => {
          const l = document.querySelector('[data-testid="msg-list"]');
          const t = l ? l.innerText : '';
          const anak = l ? [...l.children].map(c => ({
            tag: c.tagName.toLowerCase(),
            testid: c.getAttribute('data-testid') || '',
            cls: (c.className || '').toString().slice(0, 70),
            n: (c.innerText || '').length,
            ekor: (c.innerText || '').slice(-40),
            html_len: (c.innerHTML || '').length,
            ada_halo: (c.innerHTML || '').includes('Halo'),
            ada_typing: (c.innerHTML || '').includes('animate-bounce')
              || (c.innerHTML || '').includes('TypingDots'),
            anak_elemen: [...c.children].map(x => ({
              cls: (x.className || '').toString().slice(0, 40),
              n: (x.innerText || '').length,
            })),
          })) : [];
          const sc = (() => {
            let s = l && l.parentElement;
            while (s && s !== document.body) {
              const st = getComputedStyle(s);
              if (/(auto|scroll)/.test(st.overflowY) && s.scrollHeight > s.clientHeight) return s;
              s = s.parentElement;
            }
            return null;
          })();
          return {
            len: t.length,
            url: location.pathname + location.search,
            scrollTop: sc ? sc.scrollTop : null,
            scrollHeight: sc ? sc.scrollHeight : null,
            clientHeight: sc ? sc.clientHeight : null,
            di_dasar: sc ? (sc.scrollHeight - sc.scrollTop - sc.clientHeight) < 40 : null,
            ada_area_chat: !!l,
            ada_sedang_memproses: t.toLowerCase().includes('sedang memproses'),
            ada_berpikir: t.toLowerCase().includes('berpikir'),
            ada_error_card: !!document.querySelector('[data-testid="error-card"]'),
            ada_coba_lagi: t.includes('Coba Lagi'),
            jumlah_bubble_anak: l ? l.children.length : -1,
            anak,
            teks_ekor: t.slice(-90),
            cache: (typeof window.__katalirCache === 'function')
              ? window.__katalirCache() : null,
          };
        }""")
        out["dom"].append({"t": el, **snap})
        print(f"  [{el:7.2f}] len={snap['len']:6} anak={snap['jumlah_bubble_anak']:3} "
              f"url={snap['url'][:34]:34} err={snap['ada_error_card']}", flush=True)
        for c in snap["anak"]:
            print(f"          anak: tag={c['tag']:8} testid={c['testid']:18} "
                  f"n={c['n']:6} cls={c['cls'][:40]!r}", flush=True)
        if snap.get("cache"):
            for k, v in snap["cache"].items():
                if "messages" in k:
                    print(f"          CACHE {k:58} -> {json.dumps(v, ensure_ascii=False)[:220]}",
                          flush=True)
        for s in (10, 60, 150):
            if s not in shot_done and el >= s:
                shot(pg, f"diag-bug01-{PANJANG}-t{s}s")
                shot_done.add(s)
        if snap["ada_error_card"] or snap["ada_coba_lagi"]:
            log("ERROR_CARD_MUNCUL", t=el)
            break

    shot(pg, f"diag-bug01-{PANJANG}-akhir")

    # ── UJI PEMICU RE-RENDER ────────────────────────────────────────────────
    # Cache sudah benar (balasan ada) tetapi DOM beku. Kalau re-render yang
    # dipaksa memunculkan balasan, berarti masalahnya BUKAN pipeline render
    # melainkan TIDAK ADA yang memicu render ulang setelah cache berubah.
    sebelum = pg.evaluate(
        "() => { const l=document.querySelector('[data-testid=\"msg-list\"]');"
        " return l ? l.innerText.length : -1; }")
    pg.evaluate("""() => {
      const l = document.querySelector('[data-testid="msg-list"]');
      const sc = l && (l.parentElement || l);
      if (sc) sc.scrollTop = sc.scrollTop + 2;
      window.dispatchEvent(new Event('resize'));
    }""")
    pg.wait_for_timeout(2500)
    sesudah = pg.evaluate(
        "() => { const l=document.querySelector('[data-testid=\"msg-list\"]');"
        " return l ? l.innerText.length : -1; }")
    # ── UJI GULIR: apakah balasan ADA tapi hanya di luar layar? ─────────────
    info = pg.evaluate("""() => {
      const l = document.querySelector('[data-testid="msg-list"]');
      let sc = l && l.parentElement;
      while (sc && sc !== document.body) {
        const st = getComputedStyle(sc);
        if (/(auto|scroll)/.test(st.overflowY) && sc.scrollHeight > sc.clientHeight) break;
        sc = sc.parentElement;
      }
      const cv = l ? getComputedStyle(l).contentVisibility : null;
      return {
        ada_wadah_gulir: !!sc,
        scrollTop: sc ? sc.scrollTop : null,
        scrollHeight: sc ? sc.scrollHeight : null,
        clientHeight: sc ? sc.clientHeight : null,
        di_dasar: sc ? (sc.scrollHeight - sc.scrollTop - sc.clientHeight) < 40 : null,
        content_visibility_msglist: cv,
      };
    }""")
    out["gulir_sebelum"] = info
    pg.evaluate("""() => {
      const l = document.querySelector('[data-testid="msg-list"]');
      let sc = l && l.parentElement;
      while (sc && sc !== document.body) {
        const st = getComputedStyle(sc);
        if (/(auto|scroll)/.test(st.overflowY) && sc.scrollHeight > sc.clientHeight) break;
        sc = sc.parentElement;
      }
      if (sc) sc.scrollTop = sc.scrollHeight;
    }""")
    pg.wait_for_timeout(2500)
    sesudah_gulir = pg.evaluate(
        "() => { const l=document.querySelector('[data-testid=\"msg-list\"]');"
        " return l ? l.innerText.length : -1; }")
    out["uji_rerender"] = {"sebelum": sebelum, "sesudah": sesudah,
                           "gulir_sebelum": info,
                           "panjang_setelah_digulir": sesudah_gulir,
                           "balasan_muncul_setelah_digulir": sesudah_gulir > sebelum + 20}
    print(f"\n  GULIR: wadah={info.get('ada_wadah_gulir')} "
          f"di_dasar={info.get('di_dasar')} scrollTop={info.get('scrollTop')}/"
          f"{info.get('scrollHeight')} content-visibility={info.get('content_visibility_msglist')}",
          flush=True)
    print(f"  panjang sebelum={sebelum} setelah gulir={sesudah_gulir} "
          f"-> {'BALASAN ADA (hanya di luar layar)' if sesudah_gulir > sebelum + 20 else 'tetap kosong'}",
          flush=True)
    shot(pg, f"diag-bug01-{PANJANG}-setelah-gulir")
    out["console"] = [e for e in ev if e["kind"] in ("CONSOLE", "PAGEERROR")]
    out["jaringan"] = [e for e in ev if e["kind"].startswith("REQ")]
    out["ringkas"] = {
        "jumlah_POST": sum(1 for e in ev if e["kind"] == "REQ"),
        "jumlah_respons": sum(1 for e in ev if e["kind"] == "RES_HEADERS"),
        "jumlah_requestfinished": sum(1 for e in ev if e["kind"] == "REQ_FINISHED"),
        "jumlah_requestfailed": sum(1 for e in ev if e["kind"] == "REQ_FAILED"),
        "panjang_dom_akhir": out["dom"][-1]["len"] if out["dom"] else None,
        "error_card_pernah_muncul": any(d["ada_error_card"] for d in out["dom"]),
    }
    print("\nRINGKASAN:", json.dumps(out["ringkas"], ensure_ascii=False, indent=1), flush=True)

    (HERE / f"_diag_bug01_{PANJANG}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"bukti -> {HERE / f'_diag_bug01_{PANJANG}.json'}", flush=True)
    ctx.close()
    b.close()
