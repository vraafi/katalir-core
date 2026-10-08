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


# ---------------------------------------------------------------------------
# Regresi temuan verifikasi endpoint LIVE (IdP nyata) — Okt 2026
# ---------------------------------------------------------------------------

# 13. BUG NYATA: `decode_saml_response` menerima base64 (binding POST) & XML
def test_13_decode_saml_response_base64_dan_xml():
    import base64
    xml = "<samlp:Response><Assertion/></samlp:Response>"
    assert sso.decode_saml_response(xml) == xml                       # XML mentah
    b64 = base64.b64encode(xml.encode()).decode()
    assert sso.decode_saml_response(b64) == xml                       # base64 POST
    assert sso.decode_saml_response(b64.encode()) == xml              # bytes
    with pytest.raises(sso.AuthFailed):
        sso.decode_saml_response("")                                  # kosong
    with pytest.raises(sso.AuthFailed):
        sso.decode_saml_response(base64.b64encode(b"bukan xml").decode())


# 14. BUG NYATA: `SamlVerifier.verify` menormalkan base64 SEBELUM verifikasi
#     (dulu selalu gagal "Start tag expected, '<' not found").
def test_14_saml_verifier_normalisasi_sebelum_verifikasi(monkeypatch):
    seen: list = []

    class FakeVerifier:
        def verify(self, data, x509_cert=None, **kw):
            seen.append(data)
            return type("R", (), {"signed_xml": data})()

    import signxml
    monkeypatch.setattr(signxml, "XMLVerifier", lambda: FakeVerifier())
    import base64
    xml = "<Response><Assertion/></Response>"
    v = sso.SamlVerifier("CERT")
    v.verify(base64.b64encode(xml.encode()).decode())
    assert seen and seen[0].lstrip().startswith("<"), \
        f"verifier menerima non-XML: {seen[0][:40]!r}"


# 15. BUG NYATA: sesi harus BERTAHAN antar request (dulu manager dibangun ulang
#     setiap request -> /sso/session selalu 404, SLO selalu 0).
def test_15_sesi_bertahan_antar_request(monkeypatch):
    import api_server
    monkeypatch.setenv("KATALIR_SSO_ADMINS", "admin@x.test")
    monkeypatch.setattr(api_server, "_SSO_MGR", None)
    # paksa store memori supaya tes tidak butuh Redis
    monkeypatch.setattr(api_server, "_sso_session_store", lambda: sso.SessionStore())
    _, m1 = api_server._sso()
    hasil = m1.login(sso.Identity("budi@acme.com", groups=["katalir-admins"],
                                  org="acme"), state="", expect_state="")
    sid = hasil["session_id"]
    _, m2 = api_server._sso()                    # request "berikutnya"
    assert m2 is m1, "manager dibangun ulang -> sesi hilang"
    assert m2.session(sid) is not None, "sesi tidak ditemukan di request berikutnya"


# 16. RedisSessionStore: create/get/rotate/destroy/destroy_all/touch
class _FakeRedis:
    """Subset Redis yang cukup untuk menguji RedisSessionStore (tanpa server)."""

    def __init__(self):
        self.h: dict = {}
        self.s: dict = {}
        self.exp: dict = {}

    def hset(self, key, mapping=None):
        self.h.setdefault(key, {}).update(mapping or {})

    def hget(self, key, field):
        return self.h.get(key, {}).get(field)

    def expire(self, key, ttl):
        self.exp[key] = ttl

    def sadd(self, key, *vals):
        self.s.setdefault(key, set()).update(vals)

    def srem(self, key, *vals):
        self.s.setdefault(key, set()).difference_update(vals)

    def smembers(self, key):
        return set(self.s.get(key, set()))

    def delete(self, *keys):
        n = 0
        for k in keys:
            n += 1 if self.h.pop(k, None) is not None else 0
            self.s.pop(k, None)
        return n

    def scan_iter(self, match=None, count=100):
        pref = (match or "").replace("*", "")
        return [k for k in list(self.h) if k.startswith(pref)]

    def pipeline(self, transaction=True):
        outer = self

        class P:
            def __init__(self):
                self.ops = []

            def __getattr__(self, name):
                def _q(*a, **k):
                    self.ops.append((name, a, k))
                    return self
                return _q

            def execute(self):
                for name, a, k in self.ops:
                    getattr(outer, name)(*a, **k)
                self.ops = []
                return []
        return P()


def test_16_redis_session_store_siklus_penuh():
    clock = {"t": 500.0}
    st = sso.RedisSessionStore(_FakeRedis(), clock=lambda: clock["t"])
    ident = sso.Identity("budi@acme.com", name="Budi", groups=["devs"])
    sid = st.create(ident, "developer", ttl=100.0)
    rec = st.get(sid)
    assert rec and rec["role"] == "developer" and rec["identity"]["email"] == "budi@acme.com"
    # TTL benar-benar dipasang
    assert st.r.exp[f"{st.ns}:{sid}"] == 100
    # rotate (anti session-fixation) -> id BARU, lama mati
    baru = st.rotate(sid)
    assert baru and baru != sid and st.get(sid) is None and st.get(baru)
    # touch memperpanjang
    clock["t"] = 550.0
    assert st.touch(baru, 300.0) is True
    assert st.get(baru)["expires_at"] == 850.0
    # destroy_all mematikan SEMUA sesi user (SLO)
    st.create(ident, "developer", ttl=100.0)
    st.create(sso.Identity("lain@acme.com"), "viewer", ttl=100.0)
    assert st.destroy_all("budi@acme.com") == 2
    assert st.destroy_all("budi@acme.com") == 0
    # kedaluwarsa -> get() None
    clock["t"] = 99999.0
    assert st.get(baru) is None


# 17. RedisSessionStore: `count()` melaporkan sesi aktif (observabilitas)
def test_17_redis_session_store_count():
    st = sso.RedisSessionStore(_FakeRedis())
    assert st.count() == 0
    st.create(sso.Identity("a@x.com"), "viewer")
    st.create(sso.Identity("b@x.com"), "viewer")
    assert st.count() == 2
