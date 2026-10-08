#!/usr/bin/env python
"""enterprise_sso_live.py — HARD TEST Fitur #7 (SSO/SAML/OIDC/LDAP) vs provider NYATA.

Tidak ada mock: setiap skenario berbicara dengan layanan yang benar-benar
berjalan.

  OIDC  : panva/oidc-provider 9.12.2  -> http://localhost:9443   (proses Node)
  LDAP  : glauth v2.5.4 (Go)          -> ldap://127.0.0.1:3893   (proses Go)
  SAML  : samlp 8.0.0 (Node)          -> http://localhost:7000   (proses Node)
  Google: https://accounts.google.com -> discovery + JWKS (internet nyata)

Pakai:
    python scripts/enterprise_sso_live.py
    python scripts/enterprise_sso_live.py --json docs/evidence/f07-sso-live.json
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sso  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OIDC_ISSUER = os.environ.get("KATALIR_TEST_OIDC", "http://localhost:9443")
OIDC_CLIENT = "katalir-app"
OIDC_SECRET = "katalir-oidc-secret"
OIDC_REDIRECT = "http://localhost:8123/sso/callback/oidc"
LDAP_URL = os.environ.get("KATALIR_TEST_LDAP", "ldap://127.0.0.1:3893")
LDAP_BASE = "dc=katalir,dc=test"
LDAP_BIND_DN = "cn=svc-bind,cn=svcaccts,ou=users,dc=katalir,dc=test"
LDAP_BIND_PW = "KatalirLdap2026!"
SAML_META = os.environ.get("KATALIR_TEST_SAML_META", "http://localhost:7000/metadata")
SAML_SSO = os.environ.get("KATALIR_TEST_SAML_SSO", "http://localhost:7000/saml/sso")

HASIL: list[dict] = []


def _catat(no: int, nama: str, lulus: bool, raw: str, detail: dict | None = None) -> None:
    HASIL.append({"no": no, "skenario": nama, "status": "PASS" if lulus else "FAIL",
                  "raw": raw, "detail": detail or {}})
    print(f"\n{'=' * 78}\n#{no:02d} [{'PASS' if lulus else 'FAIL'}] {nama}\n"
          f"{'-' * 78}\n{raw}\n", flush=True)


class _Captured(Exception):
    def __init__(self, url: str) -> None:
        self.url = url


class _StopAtCallback(urllib.request.HTTPRedirectHandler):
    """Hentikan rantai redirect tepat di `redirect_uri` (callback kita).

    Tanpa ini, urllib mencoba MEMBUKA callback (localhost:8123) yang tidak
    melayani apa pun dan melempar ConnectionRefused.
    """

    def __init__(self, stop_prefix: str) -> None:
        self.stop_prefix = stop_prefix

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if newurl.startswith(self.stop_prefix):
            raise _Captured(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _oidc_opener():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(jar),
        _StopAtCallback(OIDC_REDIRECT)), jar


def _transport(op=None):
    return sso.OidcHttpTransport(OIDC_ISSUER, OIDC_CLIENT, OIDC_SECRET,
                                 OIDC_REDIRECT, timeout=25.0, opener=op)


def _full_oidc_flow(login_hint: str = "user-alice"):
    """Authorization-code + PKCE lengkap. Return (claims, token, transport)."""
    op, _jar = _oidc_opener()
    t = _transport(op)
    state = sso.make_state()
    nonce = sso.secrets.token_urlsafe(16)
    verifier, _ = sso.make_pkce_pair()
    url = t.authorize_url(state, nonce, verifier, login_hint=login_hint)
    try:
        op.open(urllib.request.Request(url, headers={"User-Agent": "Katalir/1.0"}),
                timeout=40)
        raise AssertionError("callback tidak tercapai")
    except _Captured as cap:
        final = cap.url
    q = urllib.parse.parse_qs(urllib.parse.urlparse(final).query)
    if q.get("state") != [state]:
        raise AssertionError(f"state tidak cocok: {q.get('state')}")
    code = q.get("code", [""])[0]
    tok = t.exchange_code(code, verifier)
    claims = t.verify_id_token(tok["id_token"], nonce=nonce)
    return claims, tok, t, final


def _ldap():
    return sso.LdapDirectory(LDAP_URL, LDAP_BASE, LDAP_BIND_DN, LDAP_BIND_PW)


# ---------------------------------------------------------------------------
# 12 skenario
# ---------------------------------------------------------------------------

def s01_oidc_discovery() -> None:
    t = _transport()
    meta = t.discover()
    keys = t.jwks()
    raw = (f"issuer              = {meta.get('issuer')}\n"
           f"authorization_endpt = {meta.get('authorization_endpoint')}\n"
           f"token_endpoint      = {meta.get('token_endpoint')}\n"
           f"jwks_uri            = {meta.get('jwks_uri')}\n"
           f"userinfo_endpoint   = {meta.get('userinfo_endpoint')}\n"
           f"end_session_endpoint= {meta.get('end_session_endpoint')}\n"
           f"pkce_methods        = {meta.get('code_challenge_methods_supported')}\n"
           f"scopes_supported    = {meta.get('scopes_supported')}\n"
           f"JWKS kid            = {[k.get('kid') for k in keys.get('keys', [])]}\n"
           f"JWKS alg            = {[k.get('alg') for k in keys.get('keys', [])]}")
    lulus = (meta.get("issuer") == OIDC_ISSUER and meta.get("token_endpoint")
             and meta.get("jwks_uri") and "S256" in
             (meta.get("code_challenge_methods_supported") or [])
             and keys.get("keys"))
    _catat(1, "OIDC provider NYATA: discovery + JWKS", bool(lulus), raw,
           {"issuer": meta.get("issuer"), "jwks_kids":
            [k.get("kid") for k in keys.get("keys", [])]})


def s02_oidc_authcode_pkce() -> None:
    t0 = time.perf_counter()
    claims, tok, t, final = _full_oidc_flow("user-alice")
    ms = (time.perf_counter() - t0) * 1000
    raw = (f"flow                = authorization_code + PKCE (S256), REAL HTTP\n"
           f"callback            = {final[:96]}\n"
           f"token_type          = {tok.get('token_type')}  expires_in={tok.get('expires_in')}\n"
           f"id_token (potong)   = {tok['id_token'][:48]}…\n"
           f"access_token (potong)= {tok['access_token'][:32]}…\n"
           f"--- ID token claims (signature DIVERIFIKASI vs JWKS IdP) ---\n"
           f"iss    = {claims.get('iss')}\n"
           f"aud    = {claims.get('aud')}\n"
           f"sub    = {claims.get('sub')}\n"
           f"email  = {claims.get('email')}\n"
           f"name   = {claims.get('name')}\n"
           f"groups = {claims.get('groups')}\n"
           f"nonce  = cocok (diverifikasi)\n"
           f"durasi = {ms:.0f} ms")
    lulus = (claims.get("iss") == OIDC_ISSUER and claims.get("aud") == OIDC_CLIENT
             and claims.get("email") == "alice@acme.test"
             and "katalir-admins" in (claims.get("groups") or [])
             and tok.get("token_type", "").lower() == "bearer")
    _catat(2, "OIDC authorization-code + PKCE -> ID token nyata (RS256)", lulus, raw,
           {"email": claims.get("email"), "groups": claims.get("groups")})


def s03_oidc_userinfo_slo() -> None:
    claims, tok, t, _ = _full_oidc_flow("user-bob")
    ui = t.userinfo(tok["access_token"])
    end = t.end_session_url(tok["id_token"],
                            "http://localhost:8123/logged-out")
    raw = (f"userinfo endpoint (Bearer access_token NYATA):\n"
           f"  sub    = {ui.get('sub')}\n"
           f"  email  = {ui.get('email')}\n"
           f"  name   = {ui.get('name')}\n"
           f"  groups = {ui.get('groups')}\n"
           f"end_session (SLO) URL = {end[:110]}\n"
           f"  id_token_hint disertakan = {'id_token_hint=' in end}")
    lulus = (ui.get("email") == "bob@acme.test"
             and ui.get("groups") == ["engineering"]
             and "id_token_hint=" in end)
    _catat(3, "OIDC userinfo + URL SLO (end_session) nyata", lulus, raw,
           {"email": ui.get("email"), "slo": end[:60]})


def s04_google_oidc() -> None:
    """Google Workspace OIDC: discovery + JWKS dari internet NYATA."""
    t = sso.OidcHttpTransport("https://accounts.google.com",
                              "katalir-google-client", timeout=25.0)
    meta = t.discover()
    keys = t.jwks()
    kids = [k.get("kid") for k in keys.get("keys", [])]
    authz = t.authorize_url("state-x", "nonce-y", sso.make_pkce_pair()[0],
                            login_hint="user@example.com")
    raw = (f"issuer       = {meta.get('issuer')}\n"
           f"authz        = {meta.get('authorization_endpoint')}\n"
           f"token        = {meta.get('token_endpoint')}\n"
           f"jwks_uri     = {meta.get('jwks_uri')}\n"
           f"jumlah kunci = {len(kids)}  (kid contoh: {kids[:2]})\n"
           f"alg          = {sorted({k.get('alg') for k in keys.get('keys', [])})}\n"
           f"authorize URL dibentuk (PKCE S256): {authz[:120]}…\n"
           f"  code_challenge_method ada = "
           f"{'code_challenge_method=S256' in authz}")
    lulus = (meta.get("issuer") == "https://accounts.google.com"
             and len(kids) >= 1 and "code_challenge_method=S256" in authz)
    _catat(4, "Google Workspace OIDC: discovery + JWKS internet nyata", lulus, raw,
           {"issuer": meta.get("issuer"), "keys": len(kids)})


def s05_saml_real() -> None:
    """SAML 2.0: metadata IdP nyata + assertion bertanda tangan + verifikasi."""
    meta = sso.SamlVerifier.fetch_idp_metadata(SAML_META)
    cert = meta.get("cert", "")
    # minta assertion nyata dari IdP (endpoint POST /saml/sso)
    form = urllib.parse.urlencode({"email": "carol@globex.test",
                                   "groups": "katalir-owners"}).encode()
    op = sso.http_opener()
    req = urllib.request.Request(
        SAML_SSO, data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "Katalir-SSO/1.0"})
    st, body = None, ""
    try:
        r = op.open(req, timeout=30)
        st, body = r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        st, body = e.code, e.read().decode("utf-8", "replace")
    saml_response = ""
    try:
        saml_response = json.loads(body).get("SAMLResponse", "")
    except Exception:  # noqa: BLE001
        pass
    import base64 as _b64
    assertion_xml = ""
    if saml_response:
        assertion_xml = _b64.b64decode(saml_response).decode("utf-8", "replace")
    verified = False
    err = ""
    if assertion_xml:
        try:
            sso.SamlVerifier(cert).verify(assertion_xml)
            verified = True
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
    ident = None
    if assertion_xml:
        try:
            ident = sso.SamlProvider().parse_assertion(assertion_xml, org="globex")
        except Exception as exc:  # noqa: BLE001
            err = err or f"parse: {exc}"
    raw = (f"metadata IdP        = {SAML_META}\n"
           f"  entity_id         = {meta.get('entity_id')}\n"
           f"  SSO URL (Redirect)= {meta.get('sso_url')}\n"
           f"  sertifikat X.509  = {len(cert)} char\n"
           f"POST /saml/sso       -> HTTP {st}, panjang respons {len(body)}\n"
           f"SAMLResponse         = {len(saml_response)} char (base64)\n"
           f"assertion XML        = {len(assertion_xml)} char\n"
           f"verifikasi XML-DSig  = {verified}  {err}\n"
           f"identitas hasil parse= "
           f"{json.dumps(ident.to_dict()) if ident else 'None'}")
    lulus = (bool(meta.get("cert")) and bool(saml_response) and verified
             and ident is not None and ident.email == "carol@globex.test"
             and "katalir-owners" in ident.groups)
    _catat(5, "SAML 2.0 NYATA: metadata + assertion bertanda tangan + XML-DSig",
           lulus, raw, {"verified": verified, "email": ident.email if ident else None})


def s06_ldap_bind() -> None:
    d = _ldap()
    ok_svc = d.available()
    rec = d.find_user("alice@acme.test")
    ok_good = d.bind("alice@acme.test", "KatalirLdap2026!")
    ok_bad = d.bind("alice@acme.test", "password-salah")
    ok_nouser = d.bind("tidak-ada@nowhere.test", "KatalirLdap2026!")
    raw = (f"server            = {LDAP_URL}   (glauth v2.5.4, proses Go)\n"
           f"bind akun layanan = {LDAP_BIND_DN}\n"
           f"  available()     = {ok_svc}\n"
           f"cari mail=alice@acme.test:\n"
           f"  DN    = {rec['dn'] if rec else None}\n"
           f"  email = {rec['email'] if rec else None}\n"
           f"  name  = {rec['name'] if rec else None}\n"
           f"  groups= {rec['groups'] if rec else None}\n"
           f"bind password BENAR  -> {ok_good}\n"
           f"bind password SALAH  -> {ok_bad}  (harus False)\n"
           f"bind user TAK ADA    -> {ok_nouser}  (harus False)")
    lulus = (ok_svc and rec is not None and rec["email"] == "alice@acme.test"
             and "katalir-admins" in rec["groups"] and ok_good
             and not ok_bad and not ok_nouser)
    _catat(6, "LDAP NYATA: bind akun layanan + cari + bind pengguna", lulus, raw,
           {"dn": rec["dn"] if rec else None, "good": ok_good, "bad": ok_bad})


def s07_role_mapping() -> None:
    m = sso.SsoManager()
    m.register_org("acme", role_mapping={"katalir-admins": "admin",
                                         "engineering": "developer"},
                   domains=["acme.test"], default_role="viewer")
    m.register_org("globex", role_mapping={"katalir-owners": "owner"},
                   domains=["globex.test"])
    hasil = {}
    for hint, org_harap, role_harap in [
            ("user-alice", "acme", "admin"),
            ("user-bob", "acme", "developer"),
            ("user-carol", "globex", "owner")]:
        claims, tok, t, _ = _full_oidc_flow(hint)
        ident = sso.Identity(email=claims["email"], name=claims.get("name", ""),
                             groups=claims.get("groups") or [], provider="oidc",
                             subject=claims.get("sub", ""))
        sesi = m.login(ident)
        hasil[hint] = (sesi["org"], sesi["role"])
    raw = "klaim `groups` OIDC NYATA -> peran Katalir (grup terkuat menang):\n"
    for hint, (org, role) in hasil.items():
        raw += f"  {hint:12s} -> org={org:8s} role={role}\n"
    raw += (f"mapping acme   = {{'katalir-admins': 'admin', "
            f"'engineering': 'developer'}}\n"
            f"mapping globex = {{'katalir-owners': 'owner'}}")
    lulus = (hasil["user-alice"] == ("acme", "admin")
             and hasil["user-bob"] == ("acme", "developer")
             and hasil["user-carol"] == ("globex", "owner"))
    _catat(7, "Role mapping: grup SSO nyata -> peran Katalir", lulus, raw,
           {"hasil": {k: list(v) for k, v in hasil.items()}})


def s08_jit_provisioning() -> None:
    m = sso.SsoManager()
    m.register_org("acme", role_mapping={"engineering": "developer"},
                   domains=["acme.test"])
    sebelum = m.get_user("bob@acme.test")
    claims, tok, t, _ = _full_oidc_flow("user-bob")
    ident = sso.Identity(email=claims["email"], name=claims.get("name", ""),
                         groups=claims.get("groups") or [], provider="oidc",
                         subject=claims.get("sub", ""))
    sesi = m.login(ident)
    sesudah = m.get_user("bob@acme.test")
    raw = (f"sebelum login  : get_user('bob@acme.test') = {sebelum}\n"
           f"login OIDC nyata -> JIT provisioning\n"
           f"sesudah login  : {json.dumps(sesudah)}\n"
           f"session_id     = {sesi['session_id'][:18]}…\n"
           f"role           = {sesi['role']}\n"
           f"provider       = {sesudah['provider']}  active={sesudah['active']}")
    lulus = (sebelum is None and sesudah is not None
             and sesudah["email"] == "bob@acme.test"
             and sesudah["active"] is True and sesudah["provider"] == "oidc"
             and sesudah["groups"] == ["engineering"])
    _catat(8, "JIT provisioning: user dibuat otomatis saat login pertama", lulus, raw,
           {"user": sesudah})


def s09_deprovision() -> None:
    m = sso.SsoManager()
    m.register_org("acme", role_mapping={"engineering": "developer"},
                   domains=["acme.test"])
    claims, tok, t, _ = _full_oidc_flow("user-bob")
    ident = sso.Identity(email=claims["email"], name=claims.get("name", ""),
                         groups=claims.get("groups") or [], provider="oidc")
    s1 = m.login(ident)["session_id"]
    s2 = m.login(ident)["session_id"]
    hidup = [m.session(s1) is not None, m.session(s2) is not None]
    out = m.deprovision("bob@acme.test")
    mati = [m.session(s1) is None, m.session(s2) is None]
    u = m.get_user("bob@acme.test")
    raw = (f"2 sesi aktif      -> {hidup}\n"
           f"deprovision()     -> {json.dumps(out)}\n"
           f"sesi setelah      -> hidup? {[m.session(s1) is not None, m.session(s2) is not None]}\n"
           f"user.active       -> {u['active']}")
    lulus = (all(hidup) and out["deactivated"] is True
             and out["sessions_terminated"] == 2 and all(mati)
             and u["active"] is False)
    _catat(9, "Deprovisioning: user nonaktif + SEMUA sesinya dimatikan", lulus, raw,
           {"terminated": out["sessions_terminated"]})


def s10_session_timeout_slo() -> None:
    clock = {"t": 1000.0}
    m = sso.SsoManager(sessions=sso.SessionStore(clock=lambda: clock["t"]))
    m.register_org("acme", role_mapping={"engineering": "developer"},
                   domains=["acme.test"])
    claims, tok, t, _ = _full_oidc_flow("user-bob")
    ident = sso.Identity(email=claims["email"], name=claims.get("name", ""),
                         groups=claims.get("groups") or [], provider="oidc")
    sid = m.login(ident, ttl=60.0)["session_id"]
    hidup_awal = m.session(sid) is not None
    clock["t"] += 30
    hidup_30 = m.session(sid) is not None
    clock["t"] += 31  # total 61s > ttl 60s
    hidup_61 = m.session(sid) is not None
    # SLO: dua sesi, logout tunggal
    m2 = sso.SsoManager()
    m2.register_org("acme", role_mapping={}, domains=["acme.test"])
    a = m2.login(ident)["session_id"]
    b = m2.login(ident)["session_id"]
    n = m2.slo("bob@acme.test")
    raw = (f"ttl = 60s\n"
           f"  t+0s  sesi hidup = {hidup_awal}\n"
           f"  t+30s sesi hidup = {hidup_30}\n"
           f"  t+61s sesi hidup = {hidup_61}  (harus False -> kedaluwarsa)\n"
           f"SLO (Single Logout): 2 sesi -> slo() mematikan {n}\n"
           f"  sesi a hidup? {m2.session(a) is not None}  "
           f"sesi b hidup? {m2.session(b) is not None}")
    lulus = (hidup_awal and hidup_30 and not hidup_61 and n == 2
             and m2.session(a) is None and m2.session(b) is None)
    _catat(10, "Session timeout (TTL) + SLO logout tunggal", lulus, raw,
           {"expired": not hidup_61, "slo_terminated": n})


def s11_multitenant_csrf() -> None:
    m = sso.SsoManager()
    m.register_org("acme", role_mapping={"engineering": "developer"},
                   domains=["acme.test"])
    m.register_org("globex", role_mapping={"katalir-owners": "owner"},
                   domains=["globex.test"])
    org_acme = m.org_for_email("bob@acme.test")
    org_globex = m.org_for_email("carol@globex.test")
    org_unknown = m.org_for_email("eve@evil.test")
    # domain tak terdaftar -> login DITOLAK
    ditolak = ""
    try:
        m.login(sso.Identity(email="eve@evil.test", groups=["katalir-owners"]))
        ditolak = "TIDAK ditolak (BAHAYA)"
    except sso.AuthFailed as exc:
        ditolak = f"AuthFailed: {exc}"
    # CSRF: state salah
    st = m.begin("acme")
    csrf = ""
    try:
        m.login(sso.Identity(email="bob@acme.test", groups=["engineering"]),
                state="state-palsu", expect_state=st)
        csrf = "TIDAK ditolak (BAHAYA)"
    except sso.StateMismatch as exc:
        csrf = f"StateMismatch: {exc}"
    # state sekali pakai
    st2 = m.begin("acme")
    m.login(sso.Identity(email="bob@acme.test", groups=["engineering"]),
            state=st2, expect_state=st2)
    replay = ""
    try:
        m.login(sso.Identity(email="bob@acme.test", groups=["engineering"]),
                state=st2, expect_state=st2)
        replay = "TIDAK ditolak (BAHAYA)"
    except sso.StateMismatch as exc:
        replay = f"StateMismatch: {exc}"
    raw = (f"multi-tenant (domain -> org):\n"
           f"  bob@acme.test   -> {org_acme}\n"
           f"  carol@globex.test -> {org_globex}\n"
           f"  eve@evil.test   -> {org_unknown} (harus None)\n"
           f"login domain TAK terdaftar -> {ditolak}\n"
           f"CSRF: state palsu          -> {csrf}\n"
           f"CSRF: state dipakai ulang  -> {replay}")
    lulus = (org_acme == "acme" and org_globex == "globex" and org_unknown is None
             and ditolak.startswith("AuthFailed")
             and csrf.startswith("StateMismatch")
             and replay.startswith("StateMismatch"))
    _catat(11, "Multi-tenant (domain->org) + proteksi CSRF state", lulus, raw,
           {"orgs": [org_acme, org_globex, org_unknown]})


def s12_token_tidak_bocor() -> None:
    claims, tok, t, _ = _full_oidc_flow("user-alice")
    jwt_tok = tok["id_token"]
    blob = {
        "id_token": jwt_tok,
        "access_token": tok["access_token"],
        "note": f"Authorization: Bearer {jwt_tok}",
        "url": f"/cb?code=abc&SAMLResponse={'A' * 40}",
        "nested": {"k": [jwt_tok, "ok"]},
    }
    red = sso.redact(blob)
    txt = json.dumps(red)
    bocor = (jwt_tok in txt) or (tok["access_token"] in txt) \
        or ("A" * 40 in txt)
    # identitas hasil login juga tidak memuat token mentah
    ident = sso.Identity(email=claims["email"], groups=claims.get("groups") or [],
                         provider="oidc")
    raw = (f"id_token len       = {len(jwt_tok)}\n"
           f"access_token len   = {len(tok['access_token'])}\n"
           f"redact(blob)       = {txt[:220]}\n"
           f"token mentah bocor = {bocor}  (harus False)\n"
           f"Identity.to_dict() = {json.dumps(ident.to_dict())}\n"
           f"  memuat token?    = "
           f"{any(x in json.dumps(ident.to_dict()) for x in (jwt_tok, tok['access_token']))}")
    lulus = (not bocor and sso.MASK in txt
             and jwt_tok not in json.dumps(ident.to_dict()))
    _catat(12, "Token tidak bocor: redaksi JWT/Bearer/SAMLResponse", lulus, raw,
           {"bocor": bocor})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    print(f"# HARD TEST Fitur #7 SSO/SAML/OIDC/LDAP — provider NYATA\n"
          f"# OIDC={OIDC_ISSUER}  LDAP={LDAP_URL}  SAML={SAML_META}\n"
          f"# python={sys.version.split()[0]}\n")

    skenario = [s01_oidc_discovery, s02_oidc_authcode_pkce, s03_oidc_userinfo_slo,
                s04_google_oidc, s05_saml_real, s06_ldap_bind, s07_role_mapping,
                s08_jit_provisioning, s09_deprovision, s10_session_timeout_slo,
                s11_multitenant_csrf, s12_token_tidak_bocor]
    for fn in skenario:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            import traceback
            _catat(len(HASIL) + 1, fn.__name__, False,
                   f"EXCEPTION: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")

    lulus = sum(1 for h in HASIL if h["status"] == "PASS")
    total = len(HASIL)
    print("=" * 78)
    print(f"RINGKASAN HARD TEST FITUR #7: {lulus}/{total} PASS")
    print("=" * 78)
    for h in HASIL:
        print(f"  #{h['no']:02d} [{h['status']}] {h['skenario']}")

    if args.json:
        os.makedirs(os.path.dirname(args.json), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"feature": "#7 SSO/SAML/OIDC/LDAP", "lulus": lulus,
                       "total": total, "hasil": HASIL}, fh, indent=2,
                      ensure_ascii=False)
        print(f"\nJSON -> {args.json}")
    return 0 if lulus == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
