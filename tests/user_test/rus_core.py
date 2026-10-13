"""Inti harness REAL USER SIMULATION — Katalir (13 Okt 2026).

Disiplin (dari skill `ux-quality-perspective` + `manual-testing` +
`edge-case-discovery`, klon di D:/caches/qa-skills):
  * state hanya PASS/FAIL/BLOCKED/NOT_RUN — tidak ada klaim tanpa bukti;
  * pisahkan fakta / bukti / inferensi / celah;
  * screenshot hanya membuktikan sel yang TERLIHAT;
  * setiap temuan menyimpan: trigger, dampak, bukti, validasi.

Modul ini TIDAK menjalankan skenario; ia hanya menyediakan alat.
Skenario ada di `rus_run.py`.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.request
import uuid

# Proxy lingkungan kadang memotong koneksi ke Supabase/Cloudflare.
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
           "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
UT = ROOT / "tests" / "user_test"
EV = ROOT / "docs" / "evidence" / "real-user-2026-10-13"
VID = EV / "video"
LOG = EV / "logs"
for _d in (EV, VID, LOG):
    _d.mkdir(parents=True, exist_ok=True)

FRONTEND = os.environ.get("RUS_FRONTEND", "https://katalir.de5.net")
BACKEND = "https://gateway.katalir.de5.net/katalir-api"
UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# Sesi akun uji: pakai akun KHUSUS run final bila ada (kuota harian penuh),
# kalau tidak jatuh ke sesi lama. Lihat rus_newuser.py.
_SESS_FILE = UT / "_session_rus.json"
if not _SESS_FILE.exists():
    _SESS_FILE = UT / "_session.json"
SESS = json.loads(_SESS_FILE.read_text(encoding="utf-8"))
SESSION_FILE = _SESS_FILE
STORAGE_KEY = SESS["storage_key"]
SESSION_OBJ = SESS["session"]
EMAIL = SESSION_OBJ["user"]["email"]
TOKEN = SESSION_OBJ["access_token"]

_AXE_PATH = ROOT / "nexus-frontend" / "node_modules" / "axe-core" / "axe.min.js"
AXE_SRC = _AXE_PATH.read_text(encoding="utf-8") if _AXE_PATH.exists() else ""


# ─────────────────────────── env / supabase admin ───────────────────────────

def env_get(name: str) -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8",
                                          errors="replace").splitlines():
        line = line.strip().lstrip("\ufeff")
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if k.strip() == name:
                return v.strip().strip('"').strip("'").strip()
    return ""


SB = env_get("SUPABASE_URL")
SVC = env_get("SUPABASE_SERVICE_ROLE_KEY") or env_get("SUPABASE_SERVICE_KEY")
ANON = env_get("SUPABASE_PUBLISHABLE_KEY") or env_get("SUPABASE_KEY")
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _http(method, url, body=None, headers=None, timeout=60):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers=headers or {"Content-Type": "application/json"})
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def api(method, path, body=None, token=None, ua=UA_BROWSER, timeout=90):
    """Panggil backend produksi. UA browser WAJIB (Cloudflare 1010)."""
    h = {"Content-Type": "application/json", "User-Agent": ua,
         "Accept": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return _http(method, f"{BACKEND}{path}", body, h, timeout)


def sb_admin(method, path, body=None):
    return _http(method, f"{SB}{path}", body,
                 {"apikey": SVC, "Authorization": f"Bearer {SVC}",
                  "Content-Type": "application/json"}, 60)


def make_user(tag="rus"):
    """Buat user Supabase NYATA sementara (untuk uji multi-user)."""
    email = f"{tag}-{uuid.uuid4().hex[:8]}@katalir-internal.dev"
    pwd = "Rs-" + uuid.uuid4().hex[:16] + "!9"
    st, body = sb_admin("POST", "/auth/v1/admin/users",
                        {"email": email, "password": pwd,
                         "email_confirm": True})
    if st not in (200, 201):
        return None
    uid = json.loads(body).get("id")
    st2, body2 = _http("POST", f"{SB}/auth/v1/token?grant_type=password",
                       {"email": email, "password": pwd},
                       {"apikey": ANON, "Content-Type": "application/json"}, 60)
    if st2 != 200:
        return {"id": uid, "email": email, "password": pwd, "session": None}
    tok = json.loads(body2)
    return {"id": uid, "email": email, "password": pwd, "session": tok}


def drop_user(uid):
    if uid:
        sb_admin("DELETE", f"/auth/v1/admin/users/{uid}")


def sb_session_payload(tok_obj, ref):
    """Bentuk objek sesi supabase-js v2 dari respons token."""
    return {
        "access_token": tok_obj["access_token"],
        "token_type": tok_obj.get("token_type", "bearer"),
        "expires_in": tok_obj.get("expires_in", 3600),
        "expires_at": tok_obj.get("expires_at"),
        "refresh_token": tok_obj.get("refresh_token"),
        "user": tok_obj.get("user"),
    }


REF = (SB or "").replace("https://", "").split(".")[0]


# ─────────────────────────────── hasil / rekaman ────────────────────────────

RESULTS: list[dict] = []


def rec(sid, persona, title, *, precondition, action, expected, actual,
        state, severity="?", shots=None, seconds=None, console=None,
        netfail=None, extra=None, evidence_note=None):
    RESULTS.append({
        "id": sid, "persona": persona, "title": title,
        "precondition": precondition, "action": action,
        "expected": expected, "actual": actual, "state": state,
        "severity": severity, "seconds": seconds,
        "screenshots": [str(s) for s in (shots or [])],
        "console_errors": (console or [])[:10],
        "failed_requests": (netfail or [])[:10],
        "extra": extra or {}, "evidence_note": evidence_note,
    })
    icon = {"PASS": "[PASS]", "FAIL": "[FAIL]",
            "BLOCKED": "[BLK]", "NOT_RUN": "[SKIP]"}.get(state, "[???]")
    print(f"  {icon} {sid} {title}  :: {str(actual)[:120]}", flush=True)


def dump(group):
    out = UT / f"_rus_{group}.json"
    out.write_text(json.dumps({"group": group, "email": EMAIL,
                               "count": len(RESULTS),
                               "results": RESULTS},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nbukti -> {out}", flush=True)
    return out


# ─────────────────────────────── playwright alat ────────────────────────────

def shot(pg, name):
    p = EV / f"{name}.png"
    try:
        pg.screenshot(path=str(p), full_page=True, timeout=20000)
    except Exception:  # noqa: BLE001
        try:
            pg.screenshot(path=str(p), timeout=20000)
        except Exception:  # noqa: BLE001
            return None
    return p


class Probe:
    """Rekam console error + request gagal + respons non-2xx."""

    def __init__(self, pg, name="page"):
        self.pg = pg
        self.name = name
        self.console: list = []
        self.netfail: list = []
        self.bad: list = []
        self.chat_posts: list = []
        pg.on("request", self._on_req)
        pg.on("console", self._on_console)
        pg.on("pageerror", lambda e: self.console.append(
            {"type": "pageerror", "text": str(e)[:240]}))
        pg.on("requestfailed", lambda r: self.netfail.append(
            {"url": r.url[:160], "failure": str(r.failure or "")[:140]}))
        pg.on("response", self._on_resp)

    def _on_req(self, r):
        try:
            if r.method == "POST" and r.url.rstrip("/").endswith("/chat"):
                self.chat_posts.append(r.url[:120])
        except Exception:  # noqa: BLE001
            pass

    def _on_console(self, m):
        if m.type in ("error", "warning"):
            self.console.append({"type": m.type, "text": m.text[:240]})

    def _on_resp(self, r):
        try:
            if r.status >= 400 and "cloudflareinsights" not in r.url:
                self.bad.append({"status": r.status, "url": r.url[:160]})
        except Exception:  # noqa: BLE001
            pass

    def reset(self):
        self.console.clear()
        self.netfail.clear()
        self.bad.clear()
        self.chat_posts.clear()

    def errs(self):
        return [c for c in self.console if c["type"] in ("error", "pageerror")]


def proxy_backend(ctx, base=None, on_call=None):
    """Proksi backend lewat Playwright + tambahkan header CORS permisif.

    Kenapa perlu: perbaikan frontend harus bisa diuji LOKAL (server statis di
    127.0.0.1) sebelum dideploy. Backend produksi hanya mengizinkan origin
    produksi, jadi preflight dari `http://127.0.0.1:<port>` ditolak CORS dan
    SEMUA request gagal — pengujian lokal jadi tidak bermakna (dan bisa
    menyesatkan: gejalanya "error card" yang tidak ada hubungannya dengan bug).

    Fungsi ini memenuhi request dari Python (urllib) memakai origin produksi,
    lalu mengembalikannya ke browser dengan `Access-Control-Allow-Origin: *`
    sehingga browser menerimanya. Isi respons TIDAK diubah.
    """
    root = (base or BACKEND).rstrip("/")
    prod_origin = "https://katalir.de5.net"

    def _handler(route):
        req = route.request
        try:
            if req.method == "OPTIONS":
                route.fulfill(status=204, headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                    "Access-Control-Max-Age": "600",
                }, body="")
                return
            url = req.url
            path = url.split(root, 1)[1] if root in url else "/"
            if on_call:
                try:
                    on_call(req.method, path)
                except Exception:  # noqa: BLE001
                    pass
            headers = {k: v for k, v in req.headers.items()
                       if k.lower() not in ("host", "content-length",
                                            "origin", "referer",
                                            "accept-encoding")}
            headers["Origin"] = prod_origin
            data = req.post_data.encode("utf-8") if req.post_data else None
            rq = urllib.request.Request(root + path, data=data,
                                       headers=headers, method=req.method)
            try:
                with urllib.request.urlopen(rq, timeout=180) as resp:
                    body = resp.read()
                    st = resp.status
                    ct = resp.headers.get("Content-Type", "application/json")
            except urllib.error.HTTPError as he:
                body = he.read()
                st = he.code
                ct = he.headers.get("Content-Type", "application/json")
            route.fulfill(status=st, headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
                "Content-Type": ct,
            }, body=body)
        except Exception:  # noqa: BLE001
            try:
                route.continue_()
            except Exception:  # noqa: BLE001
                pass

    ctx.route("**/katalir-api/**", _handler)
    return _handler


def new_ctx(b, *, width=1440, height=900, locale="id-ID", video=False,
            mobile=False, scale=1):
    kw = {"viewport": {"width": width, "height": height}, "locale": locale}
    if scale != 1:
        kw["device_scale_factor"] = scale
    if mobile:
        kw["is_mobile"] = True
        kw["has_touch"] = True
        kw["user_agent"] = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like "
                            "Mac OS X) AppleWebKit/605.1.15 (KHTML, like "
                            "Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
    if video:
        kw["record_video_dir"] = str(VID)
        kw["record_video_size"] = {"width": 1280, "height": 720}
    return b.new_context(**kw)


def settle(pg, ms=2500):
    pg.wait_for_timeout(ms)


def goto(pg, path, wait="domcontentloaded", timeout=60000, ms=3000):
    t0 = time.time()
    pg.goto(f"{FRONTEND}{path}", wait_until=wait, timeout=timeout)
    settle(pg, ms)
    return round(time.time() - t0, 2)


def goto_stat(pg, path, timeout=60000, ms=2600):
    """Buka rute dan kembalikan status HTTP nyata + waktu muat."""
    t0 = time.time()
    st = None
    try:
        resp = pg.goto(f"{FRONTEND}{path}", wait_until="domcontentloaded",
                       timeout=timeout)
        st = resp.status if resp else None
    except Exception as exc:  # noqa: BLE001
        st = f"ERR:{type(exc).__name__}"
    settle(pg, ms)
    return {"path": path, "status": st, "sec": round(time.time() - t0, 2)}


def inject_session(pg, session_obj=None, email=None):
    """Tanam sesi Supabase (kunci yang dibaca supabase-js v2)."""
    obj = session_obj or SESSION_OBJ
    key = f"sb-{REF}-auth-token" if session_obj else STORAGE_KEY
    pg.evaluate("([k,v]) => { try { localStorage.setItem(k, v); } catch(e){} }",
                [key, json.dumps(obj)])
    return key


def dismiss_onboarding(pg, timeout=6000):
    """Wizard onboarding menghalangi; user nyata menutupnya."""
    for sel in ('[data-testid="onboarding-skip"]',):
        try:
            el = pg.locator(sel)
            if el.count() and el.first.is_visible():
                el.first.click(timeout=4000)
                settle(pg, 900)
                return "onboarding-skip"
        except Exception:  # noqa: BLE001
            pass
    for label in ("Lewati", "Tutup", "Nanti saja", "Skip"):
        try:
            el = pg.get_by_role("button", name=label, exact=False)
            if el.count() and el.first.is_visible():
                el.first.click(timeout=4000)
                settle(pg, 900)
                return label
        except Exception:  # noqa: BLE001
            continue
    return None


def login(pg, session_obj=None):
    """Buka /chat dengan sesi terpasang + onboarding dilewati."""
    goto(pg, "/chat", ms=2500)
    inject_session(pg, session_obj)
    pg.reload(wait_until="domcontentloaded", timeout=60000)
    settle(pg, 3000)
    skip = dismiss_onboarding(pg)
    return skip


COMPOSER = '[data-testid="chat-composer"] textarea, textarea'
MSGLIST = '[data-testid="msg-list"]'


# Footer yang HANYA muncul di bawah balasan asisten, mis.
# "gemini-3.5-flash-lite · 11.9s · 4506→72 tok". Jauh lebih andal daripada
# membandingkan panjang teks (UI "berpikir" bisa menyusut saat jawaban final
# menggantikannya).
_ASSIST_RE = re.compile(r"\u2192\s*\d+\s*tok")


def assistant_replies(pg):
    try:
        return len(_ASSIST_RE.findall(msg_text(pg)))
    except Exception:  # noqa: BLE001
        return 0


def msg_text(pg):
    try:
        el = pg.locator(MSGLIST)
        if el.count():
            return el.first.inner_text(timeout=4000)
    except Exception:  # noqa: BLE001
        pass
    try:
        return pg.inner_text("body")
    except Exception:  # noqa: BLE001
        return ""


def msglist_text(pg):
    """Teks HANYA dari area percakapan ([data-testid="msg-list"]).

    Berbeda dari msg_text() yang jatuh ke seluruh <body> bila msg-list tidak
    ada. Fallback itu pernah menghasilkan kesimpulan PALSU: judul sesi di
    sidebar mengandung penanda, sehingga "pesan tampil di layar" terbaca True
    padahal area percakapan kosong. Pakai fungsi ini bila pertanyaannya
    "apakah isi percakapan benar-benar ditampilkan?".
    """
    try:
        el = pg.locator(MSGLIST)
        if el.count():
            return el.first.inner_text(timeout=4000)
    except Exception:  # noqa: BLE001
        pass
    return ""


def sidebar_text(pg):
    try:
        el = pg.locator("aside")
        if el.count():
            return el.first.inner_text(timeout=4000)
    except Exception:  # noqa: BLE001
        pass
    return ""


def send_measured(pg, text, max_wait=90.0, poll=0.4, label="", enter=True):
    """Kirim pesan seperti user lalu UKUR waktu balasan.

    Mengembalikan dict: t_echo, t_reply, t_done, status, reply_tail, len.
    t_reply = pertumbuhan teks pertama SETELAH bubble user sendiri berhenti
    tumbuh (jadi ini mendekati waktu token pertama balasan asisten).
    """
    ta = pg.locator(COMPOSER).first
    ta.click(timeout=15000)
    try:
        ta.fill("")
        ta.fill(text)
    except Exception:  # noqa: BLE001
        ta.press("Control+A")
        pg.keyboard.type(text[:4000])
    base = len(msg_text(pg))
    base_replies = assistant_replies(pg)
    t0 = time.time()
    if enter:
        ta.press("Enter")
    else:
        btn = pg.locator('[data-testid="chat-composer"] button[type="submit"]')
        if btn.count():
            btn.first.click(timeout=8000)
        else:
            ta.press("Enter")

    t_echo = None
    t_reply = None
    t_marker = None
    last_len = base
    stable = 0
    growths = 0
    status = "timeout"
    # Penanda "aplikasi masih bekerja" dari UI sendiri. Dipakai agar kita tidak
    # menyimpulkan "tidak ada balasan" padahal aplikasi masih memproses.
    # Sengaja SPESIFIK: frasa umum seperti "memproses"/"menunggu" muncul di
    # teks lain (mis. catatan form kredensial) dan pernah membuat balasan yang
    # SUDAH tiba dinilai "echo_only" (J1-B).
    def _busy(txt):
        low = txt.lower()
        return any(w in low for w in ("agen sedang berpikir",
                                      "sedang memproses",
                                      "sedang berpikir"))
    while time.time() - t0 < max_wait:
        pg.wait_for_timeout(int(poll * 1000))
        body = msg_text(pg)
        n = len(body)
        replies_now = len(_ASSIST_RE.findall(body))
        err = ("Gagal mengirim" in body or "Koneksi lambat" in body
               or "Coba Lagi" in body)
        if n != last_len:
            growths += 1
            if growths == 1:
                t_echo = round(time.time() - t0, 2)     # bubble user muncul
            elif t_reply is None:
                # FIX harness 13 Okt (2): sebelumnya perubahannya hanya dihitung
                # saat teks MEMANJANG. UI "sedang berpikir" (chain-of-thought)
                # panjang lalu menyusut saat jawaban final menggantikannya,
                # sehingga pertumbuhan kedua tidak pernah terdeteksi dan
                # skenario dilaporkan timeout PALSU. Sekarang setiap PERUBAHAN
                # dihitung.
                t_reply = round(time.time() - t0, 2)
            last_len = n
            stable = 0
        else:
            stable += 1
        # FIX harness 13 Okt (3): status HANYA ditentukan oleh penanda balasan
        # asisten (`→ N tok`) atau kartu galat. Sebelumnya status "replied"
        # bisa muncul hanya karena indikator "Sedang memproses..." berubah lalu
        # diam 1,6 s -> skenario menilai isi balasan yang BELUM ada (mis.
        # P2-02 melaporkan kata_bimbingan=0 padahal balasan belum tiba).
        if replies_now > base_replies:
            t_marker = round(time.time() - t0, 2)
            status = "replied"
            break
        # Cadangan: sebagian balasan mungkin tidak menampilkan footer token.
        # Dianggap selesai hanya bila teks benar-benar bertambah banyak DAN
        # aplikasi tidak lagi menyatakan sedang bekerja.
        if (t_reply is not None and stable >= 6 and not _busy(body)
                and n > base + 40):
            status = "replied"
            break
        if err:
            status = "error"
            break
        # Bubble user sudah muncul, tidak ada perubahan selama ~16 s, DAN
        # aplikasi tidak menyatakan sedang bekerja -> memang tidak ada balasan.
        if t_echo is not None and stable >= 40 and not _busy(body):
            status = "echo_only"
            break
    t_done = round(time.time() - t0, 2)
    body = msg_text(pg)
    if status == "timeout" and assistant_replies(pg) > base_replies:
        status = "replied"
    if status == "replied" and t_reply is None:
        t_reply = t_marker
    return {"t_echo": t_echo, "t_reply": t_reply, "t_done": t_done,
            "t_marker": t_marker, "status": status, "len": len(body),
            "reply_tail": body[-600:], "growths": growths,
            "replies": assistant_replies(pg),
            "base_replies": base_replies, "label": label}


def visible_error_card(pg):
    try:
        el = pg.locator('[data-testid="error-card"]')
        return el.count() > 0 and el.first.is_visible()
    except Exception:  # noqa: BLE001
        return False


def throttle(ctx, pg, down_kbps=400, up_kbps=160, latency=500):
    """Simulasi jaringan lambat (CDP). Nilai dalam kbps."""
    cdp = ctx.new_cdp_session(pg)
    cdp.send("Network.enable")
    cdp.send("Network.emulateNetworkConditions", {
        "offline": False,
        "downloadThroughput": int(down_kbps * 1024 / 8),
        "uploadThroughput": int(up_kbps * 1024 / 8),
        "latency": latency,
    })
    return cdp


def set_offline(ctx, pg, offline=True):
    cdp = ctx.new_cdp_session(pg)
    cdp.send("Network.enable")
    cdp.send("Network.emulateNetworkConditions", {
        "offline": offline, "downloadThroughput": -1,
        "uploadThroughput": -1, "latency": 0})
    return cdp


def axe_scan(pg, tag):
    """Audit aksesibilitas dengan axe-core (disuntik dari node_modules)."""
    if not AXE_SRC:
        return {"ok": False, "reason": "axe-core tidak ditemukan"}
    try:
        pg.add_script_tag(content=AXE_SRC)
        res = pg.evaluate("""async () => {
            const r = await axe.run(document, {resultTypes: ['violations']});
            return r.violations.map(v => ({
              id: v.id, impact: v.impact, help: v.help,
              nodes: v.nodes.length,
              sample: (v.nodes[0] && v.nodes[0].target || []).join(' '),
            }));
        }""")
        return {"ok": True, "violations": res}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"{type(exc).__name__}: {str(exc)[:160]}"}


def netlog_attach(ctx, path):
    """Catat semua request/response ke JSONL (bukan HAR; log terstruktur)."""
    fh = open(path, "a", encoding="utf-8")

    def on_req(r):
        try:
            fh.write(json.dumps({"k": "req", "m": r.method, "u": r.url[:300],
                                 "t": time.time()}) + "\n")
            fh.flush()
        except Exception:  # noqa: BLE001
            pass

    def on_resp(r):
        try:
            fh.write(json.dumps({"k": "res", "s": r.status, "u": r.url[:300],
                                 "t": time.time()}) + "\n")
            fh.flush()
        except Exception:  # noqa: BLE001
            pass

    ctx.on("request", on_req)
    ctx.on("response", on_resp)
    return fh
