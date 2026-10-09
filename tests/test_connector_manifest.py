"""tests/test_connector_manifest.py — uji skema manifest + harness 10-test.

Distribusi (mengikuti pola proyek):
  B  = dasar
  D  = durability/determinisme
  E  = edge case
  P  = performa
  S  = keamanan
  X  = invarian lintas-fungsi

Test jaringan (test 5/6/10 harness) TIDAK dijalankan di sini karena suite
harus dapat jalan offline. Yang diuji adalah **aturan penilaiannya**: bahwa
tanpa jaringan hasilnya `skipped` — dan `skipped` tidak pernah dihitung PASS.
Itu justru invarian paling penting dari harness ini.
"""

from __future__ import annotations

import json

import pytest

import connector_harness as ch
import connector_manifest as cm


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

VALID_YAML = """
manifest_version: 1
id: test.service.ping
slug: test_service_ping
display_name: "Test — Ping"
description: "Connector uji."
category: testing
source: native
tenant_scope: public
credential_free: true
auth:
  type: none
actions:
  - name: ping
    operation_type: read
    method: GET
    url_base: https://restcountries.com
    path: /v3.2/all
    error_handler:
      type: DefaultErrorHandler
      retry:
        type: ExponentialBackoffStrategy
        max_retries: 3
    verification:
      level: call_verified
rate_limit:
  type: FixedWindowCallRatePolicy
  max_calls: 60
  window_seconds: 60
"""


def _load(text: str = VALID_YAML) -> dict:
    return cm.parse_manifest(text)


def _mut(**overrides) -> dict:
    d = _load()
    d.update(overrides)
    return d


# ---------------------------------------------------------------------------
# B — dasar
# ---------------------------------------------------------------------------


def test_b1_manifest_valid():
    errors = cm.validate_manifest(_load())
    assert errors == [], errors


def test_b2_compile_menghasilkan_entri_registry():
    e = cm.compile_manifest(_load())
    assert e["id"] == "test.service.ping"
    assert e["slug"] == "test_service_ping"
    assert e["source"] == "native"
    assert e["tools_count"] == 1
    assert e["install_config"]["transport"] == "http"
    assert e["runtime_verified"] is True


def test_b3_describe_memuat_seluruh_kosakata():
    d = cm.describe()
    assert d["manifest_version"] == cm.MANIFEST_VERSION
    assert d["auth_types"] == list(cm.AUTH_TYPES)
    assert d["verification_levels"] == ["listed", "callable", "call_verified"]
    assert d["interpolation_filters"] == list(cm.INTERPOLATION_FILTERS)


def test_b4_harness_mengembalikan_10_test():
    r = ch.run_harness(VALID_YAML)
    assert len(r.results) == 10
    assert [x.test for x in r.results] == list(range(1, 11))
    assert [x.name for x in r.results] == list(ch.TEST_NAMES)


# ---------------------------------------------------------------------------
# D — determinisme
# ---------------------------------------------------------------------------


def test_d1_compile_deterministik():
    a = cm.compile_manifest(_load())
    b = cm.compile_manifest(_load())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True), \
        "compile_manifest harus deterministik"


def test_d2_manifest_hash_stabil():
    h1 = cm.manifest_hash(_load())
    h2 = cm.manifest_hash(_load())
    assert h1 == h2 and len(h1) == 64


def test_d3_manifest_hash_berubah_bila_isi_berubah():
    d = _load()
    h1 = cm.manifest_hash(d)
    d["description"] = "berubah"
    assert cm.manifest_hash(d) != h1


def test_d4_harness_dapat_diulang_hasilnya_sama():
    r1 = ch.run_harness(VALID_YAML)
    r2 = ch.run_harness(VALID_YAML)
    assert r1.passed == r2.passed and r1.failed == r2.failed and r1.skipped == r2.skipped


# ---------------------------------------------------------------------------
# E — edge case pada validasi
# ---------------------------------------------------------------------------


def test_e1_manifest_version_salah_ditolak():
    errs = cm.validate_manifest(_mut(manifest_version=2))
    assert any("manifest_version" in e for e in errs)


def test_e2_id_tanpa_titik_ditolak():
    errs = cm.validate_manifest(_mut(id="tidakadaNamespace"))
    assert any(e.startswith("id:") for e in errs)


def test_e3_actions_kosong_ditolak():
    errs = cm.validate_manifest(_mut(actions=[]))
    assert any("actions:" in e for e in errs)


def test_e4_nama_action_duplikat_ditolak():
    d = _load()
    d["actions"] = [d["actions"][0], dict(d["actions"][0])]
    errs = cm.validate_manifest(d)
    assert any("duplikat" in e for e in errs)


def test_e5_operation_type_tidak_dikenal_ditolak():
    d = _load()
    d["actions"][0]["operation_type"] = "destroy"
    errs = cm.validate_manifest(d)
    assert any("operation_type" in e for e in errs)


def test_e6_tenant_scope_tidak_dikenal_ditolak():
    errs = cm.validate_manifest(_mut(tenant_scope="semua"))
    assert any("tenant_scope" in e for e in errs)


def test_e7_auth_bukan_none_tanpa_credential_form_ditolak():
    d = _load()
    d["auth"] = {"type": "bearer"}
    errs = cm.validate_manifest(d)
    assert any("credential_form" in e for e in errs)


def test_e8_oauth2_tanpa_connect_url_ditolak():
    d = _load()
    d["auth"] = {"type": "oauth2", "credential_form": "google"}
    errs = cm.validate_manifest(d)
    assert any("connect_url" in e for e in errs)


def test_e9_webhook_tanpa_signature_ditolak():
    d = _load()
    d["triggers"] = [{"name": "t", "type": "webhook", "header": "X-Sig"}]
    errs = cm.validate_manifest(d)
    assert any("signature" in e for e in errs)


def test_e10_cron_schedule_salah_ditolak():
    d = _load()
    d["triggers"] = [{"name": "t", "type": "cron", "schedule": "tiap jam"}]
    errs = cm.validate_manifest(d)
    assert any("schedule" in e for e in errs)


def test_e11_rate_limit_tanpa_max_calls_ditolak():
    d = _load()
    d["rate_limit"] = {"type": "FixedWindowCallRatePolicy", "window_seconds": 60}
    errs = cm.validate_manifest(d)
    assert any("max_calls" in e for e in errs)


def test_e12_unlimited_rate_limit_tidak_butuh_max_calls():
    d = _load()
    d["rate_limit"] = {"type": "UnlimitedCallRatePolicy"}
    assert cm.validate_manifest(d) == []


def test_e13_retry_max_retries_di_luar_rentang_ditolak():
    d = _load()
    d["actions"][0]["error_handler"]["retry"]["max_retries"] = 99
    errs = cm.validate_manifest(d)
    assert any("max_retries" in e for e in errs)


def test_e14_interpolasi_variabel_asing_ditolak():
    d = _load()
    d["actions"][0]["path"] = "/x/{{ os.environ.HOME }}"
    errs = cm.validate_manifest(d)
    assert any("variabel interpolasi" in e for e in errs)


def test_e15_interpolasi_filter_asing_ditolak():
    d = _load()
    d["actions"][0]["path"] = "/x/{{ config.a | pickle }}"
    errs = cm.validate_manifest(d)
    assert any("filter interpolasi" in e for e in errs)


def test_e16_semver_minimum_supported_release():
    assert cm.validate_manifest(_mut(minimum_supported_release="1.0")) != []
    assert cm.validate_manifest(_mut(minimum_supported_release="1.0.0")) == []


def test_e17_parse_yaml_bukan_mapping_ditolak():
    with pytest.raises(cm.ManifestError):
        cm.parse_manifest("- satu\n- dua\n")


def test_e18_harness_manifest_rusak_tetap_10_hasil():
    r = ch.run_harness("ini: [bukan: yaml: valid")
    assert len(r.results) == 10
    assert r.failed > 0
    assert r.verdict() == ch.FAIL


# ---------------------------------------------------------------------------
# P — performa
# ---------------------------------------------------------------------------


def test_p1_validate_100_manifest_cepat():
    import time

    d = _load()
    t0 = time.perf_counter()
    for _ in range(100):
        cm.validate_manifest(d)
    dt = time.perf_counter() - t0
    assert dt < 3.0, f"100 validasi memakan {dt:.2f}s"


def test_p2_compile_50_manifest_cepat():
    import time

    d = _load()
    t0 = time.perf_counter()
    for _ in range(50):
        cm.compile_manifest(d)
    dt = time.perf_counter() - t0
    assert dt < 3.0, f"50 compile memakan {dt:.2f}s"


def test_p3_harness_tanpa_jaringan_cepat():
    import time

    t0 = time.perf_counter()
    for _ in range(20):
        ch.run_harness(VALID_YAML)
    dt = time.perf_counter() - t0
    assert dt < 3.0, f"20 harness tanpa jaringan memakan {dt:.2f}s"


# ---------------------------------------------------------------------------
# S — keamanan
# ---------------------------------------------------------------------------


def test_s1_loopback_diblokir():
    assert cm.host_is_blocked("http://127.0.0.1/x") is True
    assert cm.host_is_blocked("http://localhost/x") is True


def test_s2_metadata_cloud_diblokir():
    assert cm.host_is_blocked("http://169.254.169.254/latest/meta-data") is True
    assert cm.host_is_blocked("http://metadata.google.internal/") is True


def test_s3_rfc1918_diblokir():
    for u in ("http://10.0.0.1/", "http://192.168.1.1/", "http://172.16.0.1/"):
        assert cm.host_is_blocked(u) is True, u


def test_s4_host_publik_diizinkan():
    assert cm.host_is_blocked("https://api.github.com") is False
    assert cm.host_is_blocked("https://restcountries.com") is False


def test_s5_token_github_terdeteksi():
    assert cm.scan_secrets("token: ghp_" + "a" * 24) != []


def test_s6_jwt_terdeteksi():
    assert cm.scan_secrets("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc") != []


def test_s7_private_key_terdeteksi():
    assert cm.scan_secrets("-----BEGIN RSA PRIVATE KEY-----") != []


def test_s8_teks_bersih_tidak_terdeteksi():
    assert cm.scan_secrets("url_base: https://api.github.com\nmethod: GET") == []


def test_s9_manifest_dengan_rahasia_ditolak_harness():
    y = VALID_YAML.replace(
        "url_base: https://restcountries.com",
        "url_base: https://restcountries.com\n    note: ghp_" + "b" * 24,
    )
    r = ch.run_harness(y)
    security = [x for x in r.results if x.test == 9][0]
    assert security.status == ch.FAIL
    assert "rahasia" in security.detail


def test_s10_url_base_loopback_gagal_test_9():
    d = _load()
    d["actions"][0]["url_base"] = "http://127.0.0.1:8080"
    y = json.dumps(d)  # harness menerima dict lewat argumen data
    r = ch.run_harness(y, data=d)
    security = [x for x in r.results if x.test == 9][0]
    assert security.status == ch.FAIL
    assert "SSRF" in security.detail


def test_s11_path_absolut_berskema_ditolak():
    d = _load()
    d["actions"][0]["path"] = "https://evil.example/steal"
    r = ch.run_harness("", data=d)
    security = [x for x in r.results if x.test == 9][0]
    assert security.status == ch.FAIL


# ---------------------------------------------------------------------------
# X — invarian
# ---------------------------------------------------------------------------


def test_x1_skipped_tidak_pernah_dihitung_pass():
    """Invarian terpenting harness: tanpa jaringan, test 5/6/10 SKIPPED."""
    r = ch.run_harness(VALID_YAML, opts=ch.HarnessOptions(allow_network=False))
    t5 = [x for x in r.results if x.test == 5][0]
    t10 = [x for x in r.results if x.test == 10][0]
    assert t5.status == ch.SKIP
    assert t10.status == ch.SKIP
    assert r.passed < 10, "manifest credential_free tanpa jaringan tidak boleh 10/10 PASS"
    assert r.verdict() == ch.FAIL


def test_x2_credential_free_false_membuat_test_6_dan_10_skip():
    d = _load()
    d["credential_free"] = False
    d["auth"] = {"type": "bearer", "credential_form": "github_pat"}
    r = ch.run_harness("", data=d)
    t6 = [x for x in r.results if x.test == 6][0]
    t10 = [x for x in r.results if x.test == 10][0]
    assert t6.status == ch.SKIP and t10.status == ch.SKIP


def test_x3_call_verified_tanpa_credential_free_tidak_dipromosikan():
    """Manifest boleh MENGKLAIM call_verified, registry tidak boleh menurutinya
    bila connector butuh kredensial."""
    d = _load()
    d["credential_free"] = False
    d["auth"] = {"type": "bearer", "credential_form": "github_pat"}
    e = cm.compile_manifest(d)
    assert e["verification"]["level"] == "callable", \
        "klaim call_verified tanpa kredensial harus diturunkan ke callable"
    assert e["verification"]["call_verified"] is False


def test_x4_credential_free_benar_mempromosikan_call_verified():
    d = _load()
    d["credential_free"] = True
    d["auth"] = {"type": "none"}
    e = cm.compile_manifest(d)
    assert e["verification"]["level"] == "call_verified"
    assert e["verification"]["call_verified"] is True


def test_x5_auth_none_selalu_credential_free():
    d = _load()
    d["auth"] = {"type": "none"}
    d["credential_free"] = False  # diklaim butuh kredensial padahal auth none
    e = cm.compile_manifest(d)
    assert e["credential_free"] is True, "auth none harus selalu credential_free"
    assert e["no_auth"] is True


def test_x6_describe_harness_konsisten_dengan_TEST_NAMES():
    d = ch.describe()
    assert d["count"] == len(ch.TEST_NAMES) == 10
    assert [t["name"] for t in d["tests"]] == list(ch.TEST_NAMES)


def test_x7_operation_types_di_entri_mencerminkan_actions():
    d = _load()
    d["actions"] = [
        d["actions"][0],
        {
            "name": "tulis",
            "operation_type": "write",
            "method": "POST",
            "url_base": "https://restcountries.com",
            "path": "/x",
            "request_body_json": {"a": "b"},
            "error_handler": {"type": "DefaultErrorHandler",
                              "retry": {"type": "ConstantBackoffStrategy", "max_retries": 2}},
        },
        {
            "name": "hapus",
            "operation_type": "delete",
            "method": "DELETE",
            "url_base": "https://restcountries.com",
            "path": "/x/1",
            "request_body_json": {"id": 1},
            "error_handler": {"type": "DefaultErrorHandler",
                              "retry": {"type": "ConstantBackoffStrategy", "max_retries": 2}},
        },
    ]
    e = cm.compile_manifest(d)
    assert set(e["operation_types"]) == {"read", "write", "delete"}
    assert e["has_write"] is True and e["has_delete"] is True


def test_x8_manifest_canonical_key_stabil():
    d = _load()
    assert cm.manifest_canonical_key(d) == "test.service.ping"


def test_x9_entri_compile_cocok_dengan_bentuk_mcp_registry():
    """Entri hasil compile harus punya field yang dibaca mcp_registry."""
    e = cm.compile_manifest(_load())
    for key in ("id", "name", "source", "category", "tools_count", "tools",
                "install_config", "runtime_verified", "verification"):
        assert key in e, f"mcp_registry membaca '{key}'"


def test_x10_tools_mencerminkan_actions_tanpa_kehilangan():
    d = _load()
    e = cm.compile_manifest(d)
    assert len(e["tools"]) == len(d["actions"])
    assert {t["name"] for t in e["tools"]} == {a["name"] for a in d["actions"]}


def test_x11_batch_gate_menolak_batch_tanpa_executable():
    g = cm.BatchGate(batch_no=1, size=2)
    g.add("a", passed=10, failed=0, executable=False)
    g.add("b", passed=10, failed=0, executable=False)
    v = g.verdict()
    assert v["checks"]["all_tests_pass"] is True
    assert v["checks"]["executable_increased"] is False
    assert v["verdict"] == "FAIL", "batch yang tidak menaikkan executable harus DITOLAK"


def test_x12_batch_gate_lulus_bila_ada_executable():
    g = cm.BatchGate(batch_no=2, size=2)
    g.add("a", passed=10, failed=0, executable=True)
    g.add("b", passed=10, failed=0, executable=True)
    v = g.verdict()
    assert v["verdict"] == "PASS"
    assert v["tests_passed"] == 20


def test_x13_batch_gate_menolak_bila_ada_test_gagal():
    g = cm.BatchGate(batch_no=3, size=1)
    g.add("a", passed=9, failed=1, executable=True)
    assert g.verdict()["verdict"] == "FAIL"


def test_x14_batch_gate_menolak_ukuran_salah():
    g = cm.BatchGate(batch_no=4, size=20)
    g.add("a", passed=10, failed=0, executable=True)
    v = g.verdict()
    assert v["checks"]["size_ok"] is False
    assert v["verdict"] == "FAIL"


def test_x15_run_batch_mengagregasi_benar():
    out = ch.run_batch([("a", VALID_YAML), ("b", VALID_YAML)])
    assert out["connectors"] == 2
    assert out["failed_tests"] == 0
    assert len(out["per_connector"]) == 2


def test_x16_harness_tidak_pernah_melempar_dari_input_aneh():
    for bad in ("", "{}", "[]", "null", "manifest_version: 1", "id: x"):
        r = ch.run_harness(bad)
        assert len(r.results) == 10


def test_x17_verdict_harness_membutuhkan_10_pass():
    r = ch.run_harness(VALID_YAML)
    if r.passed == 10:
        assert r.verdict() == ch.PASS
    else:
        assert r.verdict() == ch.FAIL
