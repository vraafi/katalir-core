# tests/test_sso.py — Fitur #7 hard test (12 skenario, Okt 2026)
# Deterministik, tanpa jaringan: provider memakai claims/directory yang disuntik.
from __future__ import annotations

import pytest

import sso


def _mgr():
    clock = {"t": 1000.0}
    store = sso.SessionStore(clock=lambda: clock["t"])
    m = sso.SsoManager(sessions=store)
    m.register_org("acme", role_mapping={"admins": "admin", "devs": "developer"},
                   domains=["acme.com"], default_role="viewer")
    return m, clock


# 1. OIDC login -> OK
def test_01_oidc_login():
    m, _ = _mgr()
    prov = sso.OidcProvider("client-1", "https://idp.example.com")
    st = m.begin("acme")
    url = prov.authorize_url("https://app/cb", st)
    assert "state=" + st in url and "client_id=client-1" in url
    ident = prov.exchange("code-xyz", claims={
        "email": "budi@acme.com", "name": "Budi", "groups": ["devs"],
        "sub": "u-1"})
    hasil = m.login(ident, state=st, expect_state=st)
    assert hasil["role"] == "developer" and hasil["org"] == "acme"
    assert m.session(hasil["session_id"]) is not None


# 2. SAML login -> OK
def test_02_saml_login():
    m, _ = _mgr()
    prov = sso.SamlProvider(entity_id="https://idp/acme")
    st = m.begin("acme")
    ident = prov.parse_assertion({"email": "siti@acme.com", "name": "Siti",
                                  "groups": ["admins"]}, org="acme")
    hasil = m.login(ident, state=st, expect_state=st)
    assert hasil["role"] == "admin"


def test_02b_saml_xml_parse():
    xml = """<Response><Assertion><Subject><NameID>dewi@acme.com</NameID></Subject>
    <AttributeStatement>
      <Attribute Name="email"><AttributeValue>dewi@acme.com</AttributeValue></Attribute>
      <Attribute Name="groups"><AttributeValue>admins</AttributeValue></Attribute>
    </AttributeStatement></Assertion></Response>"""
    ident = sso.SamlProvider().parse_assertion(xml, org="acme")
    assert ident.email == "dewi@acme.com"
    assert "admins" in ident.groups


# 3. LDAP bind -> OK
def test_03_ldap_bind():
    directory = {"agus": {"password": "rahasia", "email": "agus@acme.com",
                          "groups": ["devs"]}}
    ldap = sso.LdapProvider(base_dn="acme.com", directory=directory)
    assert ldap.bind("agus", "rahasia") is True
    assert ldap.bind("agus", "salah") is False
    assert ldap.bind("tidakada", "x") is False
    m, _ = _mgr()
    st = m.begin("acme")
    hasil = m.login(ldap.identity("agus", org="acme"), state=st, expect_state=st)
    assert hasil["role"] == "developer"


# 4. Role mapping: grup admin -> peran admin
def test_04_role_mapping():
    mapping = {"admins": "admin", "devs": "developer", "viewers": "viewer"}
    assert sso.map_role(["admins"], mapping) == "admin"
    assert sso.map_role(["devs", "viewers"], mapping) == "developer"
    # banyak cocok -> ambil yang TERKUAT
    assert sso.map_role(["viewers", "admins", "devs"], mapping) == "admin"
    assert sso.map_role(["unknown"], mapping, default="viewer") == "viewer"
    assert sso.ROLE_PRIORITY[-1] == "owner"


# 5. Session timeout
def test_05_session_timeout():
    m, clock = _mgr()
    st = m.begin("acme")
    hasil = m.login(sso.Identity("budi@acme.com", groups=["devs"], org="acme"),
                    state=st, expect_state=st, ttl=100)
    sid = hasil["session_id"]
    assert m.session(sid) is not None
    clock["t"] += 101
    assert m.session(sid) is None      # kedaluwarsa


# 6. Logout / SLO
def test_06_logout_slo():
    m, _ = _mgr()
    ids = []
    for _ in range(3):
        st = m.begin("acme")
        r = m.login(sso.Identity("budi@acme.com", groups=["devs"], org="acme"),
                    state=st, expect_state=st)
        ids.append(r["session_id"])
    assert m.logout(ids[0]) is True
    assert m.session(ids[0]) is None
    n = m.slo("budi@acme.com")
    assert n == 2                       # dua sesi tersisa dimatikan
    assert m.session(ids[1]) is None and m.session(ids[2]) is None


# 7. Provisioning JIT
def test_07_jit_provisioning():
    m, _ = _mgr()
    assert m.get_user("baru@acme.com") is None
    st = m.begin("acme")
    hasil = m.login(sso.Identity("baru@acme.com", name="Baru",
                                 groups=["admins"], org="acme"),
                    state=st, expect_state=st)
    u = m.get_user("baru@acme.com")
    assert u and u["active"] is True and u["name"] == "Baru"
    assert u["org"] == "acme" and hasil["user"]["email"] == "baru@acme.com"


# 8. Deprovisioning
def test_08_deprovisioning():
    m, _ = _mgr()
    st = m.begin("acme")
    r = m.login(sso.Identity("keluar@acme.com", groups=["devs"], org="acme"),
                state=st, expect_state=st)
    hasil = m.deprovision("keluar@acme.com")
    assert hasil["deactivated"] is True
    assert hasil["sessions_terminated"] == 1
    assert m.session(r["session_id"]) is None
    assert m.get_user("keluar@acme.com")["active"] is False


# 9. Multi-tenant SSO (per org)
def test_09_multi_tenant():
    m, _ = _mgr()
    m.register_org("globex", role_mapping={"staff": "admin"},
                   domains=["globex.io"])
    assert m.org_for_email("x@acme.com") == "acme"
    assert m.org_for_email("y@globex.io") == "globex"
    assert m.org_for_email("z@other.com") is None
    # domain tak terdaftar -> ditolak saat login
    with pytest.raises(sso.AuthFailed):
        m.login(sso.Identity("z@other.com", groups=[]), state="", expect_state="")
    st = m.begin("globex")
    r = m.login(sso.Identity("boss@globex.io", groups=["staff"]),
                state=st, expect_state=st)
    assert r["org"] == "globex" and r["role"] == "admin"


# 10. Proteksi session fixation
def test_10_session_fixation():
    m, _ = _mgr()
    st = m.begin("acme")
    lama = m.login(sso.Identity("budi@acme.com", groups=["devs"], org="acme"),
                   state=st, expect_state=st)
    st2 = m.begin("acme")
    baru = m.login(sso.Identity("budi@acme.com", groups=["admins"], org="acme"),
                   state=st2, expect_state=st2,
                   existing_session=lama["session_id"])
    assert baru["session_id"] != lama["session_id"]
    assert m.session(lama["session_id"]) is None    # id lama dibuang
    assert m.session(baru["session_id"]) is not None


# 11. Proteksi CSRF (state)
def test_11_csrf_state():
    m, _ = _mgr()
    st = m.begin("acme")
    with pytest.raises(sso.StateMismatch):
        m.login(sso.Identity("budi@acme.com", groups=["devs"], org="acme"),
                state="salah", expect_state=st)
    # state sekali pakai
    m.login(sso.Identity("budi@acme.com", groups=["devs"], org="acme"),
            state=st, expect_state=st)
    with pytest.raises(sso.StateMismatch):
        m.consume_state(st)


# 12. Keamanan: token/assertion tidak bocor
def test_12_no_token_leak():
    teks = ("id_token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefghij "
            "dan SAMLResponse=PHNhbWxwOlJlc3BvbnNlPj4=")
    bersih = sso.redact(teks)
    assert "eyJhbGciOiJIUzI1NiJ9" not in bersih
    assert "PHNhbWxwOlJlc3BvbnNlPj4=" not in bersih
    assert sso.MASK in bersih
    # identity.to_dict tidak pernah memuat kredensial
    d = sso.Identity("a@b.com", groups=["x"]).to_dict()
    assert "password" not in d and "token" not in d
