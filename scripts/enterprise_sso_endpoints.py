#!/usr/bin/env python
"""enterprise_sso_endpoints.py — Verifikasi endpoint /sso/* Fitur #7.

Membuktikan jalur PRODUKSI (HTTP API, bukan unit test) benar-benar terhubung
ke IdP NYATA:

  * OIDC  -> oidc-provider (panva) di http://localhost:9443
             authorization-code + PKCE SUNGGUHAN, lalu `code` ditukar oleh
             api_server ke token endpoint nyata dan ID token diverifikasi
             terhadap JWKS IdP.
  * SAML  -> samlp IdP di http://localhost:7000 (assertion bertanda tangan;
             XML-DSig diverifikasi signxml terhadap sertifikat IdP).
  * LDAP  -> glauth v2.5.4 di ldap://127.0.0.1:3893 (bind akun layanan ->
             cari DN -> bind pengguna; password dinilai oleh SERVER).

Pakai:
    python scripts/enterprise_sso_endpoints.py
    python scripts/enterprise_sso_endpoints.py --skip-prod
"""

from __future__ import annotations

import argparse
import base64
import http.cookiejar
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv_loader import load_repo_env  # noqa: E402

load_repo_env()

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMAIL = "otonom-test@katalir-internal.dev"
PASSWORD = "AutoTestKatalir2026!"

OIDC_ISSUER = "http://localhost:9443"
OIDC_CLIENT = "katalir-app"
OIDC_SECRET = "katalir-oidc-secret"
OIDC_REDIRECT = "http://localhost:8123/sso/callback/oidc"
SAML_META = "http://localhost:7000/metadata"
LDAP_URL = "ldap://127.0.0.1:3893"
LDAP_BASE = "dc=katalir,dc=test"
LDAP_BIND_DN = "cn=svc-bind,cn=svcaccts,dc=katalir,dc=test"
LDAP_BIND_PW = "KatalirLdap2026!"
LDAP_FILTER = "(mail={login})"
SAML_CERT = os.path.join("C:/katalir-sso", "idp-cert.pem")


def _opener(cookies: bool = False):
    handlers = [urllib.request.ProxyHandler({})]
    if cookies:
        handlers.append(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    return urllib.request.build_opener(*handlers)


def _call(op, url, method="GET", token=None, body=None, timeout=40):
    h = {"User-Agent": "KatalirSsoVerify/1.0", "Accept": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        r = op.open(req, timeout=timeout)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {str(e)[:250]}"


def mint_jwt(op) -> str:
    url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    pub = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_KEY") or ""
    body = json.dumps({"email": EMAIL, "password": PASSWORD}).encode()
    h = {"apikey": pub, "Content-Type": "application/json",
         "User-Agent": "KatalirSsoVerify/1.0"}
    req = urllib.request.Request(url + "/auth/v1/signup", data=body, headers=h)
    try:
        op.open(req, timeout=30).read()
    except Exception:  # noqa: BLE001
        pass
    req = urllib.request.Request(
        url + "/auth/v1/token?grant_type=password", data=body, headers=h)
    return json.loads(op.open(req, timeout=30).read())["access_token"]


def tunggu_sehat(op, base, batas=90) -> bool:
    t0 = time.time()
    while time.time() - t0 < batas:
        st, _ = _call(op, base + "/health")
        if st == 200:
            return True
        time.sleep(1.0)
    return False


# --- helper alur OIDC nyata (authorize -> code) ----------------------------
class _StopRedirect(urllib.request.HTTPRedirectHandler):
    """Berhenti pada redirect pertama ke redirect_uri -> ambil `code`."""

    def __init__(self, target: str) -> None:
        self.target = target
        self.captured = None

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if newurl.startswith(self.target):
            self.captured = newurl
            return None  # hentikan rantai redirect
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def oidc_get_code(login_hint: str = "user-alice") -> tuple[str, str, str]:
    """Jalankan authorize nyata; return (code, state, verifier)."""
    import sso as _sso
    stop = _StopRedirect(OIDC_REDIRECT)
    op = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), stop)
    t = _sso.OidcHttpTransport(OIDC_ISSUER, OIDC_CLIENT, OIDC_SECRET,
                               OIDC_REDIRECT, opener=op)
    state = _sso.make_state()
    nonce = _sso.secrets.token_urlsafe(16)
    verifier, _ = _sso.make_pkce_pair()
    url = t.authorize_url(state, nonce, verifier, login_hint=login_hint)
    try:
        op.open(urllib.request.Request(url, headers={"User-Agent": "Katalir/1.0"}),
                timeout=30)
    except urllib.error.HTTPError:
        pass  # redirect dihentikan sengaja
    if not stop.captured:
        raise RuntimeError("authorize tidak menghasilkan redirect ke callback")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(stop.captured).query)
    return q["code"][0], state, verifier


def saml_get_assertion(email: str = "carol@globex.test",
                       groups: str = "katalir-owners") -> str:
    """Minta SAMLResponse NYATA (base64) dari IdP samlp."""
    form = urllib.parse.urlencode({"email": email, "groups": groups}).encode()
    req = urllib.request.Request(
        "http://localhost:7000/saml/sso", data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "KatalirSsoVerify/1.0"})
    body = _opener().open(req, timeout=30).read().decode()
    return json.loads(body)["SAMLResponse"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8123)
    ap.add_argument("--redis", default="redis://127.0.0.1:6379/0")
    ap.add_argument("--prod", default="https://web-production-dc90b.up.railway.app")
    ap.add_argument("--skip-prod", action="store_true")
    args = ap.parse_args()

    op = _opener()
    hasil: dict = {}
    print("# VERIFIKASI ENDPOINT /sso/* — Fitur #7 (SSO/SAML/OIDC/LDAP)")
    print(f"# OIDC  = {OIDC_ISSUER}\n# SAML  = {SAML_META}\n# LDAP  = {LDAP_URL}\n")

    cert = ""
    if os.path.exists(SAML_CERT):
        cert = open(SAML_CERT, encoding="utf-8").read().strip()

    sso_cfg = {
        "orgs": {
            "acme": {
                "role_mapping": {"katalir-admins": "admin",
                                 "katalir-owners": "owner",
                                 "engineering": "developer"},
                "domains": ["acme.test", "globex.test"],
                "default_role": "viewer",
            }
        },
        "oidc": {"issuer": OIDC_ISSUER, "client_id": OIDC_CLIENT,
                 "client_secret": OIDC_SECRET, "redirect_uri": OIDC_REDIRECT},
        "ldap": {"server_url": LDAP_URL, "base_dn": LDAP_BASE,
                 "bind_dn": LDAP_BIND_DN, "bind_password": LDAP_BIND_PW,
                 "user_filter": LDAP_FILTER},
        "saml": {"metadata_url": SAML_META, "cert": cert,
                 "sso_url": "http://localhost:7000/saml/sso"},
    }

    tok = mint_jwt(op)
    print(f"JWT diperoleh: prefix={tok[:12]}... len={len(tok)}\n")

    env = dict(os.environ)
    env["KATALIR_SSO_CONFIG"] = json.dumps(sso_cfg)
    env["KATALIR_SSO_ADMINS"] = EMAIL
    # Sesi SSO disimpan di Redis (durable + lintas proses). Wajib ada supaya
    # /sso/session & SLO terbukti memakai store NYATA, bukan memori proses.
    env["KATALIR_REDIS_URL"] = args.redis
    env["PYTHONUNBUFFERED"] = "1"
    logpath = os.path.join(HERE, "docs", "evidence", "f07-server.log")
    log = open(logpath, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api_server:app",
         "--host", "127.0.0.1", "--port", str(args.port), "--log-level", "warning"],
        cwd=HERE, env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://localhost:{args.port}"
    try:
        if not tunggu_sehat(op, base):
            print("!! server tidak sehat; log:")
            print(open(logpath, encoding="utf-8").read()[-3000:])
            return 1
        print(f"server siap di {base} (PID {proc.pid})\n")

        # 1. /sso/providers -> provider aktif
        st, b = _call(op, base + "/sso/providers")
        print(f"### GET /sso/providers -> HTTP {st}\n{b}\n")
        hasil["providers"] = json.loads(b) if st == 200 else {}

        # 2. /sso/discovery -> probe NYATA ke IdP
        st, b = _call(op, base + "/sso/discovery", token=tok)
        print(f"### GET /sso/discovery -> HTTP {st}\n{json.dumps(json.loads(b), indent=1) if st == 200 else b}\n")
        hasil["discovery"] = json.loads(b) if st == 200 else {}

        # 3. OIDC login NYATA (code dari authorize sungguhan)
        code, state, verifier = oidc_get_code("user-alice")
        print(f"### OIDC authorize NYATA -> code={code[:20]}… state={state[:12]}…")
        st, b = _call(op, base + "/sso/login/oidc", method="POST", token=tok,
                      body={"code": code, "code_verifier": verifier, "org": "acme"})
        print(f"### POST /sso/login/oidc -> HTTP {st}\n{b}\n")
        hasil["oidc_login"] = json.loads(b) if st == 200 else {"raw": b}

        # 4. LDAP login NYATA (bind layanan -> cari -> bind user)
        st, b = _call(op, base + "/sso/login/ldap", method="POST", token=tok,
                      body={"username": "alice@acme.test",
                            "password": LDAP_BIND_PW, "org": "acme"})
        print(f"### POST /sso/login/ldap (alice, benar) -> HTTP {st}\n{b}\n")
        hasil["ldap_login_ok"] = json.loads(b) if st == 200 else {"raw": b}

        # 4b. LDAP password SALAH harus 401
        st, b = _call(op, base + "/sso/login/ldap", method="POST", token=tok,
                      body={"username": "alice@acme.test",
                            "password": "salah-banget", "org": "acme"})
        print(f"### POST /sso/login/ldap (alice, SALAH) -> HTTP {st} (harus 401)\n{b}\n")
        hasil["ldap_login_bad"] = {"status": st, "body": b}

        # 5. SAML login NYATA (assertion bertanda tangan + XML-DSig)
        assertion = saml_get_assertion()
        print(f"### SAML IdP -> SAMLResponse {len(assertion)} char (base64)")
        st, b = _call(op, base + "/sso/login/saml", method="POST", token=tok,
                      body={"assertion": assertion, "org": "acme", "verify": True})
        print(f"### POST /sso/login/saml (tanda tangan DIVERIFIKASI) -> HTTP {st}\n{b}\n")
        hasil["saml_login"] = json.loads(b) if st == 200 else {"raw": b}

        # 5b. SAML assertion DIPALSUKAN (tanda tangan rusak) harus 401
        bad = base64.b64encode(
            base64.b64decode(assertion).replace(b"carol@globex.test",
                                                 b"attacker@evil.test")).decode()
        st, b = _call(op, base + "/sso/login/saml", method="POST", token=tok,
                      body={"assertion": bad, "org": "acme", "verify": True})
        print(f"### POST /sso/login/saml (assertion DIMODIFIKASI) -> HTTP {st} (harus 401)\n{b}\n")
        hasil["saml_tamper"] = {"status": st, "body": b}

        # 6. /sso/session/{id}
        sid = ""
        if isinstance(hasil.get("oidc_login"), dict):
            sid = ((hasil["oidc_login"].get("login") or {}).get("session_id") or "")
        st, b = _call(op, base + f"/sso/session/{sid}", token=tok)
        print(f"### GET /sso/session/{sid[:14]}… -> HTTP {st}\n{b}\n")
        hasil["session"] = json.loads(b) if st == 200 else {"raw": b}

        # 7. /sso/logout (SLO semua sesi email)
        st, b = _call(op, base + "/sso/logout", method="POST", token=tok,
                      body={"email": "alice@acme.test"})
        print(f"### POST /sso/logout (SLO alice) -> HTTP {st}\n{b}\n")
        hasil["logout"] = json.loads(b) if st == 200 else {"raw": b}

        # 8. /sso/config GET -> kredensial DIMASK
        st, b = _call(op, base + "/sso/config", token=tok)
        pub = json.loads(b) if st == 200 else {}
        print(f"### GET /sso/config -> HTTP {st} (client_secret & bind_password harus '***')")
        print(json.dumps(pub.get("config", {}), indent=1)[:700], "\n")
        hasil["config_get"] = pub

        # 9. /sso/config POST -> rahasia '***' DIPERTAHANKAN
        st, b = _call(op, base + "/sso/config", method="POST", token=tok,
                      body={"config": {"ldap": {"bind_password": "***"},
                                       "orgs": {"acme": {"default_role": "developer"}}}})
        print(f"### POST /sso/config (kirim '***') -> HTTP {st}\n{b[:400]}\n")
        hasil["config_post"] = json.loads(b) if st == 200 else {"raw": b}

        # 10. /sso/ui -> 200 HTML
        st, b = _call(op, base + "/sso/ui")
        print(f"### GET /sso/ui -> HTTP {st}, {len(b)} byte, "
              f"judul ada = {'Admin SSO' in b or 'SSO' in b}\n")
        hasil["ui"] = {"status": st, "len": len(b)}

        # 11. tanpa token -> 401
        st, b = _call(op, base + "/sso/config")
        print(f"### GET /sso/config tanpa token -> HTTP {st} (harus 401)\n")
        hasil["no_token"] = {"status": st}
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=15)
        except Exception:  # noqa: BLE001
            proc.kill()

    out = os.path.join(HERE, "docs", "evidence", "f07-endpoints.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(hasil, fh, indent=2, ensure_ascii=False)
    print(f"# tersimpan: {out}")

    # 12. produksi (bila endpoint sudah ter-deploy)
    if not args.skip_prod:
        print(f"\n# === PRODUKSI {args.prod} ===")
        for path in ("/sso/providers", "/sso/ui"):
            st, b = _call(op, args.prod + path, timeout=60)
            print(f"  GET {path:20s} -> HTTP {st} "
                  f"({'ok' if st == 200 else str(b)[:120]})")
        st, b = _call(op, args.prod + "/sso/config", token=tok, timeout=60)
        print(f"  GET /sso/config (token) -> HTTP {st} "
              f"{'(butuh deploy baru)' if st == 404 else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
