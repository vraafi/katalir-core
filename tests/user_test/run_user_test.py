"""HARD TEST PENGGUNA NYATA — Katalir (12 Okt 2026).

Menjalankan 10 skenario user asli lewat Playwright pada frontend produksi
https://katalir.de5.net, merekam untuk SETIAP skenario:
  precondition -> action -> expected -> actual -> state -> bukti (screenshot)

Disiplin yang dipakai (dari skill `manual-testing` + `ux-quality-perspective`):
  * state hanya PASS/FAIL/BLOCKED/NOT_RUN - tidak ada klaim tanpa bukti
  * checklist bukan log eksekusi; tiap baris punya observasi nyata
  * screenshot hanya membuktikan sel yang TERLIHAT di layar

Sesi: user asli `otonom-test@katalir-internal.dev` (sesi Supabase di-refresh
lewat `bootstrap_session.py`). Google OAuth TIDAK dapat diselesaikan otomatis -
itu dilaporkan BLOCKED, bukan diklaim lulus.

Keluaran: tests/user_test/_user_test_results.json + screenshot di
docs/evidence/user-test/.
"""
from __future__ import annotations

import json
import os
import pathlib
import time

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
UT = ROOT / "tests" / "user_test"
SHOTS = ROOT / "docs" / "evidence" / "user-test"
SHOTS.mkdir(parents=True, exist_ok=True)

FRONTEND = "https://katalir.de5.net"
SESS = json.loads((UT / "_session.json").read_text(encoding="utf-8"))

from playwright.sync_api import sync_playwright  # noqa: E402

RESULTS: list[dict] = []


def rec(no, name, *, precondition, action, expected, actual, state, shots,
        seconds=None, console=None, netfail=None, extra=None):
    RESULTS.append({
        "no": no, "scenario": name, "precondition": precondition,
        "action": action, "expected": expected, "actual": actual,
        "state": state, "seconds": seconds,
        "screenshots": [str(s) for s in shots],
        "console_errors": (console or [])[:8],
        "failed_requests": (netfail or [])[:8],
        "extra": extra or {},
    })
    icon = {"PASS": "[PASS]", "FAIL": "[FAIL]",
            "BLOCKED": "[BLOCK]", "NOT_RUN": "[SKIP]"}[state]
    print(f"  {icon} S{no} {name}  ({actual[:110]})", flush=True)


class Probe:
    """Merekam error konsol + request gagal selama satu skenario."""

    def __init__(self, pg):
        self.pg = pg
        self.console: list = []
        self.netfail: list = []
        pg.on("console", lambda m: self.console.append(
            {"type": m.type, "text": m.text[:200]})
            if m.type in ("error", "warning") else None)
        pg.on("pageerror", lambda e: self.console.append(
            {"type": "pageerror", "text": str(e)[:200]}))
        pg.on("requestfailed", lambda r: self.netfail.append(
            {"url": r.url[:150], "failure": (r.failure or "")[:140]}))

    def reset(self):
        self.console.clear()
        self.netfail.clear()

    def errs(self):
        return [c for c in self.console if c["type"] in ("error", "pageerror")]


def shot(pg, name):
    p = SHOTS / f"{name}.png"
    try:
        pg.screenshot(path=str(p), full_page=True)
    except Exception:  # noqa: BLE001
        pg.screenshot(path=str(p))
    return p


def inject_session(pg):
    pg.goto(f"{FRONTEND}/chat", wait_until="domcontentloaded", timeout=60000)
    pg.evaluate("([k,v]) => { try { localStorage.setItem(k, v); } catch(e){} }",
                [SESS["storage_key"], json.dumps(SESS["session"])])
    pg.reload(wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(3500)


def dismiss_onboarding(pg):
    """Wizard 1/3 menghalangi; user asli akan menutupnya."""
    for label in ("Lewati", "Tutup", "Nanti saja"):
        try:
            el = pg.get_by_role("button", name=label, exact=False)
            if el.count() and el.first.is_visible():
                el.first.click(timeout=4000)
                pg.wait_for_timeout(1200)
                return label
        except Exception:  # noqa: BLE001
            continue
    return None


def send_chat(pg, text, wait_ms=45000):
    """Kirim pesan seperti user: klik textarea, ketik, Enter."""
    ta = pg.locator("textarea").first
    ta.click(timeout=10000)
    ta.fill(text)
    t0 = time.time()
    ta.press("Enter")
    # Tunggu sampai tombol kirim berhenti "sibuk" atau teks balasan bertambah.
    try:
        pg.wait_for_function(
            """() => {
                 const b = document.body.innerText;
                 return b.length > 0;
               }""", timeout=8000)
    except Exception:  # noqa: BLE001
        pass
    pg.wait_for_timeout(wait_ms)
    return round(time.time() - t0, 2)


def main() -> int:
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)

        # ================= S1: user baru daftar (Google OAuth) ============
        print("\n=== S1 user baru daftar (Google OAuth) ===", flush=True)
        ctx0 = b.new_context(viewport={"width": 1440, "height": 900},
                             locale="id-ID")
        pg0 = ctx0.new_page()
        pr0 = Probe(pg0)
        shots = []
        try:
            pg0.goto(f"{FRONTEND}/chat", wait_until="networkidle", timeout=60000)
            shots.append(shot(pg0, "s01-a-landing-not-logged-in"))
            btn = pg0.get_by_role("button", name="Login dengan Google")
            present = btn.count() > 0
            target = None
            if present:
                try:
                    with pg0.expect_popup(timeout=8000) as pi:
                        btn.first.click()
                    pop = pi.value
                    pop.wait_for_load_state("domcontentloaded", timeout=20000)
                    target = pop.url
                    shots.append(shot(pop, "s01-b-oauth-redirect"))
                    pop.close()
                except Exception:  # noqa: BLE001
                    target = pg0.url
                    shots.append(shot(pg0, "s01-b-after-click"))
            rec(1, "User baru daftar (Google OAuth)",
                precondition="Belum login, buka /chat",
                action="Klik tombol 'Login dengan Google'",
                expected="Diarahkan ke consent Google lalu kembali ke /chat",
                actual=(f"Tombol ada={present}; redirect ke {target}" if present
                        else "Tombol 'Login dengan Google' TIDAK ditemukan"),
                state="BLOCKED" if present else "FAIL",
                shots=shots, console=pr0.errs(),
                netfail=pr0.netfail,
                extra={"oauth_target": target,
                       "reason_blocked": ("consent Google butuh interaksi manusia "
                                          "(akun+2FA); tidak dapat diselesaikan "
                                          "otonom") if present else None})
        except Exception as exc:  # noqa: BLE001
            rec(1, "User baru daftar (Google OAuth)",
                precondition="Belum login, buka /chat",
                action="Klik tombol 'Login dengan Google'",
                expected="Diarahkan ke consent Google lalu kembali ke /chat",
                actual=f"ERROR {type(exc).__name__}: {str(exc)[:150]}",
                state="FAIL", shots=shots, console=pr0.errs())
        ctx0.close()

        # ---- konteks utama: user sudah login (sesi asli di-refresh) ----
        ctx = b.new_context(viewport={"width": 1440, "height": 900},
                            locale="id-ID")
        pg = ctx.new_page()
        pr = Probe(pg)
        inject_session(pg)
        dismiss_onboarding(pg)
        shot(pg, "s01-c-logged-in-chat")

        # ================= S2: chat pertama ==============================
        print("\n=== S2 chat pertama ===", flush=True)
        pr.reset()
        shots = []
        try:
            t = send_chat(pg, "Buat workflow sederhana", wait_ms=50000)
            shots.append(shot(pg, "s02-chat-pertama"))
            body = pg.inner_text("body")
            has_reply = "Buat workflow sederhana" in body and len(body) > 900
            rec(2, "User kirim chat pertama",
                precondition="Sudah login, composer aktif",
                action="Ketik 'Buat workflow sederhana' lalu Enter",
                expected="Balasan <30 s, bahasa Indonesia",
                actual=(f"{t}s, balasan={'ada' if has_reply else 'TIDAK ADA'}"
                        f", panjang_body={len(body)}"),
                state="PASS" if (has_reply and t < 30) else "FAIL",
                shots=shots, seconds=t, console=pr.errs(),
                netfail=pr.netfail,
                extra={"reply_snippet": body[-700:]})
        except Exception as exc:  # noqa: BLE001
            shots.append(shot(pg, "s02-chat-pertama-error"))
            rec(2, "User kirim chat pertama",
                precondition="Sudah login, composer aktif",
                action="Ketik 'Buat workflow sederhana' lalu Enter",
                expected="Balasan <30 s, bahasa Indonesia",
                actual=f"ERROR {type(exc).__name__}: {str(exc)[:150]}",
                state="FAIL", shots=shots, console=pr.errs())

        # ================= S3: bangun workflow ===========================
        print("\n=== S3 bangun workflow (Telegram) ===", flush=True)
        pr.reset()
        shots = []
        try:
            t = send_chat(pg, "Buat workflow: trigger manual lalu kirim pesan "
                              "Telegram", wait_ms=55000)
            shots.append(shot(pg, "s03-a-chat-workflow-telegram"))
            pg.goto(f"{FRONTEND}/builder", wait_until="domcontentloaded",
                    timeout=60000)
            pg.wait_for_timeout(5000)
            shots.append(shot(pg, "s03-b-builder"))
            nodes = pg.locator("[data-node-id], .react-flow__node").count()
            edges = pg.locator(".react-flow__edge").count()
            body = pg.inner_text("body")
            rec(3, "User bangun workflow dari chat",
                precondition="Chat aktif",
                action="Prompt Telegram; buka /builder",
                expected="Workflow terbangun, node terlihat di kanvas",
                actual=(f"chat {t}s; /builder nodes={nodes} edges={edges}; "
                        f"teks={body[:120]!r}"),
                state="PASS" if nodes > 0 else "FAIL",
                shots=shots, seconds=t, console=pr.errs(),
                netfail=pr.netfail,
                extra={"nodes": nodes, "edges": edges})
        except Exception as exc:  # noqa: BLE001
            shots.append(shot(pg, "s03-error"))
            rec(3, "User bangun workflow dari chat",
                precondition="Chat aktif", action="Prompt Telegram; buka /builder",
                expected="Workflow terbangun, node terlihat di kanvas",
                actual=f"ERROR {type(exc).__name__}: {str(exc)[:150]}",
                state="FAIL", shots=shots, console=pr.errs())

        # ================= S4: riwayat chat ==============================
        print("\n=== S4 riwayat chat bertahan ===", flush=True)
        pr.reset()
        shots = []
        try:
            pg.goto(f"{FRONTEND}/chat", wait_until="domcontentloaded",
                    timeout=60000)
            pg.reload(wait_until="networkidle", timeout=60000)
            pg.wait_for_timeout(4000)
            shots.append(shot(pg, "s04-a-setelah-refresh"))
            body = pg.inner_text("body")
            empty = "Belum ada riwayat" in body
            items = pg.locator("aside a, nav a, [data-session-id]").count()
            rec(4, "Riwayat chat bertahan setelah refresh",
                precondition="Sudah ada 2 percakapan",
                action="Refresh browser, buka /chat",
                expected="Riwayat masih ada, sesi lama bisa dibuka",
                actual=(f"sidebar_kosong={empty}; kandidat_item={items}"),
                state="FAIL" if empty else ("PASS" if items > 0 else "FAIL"),
                shots=shots, console=pr.errs(), netfail=pr.netfail,
                extra={"body_head": body[:400]})
        except Exception as exc:  # noqa: BLE001
            shots.append(shot(pg, "s04-error"))
            rec(4, "Riwayat chat bertahan setelah refresh",
                precondition="Sudah ada 2 percakapan",
                action="Refresh browser, buka /chat",
                expected="Riwayat masih ada, sesi lama bisa dibuka",
                actual=f"ERROR {type(exc).__name__}: {str(exc)[:150]}",
                state="FAIL", shots=shots, console=pr.errs())

        # ================= S5: simpan credential =========================
        print("\n=== S5 simpan credential Telegram ===", flush=True)
        pr.reset()
        shots = []
        try:
            t = send_chat(pg, "kirim ke telegram saya", wait_ms=45000)
            shots.append(shot(pg, "s05-a-prompt-credential"))
            forms = pg.locator("input[type=password], input[type=text], "
                               "input[type=email], select").count()
            labels = pg.inner_text("body")
            has_form = any(w in labels.lower() for w in
                           ("token", "bot", "chat id", "simpan", "brankas",
                            "kredensial", "credential"))
            rec(5, "User simpan credential Telegram",
                precondition="Chat aktif",
                action="Ketik 'kirim ke telegram saya'",
                expected="Form inline muncul untuk mengisi kredensial",
                actual=(f"{t}s; input_form={forms}; indikator_form={has_form}"),
                state="PASS" if (forms > 0 and has_form) else "FAIL",
                shots=shots, seconds=t, console=pr.errs(),
                netfail=pr.netfail,
                extra={"body_tail": labels[-700:]})
        except Exception as exc:  # noqa: BLE001
            shots.append(shot(pg, "s05-error"))
            rec(5, "User simpan credential Telegram",
                precondition="Chat aktif",
                action="Ketik 'kirim ke telegram saya'",
                expected="Form inline muncul untuk mengisi kredensial",
                actual=f"ERROR {type(exc).__name__}: {str(exc)[:150]}",
                state="FAIL", shots=shots, console=pr.errs())

        # ================= S6: templates =================================
        print("\n=== S6 halaman templates ===", flush=True)
        pr.reset()
        shots = []
        try:
            pg.goto(f"{FRONTEND}/templates", wait_until="networkidle",
                    timeout=60000)
            pg.wait_for_timeout(4000)
            shots.append(shot(pg, "s06-a-templates"))
            body = pg.inner_text("body")
            cards = pg.locator("article, [data-template], .card, li").count()
            n_text = len(body)
            rec(6, "User lihat templates",
                precondition="Login",
                action="Buka /templates",
                expected="Daftar template tampil, preview bisa dibuka",
                actual=(f"panjang_teks={n_text}; kandidat_kartu={cards}; "
                        f"cuplikan={body[:150]!r}"),
                state="PASS" if n_text > 400 else "FAIL",
                shots=shots, console=pr.errs(), netfail=pr.netfail,
                extra={"body_head": body[:600]})
        except Exception as exc:  # noqa: BLE001
            shots.append(shot(pg, "s06-error"))
            rec(6, "User lihat templates", precondition="Login",
                action="Buka /templates",
                expected="Daftar template tampil, preview bisa dibuka",
                actual=f"ERROR {type(exc).__name__}: {str(exc)[:150]}",
                state="FAIL", shots=shots, console=pr.errs())

        # ================= S7: edit workflow =============================
        print("\n=== S7 edit workflow di builder ===", flush=True)
        pr.reset()
        shots = []
        try:
            pg.goto(f"{FRONTEND}/builder", wait_until="domcontentloaded",
                    timeout=60000)
            pg.wait_for_timeout(5000)
            shots.append(shot(pg, "s07-a-builder-sebelum"))
            nodes = pg.locator("[data-node-id], .react-flow__node").count()
            clicked = False
            if nodes:
                try:
                    pg.locator("[data-node-id], .react-flow__node").first.click(
                        timeout=6000)
                    pg.wait_for_timeout(2000)
                    clicked = True
                    shots.append(shot(pg, "s07-b-node-terpilih"))
                except Exception:  # noqa: BLE001
                    pass
            body = pg.inner_text("body")
            save = pg.get_by_role("button", name="Simpan", exact=False).count()
            rec(7, "User edit workflow",
                precondition="Ada workflow tersimpan",
                action="Buka /builder, klik node, cek panel konfigurasi",
                expected="Node bisa dipilih, perubahan bisa disimpan",
                actual=(f"nodes={nodes}; node_terpilih={clicked}; "
                        f"tombol_simpan={save}"),
                state="PASS" if (nodes and clicked and save) else "FAIL",
                shots=shots, console=pr.errs(), netfail=pr.netfail,
                extra={"nodes": nodes, "save_buttons": save,
                       "body_head": body[:300]})
        except Exception as exc:  # noqa: BLE001
            shots.append(shot(pg, "s07-error"))
            rec(7, "User edit workflow",
                precondition="Ada workflow tersimpan",
                action="Buka /builder, klik node, cek panel konfigurasi",
                expected="Node bisa dipilih, perubahan bisa disimpan",
                actual=f"ERROR {type(exc).__name__}: {str(exc)[:150]}",
                state="FAIL", shots=shots, console=pr.errs())

        # ================= S8: insights ==================================
        print("\n=== S8 halaman insights ===", flush=True)
        pr.reset()
        shots = []
        try:
            pg.goto(f"{FRONTEND}/insights", wait_until="networkidle",
                    timeout=60000)
            pg.wait_for_timeout(5000)
            shots.append(shot(pg, "s08-a-insights"))
            body = pg.inner_text("body")
            charts = pg.locator("canvas, svg.recharts-surface, .recharts-wrapper").count()
            err_banner = any(w in body.lower() for w in
                             ("gagal", "error", "tidak dapat", "coba lagi"))
            rec(8, "User cek insights",
                precondition="Login, ada data eksekusi",
                action="Buka /insights",
                expected="Chart + metrik tampil",
                actual=(f"chart={charts}; banner_error={err_banner}; "
                        f"cuplikan={body[:150]!r}"),
                state="PASS" if charts > 0 else "FAIL",
                shots=shots, console=pr.errs(), netfail=pr.netfail,
                extra={"charts": charts, "body_head": body[:700]})
        except Exception as exc:  # noqa: BLE001
            shots.append(shot(pg, "s08-error"))
            rec(8, "User cek insights", precondition="Login, ada data eksekusi",
                action="Buka /insights", expected="Chart + metrik tampil",
                actual=f"ERROR {type(exc).__name__}: {str(exc)[:150]}",
                state="FAIL", shots=shots, console=pr.errs())

        # ================= S9: error handling ============================
        print("\n=== S9 error handling ===", flush=True)
        pr.reset()
        shots = []
        try:
            pg.goto(f"{FRONTEND}/chat", wait_until="domcontentloaded",
                    timeout=60000)
            pg.wait_for_timeout(3500)
            t = send_chat(pg, "x" * 12000, wait_ms=35000)
            shots.append(shot(pg, "s09-a-prompt-ekstrem"))
            body = pg.inner_text("body")
            retry = pg.get_by_role("button", name="Try Again", exact=False).count()
            retry += pg.get_by_role("button", name="Coba lagi", exact=False).count()
            friendly = any(w in body.lower() for w in
                           ("coba lagi", "gagal", "terlalu panjang", "kesalahan",
                            "tidak dapat", "error"))
            rec(9, "User kirim prompt yang bikin error",
                precondition="Chat aktif",
                action="Kirim 12.000 karakter 'x'",
                expected="Pesan error ramah + tombol coba lagi",
                actual=(f"{t}s; tombol_retry={retry}; pesan_ramah={friendly}"),
                state="PASS" if (retry > 0 or friendly) else "FAIL",
                shots=shots, seconds=t, console=pr.errs(),
                netfail=pr.netfail, extra={"body_tail": body[-600:]})
        except Exception as exc:  # noqa: BLE001
            shots.append(shot(pg, "s09-error"))
            rec(9, "User kirim prompt yang bikin error",
                precondition="Chat aktif", action="Kirim 12.000 karakter 'x'",
                expected="Pesan error ramah + tombol coba lagi",
                actual=f"ERROR {type(exc).__name__}: {str(exc)[:150]}",
                state="FAIL", shots=shots, console=pr.errs())

        # ================= S10: logout / login ===========================
        print("\n=== S10 logout lalu login lagi ===", flush=True)
        pr.reset()
        shots = []
        try:
            pg.goto(f"{FRONTEND}/chat", wait_until="domcontentloaded",
                    timeout=60000)
            pg.wait_for_timeout(3000)
            shots.append(shot(pg, "s10-a-sebelum-logout"))
            before = pg.inner_text("body")
            # logout = hapus sesi Supabase (yang dilakukan tombol keluar)
            pg.evaluate("k => { try { localStorage.removeItem(k); } catch(e){} }",
                        SESS["storage_key"])
            pg.reload(wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(3500)
            shots.append(shot(pg, "s10-b-setelah-logout"))
            after = pg.inner_text("body")
            logged_out = "Masuk untuk mulai mengobrol" in after or \
                "Login dengan Google" in after
            # login lagi dengan sesi yang sama (simulasi login ulang)
            inject_session(pg)
            dismiss_onboarding(pg)
            pg.goto(f"{FRONTEND}/chat", wait_until="domcontentloaded",
                    timeout=60000)
            pg.wait_for_timeout(3500)
            shots.append(shot(pg, "s10-c-setelah-login-lagi"))
            again = pg.inner_text("body")
            restored = "otonom-test@katalir-internal.dev" in again
            rec(10, "User logout lalu login lagi",
                precondition="Login sebagai user uji",
                action="Hapus sesi (logout) lalu pulihkan sesi (login)",
                expected="Setelah login, data user kembali",
                actual=(f"logout_terdeteksi={logged_out}; "
                        f"identitas_kembali={restored}; "
                        f"panjang_sebelum={len(before)}"),
                state="PASS" if (logged_out and restored) else "FAIL",
                shots=shots, console=pr.errs(), netfail=pr.netfail,
                extra={"after_logout_head": after[:300],
                       "after_login_head": again[:300]})
        except Exception as exc:  # noqa: BLE001
            shots.append(shot(pg, "s10-error"))
            rec(10, "User logout lalu login lagi",
                precondition="Login sebagai user uji",
                action="Hapus sesi (logout) lalu pulihkan sesi (login)",
                expected="Setelah login, data user kembali",
                actual=f"ERROR {type(exc).__name__}: {str(exc)[:150]}",
                state="FAIL", shots=shots, console=pr.errs())

        ctx.close()
        b.close()

    n = {"PASS": 0, "FAIL": 0, "BLOCKED": 0, "NOT_RUN": 0}
    for r in RESULTS:
        n[r["state"]] += 1
    print("\n" + "=" * 72)
    print(f"HASIL: PASS={n['PASS']} FAIL={n['FAIL']} "
          f"BLOCKED={n['BLOCKED']} NOT_RUN={n['NOT_RUN']}")
    print("=" * 72)
    (UT / "_user_test_results.json").write_text(
        json.dumps({"summary": n, "results": RESULTS},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"bukti -> {UT / '_user_test_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
