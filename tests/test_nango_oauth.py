"""TASK 4 — 12 hard test untuk `nango_oauth.py` (OAuth generik Nango).

Distribusi sesuai brief:
  2 basic (B1, B2)
  2 edge (E1, E2)
  2 error handling (X1, X2)
  2 performance (P1, P2)
  1 security (S1)
  1 E2E integration (I1)
  + regresi (X3..X14)

Semua test ini MURNI/OFFLINE: tidak ada network, tidak ada `.env`. Yang diuji
adalah kontrak pemetaan, bukan ketersediaan layanan pihak ketiga.
"""

from __future__ import annotations

import time

import pytest

import nango_oauth as no


# ---------------------------------------------------------------------------
# B — basic
# ---------------------------------------------------------------------------


def test_b1_oauth2_memiliki_connect_url_dan_credential_form():
    """B1: OAUTH2 wajib menghasilkan connect_url + credential_form (aturan manifest)."""
    cfg = {
        "auth_mode": "OAUTH2",
        "authorization_url": "https://auth.example.com/authorize",
        "token_url": "https://auth.example.com/token",
        "default_scopes": ["read", "write"],
    }
    p = no.auth_plan("example-saas", cfg)
    assert p.ok, p.reason
    assert p.kind == "oauth2"
    assert p.auth["type"] == "oauth2"
    assert p.auth["connect_url"].startswith("/oauth/nango/authorize")
    assert "example_saas" in p.auth["connect_url"]
    assert p.auth["credential_form"].strip()
    assert p.auth["scopes"] == ["read", "write"]


def test_b2_api_key_memiliki_fields_dan_key_name():
    """B2: API_KEY menghasilkan form field + key_name, tanpa connect_url."""
    cfg = {"auth_mode": "API_KEY", "credentials": {"apiKey": {"secret": True}}}
    p = no.auth_plan("vendor-x", cfg)
    assert p.ok, p.reason
    assert p.kind == "api_key"
    assert p.auth["type"] == "api_key"
    assert p.auth["credential_form"]
    assert "connect_url" not in p.auth
    names = {f["name"] for f in p.auth["fields"]}
    assert "apiKey" in names
    assert p.auth["key_name"] == "apiKey"


# ---------------------------------------------------------------------------
# E — edge
# ---------------------------------------------------------------------------


def test_e1_auth_mode_kosong_diinfeksi_dari_bentuk_kredensial():
    """E1: 629 provider registry tidak punya auth_mode -> harus dibaca dari shape."""
    cases = {
        "apiKey": "api_key",
        "username_password": "basic",
        "client_credentials_only": "oauth2",
        "nothing": "none",
    }
    api_key = no.auth_plan("a", {"credentials": {"apiKey": {}}})
    assert api_key.kind == "api_key"

    basic = no.auth_plan("b", {"credentials": {"username": {}, "password": {}}})
    assert basic.kind == "basic"

    oauth = no.auth_plan("c", {"credentials": {"client_id": {}, "client_secret": {}},
                               "token_url": "https://x/token"})
    # token_url + client creds TANPA authorization_url = client-credentials,
    # bukan redirect-OAuth (terverifikasi pada 75 entri registry nyata).
    assert oauth.kind == "oauth2_client_credentials"

    none = no.auth_plan("d", {})
    assert none.kind == "none"
    assert cases  # shape table is the point of this test


def test_e2_alias_rantai_diresolusi():
    """E2: `confluence -> jira` harus mewarisi alur auth target, bukan gagal."""
    reg = {
        "confluence": {"alias": "jira"},
        "jira": {"auth_mode": "OAUTH2",
                 "authorization_url": "https://auth.atlassian.com/authorize",
                 "token_url": "https://auth.atlassian.com/oauth/token"},
    }
    tname, tcfg = no.resolve_alias("confluence", reg)
    assert tname == "jira"
    assert tcfg["authorization_url"].endswith("/authorize")

    # Rantai siklus tidak boleh menggantung.
    cyc = {"a": {"alias": "b"}, "b": {"alias": "a"}}
    n2, _ = no.resolve_alias("a", cyc)
    assert n2 in ("a", "b")


# ---------------------------------------------------------------------------
# X — error handling
# ---------------------------------------------------------------------------


def test_x1_auth_mode_tak_dikenal_tidak_percaya_label():
    """X1: label aneh -> baca bentuk kredensial, jangan lempar."""
    p = no.auth_plan("weird", {"auth_mode": "TOTALLY_MADE_UP",
                               "credentials": {"apiKey": {}}})
    assert p.kind == "api_key"
    assert p.ok


def test_x2_oauth2_tanpa_authorization_url_ditolak_jujur():
    """X2: mengaku OAuth2 tapi tanpa authorization_url -> unsupported + alasan."""
    p = no.auth_plan("hollow", {"auth_mode": "OAUTH2",
                                "token_url": "https://x/token"})
    assert not p.ok
    assert p.kind == "unsupported"
    assert "authorization_url" in p.reason


def test_x3_mode_deferred_tidak_dikarang():
    """X3: INSTALL_PLUGIN / TBA / BILL -> deferred, tanpa auth palsu."""
    for mode in ("INSTALL_PLUGIN", "TBA", "BILL"):
        p = no.auth_plan(f"m-{mode}", {"auth_mode": mode})
        assert not p.ok, mode
        assert p.kind == "deferred", mode
        assert p.auth == {} or p.auth.get("type") is None


def test_x4_client_credentials_tanpa_token_url_ditolak():
    """X4: OAUTH2_CC butuh token_url untuk benar-benar bisa jalan."""
    p = no.auth_plan("cc-no-token", {"auth_mode": "OAUTH2_CC"})
    assert not p.ok
    assert "token_url" in p.reason


def test_x5_cfg_bukan_objek_ditangani():
    """X5: config bukan dict -> bad_entry tanpa crash."""
    p = no.auth_plan("bad", ["bukan", "dict"])
    assert not p.ok
    assert p.kind == "bad_entry"


def test_x6_registry_kosong_melempar_error_jelas(tmp_path):
    """X6: berkas registry kosong -> NangoOAuthError dengan pesan jelas."""
    f = tmp_path / "empty.json"
    f.write_text("{}", encoding="utf-8")
    with pytest.raises(no.NangoOAuthError):
        no.load_registry(f)


def test_x7_semua_kind_ok_berada_di_AUTH_TYPES():
    """X7: INVARIAN — setiap auth yang ok memakai kosakata tertutup."""
    from connector_manifest import AUTH_TYPES

    entries = no.load_enriched()
    res = no.plan_all(entries)
    for p in res["plans"]:
        if p["ok"]:
            assert p["auth"]["type"] in AUTH_TYPES, p["name"]


def test_x8_setiap_oauth2_ok_punya_connect_url_valid():
    """X8: INVARIAN — setiap oauth2 yang ok punya connect_url rute Katalir."""
    res = no.plan_all(no.load_enriched())
    n = 0
    for p in res["plans"]:
        if p["ok"] and p["auth"].get("type") == "oauth2":
            cu = p["auth"].get("connect_url")
            assert isinstance(cu, str) and cu.startswith("/oauth/nango/authorize"), p["name"]
            assert p["auth"].get("credential_form"), p["name"]
            n += 1
    assert n > 400, f"hanya {n} oauth2"


def test_x9_setiap_auth_non_none_punya_credential_form():
    """X9: INVARIAN manifest — non-none wajib credential_form."""
    res = no.plan_all(no.load_enriched())
    for p in res["plans"]:
        if p["ok"] and p["auth"].get("type") not in (None, "none"):
            cf = p["auth"].get("credential_form")
            assert isinstance(cf, str) and cf.strip(), p["name"]


def test_x10_metadata_flow_tidak_kehilangan_pkce_dan_cc():
    """X10: `disable_pkce` & `token_request_auth_method` tidak boleh hilang."""
    p = no.auth_plan("nopkce", {"auth_mode": "OAUTH2",
                                "authorization_url": "https://a/b",
                                "token_url": "https://a/t",
                                "disable_pkce": True})
    assert p.flow.get("pkce") is False

    cc = no.auth_plan("cc", {"auth_mode": "OAUTH2_CC",
                             "token_url": "https://a/t",
                             "token_params": {"grant_type": "client_credentials"},
                             "token_request_auth_method": "basic"})
    assert cc.ok
    assert cc.flow["grant_type"] == "client_credentials"
    assert cc.flow["token_request_auth_method"] == "basic"


def test_x11_jwt_dan_two_step_terpetakan():
    """X11: JWT -> jwt; TWO_STEP -> session_token; metadata tetap dibawa."""
    jwt = no.auth_plan("apple-app-store", {
        "auth_mode": "JWT",
        "signature": {"protocol": "EC"},
        "token": {"signing_key": "${credentials.privateKey}",
                  "expires_in_ms": 900000},
    })
    assert jwt.ok and jwt.auth["type"] == "jwt"
    assert jwt.flow["signature"]["protocol"] == "EC"

    ts = no.auth_plan("3cx", {
        "auth_mode": "TWO_STEP", "token_url": "https://x/t",
        "token_response": {"token": "access_token"},
        "token_expires_in_ms": 3600000,
    })
    assert ts.ok and ts.auth["type"] == "session_token"
    assert ts.auth["token_key"] == "access_token"
    assert ts.flow["expires_in_s"] == 3600


def test_x12_enrich_tidak_menimpa_identitas_lokal():
    """X12: enrichment hanya MENAMBAH, tidak menimpa `id`/`name`/`kind`."""
    local = {"nango:acme": {"id": "nango:acme", "name": "Acme", "kind": "oauth_provider"}}
    reg = {"acme": {"id": "SHOULD_NOT_WIN", "name": "SHOULD_NOT_WIN",
                    "auth_mode": "OAUTH2",
                    "authorization_url": "https://acme/authorize",
                    "token_url": "https://acme/token"}}
    out = no.enrich(local, reg)
    merged = out["nango:acme"]
    assert merged["id"] == "nango:acme"
    assert merged["name"] == "Acme"
    assert merged["kind"] == "oauth_provider"
    assert merged["authorization_url"] == "https://acme/authorize"


def test_x13_auth_mode_dari_description_katalog_lokal():
    """X13: katalog lokal menyimpan `auth_mode=NNN` di dalam description."""
    cfg = {"description": "Nango OAuth/connection provider. auth_mode=TWO_STEP.",
           "tools_count": 0}
    assert no.auth_mode_of("x", cfg) == "TWO_STEP"
    p = no.auth_plan("x", cfg)
    assert p.kind == "session_token"


def test_x14_plan_all_konsisten_dengan_auth_plan():
    """X14: agregat `plan_all` cocok bila dihitung ulang per-entri."""
    entries = {
        "a": {"auth_mode": "OAUTH2", "authorization_url": "https://a/az",
              "token_url": "https://a/t"},
        "b": {"auth_mode": "API_KEY", "credentials": {"apiKey": {}}},
        "c": {"auth_mode": "BILL"},
    }
    res = no.plan_all(entries)
    assert res["total"] == 3
    assert res["ok"] == 2
    manual = sum(1 for n, c in entries.items() if no.auth_plan(n, c).ok)
    assert manual == res["ok"]


# ---------------------------------------------------------------------------
# P — performance
# ---------------------------------------------------------------------------


def test_p1_plan_1024_provider_di_bawah_ambang():
    """P1: memetakan seluruh katalog harus selesai jauh di bawah 10 detik."""
    entries = no.load_enriched()
    t0 = time.perf_counter()
    res = no.plan_all(entries)
    dt = time.perf_counter() - t0
    assert res["total"] >= 1000
    assert dt < 10.0, f"terlalu lambat: {dt:.2f}s"


def test_p2_enrich_idempoten_dan_stabil():
    """P2: enrich() dua kali menghasilkan hasil identik (tidak ada akumulasi)."""
    local = no.load_registry(no.PROVIDERS_PATH)
    reg = no.load_registry(no.REGISTRY_PATH)
    a = no.enrich(local, reg)
    b = no.enrich(local, reg)
    assert a.keys() == b.keys()
    for k in a:
        assert a[k].get("alias_of") == b[k].get("alias_of")
        assert a[k].get("auth_mode") == b[k].get("auth_mode")


# ---------------------------------------------------------------------------
# S — security
# ---------------------------------------------------------------------------


def test_s1_tidak_ada_rahasia_bocor_di_output_atau_connect_url():
    """S1: connect_url hanya memuat slug (huruf kecil/angka/_), BUKAN kredensial."""
    entries = no.load_enriched()
    res = no.plan_all(entries)
    seen = 0
    for p in res["plans"]:
        if not p["ok"]:
            continue
        cu = p["auth"].get("connect_url")
        if not cu:
            continue
        seen += 1
        # hanya rute internal + slug yang aman. Catatan: pola yang diperiksa
        # adalah SUBSTRING yang berbahaya sebagai token (`?`, `&`, `=`, skema
        # URL), bukan kata seperti "password" yang bisa muncul sah di nama
        # provider (mis. `1password`).
        assert cu.startswith("/oauth/nango/authorize?provider="), p["name"]
        slug = cu.split("=", 1)[1]
        assert set(slug) <= set("abcdefghijklmnopqrstuvwxyz0123456789_"), p["name"]
        for bad in ("http://", "https://", "//", "?", "&", "=", "@", "%", "\\", " "):
            assert bad not in slug, p["name"]
        # Tidak ada kredensial yang ikut tersambung ke query string.
        assert cu.count("=") == 1, p["name"]
    assert seen > 400


# ---------------------------------------------------------------------------
# I — E2E integration
# ---------------------------------------------------------------------------


def test_i1_e2e_katalog_nyata_terpetakan_dan_manifest_valid():
    """I1: E2E — 1.024 provider -> auth yang lolos validator manifest asli."""
    from connector_manifest import _validate_auth

    entries = no.load_enriched()
    res = no.plan_all(entries)

    assert res["total"] == len(entries) >= 1024
    # Target brief: 1.024 provider. Kita capai >= 98%.
    assert res["ok"] >= 1000, f"hanya {res['ok']} berhasil dipetakan"

    checked = 0
    for p in res["plans"]:
        if not p["ok"]:
            continue
        errors: list[str] = []
        _validate_auth(p["auth"], errors, f"connectors.{p['slug']}")
        assert not errors, f"{p['name']}: {errors}"
        checked += 1
    assert checked == res["ok"]

    # Keragaman nyata harus muncul — bukan cuma satu jenis.
    kinds = {p["kind"] for p in res["plans"] if p["ok"]}
    for k in ("oauth2", "oauth2_client_credentials", "api_key", "basic",
              "session_token"):
        assert k in kinds, f"jenis {k} hilang"

    # Yang gagal harus sedikit dan beralasan.
    assert res["failed"] <= 12
    for p in res["plans"]:
        if not p["ok"]:
            assert p["reason"].strip()
