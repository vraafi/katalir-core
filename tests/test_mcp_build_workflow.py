"""Unit test untuk fitur #2 — MCP Build Workflow.

Struktur mengikuti paket sebelumnya: Basic (B), Durability (D), Edge (E),
Performance (P), Security (S), dan Extra/invariant (X).

Kebijakan tulis: uji ini mengunci FAKTA yang diambil dari docs resmi n8n dan
spesifikasi MCP 2026-07-28. Bila n8n/ spesifikasi berubah, yang gagal lebih
dulu harus uji ini — bukan perilaku di produksi.
"""

from __future__ import annotations

import threading
import time

import pytest

import mcp_build_workflow as M


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
class Clock:
    """Jam palsu deterministik."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, dt: float) -> float:
        self.now += float(dt)
        return self.now


def make_session(version: str = "2.43.0", clk: Clock | None = None
                 ) -> M.BuildSession:
    return M.BuildSession(version=version, _clock=clk or Clock())


def classic_headers(method: str = "tools/call", name: str = "search_nodes",
                    rev: str = M.LATEST_MODERN_REVISION) -> dict:
    return {"Mcp-Method": method, "Mcp-Name": name,
            "MCP-Protocol-Version": rev}


def modern_meta(rev: str = M.LATEST_MODERN_REVISION) -> dict:
    return {
        M.META_PROTOCOL_VERSION: rev,
        M.META_CLIENT_INFO: {"name": "test-client", "version": "1.0.0"},
        M.META_CLIENT_CAPABILITIES: {"tools": {}},
    }


# ---------------------------------------------------------------------------
# B. Basic
# ---------------------------------------------------------------------------
def test_b1_katalog_persis_dari_docs():
    """B1: 53 tool, 7 kategori — angka yang sama dengan docs n8n."""
    assert len(M.TOOLS) == 53
    assert len(M.TOOL_CATEGORIES) == 7
    assert len(set(M.TOOL_NAMES)) == 53, "nama tool harus unik"

    counts = {c: len(M.tools_in_category(c)) for c in M.TOOL_CATEGORIES}
    assert counts == {
        "Workflow management": 13,
        "Execution management": 2,
        "Credential management": 1,
        "Instance context": 4,
        "Workflow builder": 11,
        "Agent management": 15,
        "Data tables": 7,
    }
    assert sum(counts.values()) == 53


def test_b2_revisi_protokol_dan_default_modern():
    """B2: registry revisi + hanya 2026-07-28 yang modern (stateless)."""
    assert M.PROTOCOL_REVISIONS == (
        "2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25",
        "2026-07-28")
    assert M.MODERN_REVISIONS == ("2026-07-28",)
    assert M.LATEST_REVISION == "2026-07-28"
    assert M.LATEST_MODERN_REVISION == "2026-07-28"
    # Handshake + modern harus memisah tanpa tumpang tindih.
    assert set(M.HANDSHAKE_REVISIONS) & set(M.MODERN_REVISIONS) == set()
    assert (set(M.HANDSHAKE_REVISIONS) | set(M.MODERN_REVISIONS)
            == set(M.PROTOCOL_REVISIONS))
    # Header & konsep wajib revisi modern.
    assert M.MODERN_REQUIRED_HEADERS == ("Mcp-Method", "Mcp-Name")
    assert M.REVOKED_SESSION_HEADER == "Mcp-Session-Id"
    assert M.DISCOVER_METHOD == "server/discover"
    assert M.CACHE_FIELDS == ("ttlMs", "cacheScope")
    assert M.RESULT_TYPES == ("complete", "input_required")


def test_b3_gerbang_versi_tool():
    """B3: `since` dihormati; instance lama tidak boleh memakai tool baru."""
    assert M.require_tool("get_workflow_sdk_reference", "2.12.0").since == "2.12.0"
    with pytest.raises(M.VersionTooOld):
        M.require_tool("call_agent", "2.34.0")     # butuh 2.35.0
    with pytest.raises(M.VersionTooOld):
        M.require_tool("search_agents", "2.30.0")  # butuh 2.34.0
    # Tanpa versi (tak diketahui) tidak ada gerbang yang dipaksakan.
    assert M.require_tool("call_agent", "").name == "call_agent"


# ---------------------------------------------------------------------------
# D. Durability (keadaan sesi)
# ---------------------------------------------------------------------------
def test_d1_sesi_melacak_kemajuan_loop():
    """D1: keadaan sesi berpindah sesuai loop build.

    Perilaku ini penting: klien MCP sering kehilangan konteks antar-request,
    jadi "di mana saya sekarang" harus bisa dihitung ulang dari catatan.
    """
    clk = Clock()
    s = make_session(clk=clk)
    assert s.next_step() == "get_workflow_sdk_reference"
    assert s.sdk_reference_loaded is False

    s.call("get_workflow_sdk_reference", section="rules")
    assert s.sdk_reference_loaded is True
    assert s.next_step() == "validate_workflow"

    s.call("validate_workflow")
    assert s.validated is True
    assert s.next_step() == "create_workflow_from_code"

    s.call("create_workflow_from_code")
    assert s.workflow_exists is True
    assert s.next_step() == ""        # selesai
    assert len(s.calls) == 3


def test_d2_update_membatalkan_validasi():
    """D2: setelah update, validasi harus diulang (gate tidak bocor).

    Docs: `update_workflow` juga butuh `validate_workflow`. Bila status
    "sudah divalidasi" tidak dicabut, update kedua bisa lolos tanpa validasi.
    """
    s = make_session()
    s.call("get_workflow_sdk_reference", section="rules")
    s.call("validate_workflow")
    s.call("create_workflow_from_code")
    assert s.validated is True

    s.call("update_workflow")
    assert s.validated is False, "update harus mencabut status tervalidasi"
    with pytest.raises(M.BuildLoopViolation):
        s.call("update_workflow")      # yang kedua ditolak


# ---------------------------------------------------------------------------
# E. Edge
# ---------------------------------------------------------------------------
def test_e1_tool_tak_dikenal_ditolak():
    """E1: nama tool yang tidak ada di katalog ditolak (bukan diabaikan)."""
    with pytest.raises(M.UnknownTool):
        M.tool_by_name("create_workflow")          # nama v1 lama
    with pytest.raises(M.UnknownTool):
        M.tool_by_name("")
    with pytest.raises(M.UnknownTool):
        M.tool_by_name("search_workflows ")        # spasi tidak di-trim
    # Nama yang benar tetap jalan.
    assert M.tool_by_name("create_workflow_from_code").category \
        == "Workflow builder"


def test_e2_versi_tidak_sah_ditolak():
    """E2: versi non-x.y.z ditolak, bukan dianggap 'cukup baru'."""
    for bad in ("latest", "2.4", "v2", "", "two.one.zero", "2.x.0"):
        with pytest.raises(ValueError):
            M.parse_version(bad)
    assert M.parse_version("v2.41.0") == (2, 41, 0)
    # Pre-release/build metadata ikut diterima: inti x.y.z-nya tetap jelas,
    # dan menolaknya akan membuat gerbang versi gagal pada rilis kandidat.
    assert M.parse_version("2.41.0-rc1") == (2, 41, 0)
    assert M.parse_version("2.12.0+build.7") == (2, 12, 0)
    assert M.at_least("2.41.0", "2.41.0") is True
    assert M.at_least("2.40.9", "2.41.0") is False
    assert M.at_least("2.41.0-rc1", "2.41.0") is True


def test_e3_reference_payload_dan_section():
    """E3: `reference_payload` memakai field cache modern + menolak section fake."""
    body = M.reference_payload("2.43.0", section="rules")
    assert body["ttlMs"] == 300_000
    assert body["cacheScope"] == "public"
    assert body["resultType"] == "complete"
    assert body["section"] == "rules"
    with pytest.raises(M.McpBuildError):
        M.reference_payload("2.43.0", section="tidak-ada")
    # `groups` hanya sejak 2.41.0, tetapi tetap sah sebagai nama section.
    assert "groups" in M.SDK_SECTIONS


def test_e4_build_reference_menandai_langkah_hilang():
    """E4: referensi build untuk instance lama menyembunyikan langkah baru."""
    old = M.build_reference("2.12.0")
    # Pada 2.12.0, test_workflow (2.15.0) belum ada.
    assert "test_workflow" not in old["steps"]
    assert "test_workflow" in old["unavailable_steps"]
    assert "validate_workflow" in old["steps"]
    assert old["required_sdk_section"] == "rules"

    new = M.build_reference("2.43.0")
    assert sorted(new["steps"]) == sorted(M.BUILD_LOOP)
    assert new["unavailable_steps"] == []
    assert new["tool_count"] == 53


# ---------------------------------------------------------------------------
# P. Performance
# ---------------------------------------------------------------------------
def test_p1_katalog_cepat_untuk_banyak_versi():
    """P1: 2000 penerapan gerbang versi selesai jauh di bawah 2 detik."""
    t0 = time.perf_counter()
    for i in range(2000):
        v = f"2.{12 + (i % 32)}.0"
        M.tools_for_version(v)
    dt = time.perf_counter() - t0
    assert dt < 2.0, f"terlalu lambat: {dt:.3f}s"


def test_p2_sesi_1000_panggilan():
    """P2: 1000 panggilan tercatat tanpa kehilangan dan tetap konsisten."""
    s = make_session(version="")
    for _ in range(500):
        s.call("search_workflows")
    for _ in range(500):
        s.call("get_instance_context")
    assert len(s.calls) == 1000
    assert s.to_dict()["calls"] == 1000
    names = [c.name for c in s.calls]
    assert names.count("search_workflows") == 500
    assert names.count("get_instance_context") == 500


# ---------------------------------------------------------------------------
# S. Security
# ---------------------------------------------------------------------------
def test_s1_envelope_modern_lengkap_lulus():
    """S1: amplop 2026-07-28 yang benar diterima."""
    r = M.check_envelope("tools/call",
                         headers=classic_headers(name="search_nodes"),
                         meta=modern_meta(), tool_name="search_nodes",
                         result={"resultType": "complete"})
    assert r["ok"] is True, r["errors"]
    assert r["errors"] == []
    assert r["modern"] is True


def test_s2_header_sesi_lama_ditolak():
    """S2: `Mcp-Session-Id` DILARANG pada revisi modern.

    Ini inti perubahan 2026-07-28: protokol jadi stateless. Menerima header
    sesi lama sama dengan menyembunyikan klien yang belum bermigrasi — dan
    membuat sticky routing tampak bekerja padahal tidak ada sesi.
    """
    h = classic_headers(name="search_nodes")
    h["Mcp-Session-Id"] = "abc123"
    r = M.check_envelope("tools/call", headers=h, meta=modern_meta(),
                         tool_name="search_nodes",
                         result={"resultType": "complete"})
    assert r["ok"] is False
    assert any("Mcp-Session-Id" in e for e in r["errors"]), r["errors"]


def test_s3_header_wajib_dan_ketidakcocokan_nama():
    """S3: `Mcp-Method`/`Mcp-Name` wajib, dan `Mcp-Name` harus cocok."""
    # Header hilang sama sekali.
    r = M.check_envelope("tools/call", headers={}, meta=modern_meta(),
                         result={"resultType": "complete"})
    assert r["ok"] is False
    assert sum("header wajib hilang" in e for e in r["errors"]) == 2

    # Mcp-Name tidak cocok dengan tool yang dipanggil -> HeaderMismatch.
    r2 = M.check_envelope("tools/call",
                          headers=classic_headers(name="execute_workflow"),
                          meta=modern_meta(),
                          tool_name="search_nodes",
                          result={"resultType": "complete"})
    assert r2["ok"] is False
    assert any("HeaderMismatch" in e for e in r2["errors"]), r2["errors"]


def test_s4_discovery_wajib_dan_digerbangi():
    """S4: `server/discover` adalah MUST; ketiadaannya harus gagal."""
    ok = M.validate_discovery(M.discover_payload("2.43.0"))
    assert ok["ok"] is True

    assert M.validate_discovery(None)["ok"] is False
    assert M.validate_discovery({})["ok"] is False

    bad = M.discover_payload()
    bad["protocolVersions"] = ["2025-11-25"]        # tidak menyebut modern
    r = M.validate_discovery(bad)
    assert r["ok"] is False
    assert any("2026-07-28" in e for e in r["errors"])

    bad2 = M.discover_payload()
    bad2["protocolVersions"] = ["2026-07-28", "9999-01-01"]
    r2 = M.validate_discovery(bad2)
    assert r2["ok"] is False
    assert any("tak dikenal" in e for e in r2["errors"])


# ---------------------------------------------------------------------------
# X. Invariant / lintas-potongan
# ---------------------------------------------------------------------------
def test_x1_create_gate_sesuai_docs():
    """X1: hanya tool yang docs-nya menyebut validasi wajib masuk gate."""
    assert M.CREATE_GATE_TOOLS == {"create_workflow_from_code",
                                   "update_workflow"}
    for n in M.CREATE_GATE_TOOLS:
        assert M.tool_by_name(n).mutating is True
        assert M.tool_by_name(n).requires_validation is True


def test_x2_menulis_tanpa_referensi_sdk_ditolak():
    """X2: 'get_workflow_sdk_reference harus dipanggil lebih dulu'.

    Gate ini berlaku untuk PENULISAN. `validate_workflow` sendiri adalah
    operasi baca-saja dan justru berguna untuk memeriksa kode yang belum
    tersimpan; memblokirnya sebelum referensi dibaca hanya akan mendorong
    klien menulis dulu lalu validasi (kebalikan dari yang diinginkan).
    """
    s = make_session()
    # Membaca referensi bukan prasyarat untuk validasi.
    s.call("validate_workflow")
    assert s.validated is True

    # Tetapi MENULIS tanpa referensi ditolak.
    s2 = make_session()
    with pytest.raises(M.BuildLoopViolation):
        s2.call("create_workflow_from_code")
    assert s2.workflow_exists is False

    # Referensi dengan bagian yang salah juga tidak membuka gerbang.
    s3 = make_session()
    s3.call("get_workflow_sdk_reference", section="design")
    assert s3.sdk_reference_loaded is False
    s3.call("validate_workflow")
    with pytest.raises(M.BuildLoopViolation):
        s3.call("create_workflow_from_code")

    # Setelah bagian 'rules' dibaca, gerbang terbuka.
    s3.call("get_workflow_sdk_reference", section="rules")
    assert s3.sdk_reference_loaded is True
    s3.call("create_workflow_from_code")
    assert s3.workflow_exists is True


def test_x3_menulis_tanpa_validasi_ditolak():
    """X3: `validate_workflow` WAJIB lulus sebelum create/update."""
    s = make_session()
    s.call("get_workflow_sdk_reference", section="rules")
    with pytest.raises(M.BuildLoopViolation):
        s.call("create_workflow_from_code")
    # Validasi yang GAGAL (ok=False) tidak membuka gerbang.
    s.call("validate_workflow", ok=False)
    assert s.validated is False
    with pytest.raises(M.BuildLoopViolation):
        s.call("create_workflow_from_code")
    # Setelah lulus, baru boleh.
    s.call("validate_workflow", ok=True)
    s.call("create_workflow_from_code")
    assert s.workflow_exists is True


def test_x4_menjalankan_tanpa_workflow_ditolak():
    """X4: test/execute butuh workflow yang sudah ada."""
    s = make_session()
    s.call("get_workflow_sdk_reference", section="rules")
    for tool in ("test_workflow", "execute_workflow"):
        with pytest.raises(M.BuildLoopViolation):
            s.call(tool)
    # Simulasi workflow sudah dimuat (mis. dibuka dari instance).
    s.call("get_workflow_details", workflow_created=True)
    s.call("test_workflow")
    s.call("execute_workflow")
    assert s.to_dict()["next_step"] in ("", "create_workflow_from_code")


def test_x5_missing_prerequisites_melaporkan_semua_alasan():
    """X5: alasan blokir dilaporkan lengkap, bukan satu per satu."""
    s = make_session(version="2.18.0")   # validate_workflow sudah ada
    reasons = s.missing_prerequisites("create_workflow_from_code")
    assert any("get_workflow_sdk_reference" in r for r in reasons)
    assert any("validate_workflow" in r for r in reasons)

    # Versi terlalu tua juga dilaporkan.
    s2 = make_session(version="2.10.0")
    r2 = s2.missing_prerequisites("call_agent")
    assert any("2.35.0" in r for r in r2), r2


def test_x6_cache_field_wajib_pada_hasil_list():
    """X6: SEP-2549 — hasil list wajib `ttlMs` + `cacheScope`."""
    # Tanpa field -> gagal.
    r = M.check_envelope("tools/list", headers=classic_headers(
        method="tools/list", name=""), meta=modern_meta(),
        result={"resultType": "complete"})
    assert r["ok"] is False
    missing = [e for e in r["errors"] if "wajib memuat" in e]
    assert len(missing) == 2, r["errors"]

    # Dengan field benar -> lulus.
    r2 = M.check_envelope("tools/list",
                          headers=classic_headers(method="tools/list", name=""),
                          meta=modern_meta(),
                          result={"resultType": "complete", "ttlMs": 60_000,
                                  "cacheScope": "private"})
    assert r2["ok"] is True, r2["errors"]

    # cacheScope tidak sah -> gagal.
    r3 = M.check_envelope("tools/list",
                          headers=classic_headers(method="tools/list", name=""),
                          meta=modern_meta(),
                          result={"resultType": "complete", "ttlMs": 1,
                                  "cacheScope": "global"})
    assert r3["ok"] is False
    assert any("cacheScope tidak sah" in e for e in r3["errors"])

    # Metode non-list tidak butuh field cache.
    r4 = M.check_envelope("tools/call",
                          headers=classic_headers(name="search_nodes"),
                          meta=modern_meta(), tool_name="search_nodes",
                          result={"resultType": "complete"})
    assert r4["ok"] is True


def test_x7_result_type_dan_input_required():
    """X7: `resultType` wajib; `input_required` butuh requestState (saran)."""
    # Hilang -> gagal.
    r = M.check_envelope("tools/call",
                         headers=classic_headers(name="search_nodes"),
                         meta=modern_meta(), tool_name="search_nodes",
                         result={})
    assert r["ok"] is False
    assert any("resultType" in e for e in r["errors"])

    # Nilai tidak sah -> gagal.
    r2 = M.check_envelope("tools/call",
                          headers=classic_headers(name="search_nodes"),
                          meta=modern_meta(), tool_name="search_nodes",
                          result={"resultType": "partial"})
    assert r2["ok"] is False

    # input_required tanpa inputRequests -> gagal.
    r3 = M.check_envelope("tools/call",
                          headers=classic_headers(name="search_nodes"),
                          meta=modern_meta(), tool_name="search_nodes",
                          result={"resultType": "input_required"})
    assert r3["ok"] is False
    assert any("inputRequests" in e for e in r3["errors"])

    # input_required lengkap tanpa requestState -> hanya peringatan.
    r4 = M.check_envelope("tools/call",
                          headers=classic_headers(name="search_nodes"),
                          meta=modern_meta(), tool_name="search_nodes",
                          result={"resultType": "input_required",
                                  "inputRequests": {"x": {}}})
    assert r4["ok"] is True
    assert any("requestState" in w for w in r4["warnings"]), r4["warnings"]


def test_x8_meta_protocol_version_harus_cocok():
    """X8: `_meta` wajib menyatakan versi yang benar-benar dipakai."""
    meta = modern_meta()
    meta[M.META_PROTOCOL_VERSION] = "2025-11-25"      # berbohong
    r = M.check_envelope("tools/call",
                         headers=classic_headers(name="search_nodes"),
                         meta=meta, tool_name="search_nodes",
                         result={"resultType": "complete"})
    assert r["ok"] is False
    assert any("protocolVersion" in e for e in r["errors"])

    # Tanpa _meta sama sekali -> gagal.
    r2 = M.check_envelope("tools/call",
                          headers=classic_headers(name="search_nodes"),
                          meta={}, tool_name="search_nodes",
                          result={"resultType": "complete"})
    assert r2["ok"] is False

    # Revisi handshake tidak butuh amplop modern.
    r3 = M.check_envelope("tools/call", revision="2025-11-25",
                          headers={}, meta={}, result=None)
    assert r3["ok"] is True, r3["errors"]
    assert r3["modern"] is False


def test_x9_policy_dari_dict_bukan_os_environ():
    """X9: kebijakan dibaca dari DICT yang di-inject."""
    pol = M.policy_from_env({
        "KATALIR_MCP_N8N_VERSION": "2.43.0",
        "KATALIR_MCP_REQUIRE_VALIDATION": "0",
        "KATALIR_MCP_REQUIRE_DISCOVERY": "no",
        "KATALIR_MCP_SDK_TTL_MS": "12345",
    })
    assert pol["n8n_version"] == "2.43.0"
    assert pol["require_validation"] is False
    assert pol["require_discovery"] is False
    assert pol["max_sdk_section_ttl_ms"] == 12345
    # Default aman bila env kosong.
    d = M.policy_from_env({})
    assert d["require_validation"] is True
    assert d["require_discovery"] is True
    assert d["enforce_routing_headers"] is True
    assert d["protocol_revision"] == M.LATEST_MODERN_REVISION
    # Versi tidak sah di env harus melempar, bukan diabaikan.
    with pytest.raises(M.McpBuildError):
        M.policy_from_env({"KATALIR_MCP_N8N_VERSION": "terbaru"})


def test_x10_deskripsi_konsisten_dengan_katalog():
    """X10 (invariant): `describe()` tidak boleh menyimpang dari katalog."""
    d = M.describe()
    assert d["tool_count"] == len(M.TOOLS)
    assert d["categories"] == list(M.TOOL_CATEGORIES)
    total = 0
    for cat, names in d["tools_by_category"].items():
        assert cat in M.TOOL_CATEGORIES
        for n in names:
            assert M.CATEGORY_OF[n] == cat, f"{n} salah kategori"
        total += len(names)
    assert total == 53
    # Setiap tool muncul tepat sekali di peta kategori.
    flat = [n for names in d["tools_by_category"].values() for n in names]
    assert sorted(flat) == sorted(M.TOOL_NAMES)
    # Protokol yang dilaporkan cocok dengan konstanta.
    assert d["protocol"]["latest"] == M.LATEST_REVISION
    assert d["protocol"]["discover_method"] == M.DISCOVER_METHOD
    assert d["protocol"]["revoked_session_header"] == M.REVOKED_SESSION_HEADER


def test_x11_loop_build_hanya_tool_yang_ada():
    """X11 (invariant): setiap langkah loop harus tool nyata di katalog."""
    for step in M.BUILD_LOOP:
        assert step in M.TOOL_NAMES, f"langkah loop bukan tool: {step}"
    # Urutan penting: referensi sebelum validasi sebelum create.
    idx = {n: i for i, n in enumerate(M.BUILD_LOOP)}
    assert idx["get_workflow_sdk_reference"] < idx["validate_workflow"]
    assert idx["validate_workflow"] < idx["create_workflow_from_code"]
    assert idx["create_workflow_from_code"] < idx["test_workflow"]


def test_x12_sesi_aman_dari_akses_bersamaan():
    """X12: pencatatan sesi thread-safe (klien MCP memakai thread pool)."""
    s = make_session(version="")
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            for _ in range(50):
                s.call("search_workflows", note=str(n))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(s.calls) == 400, len(s.calls)


def test_x13_agent_preview_ditandai():
    """X13: seluruh kategori Agent muncul sejak 2.34.0 (kecuali call_agent)."""
    agents = M.tools_in_category("Agent management")
    assert len(agents) == 15
    for t in agents:
        if t.name == "call_agent":
            assert t.since == "2.35.0"
        else:
            assert t.since == "2.34.0", (t.name, t.since)
    # Instance di bawah 2.34.0 tidak melihat satu pun tool agent.
    names = {t.name for t in M.tools_for_version("2.33.0")}
    assert not (names & {t.name for t in agents})


def test_x14_docs_tidak_diragukan_karena_gerbang_versi_monoton():
    """X14: gerbang versi tidak boleh menurun seiring bertambahnya tool.

    Invariant: himpunan tool untuk versi lebih baru selalu superset dari
    versi lebih lama. Bila seseorang menaikkan `since` tool lama, atau salah
    menulis versi, superset ini pecah dan terdeteksi di sini.
    """
    versions = ["2.12.0", "2.14.0", "2.16.0", "2.20.0", "2.21.0", "2.25.1",
                "2.26.0", "2.27.0", "2.29.0", "2.33.0", "2.34.0", "2.35.0",
                "2.36.0", "2.41.0", "2.43.0"]
    prev: set[str] = set()
    for v in versions:
        cur = {t.name for t in M.tools_for_version(v)}
        assert prev <= cur, f"{v} kehilangan tool: {sorted(prev - cur)}"
        prev = cur
    assert prev == set(M.TOOL_NAMES), "versi tertinggi harus punya semua tool"


def test_x15_reference_payload_tidak_mengubah_input():
    """X15: helper tidak memutasi argumen pemanggil."""
    hdrs = classic_headers(name="search_nodes")
    snapshot = dict(hdrs)
    M.check_envelope("tools/call", headers=hdrs, meta=modern_meta(),
                     tool_name="search_nodes",
                     result={"resultType": "complete"})
    assert hdrs == snapshot

    src = {"reference": "x"}
    M.reference_payload("2.43.0", result=src)
    assert src == {"reference": "x"}, "input tidak boleh dimutasi"

    r = {"resultType": "complete"}
    M.check_envelope("tools/call", headers=classic_headers(name="search_nodes"),
                     meta=modern_meta(), tool_name="search_nodes", result=r)
    assert r == {"resultType": "complete"}
