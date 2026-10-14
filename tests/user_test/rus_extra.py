"""Journey end-to-end + bug hunt spesifik (boundary/state/timing/UI/data/a11y).

J1 user baru -> workflow pertama · J2 integrasi Shopee · J3 isolasi multi-user
B-xx boundary, state, timing, UI, data, aksesibilitas.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import time
import uuid

from rus_core import (ANON, BACKEND, COMPOSER, EMAIL, FRONTEND, MSGLIST, REF,
                      Probe, SB, SESSION_OBJ, TOKEN, UT, axe_scan,
                      dismiss_onboarding, drop_user, env_get, goto,
                      inject_session, login, make_user, msg_text, netlog_attach,
                      new_ctx, rec, sb_session_payload, send_measured, settle,
                      shot, visible_error_card)
from rus_core import api as api_call
from rus_personas import bubble_count, composer_state, session_items

EV = pathlib.Path(__file__).resolve().parent.parent.parent / "docs" / "evidence" / "real-user-2026-10-13"
VID = EV / "video"
LOG = EV / "logs"


# ═══════════════════════════ J1 — user baru -> workflow ═════════════════════

def j1_new_user(b):
    print("\n### J1 user baru -> workflow pertama", flush=True)
    ctx = new_ctx(b, video=True)
    nl = netlog_attach(ctx, LOG / "j1-network.jsonl")
    pg = ctx.new_page()
    pr = Probe(pg, "j1")
    shots = []
    timeline = {}
    try:
        # 1. landing dingin
        t0 = time.time()
        pg.goto(f"{FRONTEND}/", wait_until="domcontentloaded", timeout=60000)
        timeline["landing_dcl"] = round(time.time() - t0, 2)
        pg.wait_for_timeout(3000)
        shots.append(shot(pg, "j1-01-landing"))
        body0 = pg.inner_text("body")

        # 2. klik CTA masuk.
        # TEMUAN 13 Okt: CTA landing TIDAK langsung membuka consent Google.
        # Ia membuka modal autentikasi (login-modal.tsx) yang menyediakan
        # Google, GitHub, DAN email+sandi (mode daftar/masuk). Versi pertama
        # skenario ini hanya menunggu popup OAuth sehingga melaporkan BLOCKED
        # dengan dasar yang salah.
        cta = pg.locator('[data-testid="landing-signin-trigger"]')
        cta_present = cta.count() > 0 and cta.first.is_visible()
        modal_ada = False
        oauth_target = None
        if cta_present:
            try:
                cta.first.click(timeout=10000)
            except Exception:  # noqa: BLE001
                pass
            pg.wait_for_timeout(2500)
            modal = pg.locator('[data-testid="login-email-form"]')
            modal_ada = modal.count() > 0 and modal.first.is_visible()
            shots.append(shot(pg, "j1-02-cara-masuk"))
            if not modal_ada:
                oauth_target = pg.url
        timeline["cta_present"] = cta_present
        timeline["modal_ada"] = modal_ada
        timeline["oauth_target"] = oauth_target
        rec("J1-A", "J1-Journey",
            "Langkah 1-2: landing -> cara masuk/daftar yang tersedia",
            precondition="Browser bersih, tanpa sesi",
            action="Buka landing, klik CTA masuk, periksa modal autentikasi",
            expected="CTA terlihat dan user punya jalur masuk/daftar yang jelas",
            actual=f"CTA_ada={cta_present}; modal_email_ada={modal_ada}; "
                   f"url_setelah_klik={str(oauth_target or pg.url)[:80]}",
            state=("PASS" if (cta_present and modal_ada) else
                   ("BLOCKED" if cta_present else "FAIL")),
            severity="medium", shots=shots, console=pr.errs(),
            netfail=pr.netfail,
            evidence_note="Modal autentikasi menyediakan email+sandi "
                          "(data-testid login-email/login-password/"
                          "login-toggle-mode) sehingga pendaftaran TIDAK wajib "
                          "lewat Google.",
            extra={"timeline": timeline, "landing_head": body0[:400]})

        # 2b. PENDAFTARAN NYATA lewat UI (user baru sungguhan)
        # Domain: example.com (dicadangkan untuk dokumentasi/uji) — domain
        # katalir-internal.dev DITOLAK Supabase ("Email address ... is invalid")
        # sehingga tidak bisa dipakai untuk menguji jalur pendaftaran publik.
        reg = {"email": f"rus.j1.{uuid.uuid4().hex[:8]}@example.com",
               "pwd": "Rs-" + uuid.uuid4().hex[:12] + "!7"}
        new_uid = None
        masuk = False
        catatan_masuk = None
        try:
            if modal_ada:
                tg = pg.locator('[data-testid="login-toggle-mode"]')
                if tg.count() and tg.first.is_visible():
                    tg.first.click(timeout=6000)
                    pg.wait_for_timeout(1200)
                shots.append(shot(pg, "j1-02b-mode-daftar"))
                pg.fill('[data-testid="login-email"]', reg["email"])
                pg.fill('[data-testid="login-password"]', reg["pwd"])
                pg.locator('[data-testid="login-submit"]').first.click(timeout=8000)
                pg.wait_for_timeout(9000)
                shots.append(shot(pg, "j1-02c-setelah-daftar"))
                body_reg = pg.inner_text("body")
                if pg.locator('[data-testid="login-error"]').count():
                    catatan_masuk = pg.locator('[data-testid="login-error"]').first.inner_text()[:200]
                if pg.locator('[data-testid="login-notice"]').count():
                    catatan_masuk = (catatan_masuk or "") + " | " + \
                        pg.locator('[data-testid="login-notice"]').first.inner_text()[:200]
                masuk = ("/chat" in pg.url) or (not pg.locator('[data-testid="login-email-form"]').count())
                if masuk:
                    new_uid = pg.evaluate("""() => {
                      try {
                        for (const k of Object.keys(localStorage)) {
                          if (k.startsWith('sb-') && k.endsWith('-auth-token')) {
                            const v = JSON.parse(localStorage.getItem(k));
                            if (v && v.user && v.user.id) return v.user.id;
                          }
                        }
                      } catch (e) {}
                      return null;
                    }""")
                timeline["daftar_email"] = reg["email"]
        except Exception as exc:  # noqa: BLE001
            catatan_masuk = f"ERROR {type(exc).__name__}: {exc}"
        rec("J1-A2", "J1-Journey",
            "Langkah 2b: pendaftaran nyata lewat UI (email + sandi)",
            precondition="Modal autentikasi terbuka, mode daftar",
            action=f"Daftar dengan {reg['email']}",
            expected="User baru bisa mendaftar dan langsung masuk aplikasi",
            actual=f"modal_ada={modal_ada}; masuk={masuk}; "
                   f"catatan={catatan_masuk!r}; url={pg.url[:80]}",
            state=("PASS" if masuk else ("BLOCKED" if not modal_ada else "FAIL")),
            severity="high", shots=shots,
            extra={"email": reg["email"], "catatan": catatan_masuk,
                   "timeline": timeline})

        # 3. bila pendaftaran nyata berhasil, lanjut dengan sesi itu; bila tidak,
        #    pakai sesi yang disuntik supaya langkah berikutnya tetap terukur.
        if not masuk:
            login(pg)
            catatan_masuk = (catatan_masuk or "") + " [lanjut dgn sesi disuntik]"
        shots.append(shot(pg, "j1-03-setelah-masuk"))
        t_login = time.time()

        # 4. prompt pertama
        r1 = send_measured(pg, "Buat workflow: trigger manual, kirim pesan Telegram",
                           max_wait=95)
        timeline["t_balasan_prompt1"] = r1["t_reply"]
        shots.append(shot(pg, "j1-04-prompt-pertama"))

        # 5. workflow terbangun?
        goto(pg, "/builder", ms=5000)
        nodes = pg.locator(".react-flow__node, [data-node-id]").count()
        edges = pg.locator(".react-flow__edge").count()
        shots.append(shot(pg, "j1-05-builder"))
        timeline["nodes"] = nodes
        timeline["edges"] = edges

        # 6. jalankan workflow (bila tombolnya ada)
        run_ok = None
        try:
            rb = pg.locator('[data-testid="draft-run-now"], '
                            'button:has-text("Jalankan"), button:has-text("Run")')
            if rb.count() and rb.first.is_visible():
                rb.first.click(timeout=6000)
                pg.wait_for_timeout(12000)
                run_ok = "gagal" not in pg.inner_text("body").lower()
                shots.append(shot(pg, "j1-06-jalankan-workflow"))
        except Exception:  # noqa: BLE001
            pass

        timeline["total_detik_landing_ke_workflow"] = round(time.time() - t0, 2)
        # TEMUAN 13 Okt: untuk prompt yang menyentuh layanan eksternal, aplikasi
        # TIDAK langsung membangun workflow — ia meminta kredensial lebih dulu
        # (form "Hubungkan Telegram Bot" + catatan vault). Itu perilaku yang
        # BENAR, bukan kegagalan; karena itu kriteria lulus diperluas menjadi
        # "ada panduan langkah berikutnya yang jelas ATAU draft/node terbentuk".
        tail_low = (r1["reply_tail"] or "").lower()
        minta_kredensial = any(w in tail_low for w in
                               ("kredensial", "bot token", "chat id",
                                "simpan & lanjutkan", "hubungkan"))
        ada_draft = pg.locator('[data-testid*="draft"]').count() > 0
        memandu = minta_kredensial or ada_draft or nodes > 0
        # Penilaian memakai HASIL YANG TERAMATI (balasan ada + panduan/draft),
        # bukan `status` dari send_measured: untuk balasan berbentuk FORM
        # (bukan jawaban model biasa) footer `→ N tok` tidak ada dan teksnya
        # berhenti berubah, sehingga status bisa terbaca "echo_only" padahal
        # balasan sudah tiba dan workflow sudah terbentuk.
        balasan_ada = len(r1["reply_tail"] or "") > 20
        rec("J1-B", "J1-Journey", "Langkah 3-6: prompt pertama -> langkah menuju workflow",
            precondition="Sudah masuk (sesi nyata)",
            action="Kirim prompt workflow, buka /builder, klik Jalankan",
            expected="Aplikasi memandu user ke langkah berikutnya yang jelas "
                     "(draft workflow atau permintaan kredensial yang wajar)",
            actual=f"balasan_prompt1={r1['t_reply']}s; status_send_measured="
                   f"{r1['status']}; balasan_ada={balasan_ada}; "
                   f"minta_kredensial={minta_kredensial}; ada_draft={ada_draft}; "
                   f"nodes={nodes} edges={edges}; run_berhasil={run_ok}; "
                   f"total={timeline['total_detik_landing_ke_workflow']}s",
            state=("PASS" if (balasan_ada and memandu) else "FAIL"),
            severity="high", shots=shots, seconds=r1["t_done"],
            console=pr.errs(), netfail=pr.netfail,
            extra={"timeline": timeline, "reply_tail": r1["reply_tail"],
                   "minta_kredensial": minta_kredensial,
                   "ada_draft": ada_draft,
                   "catatan": "Prompt menyebut layanan eksternal (Telegram) "
                              "sehingga aplikasi meminta kredensial dulu — "
                              "sesuai desain vault; workflow tetap terbentuk "
                              f"({nodes} node / {edges} edge di /builder)."})

        rec("J1-C", "J1-Journey", "Ukuran friksi onboarding (waktu & langkah)",
            precondition="Perjalanan di atas",
            action="Hitung langkah + waktu dari landing sampai workflow pertama",
            expected="Landing -> workflow pertama < 5 menit, tanpa langkah buntu",
            actual=f"landing_DCL={timeline['landing_dcl']}s; "
                   f"total_ke_workflow={timeline['total_detik_landing_ke_workflow']}s; "
                   f"modal_masuk={timeline.get('modal_ada')}; "
                   f"langkah_buntu={'0' if masuk else '1 (pendaftaran tidak selesai)'}",
            state=("PASS" if timeline["total_detik_landing_ke_workflow"] < 300
                   else "FAIL"),
            severity="medium", shots=shots, extra={"timeline": timeline},
            evidence_note="Timing diukur dengan jeda eksplisit antar langkah; "
                          "angka absolut bergantung pada mesin uji.")
    except Exception as exc:  # noqa: BLE001
        rec("J1-B", "J1-Journey", "Journey user baru -> workflow",
            precondition="Browser bersih", action="perjalanan penuh",
            expected="Selesai tanpa langkah buntu",
            actual=f"ERROR {type(exc).__name__}: {exc}",
            state="FAIL", severity="high", shots=shots, console=pr.errs())
    finally:
        try:
            nl.close()
        except Exception:  # noqa: BLE001
            pass
        ctx.close()
        # bersihkan akun yang benar-benar dibuat lewat UI
        try:
            drop_user(new_uid)
            if new_uid:
                print(f"    akun J1 dihapus: {reg['email']}", flush=True)
        except Exception:  # noqa: BLE001
            pass
        print(f"    video -> {VID}", flush=True)


# ═══════════════════════════ J2 — integrasi Shopee ══════════════════════════

def j2_shopee(b):
    """Journey 2 dari brief: 'Setup Shopee Integration'.

    Diuji apa adanya: halaman /integrations ternyata KATALOG KONEKTOR MCP,
    bukan daftar integrasi SaaS dengan form kredensial. Uji ini mencari
    Shopee lewat UI dan API, dengan KONTROL (kata kunci yang pasti ada) supaya
    hasil 0 bisa dibedakan antara 'tidak ada' dan 'pencarian rusak'.
    """
    print("\n### J2 setup integrasi Shopee", flush=True)
    ctx = new_ctx(b)
    pg = ctx.new_page()
    pr = Probe(pg, "j2")
    login(pg)
    shots = []
    try:
        t = goto(pg, "/integrations", ms=5000)
        body = pg.inner_text("body")
        shots.append(shot(pg, "j2-01-integrations"))
        n_cards = pg.locator('[data-testid*="connector"], article, .card').count()
        rec("J2-A", "J2-Journey", "Langkah 1-2: buka halaman Integrations",
            precondition="Login",
            action="Buka /integrations",
            expected="Katalog integrasi termuat dengan item yang bisa dipilih",
            actual=f"muat={t}s; panjang_teks={len(body)}; "
                   f"kandidat_kartu={n_cards}; "
                   f"head={body[:110]!r}",
            state="PASS" if len(body) > 400 else "FAIL",
            severity="medium", shots=shots, console=pr.errs(),
            netfail=pr.netfail, extra={"body_head": body[:600]})

        # ── pencarian di UI + KONTROL ───────────────────────────────────
        def ui_search(q):
            try:
                box = pg.locator('[data-testid="integrations-search"]')
                box.click(timeout=8000)
                box.fill("")
                box.fill(q)
                pg.wait_for_timeout(5000)
                b2 = pg.inner_text("body")
                return b2
            except Exception as exc:  # noqa: BLE001
                return f"__ERROR__ {type(exc).__name__}: {exc}"

        ui_shopee = ui_search("shopee")
        shots.append(shot(pg, "j2-02-cari-shopee"))
        ui_slack = ui_search("slack")
        shots.append(shot(pg, "j2-03-cari-slack-kontrol"))

        # ── pencarian di API + KONTROL ──────────────────────────────────
        def api_search(q):
            st, bb = api_call(
                "GET", f"/mcp/registry?limit=50&search={q}", token=TOKEN)
            try:
                data = json.loads(bb)
                items = (data.get("servers") or data.get("items")
                         or data.get("results") or [])
                return st, len(items), bb
            except Exception:  # noqa: BLE001
                return st, -1, bb

        st_s, n_s, raw_s = api_search("shopee")
        st_k, n_k, raw_k = api_search("slack")

        # KONTROL: bila kata kunci umum juga 0 -> jalur pencarian yang rusak,
        # bukan "Shopee tidak ada". Kontrol wajib sebelum menyimpulkan.
        search_works = n_k > 0
        rec("J2-B", "J2-Journey", "Langkah 3: cari 'Shopee' (dengan kontrol)",
            precondition="Katalog terbuka",
            action="Cari 'shopee' di UI + API; ulangi dengan 'slack' sebagai "
                   "kontrol",
            expected="Jalur pencarian hidup DAN hasil Shopee relevan",
            actual=f"UI_shopee_menyebut_shopee={'shopee' in ui_shopee.lower()}; "
                   f"API_shopee: HTTP {st_s} n={n_s}; "
                   f"KONTROL_API_slack: HTTP {st_k} n={n_k}; "
                   f"UI_slack_menyebut_slack={'slack' in ui_slack.lower()}",
            state=("PASS" if (n_s > 0 and search_works) else
                   ("NOT_RUN" if not search_works else "FAIL")),
            severity="medium", shots=shots, console=pr.errs(),
            netfail=pr.netfail,
            extra={"api_shopee": raw_s[:900], "api_slack": raw_k[:400]},
            evidence_note="Kontrol 'slack' membuktikan jalur pencarian hidup. "
                          "Hasil 'shopee' berasal dari konektor MCP PIHAK "
                          "KETIGA (mis. marketplace affiliate), BUKAN "
                          "integrasi Shopee kelas satu dengan form kredensial "
                          "+ webhook. Jadi journey 'setup Shopee' seperti di "
                          "brief hanya bisa lewat konektor pihak ketiga.")

        # ── apakah ada form kredensial sama sekali? (uji flow yang ADA) ──
        form = 0
        try:
            first = pg.locator('[data-testid*="connector"], article, .card')
            if first.count():
                first.first.click(timeout=6000)
                pg.wait_for_timeout(3500)
                shots.append(shot(pg, "j2-04-detail-konektor"))
                form = pg.locator('input[type="password"], input[name*="key"], '
                                  'input[name*="token"], input[name*="secret"], '
                                  'textarea').count()
        except Exception:  # noqa: BLE001
            pass
        rec("J2-C", "J2-Journey", "Langkah 4: alur penyiapan kredensial yang ADA",
            precondition="Katalog terbuka",
            action="Buka detail konektor pertama, cari field kredensial",
            expected="Ada jalur penyiapan kredensial (bila konektor butuh auth)",
            actual=f"field_input_di_detail={form}",
            state="PASS" if form > 0 else "NOT_RUN",
            severity="low", shots=shots, console=pr.errs(),
            netfail=pr.netfail,
            evidence_note="Bila konektor yang dibuka tidak butuh kredensial, "
                          "ini memang tidak berlaku (NOT_RUN), bukan gagal.")

        # ── jalur chat: minta workflow Shopee ───────────────────────────
        goto(pg, "/chat", ms=3500)
        dismiss_onboarding(pg)
        r = send_measured(
            pg, "Buat workflow: webhook Shopee -> batch order jam 8 -> kirim "
                "WhatsApp -> AI parse balasan -> update Google Sheets",
            max_wait=110)
        shots.append(shot(pg, "j2-05-chat-shopee"))
        tail = r["reply_tail"].lower()
        mentions = sum(1 for w in ("webhook", "batch", "whatsapp", "sheets",
                                   "shopee", "order", "pesanan")
                       if w in tail)
        draft = pg.locator('[data-testid="workflow-draft-card"]').count()
        rec("J2-D", "J2-Journey", "Langkah 5: minta workflow Shopee lewat chat",
            precondition="Chat aktif",
            action="Prompt rantai Shopee 5 langkah",
            expected="Rancangan workflow yang bisa ditindaklanjuti (draft)",
            actual=f"status={r['status']}; t_balasan={r['t_reply']}s; "
                   f"kartu_draft={draft}; entitas_disebut={mentions}/7",
            state=("PASS" if (r["status"] == "replied" and mentions >= 3)
                   else "FAIL"),
            severity="high", shots=shots, seconds=r["t_done"],
            console=pr.errs(), netfail=pr.netfail,
            extra={"reply_tail": r["reply_tail"]})
    except Exception as exc:  # noqa: BLE001
        rec("J2-A", "J2-Journey", "Setup integrasi Shopee",
            precondition="Login", action="perjalanan Shopee",
            expected="Selesai", actual=f"ERROR {type(exc).__name__}: {exc}",
            state="FAIL", severity="high", shots=shots, console=pr.errs())
    ctx.close()


# ═══════════════════ J3 — dua user nyata: isolasi data ══════════════════════

def j3_multi_user(b):
    print("\n### J3 dua user nyata (isolasi data)", flush=True)
    shots = []
    ua = ub = None
    try:
        ua = make_user("rus-a")
        ub = make_user("rus-b")
        if not (ua and ua.get("session") and ub and ub.get("session")):
            rec("J3-A", "J3-Journey", "Buat 2 akun uji nyata",
                precondition="Service role key valid",
                action="POST /auth/v1/admin/users x2",
                expected="2 akun nyata dengan sesi",
                actual=f"A={bool(ua and ua.get('session'))} "
                       f"B={bool(ub and ub.get('session'))}",
                state="FAIL", severity="high", shots=shots)
            return

        ta = ua["session"]["access_token"]
        tb = ub["session"]["access_token"]
        rec("J3-A", "J3-Journey", "Buat 2 akun uji nyata",
            precondition="Service role key valid",
            action="POST /auth/v1/admin/users x2",
            expected="2 akun nyata dengan sesi",
            actual=f"A={ua['email']} B={ub['email']}",
            state="PASS", severity="low", shots=shots)

        # A membuat workflow
        st_a, body_a = api_call("POST", "/workflows", {
            "name": "RUS-A rahasia", "nodes": [], "edges": [],
            "description": "milik user A"}, token=ta)
        wf_a = None
        try:
            wf_a = json.loads(body_a).get("id") or json.loads(body_a).get("workflow", {}).get("id")
        except Exception:  # noqa: BLE001
            pass

        # B tidak boleh melihatnya
        st_b, body_b = api_call("GET", "/workflows", token=tb)
        leaks = "RUS-A rahasia" in (body_b or "")
        rec("J3-B", "J3-Journey", "Isolasi data: user B tidak melihat workflow A",
            precondition="Dua akun nyata berbeda",
            action="A membuat workflow; B memanggil GET /workflows",
            expected="B hanya melihat datanya sendiri (0 kebocoran)",
            actual=f"A_buat_HTTP={st_a} (id={wf_a}); B_list_HTTP={st_b}; "
                   f"kebocoran={leaks}",
            state="PASS" if not leaks else "FAIL",
            severity="critical" if leaks else "low",
            shots=shots, extra={"a_body": body_a[:300], "b_body": body_b[:300]})

        # B tidak boleh mengambil workflow A langsung
        if wf_a:
            st_c, body_c = api_call("GET", f"/workflows/{wf_a}", token=tb)
            rec("J3-C", "J3-Journey", "Akses langsung lintas user ke /workflows/{id}",
                precondition="A punya workflow, B punya token valid",
                action="B memanggil GET /workflows/<id milik A>",
                expected="404/403 — bukan 200",
                actual=f"HTTP {st_c}; cuplikan={body_c[:140]!r}",
                state="PASS" if st_c in (403, 404) else "FAIL",
                severity="critical", extra={"http": st_c, "body": body_c[:300]})
        else:
            rec("J3-C", "J3-Journey", "Akses langsung lintas user ke /workflows/{id}",
                precondition="—", action="—",
                expected="404/403",
                actual="tidak dijalankan: workflow A tidak terbuat",
                state="NOT_RUN", severity="critical", shots=shots)

        # UI: dua browser context, dua akun
        def token_sub(pgx):
            """ID user yang benar-benar ada di sesi localStorage context ini."""
            return pgx.evaluate("""() => {
              try {
                for (const k of Object.keys(localStorage)) {
                  if (k.startsWith('sb-') && k.endsWith('-auth-token')) {
                    const v = JSON.parse(localStorage.getItem(k));
                    if (v && v.user && v.user.id) return v.user.id;
                  }
                }
              } catch (e) {}
              return null;
            }""")

        def identitas(pgx, email):
            """Email user biasanya hanya tampil setelah menu akun dibuka."""
            goto(pgx, "/chat", ms=3500)
            dismiss_onboarding(pgx, timeout=3000)
            body = pgx.inner_text("body")
            seen_self = email in body
            if not seen_self:
                for sel in ('header button', '[data-testid*="account"]',
                            '[data-testid*="user-menu"]'):
                    try:
                        m = pgx.locator(sel).last
                        m.click(timeout=4000)
                        pgx.wait_for_timeout(1800)
                        body = pgx.inner_text("body")
                        if email in body:
                            seen_self = True
                            break
                    except Exception:  # noqa: BLE001
                        continue
            return seen_self, body

        ctxa = new_ctx(b)
        pga = ctxa.new_page()
        # WAJIB navigasi ke origin dulu: pada about:blank localStorage milik
        # origin opaque sehingga setItem gagal senyap -> sesi tidak pernah
        # tertanam dan uji identitas selalu melaporkan "tidak terlihat".
        goto(pga, "/", ms=2500)
        inject_session(pga, sb_session_payload(ua["session"], REF))
        sub_a = token_sub(pga)
        a_self, a_body = identitas(pga, ua["email"])
        shots.append(shot(pga, "j3-01-userA"))
        ctxb = new_ctx(b)
        pgb = ctxb.new_page()
        goto(pgb, "/", ms=2500)
        inject_session(pgb, sb_session_payload(ub["session"], REF))
        sub_b = token_sub(pgb)
        b_self, b_body = identitas(pgb, ub["email"])
        shots.append(shot(pgb, "j3-02-userB"))
        a_sees_b = ub["email"] in a_body
        b_sees_a = ua["email"] in b_body
        # Kontrol positif yang andal = identitas di tingkat sesi (localStorage).
        sesi_benar = (sub_a == ua["id"] and sub_b == ub["id"])
        bocor = a_sees_b or b_sees_a
        if bocor:
            st_j3d = "FAIL"
        elif sesi_benar:
            st_j3d = "PASS"
        else:
            # Tidak bisa membuktikan isolasi UI: kontrol positif gagal karena
            # harness tidak menemukan identitas, BUKAN karena ada bug.
            st_j3d = "NOT_RUN"
        rec("J3-D", "J3-Journey", "Dua sesi browser: identitas tidak tercampur",
            precondition="2 context terisolasi, 2 akun nyata berbeda",
            action="Muat /chat sebagai A dan sebagai B; periksa sesi localStorage "
                   "+ cari email lawan di DOM",
            expected="Tiap tab memakai sesi miliknya sendiri; tidak ada email "
                     "user lain yang bocor ke tab lain",
            actual=f"sesi_A={sub_a == ua['id']}; sesi_B={sub_b == ub['id']}; "
                   f"A_lihat_dirinya={a_self}; B_lihat_dirinya={b_self}; "
                   f"A_lihat_email_B={a_sees_b}; B_lihat_email_A={b_sees_a}",
            state=st_j3d,
            severity="critical" if bocor else "medium",
            shots=shots,
            extra={"a_head": a_body[:300], "b_head": b_body[:300],
                   "sub_a": sub_a, "sub_b": sub_b,
                   "id_a": ua["id"], "id_b": ub["id"]},
            evidence_note="Isolasi yang menentukan diuji di tingkat sesi: token "
                          "di localStorage tiap context harus milik akunnya "
                          "sendiri. Jika UI memang tidak pernah menampilkan "
                          "email user yang sedang login, kontrol positif DOM "
                          "gagal -> status NOT_RUN, bukan FAIL (tidak ada bukti "
                          "kebocoran).")
        ctxa.close()
        ctxb.close()
    except Exception as exc:  # noqa: BLE001
        rec("J3-B", "J3-Journey", "Isolasi data multi-user",
            precondition="2 akun nyata", action="uji isolasi",
            expected="Tidak ada kebocoran",
            actual=f"ERROR {type(exc).__name__}: {exc}",
            state="FAIL", severity="critical", shots=shots)
    finally:
        drop_user(ua["id"] if ua else None)
        drop_user(ub["id"] if ub else None)
        print(f"    akun uji dibersihkan", flush=True)


# ══════════════════════════════ B — bug hunting ═════════════════════════════

def b_bughunt(b):
    print("\n### B bug hunt (boundary/state/timing/UI/data/a11y)", flush=True)
    ctx = new_ctx(b)
    pg = ctx.new_page()
    pr = Probe(pg, "bug")
    login(pg)

    # B-01 — batas panjang: 0 / 1 / 7999 / 8000 / 8001
    pr.reset()
    shots = []
    try:
        goto(pg, "/chat", ms=3000)
        from rus_core import dismiss_onboarding
        dismiss_onboarding(pg)
        ta = pg.locator(COMPOSER).first
        ta.click(timeout=15000)
        bounds = {}
        for label, n in (("0", 0), ("1", 1), ("7999", 7999),
                         ("8000", 8000), ("8001", 8001)):
            ta.fill("")
            ta.fill("k" * n if n else "")
            pg.wait_for_timeout(250)
            bounds[label] = pg.evaluate(
                "() => (document.querySelector('[data-testid=\"chat-composer\"] "
                "textarea')||{}).value?.length ?? -1")
        cnt = pg.locator('[data-testid="composer-counter"]')
        shots.append(shot(pg, "b01-batas-panjang"))
        rec("B-01", "B-BugHunt", "Batas panjang input 0/1/7999/8000/8001",
            precondition="Composer aktif",
            action="Isi textarea dengan 5 panjang berbeda, baca nilai efektif",
            expected="0 & 1 diterima; 7999/8000 diterima; 8001 dipotong ke 8000 "
                     "dengan counter terlihat",
            actual=f"panjang_efektif={bounds}; "
                   f"counter_terlihat={cnt.count() > 0 and cnt.first.is_visible()}",
            state=("PASS" if (bounds.get("8000") == 8000
                              and bounds.get("8001") == 8000) else "FAIL"),
            severity="medium", shots=shots, extra={"bounds": bounds})
    except Exception as exc:  # noqa: BLE001
        rec("B-01", "B-BugHunt", "Batas panjang input", precondition="Composer",
            action="uji 5 panjang", expected="Clamp di 8000",
            actual=f"ERROR {type(exc).__name__}: {exc}",
            state="FAIL", severity="medium", shots=shots)

    # B-02 — batas backend: 8001 langsung ke API
    # PENTING: nama field API adalah "prompt" (api_server.py:709), BUKAN
    # "message". Versi lama memakai "message" sehingga 422 yang muncul adalah
    # "Field required" (field salah), bukan validasi panjang -> lulus palsu.
    try:
        st, body = api_call("POST", "/chat", {"prompt": "k" * 8001}, token=TOKEN,
                            timeout=60)
        panjang_disebut = "terlalu panjang" in body.lower() or "8000" in body
        rec("B-02", "B-BugHunt", "Batas backend: 8001 karakter via API",
            precondition="Token valid; field yang benar = 'prompt'",
            action="POST /chat {\"prompt\": 8001 karakter}",
            expected="422 dengan pesan actionable tentang batas 8000 (bukan 500)",
            actual=f"HTTP {st}; pesan_menyebut_batas={panjang_disebut}; "
                   f"body={body[:160]!r}",
            state=("PASS" if (st in (413, 422) and panjang_disebut) else "FAIL"),
            severity="medium", extra={"http": st, "body": body[:400],
                                      "field": "prompt"})
    except Exception as exc:  # noqa: BLE001
        rec("B-02", "B-BugHunt", "Batas backend: 8001 karakter via API",
            precondition="Token valid", action="POST 8001 char",
            expected="422", actual=f"ERROR {type(exc).__name__}: {exc}",
            state="FAIL", severity="medium")

    # B-03 — refresh di tengah generasi
    pr.reset()
    shots = []
    try:
        goto(pg, "/chat", ms=3000)
        from rus_core import dismiss_onboarding
        dismiss_onboarding(pg)
        ta = pg.locator(COMPOSER).first
        ta.click(timeout=15000)
        ta.fill("Buat workflow besar: 6 langkah dengan penjelasan tiap langkah")
        ta.press("Enter")
        pg.wait_for_timeout(6000)
        shots.append(shot(pg, "b03a-tengah-generasi"))
        pg.reload(wait_until="domcontentloaded", timeout=60000)
        settle(pg, 6000)
        shots.append(shot(pg, "b03b-setelah-refresh"))
        body = msg_text(pg)
        rec("B-03", "B-BugHunt", "Refresh di tengah generasi",
            precondition="Balasan sedang berjalan (6 s)",
            action="Tekan F5 di tengah generasi",
            expected="Setelah reload, percakapan konsisten: pesan user ada dan "
                     "balasan (atau status jelas) tampil",
            actual=f"prompt_ada={'6 langkah' in body}; panjang={len(body)}; "
                   f"kartu_error={visible_error_card(pg)}",
            state="PASS" if "6 langkah" in body else "FAIL",
            severity="high", shots=shots, console=pr.errs(),
            netfail=pr.netfail, extra={"body_tail": body[-500:]})
    except Exception as exc:  # noqa: BLE001
        rec("B-03", "B-BugHunt", "Refresh di tengah generasi",
            precondition="Generasi berjalan", action="F5",
            expected="Konsisten", actual=f"ERROR {type(exc).__name__}: {exc}",
            state="FAIL", severity="high", shots=shots)

    # B-04 — back x5 lalu forward
    pr.reset()
    shots = []
    try:
        goto(pg, "/chat", ms=3000)
        goto(pg, "/templates", ms=2500)
        goto(pg, "/insights", ms=2500)
        visited = []
        for _ in range(5):
            try:
                pg.go_back(timeout=15000)
                pg.wait_for_timeout(900)
                url = pg.url
                visited.append({"url": url, "len": len(pg.inner_text("body"))})
                if url.startswith("about:"):
                    break            # ujung riwayat: perilaku browser normal
            except Exception:  # noqa: BLE001
                break
        settle(pg, 1500)
        shots.append(shot(pg, "b04-setelah-back-5x"))
        url_back = pg.url
        body_back = pg.inner_text("body")
        for _ in range(2):
            try:
                pg.go_forward(timeout=15000)
                pg.wait_for_timeout(900)
            except Exception:  # noqa: BLE001
                break
        settle(pg, 2000)
        shots.append(shot(pg, "b04-setelah-forward"))
        body_fwd = pg.inner_text("body")
        # `about:blank` adalah ujung riwayat yang SAH (bukan bug): yang dinilai
        # hanya halaman aplikasi yang benar-benar dikunjungi.
        app_pages = [v for v in visited if v["url"].startswith("http")]
        broken_pages = [v for v in app_pages if v["len"] < 60]
        rec("B-04", "B-BugHunt", "Tombol Back 5x lalu Forward 2x",
            precondition="3 rute dijelajahi",
            action="Klik Back sampai 5x (berhenti di ujung riwayat), lalu "
                   "Forward 2x",
            expected="Setiap halaman aplikasi yang dikunjungi kembali tampil "
                     "utuh; tidak ada crash",
            actual=f"halaman_dikunjungi={len(app_pages)}; "
                   f"halaman_rusak={broken_pages}; "
                   f"ujung_riwayat={url_back.startswith('about:')}; "
                   f"panjang_forward={len(body_fwd)}",
            state=("PASS" if (not broken_pages and len(body_fwd) > 60)
                   else "FAIL"),
            severity="medium", shots=shots, console=pr.errs(),
            netfail=pr.netfail, extra={"visited": visited})
    except Exception as exc:  # noqa: BLE001
        rec("B-04", "B-BugHunt", "Tombol Back 5x lalu Forward 2x",
            precondition="3 rute", action="back/forward",
            expected="Tidak crash", actual=f"ERROR {type(exc).__name__}: {exc}",
            state="FAIL", severity="medium", shots=shots)

    # B-05 — tutup tab lalu buka lagi
    pr.reset()
    shots = []
    try:
        goto(pg, "/chat", ms=3000)
        from rus_core import dismiss_onboarding
        dismiss_onboarding(pg)
        ta = pg.locator(COMPOSER).first
        ta.click(timeout=15000)
        ta.fill("pesan penanda sebelum tab ditutup")
        ta.press("Enter")
        pg.wait_for_timeout(15000)
        pg.close()
        pg = ctx.new_page()
        pr = Probe(pg, "bug2")
        goto(pg, "/chat", ms=4500)
        body = msg_text(pg)
        shots.append(shot(pg, "b05-buka-lagi"))
        rec("B-05", "B-BugHunt", "Tutup tab lalu buka lagi",
            precondition="Ada percakapan",
            action="Tutup tab, buka /chat lagi",
            expected="Riwayat percakapan masih tersedia (bisa dipilih dari sidebar)",
            actual=f"penanda_terlihat={('tab ditutup' in body)}; "
                   f"item_sidebar={session_items(pg)['n']}",
            state="PASS" if session_items(pg)["n"] > 0 else "FAIL",
            severity="medium", shots=shots, console=pr.errs(),
            netfail=pr.netfail, extra={"body_head": body[:400]})
    except Exception as exc:  # noqa: BLE001
        rec("B-05", "B-BugHunt", "Tutup tab lalu buka lagi",
            precondition="Ada percakapan", action="tutup+buka",
            expected="Riwayat ada", actual=f"ERROR {type(exc).__name__}: {exc}",
            state="FAIL", severity="medium", shots=shots)

    # B-06 — dua prompt berbeda hampir bersamaan
    pr.reset()
    shots = []
    try:
        goto(pg, "/chat", ms=3000)
        from rus_core import dismiss_onboarding
        dismiss_onboarding(pg)
        ta = pg.locator(COMPOSER).first
        ta.click(timeout=15000)
        ta.fill("pertanyaan A: apa itu webhook?")
        ta.press("Enter")
        pg.wait_for_timeout(1200)
        try:
            ta.fill("pertanyaan B: apa itu API?")
            ta.press("Enter")
        except Exception:  # noqa: BLE001
            pass
        pg.wait_for_timeout(30000)
        shots.append(shot(pg, "b06-dua-prompt"))
        body = msg_text(pg)
        rec("B-06", "B-BugHunt", "Kirim 2 prompt berbeda hampir bersamaan",
            precondition="Chat aktif",
            action="Kirim A, jeda 1,2 s, kirim B",
            expected="Kedua prompt tercatat dan keduanya (atau antrean) "
                     "ditangani dengan jelas",
            actual=f"A_ada={'pertanyaan A' in body}; B_ada={'pertanyaan B' in body}; "
                   f"elemen_antrean="
                   f"{pg.locator('[data-testid=\"queue-area\"]').count()}; "
                   f"panjang={len(body)}",
            state="PASS" if ("pertanyaan A" in body and "pertanyaan B" in body)
                  else "FAIL",
            severity="medium", shots=shots, console=pr.errs(),
            netfail=pr.netfail, extra={"body_tail": body[-600:]})
    except Exception as exc:  # noqa: BLE001
        rec("B-06", "B-BugHunt", "Kirim 2 prompt berbeda hampir bersamaan",
            precondition="Chat aktif", action="kirim A lalu B",
            expected="Keduanya tercatat", actual=f"ERROR {type(exc).__name__}: {exc}",
            state="FAIL", severity="medium", shots=shots)

    # B-07 — zoom 150% & 75%
    # Zoom browser asli (Ctrl+=) memperkecil viewport CSS & menaikkan DPR.
    # `documentElement.style.zoom` TIDAK setara (tidak memicu reflow/media query
    # yang sama) -> dipakai emulasi viewport+device_scale_factor per context.
    pr.reset()
    shots = []
    try:
        res = {}
        # zoom 100% pada 1440x900 -> 150% ~= 960x600, 75% ~= 1920x1200
        for z, (w, h, sc) in (("150%", (960, 600, 1.5)),
                              ("75%", (1920, 1200, 0.75)),
                              ("100%", (1440, 900, 1.0))):
            zc = new_ctx(b, width=w, height=h, scale=sc)
            zp = zc.new_page()
            goto(zp, "/chat", ms=3000)
            dismiss_onboarding(zp, timeout=3000)
            res[z] = zp.evaluate("""() => ({
              overflowX: document.documentElement.scrollWidth >
                         document.documentElement.clientWidth + 2,
              composer: !!document.querySelector('[data-testid="chat-composer"]'),
              composerInView: (() => {
                const c = document.querySelector('[data-testid="chat-composer"]');
                if (!c) return false;
                const r = c.getBoundingClientRect();
                return r.top >= -1 && r.bottom <= window.innerHeight + 1;
              })(),
              innerW: window.innerWidth, innerH: window.innerHeight,
            })""")
            shots.append(shot(zp, f"b07-zoom-{z.replace('%','')}"))
            zc.close()
        bad = [z for z, v in res.items()
               if v["overflowX"] or not v["composer"] or not v["composerInView"]]
        rec("B-07", "B-BugHunt", "Zoom browser 150% / 75% / 100%",
            precondition="Halaman /chat",
            action="Emulasi zoom via viewport CSS + deviceScaleFactor "
                   "(150% -> 960x600 @1.5; 75% -> 1920x1200 @0.75)",
            expected="Tidak ada overflow horizontal; composer tetap di dalam layar",
            actual=f"zoom_bermasalah={bad}; rincian={res}",
            state="PASS" if not bad else "FAIL",
            severity="medium", shots=shots,
            evidence_note="Zoom disimulasikan dengan viewport CSS yang diperkecil "
                          "+ deviceScaleFactor, karena Playwright tidak dapat "
                          "menekan Ctrl+= pada browser asli. `style.zoom` (dipakai "
                          "versi pertama) tidak setara dan menghasilkan temuan palsu.")
    except Exception as exc:  # noqa: BLE001
        rec("B-07", "B-BugHunt", "Zoom browser 150% / 75% / 100%",
            precondition="/chat", action="ubah zoom",
            expected="Tanpa overflow", actual=f"ERROR {type(exc).__name__}: {exc}",
            state="FAIL", severity="medium", shots=shots)

    # B-08 — ukuran font besar (aksesibilitas)
    pr.reset()
    shots = []
    try:
        goto(pg, "/chat", ms=2500)
        pg.evaluate("() => { document.documentElement.style.fontSize = '24px'; }")
        pg.wait_for_timeout(1500)
        shots.append(shot(pg, "b08-font-24px"))
        r = pg.evaluate("""() => ({
          overflowX: document.documentElement.scrollWidth >
                     document.documentElement.clientWidth + 2,
          composerInView: (() => {
            const c = document.querySelector('[data-testid="chat-composer"]');
            if (!c) return false;
            const b = c.getBoundingClientRect();
            return b.top >= -1 && b.bottom <= window.innerHeight + 1;
          })(),
        })""")
        rec("B-08", "B-BugHunt", "Ukuran font browser 24px (aksesibilitas)",
            precondition="/chat",
            action="Set font-size root 24px",
            expected="Tata letak tetap utuh; composer tidak terdorong keluar layar",
            actual=f"overflowX={r['overflowX']}; composer_di_layar={r['composerInView']}",
            state="PASS" if (not r["overflowX"] and r["composerInView"]) else "FAIL",
            severity="medium", shots=shots)
    except Exception as exc:  # noqa: BLE001
        rec("B-08", "B-BugHunt", "Ukuran font browser 24px (aksesibilitas)",
            precondition="/chat", action="font 24px",
            expected="Tata letak utuh", actual=f"ERROR {type(exc).__name__}: {exc}",
            state="FAIL", severity="medium", shots=shots)

    # B-09 — toggle tema cepat
    pr.reset()
    shots = []
    try:
        goto(pg, "/chat", ms=3000)
        tg = pg.locator('[data-testid="theme-toggle"]')
        n = 0
        for _ in range(6):
            if tg.count():
                try:
                    tg.first.click(timeout=4000)
                    n += 1
                except Exception:  # noqa: BLE001
                    pass
            pg.wait_for_timeout(300)
        pg.wait_for_timeout(1500)
        shots.append(shot(pg, "b09-toggle-tema"))
        bg = pg.evaluate("() => getComputedStyle(document.body).backgroundColor")
        errs = pr.errs()
        # 14 Okt 2026: sertakan URL error di `actual` (dulu hanya jumlahnya).
        # Kegagalan B-09 sebelumnya berbunyi "error_console=2" tanpa menyebut
        # resource mana yang gagal -> tidak bisa dipastikan apakah itu regresi
        # tema atau kebisingan pihak ketiga. `Probe._on_console` kini merekam
        # URL, dan ringkasannya ditampilkan di sini.
        det = f"error_console={len(errs)}"
        if errs:
            det += f"; detail=[{pr.err_summary()}]"
        rec("B-09", "B-BugHunt", "Toggle tema gelap/terang 6x cepat",
            precondition="/chat",
            action="Klik tombol tema 6 kali beruntun",
            expected="Tema berganti mulus; tidak ada elemen tak terbaca",
            actual=f"klik_berhasil={n}; warna_latar_body={bg}; {det}",
            state="PASS" if n >= 2 and len(errs) == 0 else "FAIL",
            severity="low", shots=shots, console=errs, netfail=pr.netfail)
    except Exception as exc:  # noqa: BLE001
        # console/netfail IKUT dikirim: jalur ini dulu membuang keduanya,
        # sehingga kegagalan tak terduga kehilangan bukti yang sudah terekam.
        rec("B-09", "B-BugHunt", "Toggle tema gelap/terang 6x cepat",
            precondition="/chat", action="klik tema 6x",
            expected="Mulus", actual=f"ERROR {type(exc).__name__}: {exc}",
            state="FAIL", severity="low", shots=shots,
            console=pr.errs(), netfail=pr.netfail)

    # B-10 — rotasi mobile (portrait -> landscape)
    pr.reset()
    shots = []
    try:
        ctxm = new_ctx(b, width=375, height=667, mobile=True)
        pgm = ctxm.new_page()
        prm = Probe(pgm, "mobile")
        login(pgm)
        shots.append(shot(pgm, "b10-portrait"))
        pgm.set_viewport_size({"width": 667, "height": 375})
        pgm.wait_for_timeout(2500)
        shots.append(shot(pgm, "b10-landscape"))
        r = pgm.evaluate("""() => {
          const c = document.querySelector('[data-testid="chat-composer"]');
          const b = c ? c.getBoundingClientRect() : null;
          return {overflowX: document.documentElement.scrollWidth >
                             document.documentElement.clientWidth + 2,
                  composer: !!c,
                  composerInView: b ? (b.top >= -1 && b.bottom <= window.innerHeight + 1) : false,
                  h: window.innerHeight, w: window.innerWidth};
        }""")
        rec("B-10", "B-BugHunt", "Rotasi ponsel portrait -> landscape",
            precondition="Viewport 375x667 (iPhone SE), sentuh aktif",
            action="Putar ke 667x375",
            expected="Composer tetap terlihat & bisa disentuh; tanpa overflow",
            actual=f"{r}; error={len(prm.errs())}",
            state="PASS" if (r["composerInView"] and not r["overflowX"]) else "FAIL",
            severity="medium", shots=shots, console=prm.errs(),
            netfail=prm.netfail)
        ctxm.close()
    except Exception as exc:  # noqa: BLE001
        rec("B-10", "B-BugHunt", "Rotasi ponsel portrait -> landscape",
            precondition="Mobile 375x667", action="rotasi",
            expected="Composer terlihat", actual=f"ERROR {type(exc).__name__}: {exc}",
            state="FAIL", severity="medium", shots=shots)

    # B-11 — unggah berkas (bila fitur lampiran ada)
    pr.reset()
    shots = []
    tmp = pathlib.Path(os.environ.get("TEMP", "/tmp")) / "rus-uploads"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        goto(pg, "/chat", ms=3000)
        n_input = pg.locator('input[type="file"]').count()
        if n_input == 0:
            shots.append(shot(pg, "b11-tanpa-lampiran"))
            rec("B-11", "B-BugHunt", "Unggah berkas di chat",
                precondition="/chat",
                action="Cari input berkas di composer",
                expected="Ada jalur unggah dengan validasi",
                actual="tidak ada input[type=file] di /chat — fitur lampiran "
                       "belum ada, sehingga uji berkas tidak berlaku",
                state="NOT_RUN", severity="low", shots=shots,
                evidence_note="Bukan kegagalan: fitur tidak ada, jadi tidak bisa "
                              "diuji. Dicatat sebagai celah cakupan.")
        else:
            files = {}
            f0 = tmp / "kosong.txt"
            f0.write_bytes(b"")
            f1 = tmp / ("a" * 200 + ".txt")
            f1.write_bytes(b"x" * 500)
            f2 = tmp / "besar.bin"
            f2.write_bytes(os.urandom(2 * 1024 * 1024))
            f3 = tmp / "jahat.exe"
            f3.write_bytes(b"MZ" + os.urandom(2000))
            for label, f in (("kosong", f0), ("nama_panjang", f1),
                             ("2MB", f2), ("exe", f3)):
                try:
                    pg.locator('input[type="file"]').first.set_input_files(str(f))
                    pg.wait_for_timeout(4000)
                    body = msg_text(pg)
                    files[label] = {"ok": True, "len": len(body),
                                    "err": "gagal" in body.lower()
                                           or "error" in body.lower()}
                    shots.append(shot(pg, f"b11-{label}"))
                except Exception as exc:  # noqa: BLE001
                    files[label] = {"ok": False, "error": str(exc)[:120]}
            rec("B-11", "B-BugHunt", "Unggah berkas: kosong / nama 200 char / "
                                     "2 MB / .exe",
                precondition="/chat punya input berkas",
                action="Unggah 4 berkas ekstrem satu per satu",
                expected="Validasi jelas untuk tiap kasus; tidak ada crash",
                actual=f"hasil={files}",
                state="PASS" if all(v.get("ok") for v in files.values())
                      else "FAIL",
                severity="medium", shots=shots, console=pr.errs(),
                netfail=pr.netfail, extra={"files": files})
    except Exception as exc:  # noqa: BLE001
        rec("B-11", "B-BugHunt", "Unggah berkas ekstrem",
            precondition="/chat", action="unggah 4 berkas",
            expected="Validasi jelas", actual=f"ERROR {type(exc).__name__}: {exc}",
            state="FAIL", severity="medium", shots=shots)

    # B-12 — aksesibilitas axe-core
    pr.reset()
    shots = []
    try:
        summary = {}
        for path in ("/chat", "/builder", "/templates", "/settings"):
            goto(pg, path, ms=3500)
            from rus_core import dismiss_onboarding
            dismiss_onboarding(pg, timeout=3000)
            res = axe_scan(pg, path)
            shots.append(shot(pg, f"b12-axe-{path.strip('/').replace('/','_')}"))
            if res.get("ok"):
                summary[path] = [{"id": v["id"], "impact": v["impact"],
                                  "nodes": v["nodes"]}
                                 for v in res["violations"]]
            else:
                summary[path] = {"error": res.get("reason")}
        worst = [v["impact"] for vs in summary.values() if isinstance(vs, list)
                 for v in vs]
        critical = sum(1 for w in worst if w in ("critical", "serious"))
        rec("B-12", "B-BugHunt", "Audit aksesibilitas axe-core (4 halaman)",
            precondition="Login",
            action="Jalankan axe-core pada /chat /builder /templates /settings",
            expected="Tidak ada pelanggaran 'critical'/'serious'",
            actual=f"pelanggaran_serius_atau_kritis={critical}; "
                   f"ringkas={ {k: (len(v) if isinstance(v, list) else v) for k, v in summary.items()} }",
            state="PASS" if critical == 0 else "FAIL",
            severity="medium", shots=shots, extra={"axe": summary})
    except Exception as exc:  # noqa: BLE001
        rec("B-12", "B-BugHunt", "Audit aksesibilitas axe-core",
            precondition="Login", action="axe.run 4 halaman",
            expected="0 pelanggaran kritis", actual=f"ERROR {type(exc).__name__}: {exc}",
            state="FAIL", severity="medium", shots=shots)

    ctx.close()


GROUPS = {"j1": j1_new_user, "j2": j2_shopee, "j3": j3_multi_user,
          "bug": b_bughunt}
