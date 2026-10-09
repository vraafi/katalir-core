"""Uji Fitur #6 — end-user credentials berbasis trigger.

12 kategori: 3 basic, 2 durability, 3 edge, 2 performance, 2 security
(+ ekstra). Waktu deterministik lewat jam yang disuntik; tidak ada `sleep`.

Acuan perilaku: n8n "End-user credentials" (Enterprise/Preview, docs Okt 2026)
dan RFC 9700 §4.14 (refresh token rotation + deteksi reuse).
"""
from __future__ import annotations

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import end_user_credentials as E  # noqa: E402


# ---------------------------------------------------------------------------
# Perkakas
# ---------------------------------------------------------------------------

class Clock:
    """Jam palsu — semua uji waktu deterministik."""

    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> float:
        self.t += dt
        return self.t


#: Cipher mainan: cukup untuk membuktikan token TIDAK disimpan mentah.
def _fake_cipher(value: str) -> str:
    return "enc(" + value[::-1] + ")"


def _fake_decipher(blob: str) -> str:
    assert blob.startswith("enc(") and blob.endswith(")")
    return blob[4:-1][::-1]


def make_resolver(clk: Clock | None = None, **kw) -> E.CredentialResolver:
    clk = clk or Clock()
    store = E.RotatingTokenStore(cipher=_fake_cipher, decipher=_fake_decipher,
                                 clock=clk)
    kw.setdefault("enforce_scope", True)
    return E.CredentialResolver(store=store, clock=clk, **kw)


def gmail_template(tid: str = "tpl-gmail", **kw) -> E.EndUserCredentialTemplate:
    cfg = {"template_id": tid, "name": "Gmail", "provider": "gmail",
           "kind": "oauth2", "owner_project": "team-1",
           "scopes": ["gmail.readonly", "gmail.send"],
           "client_id": "client-abc"}
    cfg.update(kw)
    return E.template_from_config(cfg)


# ===========================================================================
# B — BASIC
# ===========================================================================

def test_b1_template_requires_oauth_kind():
    """B1: hanya kredensial OAuth yang boleh jadi template end-user."""
    t = gmail_template()
    assert t.kind == "oauth2"
    assert t.to_dict()["template_id"] == "tpl-gmail"
    assert set(E.CREDENTIAL_KINDS) == {"oauth2", "oauth1"}
    with pytest.raises(E.EndUserCredentialError):
        E.template_from_config({"template_id": "x", "kind": "api-key"})


def test_b2_connect_then_resolve_for_triggering_user():
    """B2: kredensial di-*resolve* ke akun pengguna yang memicu."""
    r = make_resolver()
    r.add_template(gmail_template())
    r.connect("tpl-gmail", "userA", {"access_token": "AT-A",
                                     "refresh_token": "RT-A"},
              account_label="a@example.com")
    out = r.resolve("tpl-gmail", trigger_mode="manual", user_id="userA")
    assert out["resolved"] is True
    assert out["account_label"] == "a@example.com"
    assert out["tokens"]["access_token"] == "AT-A"
    assert out["connection_id"] == "tpl-gmail:userA"
    # Pengguna lain tidak memakai koneksi userA (isolasi).
    assert r.connections["tpl-gmail:userA"].user_id == "userA"


def test_b3_missing_connection_optional_vs_required():
    """B3: opsional -> resolved=False; wajib -> ConnectionMissing."""
    r = make_resolver()
    r.add_template(gmail_template(required=False))
    out = r.resolve("tpl-gmail", trigger_mode="manual", user_id="userB")
    assert out["resolved"] is False
    assert "belum menghubungkan" in out["reason"]

    r2 = make_resolver()
    r2.add_template(gmail_template(required=True))
    with pytest.raises(E.ConnectionMissing):
        r2.resolve("tpl-gmail", trigger_mode="manual", user_id="userB")


# ===========================================================================
# D — DURABILITY
# ===========================================================================

def test_d1_tokens_survive_serialisation_roundtrip():
    """D1: template + koneksi bisa dimuat ulang tanpa kehilangan makna."""
    r = make_resolver()
    r.add_template(gmail_template())
    r.connect("tpl-gmail", "userA", {"access_token": "AT", "refresh_token": "RT"},
              account_label="a@x.com")
    conn = r.get_connection("tpl-gmail", "userA")

    # Simulasi persistensi: hanya kolom aman yang ditulis.
    saved = conn.to_dict()
    blob = json.loads(json.dumps(saved))
    assert "token_blob" not in blob, "token tidak boleh ikut terserialisasi"
    assert blob["connected"] is True and blob["generation"] == 1

    r2 = make_resolver()
    r2.add_template(gmail_template())
    c2 = E.connection_from_config({"template_id": "tpl-gmail",
                                   "user_id": "userA",
                                   "account_label": "a@x.com"})
    r2.connections[c2.connection_id] = c2
    assert r2.get_connection("tpl-gmail", "userA").account_label == "a@x.com"


def test_d2_rotation_generation_and_relationship_retained():
    """D2: rotasi menaikkan generation dan MEMPERTAHANKAN relasi token lama."""
    clk = Clock()
    r = make_resolver(clk)
    r.add_template(gmail_template())
    r.connect("tpl-gmail", "userA", {"access_token": "AT1",
                                     "refresh_token": "RT1"})
    c = r.get_connection("tpl-gmail", "userA")
    assert c.generation == 1
    r.store.rotate(c, {"access_token": "AT2", "refresh_token": "RT2"},
                   presented_refresh="RT1")
    assert c.generation == 2
    # RFC 9700 §4.14.2: token lama TIDAK berlaku, tetapi relasinya disimpan.
    assert r.store.is_retired("RT1") is True
    assert r.store.is_live("RT1") is False
    assert r.store.is_live("RT2") is True
    assert r.store.stats()["rotations"] == 1


# ===========================================================================
# E — EDGE
# ===========================================================================

def test_e1_trigger_support_matrix_matches_n8n():
    """E1: matriks trigger persis n8n (Form/Chat butuh User Auth, Chat=Hosted)."""
    assert E.SUPPORTED_TRIGGER_MODES == ("manual", "chat-hub", "mcp-server",
                                        "form", "chat")
    assert E.supports_end_user_credentials("manual") is True
    assert E.supports_end_user_credentials("chat-hub") is True
    assert E.supports_end_user_credentials("mcp-server") is True
    # Form/Chat butuh n8n User Auth
    assert E.supports_end_user_credentials("form") is False
    assert E.supports_end_user_credentials("form", auth="n8n-user-auth") is True
    assert E.supports_end_user_credentials("chat", auth="n8n-user-auth") is True
    # Chat hanya Hosted Chat, bukan embedded/webhook
    assert E.supports_end_user_credentials(
        "chat", auth="n8n-user-auth", chat_mode="embedded") is False
    assert E.supports_end_user_credentials(
        "chat", auth="n8n-user-auth", chat_mode="webhook") is False
    # Mode non-trigger tidak didukung
    assert E.supports_end_user_credentials("webhook") is False
    assert E.supports_end_user_credentials("schedule") is False
    cat = E.iter_supported_triggers()
    assert len(cat) == 5
    assert {c["mode"] for c in cat} == set(E.SUPPORTED_TRIGGER_MODES)


def test_e2_one_connection_per_user_per_template():
    """E2: satu pengguna hanya punya SATU koneksi per template."""
    r = make_resolver()
    r.add_template(gmail_template())
    c1 = r.connect("tpl-gmail", "userA", {"access_token": "AT1",
                                          "refresh_token": "RT1"})
    c2 = r.connect("tpl-gmail", "userA", {"access_token": "AT2",
                                          "refresh_token": "RT2"})
    assert c1.connection_id == c2.connection_id
    mine = [c for c in r.connections.values() if c.user_id == "userA"]
    assert len(mine) == 1
    # Token diperbarui, bukan ditambah.
    assert r.resolve("tpl-gmail", trigger_mode="manual",
                     user_id="userA")["tokens"]["access_token"] == "AT2"
    # Pengguna berbeda -> koneksi berbeda.
    r.connect("tpl-gmail", "userB", {"access_token": "BT", "refresh_token": "BR"})
    assert len(r.connections) == 2


def test_e3_template_scope_and_mode_restrictions():
    """E3: allowed_modes membatasi; delete template menghapus semua koneksi."""
    r = make_resolver()
    r.add_template(gmail_template(allowed_modes=["manual", "form"]))
    r.connect("tpl-gmail", "userA", {"access_token": "AT", "refresh_token": "RT"})
    assert r.resolve("tpl-gmail", trigger_mode="manual",
                     user_id="userA")["resolved"] is True
    with pytest.raises(E.TriggerNotSupported):
        r.resolve("tpl-gmail", trigger_mode="chat-hub", user_id="userA")

    r.connect("tpl-gmail", "userB", {"access_token": "BT", "refresh_token": "BR"})
    out = r.delete_template("tpl-gmail")
    assert out["connections_removed"] == 2
    assert r.connections == {}
    with pytest.raises(E.TemplateNotFound):
        r.get_template("tpl-gmail")


# ===========================================================================
# P — PERFORMANCE
# ===========================================================================

def test_p1_resolve_1000_connections_under_budget():
    """P1: 1000 koneksi + 1000 resolusi tetap cepat."""
    r = make_resolver()
    r.add_template(gmail_template())
    for i in range(1000):
        r.connect("tpl-gmail", f"user{i}",
                  {"access_token": f"AT{i}", "refresh_token": f"RT{i}"})
    t0 = time.perf_counter()
    for i in range(1000):
        out = r.resolve("tpl-gmail", trigger_mode="manual", user_id=f"user{i}")
        assert out["resolved"] is True
    dt = time.perf_counter() - t0
    assert dt < 2.0, f"terlalu lambat: {dt:.4f} s"
    assert r.stats()["resolutions"] == 1000


def test_p2_rotation_is_constant_time_and_bounded():
    """P2: 500 rotasi tidak tumbuh kuadratik; relasi lama terbatas."""
    clk = Clock()
    r = make_resolver(clk)
    r.add_template(gmail_template())
    r.connect("tpl-gmail", "userA", {"access_token": "AT0",
                                     "refresh_token": "RT0"})
    c = r.get_connection("tpl-gmail", "userA")
    t0 = time.perf_counter()
    for i in range(1, 501):
        r.store.rotate(c, {"access_token": f"AT{i}",
                           "refresh_token": f"RT{i}"},
                       presented_refresh=f"RT{i-1}")
    dt = time.perf_counter() - t0
    assert dt < 2.0, f"terlalu lambat: {dt:.4f} s"
    assert c.generation == 501
    st = r.store.stats()
    assert st["rotations"] == 500 and st["live"] == 1


# ===========================================================================
# S — SECURITY
# ===========================================================================

def test_s1_reuse_of_rotated_refresh_token_revokes_grant():
    """S1: RFC 9700 §4.14.2 — reuse token lama -> seluruh grant dicabut."""
    r = make_resolver()
    r.add_template(gmail_template(required=True))
    r.connect("tpl-gmail", "userA", {"access_token": "AT1",
                                     "refresh_token": "RT1"})
    c = r.get_connection("tpl-gmail", "userA")
    r.store.rotate(c, {"access_token": "AT2", "refresh_token": "RT2"},
                   presented_refresh="RT1")
    with pytest.raises(E.RotationReuseDetected):
        r.store.rotate(c, {"access_token": "AT3", "refresh_token": "RT3"},
                       presented_refresh="RT1")
    assert c.revoked is True
    assert r.store.stats()["reuse_events"] == 1
    # Setelah dicabut, resolusi gagal (template wajib -> exception).
    with pytest.raises(E.ConnectionMissing):
        r.resolve("tpl-gmail", trigger_mode="manual", user_id="userA")
    # Untuk template opsional, hasilnya resolved=False (bukan exception).
    r2 = make_resolver()
    r2.add_template(gmail_template())
    r2.connect("tpl-gmail", "userA", {"access_token": "A", "refresh_token": "R"})
    c2 = r2.get_connection("tpl-gmail", "userA")
    r2.store.rotate(c2, {"access_token": "A2", "refresh_token": "R2"},
                    presented_refresh="R")
    with pytest.raises(E.RotationReuseDetected):
        r2.store.rotate(c2, {"access_token": "A3", "refresh_token": "R3"},
                        presented_refresh="R")
    out = r2.resolve("tpl-gmail", trigger_mode="manual", user_id="userA")
    assert out["resolved"] is False


def test_s2_tokens_never_stored_raw_and_never_leaked():
    """S2: token terenkripsi; API aman tidak memuat token."""
    r = make_resolver()
    r.add_template(gmail_template())
    r.connect("tpl-gmail", "userA",
              {"access_token": "SECRET-AT", "refresh_token": "SECRET-RT"})
    c = r.get_connection("tpl-gmail", "userA")
    # Disimpan terenkripsi (cipher mainan) -> bukan teks polos.
    assert "SECRET-AT" not in c.token_blob
    assert "SECRET-RT" not in c.token_blob
    assert c.token_blob.startswith("enc(")
    # to_dict() aman.
    blob = json.dumps(c.to_dict())
    assert "SECRET-AT" not in blob and "SECRET-RT" not in blob
    assert "token_blob" not in blob and "refresh_fingerprint" not in blob
    # admin_summary() tidak pernah membocorkan isi koneksi.
    s = r.admin_summary("tpl-gmail")
    assert s["connection_count"] == 1
    assert s["secrets_visible"] is False
    assert "userA" not in json.dumps(s)
    # denials tidak memuat nilai token.
    r.add_template(gmail_template("tpl2", scopes=["a"]))
    r.connect("tpl2", "userA", {"access_token": "S2-AT", "refresh_token": "S2-RT"})
    with pytest.raises(E.ScopeViolation):
        r.resolve("tpl2", trigger_mode="manual", user_id="userA",
                  requested_scopes=["b"])
    assert "S2-AT" not in json.dumps(r.denials)


# ===========================================================================
# X — EKSTRA
# ===========================================================================

def test_x1_redaction_isolation_from_n8n():
    """X1: hanya pengguna pemicu melihat I/O node kredensial end-user."""
    r = make_resolver()
    r.add_template(gmail_template("tpl1"))
    execu = {
        "execution_id": "ex1", "status": "success",
        "nodes": {
            "Gmail": {"credential_type": "end-user", "template_id": "tpl1",
                      "input": {"q": "from:me"},
                      "output": [{"body": "isi pribadi A"}]},
            "Slack": {"credential_type": "fixed", "output": [{"ok": True}]},
        },
    }
    mine = r.redact_for(execu, trigger_user_id="userA", viewer_id="userA")
    assert mine["data_redacted"] is False
    assert mine["nodes"]["Gmail"]["output"][0]["body"] == "isi pribadi A"

    other = r.redact_for(execu, trigger_user_id="userA", viewer_id="adminX")
    assert other["data_redacted"] is True
    assert other["nodes"]["Gmail"]["output"] == E.REDACTED
    assert other["nodes"]["Gmail"]["input"] == E.REDACTED
    assert other["nodes"]["Gmail"]["redacted"] is True
    # Node kredensial tetap TIDAK teredaksi.
    assert other["nodes"]["Slack"]["output"][0]["ok"] is True
    # Metadata eksekusi tetap terlihat (perilaku n8n).
    assert other["execution_id"] == "ex1" and other["status"] == "success"
    assert other["viewer"]["is_triggering_user"] is False
    assert "isi pribadi A" not in json.dumps(other)


def test_x2_scope_enforcement_and_env_factory():
    """X2: gerbang scope + konfigurasi lewat env (injectable)."""
    r = make_resolver()
    r.add_template(gmail_template())
    r.connect("tpl-gmail", "userA",
              {"access_token": "AT", "refresh_token": "RT"})
    # Scope sesuai -> lolos.
    ok = r.resolve("tpl-gmail", trigger_mode="manual", user_id="userA",
                   requested_scopes=["gmail.readonly"])
    assert ok["resolved"] is True
    # Scope di luar persetujuan -> ditolak.
    with pytest.raises(E.ScopeViolation) as ei:
        r.resolve("tpl-gmail", trigger_mode="manual", user_id="userA",
                  requested_scopes=["gmail.readonly", "drive.full"])
    assert "drive.full" in str(ei.value)
    # Bila penegakan dimatikan -> lolos.
    r.enforce_scope = False
    assert r.resolve("tpl-gmail", trigger_mode="manual", user_id="userA",
                     requested_scopes=["drive.full"])["resolved"] is True

    env = {"KATALIR_EUC_ENFORCE_SCOPE": "0",
           "KATALIR_EUC_REQUIRE_MODES": "manual, form",
           "KATALIR_EUC_IDLE_EXPIRE_SEC": "123",
           "KATALIR_EUC_REVOKE_ON_REUSE": "0"}
    r2 = E.resolver_from_env(env)
    assert r2.enforce_scope is False
    assert r2.require_modes == ["manual", "form"]
    assert r2.store.idle_expire_sec == 123.0
    assert r2.store.revoke_on_reuse is False
    d = E.describe(env)
    assert d["enforce_scope"] is False
    assert d["revoke_on_reuse"] is False
    assert len(d["supported_triggers"]) == 5
    assert E.describe({})["enforce_scope"] is True


def test_x3_idle_expiry_and_logout_revocation():
    """X3: token kedaluwarsa karena diam (MAY); logout mencabut grant."""
    clk = Clock()
    r = make_resolver(clk)
    r.add_template(gmail_template(required=True))
    r.connect("tpl-gmail", "userA",
              {"access_token": "AT", "refresh_token": "RT"})
    # Diam 30 hari + 1 detik -> kedaluwarsa.
    clk.advance(E.DEFAULT_IDLE_EXPIRE_SEC + 1)
    with pytest.raises(E.ConnectionMissing):
        r.resolve("tpl-gmail", trigger_mode="manual", user_id="userA")

    # Skenario kedua: logout mencabut segera.
    clk2 = Clock()
    r2 = make_resolver(clk2)
    r2.add_template(gmail_template(required=True))
    r2.connect("tpl-gmail", "userA",
               {"access_token": "AT", "refresh_token": "RT"})
    assert r2.disconnect("tpl-gmail", "userA") is True
    assert r2.store.is_live("RT") is False
    with pytest.raises(E.ConnectionMissing):
        r2.resolve("tpl-gmail", trigger_mode="manual", user_id="userA")
    assert r2.disconnect("tpl-gmail", "userA") is False   # sudah tiada


def test_x4_registry_and_stats():
    """X4: registry proses + statistik lengkap."""
    r = make_resolver()
    E.set_resolver(r)
    assert E.resolver() is r
    r.add_template(gmail_template())
    r.connect("tpl-gmail", "userA",
              {"access_token": "AT", "refresh_token": "RT"})
    r.resolve("tpl-gmail", trigger_mode="manual", user_id="userA")
    r.resolve("tpl-gmail", trigger_mode="manual", user_id="nobody")
    st = r.stats()
    assert st["templates"] == 1 and st["connections"] == 1
    assert st["resolutions"] == 1 and st["misses"] == 1
    assert st["supported_triggers"] == list(E.SUPPORTED_TRIGGER_MODES)
    E.set_resolver(None)
    assert E.resolver() is not None
