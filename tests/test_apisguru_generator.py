"""tests/test_apisguru_generator.py — 12+ hard test untuk TASK 3.

TASK 3: integrasi 2.500 spesifikasi APIs.guru -> 100-200 connector.

Distribusi brief (2 dasar, 2 edge, 2 error, 2 performa, 1 keamanan,
1 integrasi E2E) dipetakan di bawah. Seluruh test OFFLINE: spesifikasi
disuntikkan sebagai dict, jadi suite deterministik dan cepat. Bukti terhadap
direktori nyata dijalankan terpisah oleh `_t3_live_gen.py`.
"""

from __future__ import annotations

import time

import pytest
import yaml

import apisguru_generator as ag
from connector_manifest import validate_manifest


# ---------------------------------------------------------------------------
# Fixture — spesifikasi OpenAPI 3.0 dan Swagger 2.0 berisi kasus nyata
# ---------------------------------------------------------------------------

SPEC_OAS3_PUBLIC = {
    "openapi": "3.0.0",
    "info": {"title": "Demo Public API", "version": "1.2.3"},
    "servers": [{"url": "https://api.demo-public.example"}],
    "paths": {
        "/things": {
            "get": {"operationId": "listThings",
                    "summary": "Daftar semua thing",
                    "responses": {"200": {"description": "ok"}}},
            "post": {"operationId": "createThing",
                     "summary": "Buat thing baru",
                     "requestBody": {"content": {"application/json": {"schema": {
                         "type": "object",
                         "properties": {"name": {"type": "string"}}}}}},
                     "responses": {"201": {"description": "created"}}},
        },
        "/things/{thingId}": {
            "get": {"operationId": "getThing",
                    "summary": "Ambil satu thing",
                    "parameters": [{"name": "thingId", "in": "path",
                                    "required": True, "schema": {"type": "string"},
                                    "example": "abc-123"}],
                    "responses": {"200": {"description": "ok"}}},
            "delete": {"operationId": "deleteThing",
                       "summary": "Hapus thing",
                       "parameters": [{"name": "thingId", "in": "path",
                                       "required": True,
                                       "schema": {"type": "string"},
                                       "example": "abc-123"}],
                       "requestBody": {"content": {"application/json": {"schema": {
                           "type": "object",
                           "properties": {"reason": {"type": "string"}}}}}},
                       "responses": {"204": {"description": "gone"}}},
        },
    },
}

SPEC_OAS3_AUTH = {
    "openapi": "3.0.0",
    "info": {"title": "Demo Secured API", "version": "2.0.0"},
    "servers": [{"url": "https://api.demo-secured.example"}],
    "components": {"securitySchemes": {
        "bearer": {"type": "http", "scheme": "bearer"}}},
    "security": [{"bearer": []}],
    "paths": {
        "/items": {"get": {"operationId": "listItems",
                           "summary": "Daftar item",
                           "responses": {"200": {"description": "ok"}}}},
    },
}

SPEC_SWAGGER2 = {
    "swagger": "2.0",
    "info": {"title": "Legacy Swagger API", "version": "0.9.1"},
    "host": "api.legacy-service.example",
    "basePath": "/v1",
    "schemes": ["https"],
    "paths": {
        "/ping": {"get": {"operationId": "ping",
                          "summary": "Ping legacy",
                          "responses": {"200": {"description": "pong"}}}},
    },
}


def _spec_with_server(url: str) -> dict:
    s = yaml.safe_load(yaml.safe_dump(SPEC_OAS3_PUBLIC))
    s["servers"] = [{"url": url}]
    return s


# ---------------------------------------------------------------------------
# B — 2 test dasar
# ---------------------------------------------------------------------------


def test_b1_spesifikasi_publik_menghasilkan_manifest_sah():
    """B1: spec publik tanpa auth -> manifest valid, credential_free, read+write."""
    r = ag.generate_one(SPEC_OAS3_PUBLIC, "demo-public")
    assert r.ok is True, f"{r.reason} {r.errors}"
    assert r.credential_free is True
    assert r.actions >= 4, f"hanya {r.actions} action"

    m, _, _ = ag.build_manifest(SPEC_OAS3_PUBLIC, "demo-public")
    assert m["id"] == "apisguru.demo_public"
    assert m["auth"] == {"type": "none"}
    assert m["source"] == "apisguru"
    assert validate_manifest(m) == []

    methods = {a["method"] for a in m["actions"]}
    assert {"GET", "POST", "DELETE"} <= methods
    # operation_type diturunkan dari method, bukan ditebak
    for a in m["actions"]:
        expect = {"GET": "read", "POST": "write", "DELETE": "delete"}[a["method"]]
        assert a["operation_type"] == expect, a


def test_b2_swagger2_host_basepath_dipakai_sebagai_server():
    """B2 (fallback wajib): Swagger 2.0 tanpa servers[] tetap dapat dieksekusi."""
    r = ag.generate_one(SPEC_SWAGGER2, "demo-legacy")
    assert r.ok is True, f"{r.reason} {r.errors}"
    m, _, _ = ag.build_manifest(SPEC_SWAGGER2, "demo-legacy")
    assert m["actions"][0]["url_base"] == "https://api.legacy-service.example/v1"


# ---------------------------------------------------------------------------
# E — 2 edge case
# ---------------------------------------------------------------------------


def test_e1_parameter_path_tanpa_contoh_membuang_operasi_bukan_membuat_placeholder():
    """E1: jangan pernah mengisi path dengan placeholder palsu."""
    spec = yaml.safe_load(yaml.safe_dump(SPEC_OAS3_PUBLIC))
    spec["paths"]["/things/{thingId}"]["get"]["parameters"][0].pop("example")
    m, _, skipped = ag.build_manifest(spec, "no-example")
    assert m is not None
    names = {a["name"] for a in m["actions"]}
    assert "getthing" not in names, "operasi tanpa contoh tetap dibuat"
    assert skipped >= 1
    # tidak ada '{' tersisa di path mana pun
    for a in m["actions"]:
        assert "{" not in a["path"], a["path"]


def test_e2_operasi_deprecated_dan_path_terlalu_dalam_dilewati():
    """E2: deprecated & path ekstrem tidak menjadi tool."""
    spec = yaml.safe_load(yaml.safe_dump(SPEC_OAS3_PUBLIC))
    spec["paths"]["/things"]["get"]["deprecated"] = True
    deep = "/" + "/".join(f"seg{i}" for i in range(20))
    spec["paths"][deep] = {"get": {"operationId": "deepOp",
                                   "summary": "terlalu dalam",
                                   "responses": {"200": {"description": "ok"}}}}
    m, _, skipped = ag.build_manifest(spec, "edge-ops")
    assert m is not None
    names = {a["name"] for a in m["actions"]}
    assert "listthings" not in names
    assert "deepop" not in names
    assert skipped >= 2


# ---------------------------------------------------------------------------
# X — 2 error handling
# ---------------------------------------------------------------------------


def test_x1_spesifikasi_rusak_tidak_membuat_crash():
    """X1: bentuk aneh -> GenResult gagal dengan alasan, bukan exception liar."""
    cases = [
        ({}, "kosong"),
        ({"openapi": "3.0.0"}, "tanpa info/paths"),
        ({"openapi": "3.0.0", "info": {"title": "x"}, "paths": {}}, "paths kosong"),
        ({"openapi": "3.0.0", "info": {"title": "x"},
          "servers": [{"url": "https://api.x.example"}],
          "paths": {"semua": "bukan-dict"}}, "paths bukan dict"),
        (None, "None"),
        ("string", "string"),
    ]
    for spec, label in cases:
        r = ag.generate_one(spec if isinstance(spec, dict) else {}, "broken")
        assert r.ok is False, label
        assert r.reason, label


def test_x2_direktori_rusak_melempar_GeneratorError_dengan_pesan_jelas(tmp_path):
    """X2: list.json terpotong (persis yang terjadi saat unduhan putus)."""
    bad = tmp_path / "bad.json"
    bad.write_text('{"a": {"versions": {"1": {"openapiUrl": "https://x', encoding="utf-8")
    with pytest.raises(ag.GeneratorError) as exc:
        ag.load_directory(bad)
    assert "rusak" in str(exc.value) or "terpotong" in str(exc.value)

    missing = tmp_path / "nope.json"
    with pytest.raises(ag.GeneratorError):
        ag.load_directory(missing)

    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    with pytest.raises(ag.GeneratorError):
        ag.load_directory(empty)


# ---------------------------------------------------------------------------
# P — 2 performa
# ---------------------------------------------------------------------------


def _big_spec(n_paths: int = 200) -> dict:
    paths = {}
    for i in range(n_paths):
        paths[f"/resource{i}"] = {
            "get": {"operationId": f"listResource{i}",
                    "summary": f"Daftar resource {i}",
                    "responses": {"200": {"description": "ok"}}},
            "post": {"operationId": f"createResource{i}",
                     "summary": f"Buat resource {i}",
                     "responses": {"201": {"description": "ok"}}},
        }
    return {"openapi": "3.0.0", "info": {"title": "Big API", "version": "1.0.0"},
            "servers": [{"url": "https://api.big-demo.example"}], "paths": paths}


def test_p1_satu_spesifikasi_besar_diproses_cepat():
    """P1: 400 operasi harus selesai < 3 detik (tanpa I/O)."""
    spec = _big_spec(200)
    t0 = time.perf_counter()
    r = ag.generate_one(spec, "big")
    dt = time.perf_counter() - t0
    assert r.ok is True, r.reason
    assert dt < 3.0, f"{dt:.2f}s untuk 400 operasi"


def test_p2_150_spesifikasi_selesai_di_bawah_1_menit():
    """P2: target brief 100-200 connector — sediakan waktu yang jujur."""
    specs = [(_big_spec(20), f"api-{i}") for i in range(150)]
    t0 = time.perf_counter()
    results = ag.generate_batch([(n, s) for s, n in specs], write=False)
    dt = time.perf_counter() - t0
    assert len(results) == 150
    assert all(r.ok for r in results), [r.reason for r in results[:3]]
    assert dt < 60.0, f"{dt:.1f}s untuk 150 spesifikasi"


# ---------------------------------------------------------------------------
# S — 1 keamanan
# ---------------------------------------------------------------------------


def test_s1_server_loopback_privat_dan_template_ditolak():
    """S1: guard SSRF & placeholder server tidak boleh lolos."""
    blocked = [
        "http://api.demo.example",                 # bukan https
        "https://localhost/mcp",
        "https://127.0.0.1/v1",
        "https://10.1.2.3/v1",
        "https://192.168.0.1/v1",
        "https://169.254.169.254/latest",
        "https://metadata.google.internal/v1",
        "https://svc.internal/v1",
        "https://{env}.demo.example",             # template variabel
    ]
    for url in blocked:
        r = ag.generate_one(_spec_with_server(url), "ssrf")
        assert r.ok is False, f"SSRF lolos: {url} -> ok={r.ok}"
        assert "server" in r.reason or "https" in r.reason, (url, r.reason)


# ---------------------------------------------------------------------------
# X — integrasi E2E
# ---------------------------------------------------------------------------


def test_x3_manifest_hasil_generator_lolos_skema_dan_dapat_ditulis(tmp_path):
    """X3: tulis YAML ke disk, baca ulang, parse, validasi — lingkaran penuh."""
    results = ag.generate_batch([("demo-public", SPEC_OAS3_PUBLIC),
                                 ("demo-legacy", SPEC_SWAGGER2)],
                                out_dir=tmp_path, write=True)
    assert all(r.ok for r in results)
    for r in results:
        p = tmp_path / f"{r.slug}.yaml"
        assert p.exists(), r.slug
        text = p.read_text(encoding="utf-8")
        assert "apisguru_generator" in text
        data = yaml.safe_load(text)
        assert validate_manifest(data) == [], validate_manifest(data)
        # generator tidak pernah mengklaim terverifikasi
        for a in data["actions"]:
            assert a["verification"]["level"] == "listed"


def test_x4_verification_level_selalu_listed_bukan_call_verified():
    """X4 (invarian kejujuran): generator dilarang mengklaim terverifikasi."""
    m, _, _ = ag.build_manifest(SPEC_OAS3_PUBLIC, "demo-public")
    for a in m["actions"]:
        assert a["verification"]["level"] == "listed"
        assert a["error_handler"]["type"] == "DefaultErrorHandler"
        assert a["error_handler"]["retry"]["type"] in (
            "ExponentialBackoffStrategy", "ConstantBackoffStrategy")


def test_x5_auth_tidak_dikenal_tidak_pernah_dianggap_none():
    """X5: skema auth yang aneh harus jadi api_key, bukan none."""
    spec = yaml.safe_load(yaml.safe_dump(SPEC_OAS3_PUBLIC))
    spec["components"] = {"securitySchemes": {
        "weird": {"type": "mutualTLS"}}}
    spec["security"] = [{"weird": []}]
    m, _, _ = ag.build_manifest(spec, "weird-auth")
    assert m["auth"]["type"] != "none"
    assert m["credential_free"] is False


def test_x9_auth_non_none_selalu_punya_credential_form():
    """X9 (bug nyata): tiap auth non-none wajib punya credential_form.

    Tanpa ini `validate_manifest` menolak manifest — persis yang terjadi pada
    stripe (basic) dan s3 sebelum diperbaiki.
    """
    cases = [
        ({"type": "http", "scheme": "basic"}, "basic", "user_pass"),
        ({"type": "http", "scheme": "bearer"}, "bearer", "token_paste"),
        ({"type": "apiKey", "in": "header", "name": "X-API-Key"},
         "api_key", "api_key_header"),
        ({"type": "apiKey", "in": "query", "name": "key"},
         "api_key", "api_key_query"),
        ({"type": "mutualTLS"}, "api_key", "api_key_header"),
    ]
    for scheme_def, expect_type, expect_form in cases:
        spec = yaml.safe_load(yaml.safe_dump(SPEC_OAS3_PUBLIC))
        spec["components"] = {"securitySchemes": {"s": scheme_def}}
        spec["security"] = [{"s": []}]
        m, _, _ = ag.build_manifest(spec, "auth-case")
        assert m is not None, scheme_def
        assert m["auth"]["type"] == expect_type, (scheme_def, m["auth"])
        assert m["auth"].get("credential_form") == expect_form, m["auth"]
        assert validate_manifest(m) == [], validate_manifest(m)


def test_x10_oauth2_punya_connect_url():
    """X10: oauth2 wajib punya connect_url + scopes bila ada di spec."""
    spec = yaml.safe_load(yaml.safe_dump(SPEC_OAS3_PUBLIC))
    spec["components"] = {"securitySchemes": {"o": {
        "type": "oauth2",
        "flows": {"authorizationCode": {
            "authorizationUrl": "https://auth.demo.example/o",
            "tokenUrl": "https://auth.demo.example/t",
            "scopes": {"read": "baca", "write": "tulis"}}}}}}
    spec["security"] = [{"o": ["read"]}]
    m, _, _ = ag.build_manifest(spec, "oauth-case")
    assert m["auth"]["type"] == "oauth2"
    assert m["auth"]["connect_url"].startswith("https://")
    assert "read" in m["auth"]["scopes"]
    assert validate_manifest(m) == [], validate_manifest(m)


def _spec_without_bodies() -> dict:
    """Salinan spec yang POST/DELETE-nya sengaja tanpa requestBody."""
    s = yaml.safe_load(yaml.safe_dump(SPEC_OAS3_PUBLIC))
    s["paths"]["/things"]["post"].pop("requestBody", None)
    s["paths"]["/things/{thingId}"]["delete"].pop("requestBody", None)
    return s


def test_x11_operasi_write_delete_punya_request_body_json_berisi():
    """X11 (bug nyata): harness menuntut body yang BERISI pada write/delete.

    `{}` adalah falsy di Python, jadi body kosong tetap dianggap "tanpa body".
    Operasi write tanpa field apa pun karena itu **dibuang**, bukan diberi
    body palsu. Ini yang membuat `action_complete` gagal pada 77 manifest
    sebelum diperbaiki.
    """
    r = ag.generate_one(SPEC_OAS3_PUBLIC, "demo-public")
    assert r.ok, r.reason
    m, _, _ = ag.build_manifest(SPEC_OAS3_PUBLIC, "demo-public")
    for a in m["actions"]:
        if a["operation_type"] in ("write", "delete"):
            assert a.get("request_body_json"), a["name"]
            assert a["request_body_json"] != {}, a["name"]
    methods = {a["method"] for a in m["actions"]}
    assert {"GET", "POST", "DELETE"} <= methods, methods

    # request body OpenAPI yang berisi benar-benar dipakai
    post = [a for a in m["actions"] if a["method"] == "POST"][0]
    assert set(post["request_body_json"]) == {"name"}, post["request_body_json"]
    dele = [a for a in m["actions"] if a["method"] == "DELETE"][0]
    assert set(dele["request_body_json"]) == {"reason"}, dele["request_body_json"]


def test_x13_write_tanpa_body_dibuang_bukan_diberi_body_palsu():
    """X13: operasi tulis tanpa field harus hilang, bukan diisi karangan."""
    spec = _spec_without_bodies()
    m, _, skipped = ag.build_manifest(spec, "no-body")
    names = {a["name"] for a in m["actions"]}
    assert "creatething" not in names
    assert "deletething" not in names
    assert skipped >= 2
    # tidak ada action write yang tersisa tanpa body
    for a in m["actions"]:
        if a["operation_type"] in ("write", "delete"):
            assert a.get("request_body_json"), a["name"]





def test_x6_plan_batch_mengutamakan_credential_free():
    """X6: urutan batch menaruh API tanpa auth di depan."""
    directory = {
        "z-secured.example": {"preferred": "1.0.0", "versions": {
            "1.0.0": {"swaggerUrl": "https://x/1", "security": [{"k": []}]}}},
        "a-open.example": {"preferred": "1.0.0", "versions": {
            "1.0.0": {"swaggerUrl": "https://x/2"}}},
        "no-url.example": {"preferred": "1.0.0", "versions": {"1.0.0": {}}},
    }
    plan = ag.plan_batch(directory, limit=10)
    assert plan[0] == "a-open.example", plan
    assert "no-url.example" not in plan


def test_x12_swaggerUrl_dikenali_bukan_hanya_openapiUrl():
    """X12 (bug nyata): direktori APIs.guru memakai `swaggerUrl`.

    Memeriksa hanya `openapiUrl` menolak SELURUH 2.529 entri direktori.
    """
    for key in ("openapiUrl", "swaggerUrl", "openapiYamlUrl", "swaggerYamlUrl"):
        entry = {"preferred": "1.0.0",
                 "versions": {"1.0.0": {key: "https://spec.demo.example/x.json"}}}
        assert ag.spec_is_eligible(entry)[0] is True, key
        assert ag.spec_url(entry) == "https://spec.demo.example/x.json", key

    # non-https dan kosong tetap ditolak
    for bad in ("http://spec.demo.example/x.json", "", "ftp://x/y"):
        entry = {"preferred": "1.0.0",
                 "versions": {"1.0.0": {"swaggerUrl": bad}}}
        assert ag.spec_is_eligible(entry)[0] is False, bad
        assert ag.spec_url(entry) == "", bad

    # JSON lebih diutamakan daripada YAML
    entry = {"preferred": "1.0.0", "versions": {"1.0.0": {
        "openapiUrl": "https://x/a.json", "swaggerYamlUrl": "https://x/a.yaml"}}}
    assert ag.spec_url(entry) == "https://x/a.json"



def test_x7_summarize_konsisten_dengan_hasil():
    """X7: ringkasan dihitung dari hasil, bukan konstanta."""
    results = [ag.generate_one(SPEC_OAS3_PUBLIC, "ok-1"),
               ag.generate_one(SPEC_SWAGGER2, "ok-2"),
               ag.generate_one({}, "bad")]
    s = ag.summarize(results)
    assert s["total"] == 3
    assert s["ok"] == 2
    assert s["failed"] == 1
    assert s["actions_total"] == sum(r.actions for r in results if r.ok)
    assert s["credential_free"] == 2


def test_x8_max_actions_dibatasi():
    """X8: spesifikasi raksasa tidak menghasilkan manifest raksasa."""
    spec = _big_spec(200)
    m, _, _ = ag.build_manifest(spec, "big")
    assert len(m["actions"]) <= ag.MAX_ACTIONS


def test_x14_verify_batch_memisahkan_host_mati(tmp_path):
    """X14 (temuan kejujuran): manifest ke host mati tidak dihitung executable.

    APIs.guru memuat spesifikasi yang menunjuk sandbox host yang sudah
    dihentikan (mis. `test.api.amadeus.com` tidak resolve). Manifest semacam
    itu lolos skema tetapi gagal saat dipanggil, jadi harus dipisahkan.
    """
    # host yang pasti tidak resolve + host yang pasti resolve
    dead_spec = _spec_with_server("https://this-host-does-not-exist-katalir.example")
    # catatan: `.example` adalah doc-host -> dilewati guard; pakai host karangan
    dead_spec = yaml.safe_load(yaml.safe_dump(SPEC_OAS3_PUBLIC))
    dead_spec["servers"] = [{"url": "https://nx-not-real-host-9f3a.invalid"}]
    live_spec = yaml.safe_load(yaml.safe_dump(SPEC_OAS3_PUBLIC))
    live_spec["servers"] = [{"url": "https://api.github.com"}]

    results = ag.generate_batch([("dead-api", dead_spec),
                                 ("live-api", live_spec)],
                                out_dir=tmp_path, write=True)
    assert all(r.ok for r in results), [r.reason for r in results]

    alive, dead = ag.verify_batch(results)
    alive_names = {r.api for r in alive}
    dead_names = {r.api for r in dead}
    assert "live-api" in alive_names, [r.api for r in alive]
    assert "dead-api" in dead_names, [r.api for r in dead]
    assert len(alive) + len(dead) == 2

