"""tests/test_connector_activator.py — 12 hard test untuk TASK 1.

TASK 1: aktifkan entri `metadata_only` (25.902) menjadi executable.

Distribusi wajib brief (2 dasar, 2 edge, 2 error, 2 performa, 1 keamanan,
1 integrasi E2E) dipetakan ke 12 skenario di bawah ini. Nomor B/E/X/P/S
mengikuti penomoran brief.

Semua test di sini OFFLINE (tanpa jaringan). Bukti jaringan nyata dicatat
terpisah oleh `_t1_live_exec.py` supaya suite tetap deterministik; yang diuji
di sini adalah **aturan penilaiannya**, termasuk invarian terpenting:
`activation_plan()` tidak boleh mempromosikan entri tanpa endpoint.
"""

from __future__ import annotations

import json
import time

import pytest

import connector_activator as ca


# ---------------------------------------------------------------------------
# Fixture — entri katalog bentuk nyata (dipangkas dari glama_connectors.json)
# ---------------------------------------------------------------------------


def _glama_entry(cid: str, url: str = "https://mcp.example-service.com/mcp",
                 auth: str = "none", healthy: bool = True,
                 tools_count: int = 12, transport: str = "streamable_http") -> dict:
    return {
        "id": cid,
        "name": cid.rsplit("/", 1)[-1],
        "source": "glama-connector",
        "endpoint_url": url,
        "auth_type": auth,
        "healthy": healthy,
        "tools_count": tools_count,
        "install_config": {"transport": transport, "package": url,
                           "install_method": "glama-remote"},
    }


def _metadata_only(cid: str = "pypi/some-package") -> dict:
    return {"id": cid, "name": cid.rsplit("/", 1)[-1],
            "install_config": {"transport": "metadata-only", "package": cid}}


def _stdio_entry(cid: str = "npm/@scope/srv") -> dict:
    return {"id": cid, "install_config": {"transport": "stdio",
                                          "package": "npx -y @scope/srv"}}


# ---------------------------------------------------------------------------
# B — 2 test dasar
# ---------------------------------------------------------------------------


def test_b1_entri_streamable_http_dengan_endpoint_nyata_diaktivasi():
    """B1 (dasar): 1 entri Glama ber-endpoint nyata -> activated."""
    entry = _glama_entry("glama-connector/context7")
    plan = ca.activation_plan(entry)
    assert plan["ok"] is True, plan["reason"]
    assert plan["kind"] == "ready"
    assert plan["transport"] == "streamable_http"

    ledger = ca.ActivationLedger()
    res = ledger.activate(entry)
    assert res.activated is True
    assert res.reason == "diaktivasi"
    assert res.endpoint_url == "https://mcp.example-service.com/mcp"
    assert res.auth_type == "none"
    assert ledger.is_active("glama-connector/context7")


def test_b2_metadata_only_tanpa_endpoint_dilewati_dengan_alasan_jelas():
    """B2 (dasar): entri metadata-only TIDAK boleh dipromosikan."""
    entry = _metadata_only()
    plan = ca.activation_plan(entry)
    assert plan["ok"] is False
    assert plan["kind"] == "deferred"
    assert "metadata-only" in plan["reason"]

    ledger = ca.ActivationLedger()
    res = ledger.activate(entry)
    assert res.activated is False
    assert ledger.is_active("pypi/some-package") is False
    assert ledger.skipped["pypi/some-package"] == plan["reason"]


# ---------------------------------------------------------------------------
# E — 2 edge case
# ---------------------------------------------------------------------------


def test_e1_stdio_diaktivasi_tapi_execute_menolak_tanpa_izin():
    """E1 (edge): stdio punya jalur runtime, tapi eksekusi butuh izin eksplisit."""
    entry = _stdio_entry()
    plan = ca.activation_plan(entry)
    assert plan["ok"] is True, plan["reason"]
    assert plan["transport"] == "stdio"

    ledger = ca.ActivationLedger()
    assert ledger.activate(entry).activated is True

    with pytest.raises(ca.UnsupportedTransport) as exc:
        ca.execute(entry, "some_tool", {})
    assert "allow_stdio" in str(exc.value)


def test_e2_transport_kosong_dengan_endpoint_https_ditolak_secara_eksplisit():
    """E2 (edge): transport '' (1.025 entri Nango) bukan jalur eksekusi."""
    entry = {"id": "nango/slack", "install_config": {"transport": "", "package": ""}}
    plan = ca.activation_plan(entry)
    assert plan["ok"] is False
    assert plan["kind"] == "deferred"

    # transport '' TAPI ada endpoint https juga belum tentu dieksekusi:
    # jalur itu hanya untuk transport yang dikenal.
    entry2 = {"id": "x/unknown", "endpoint_url": "https://api.example-service.com",
              "install_config": {"transport": "openapi-generated", "package": ""}}
    plan2 = ca.activation_plan(entry2)
    assert plan2["ok"] is False
    assert plan2["kind"] == "unsupported"


# ---------------------------------------------------------------------------
# E — 2 error handling
# ---------------------------------------------------------------------------


def test_x1_endpoint_http_telanjang_ditolak_oleh_plan_dan_execute():
    """X1 (error): http:// bukan https -> ditolak, dan execute melempar."""
    entry = _glama_entry("glama-connector/insecure", url="http://mcp.evil-demo.com/mcp")
    plan = ca.activation_plan(entry)
    assert plan["ok"] is False
    assert plan["kind"] == "bad_endpoint"
    assert "https" in plan["reason"]

    with pytest.raises(ca.ActivationError):
        ca.execute(entry, "anything", {})


def test_x2_endpoint_url_rusak_tidak_membuat_crash():
    """X2 (error): url tanpa host / url sampah -> ditolak, tidak exception liar."""
    for bad in ("https://", "https:///path-only", "not-a-url-at-all", ""):
        entry = _glama_entry("glama-connector/broken", url=bad)
        plan = ca.activation_plan(entry)
        assert plan["ok"] is False, bad
        ledger = ca.ActivationLedger()
        res = ledger.activate(entry)
        assert res.activated is False
        assert res.reason, "alasan penolakan harus tidak kosong"


# ---------------------------------------------------------------------------
# P — 2 performa
# ---------------------------------------------------------------------------


def test_p1_aktivasi_100_connector_di_bawah_5_menit():
    """P1 (performa): brief mensyaratkan 100 connector < 5 menit.

    Ambang nyata jauh lebih ketat: operasi murni katalog harus selesai dalam
    1 detik untuk 100 entri. Ambang longgar brief tetap diassert agar
    kegagalan regresi besar apa pun tertangkap.
    """
    entries = [_glama_entry(f"glama-connector/perf-{i}",
                            url=f"https://mcp.perf-{i}.example-service.com/mcp")
               for i in range(100)]
    t0 = time.perf_counter()
    ledger, report = ca.bulk_activate(entries, verify_network=False)
    elapsed = time.perf_counter() - t0

    assert report["stats"]["activated"] == 100
    assert elapsed < 300, f"100 connector butuh {elapsed:.2f}s (>5 menit)"
    assert elapsed < 1.0, f"aktivasi katalog 100 entri terlalu lambat: {elapsed:.3f}s"


def test_p2_skip_jutaan_entri_tetap_linear_dan_cepat():
    """P2 (performa): 30.000 entri campuran (katalog penuh) harus < 10 detik.

    Ini angka nyata katalog Katalir (25.925 metadata + 1.000 glama). Kalau
    `activation_plan` mulai melakukan I/O per entri, test ini akan meledak.
    """
    entries = [_metadata_only(f"pkg/{i}") for i in range(20_000)]
    entries += [_glama_entry(f"glama-connector/mix-{i}",
                             url=f"https://mcp.mix-{i}.example-service.com/mcp")
                for i in range(10_000)]
    t0 = time.perf_counter()
    ledger, report = ca.bulk_activate(entries, verify_network=False)
    elapsed = time.perf_counter() - t0

    assert report["stats"]["activated"] == 10_000
    assert report["stats"]["skipped"] == 20_000
    assert elapsed < 10.0, f"30k entri butuh {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# S — 1 keamanan
# ---------------------------------------------------------------------------


def test_s1_ssrf_loopback_privat_dan_metadata_ditolak():
    """S1 (keamanan): guard SSRF harus menolak semua target internal."""
    blocked = [
        "https://localhost/mcp",
        "https://127.0.0.1/mcp",
        "https://127.0.0.1:8080/mcp",
        "https://10.0.0.5/mcp",
        "https://192.168.1.1/mcp",
        "https://172.16.0.1/mcp",
        "https://169.254.169.254/latest/meta-data/",
        "https://metadata.google.internal/computeMetadata/v1/",
        "https://mcp.internal/mcp",
        "https://thing.local/mcp",
    ]
    for url in blocked:
        entry = _glama_entry("glama-connector/ssrf", url=url)
        plan = ca.activation_plan(entry)
        assert plan["ok"] is False, f"SSRF lolos: {url}"
        assert plan["kind"] == "bad_endpoint", f"{url} -> {plan['kind']}"

    # resolver DNS juga harus menolak host yang resolve ke privat.
    assert ca._resolve_blocked("localhost") is True
    # host publik nyata tidak diblokir oleh pemeriksaan nama.
    assert ca.host_blocked("mcp.githubcopilot.com") is False


# ---------------------------------------------------------------------------
# X — integrasi E2E
# ---------------------------------------------------------------------------


def test_x3_bulk_activate_pada_katalog_nyata_menghasilkan_endpoint_nyata():
    """X3 (integrasi): jalankan pada katalog Katalir yang sebenarnya.

    Ini E2E tanpa jaringan: seluruh katalog dimuat dari `mcp_registry`,
    diaktivasi, lalu setiap hasil aktivasi diperiksa punya endpoint https
    yang sungguh-sungguh dapat di-`execute()` (guard-nya lulus).
    """
    catalog = ca.load_catalog()
    assert len(catalog) > 10_000, f"katalog terlalu kecil: {len(catalog)}"

    ledger, report = ca.bulk_activate(catalog, verify_network=False)
    stats = report["stats"]

    assert stats["activated"] > 23, (
        f"tidak ada peningkatan executable: {stats['activated']} (baseline 23)")

    # Setiap yang diaktivasi benar-benar siap dieksekusi.
    for cid, rec in ledger.activated.items():
        ok, why = ca.url_activatable(rec["endpoint_url"])
        assert ok, f"{cid} diaktivasi tapi endpoint tidak valid: {why}"
        assert rec["transport"] in ca.EXECUTABLE_TRANSPORTS

    # Yang dilewati punya alasan yang dapat dibaca (tidak ada skip senyap).
    for cid, reason in ledger.skipped.items():
        assert reason and reason.strip(), f"{cid} dilewati tanpa alasan"

    by_tr = stats["by_transport"]
    assert "streamable_http" in by_tr
    # Integrasi dengan invarian global: transport non-eksekusi tidak boleh ada.
    for tr in by_tr:
        assert tr in ca.EXECUTABLE_TRANSPORTS, f"transport bocor: {tr}"


# ---------------------------------------------------------------------------
# Invariant lintas — idempotensi & rollback (bagian dari X3/E2 di brief)
# ---------------------------------------------------------------------------


def test_x4_aktivasi_idempoten_dan_dapat_di_rollback():
    """X4: aktivasi dua kali tidak menggandakan; deactivate mengembalikan."""
    entry = _glama_entry("glama-connector/idem")
    ledger = ca.ActivationLedger()

    first = ledger.activate(entry)
    assert first.activated and first.reason == "diaktivasi"

    second = ledger.activate(entry)
    assert second.activated and second.reason == "sudah aktif (idempoten)"
    assert len(ledger.activated) == 1

    # entri yang tadinya skipped lalu menjadi sah -> skip-nya hilang
    bad = _metadata_only("pkg/x")
    ledger.activate(bad)
    assert "pkg/x" in ledger.skipped
    assert ledger.activate(_glama_entry("pkg/x",
                                        url="https://mcp.example-service.com/mcp")
                           ).activated is True
    assert "pkg/x" not in ledger.skipped

    # rollback
    assert ledger.deactivate("glama-connector/idem") is True
    assert ledger.is_active("glama-connector/idem") is False
    assert ledger.deactivate("glama-connector/idem") is False  # sudah tidak ada


def test_x5_verify_network_menurunkan_entri_dari_host_yang_diblokir_dns():
    """X5: saat DNS dipaksakan, host yang gagal resolusi harus diturunkan.

    `resolver` disuntikkan supaya deterministic tanpa jaringan.
    """
    good = _glama_entry("glama-connector/good",
                        url="https://mcp.good-service.com/mcp")
    bad = _glama_entry("glama-connector/bad",
                       url="https://mcp.blocked-service.com/mcp")

    def fake_resolver(host: str) -> bool:
        return host == "mcp.blocked-service.com"

    ledger, report = ca.bulk_activate(
        [good, bad], verify_network=True, resolver=fake_resolver, max_verify=0)

    assert ledger.is_active("glama-connector/good") is True
    assert ledger.is_active("glama-connector/bad") is False
    assert "mcp.blocked-service.com" in report["blocked_hosts"]
    assert ledger.skipped["glama-connector/bad"].startswith("host gagal resolusi")


def test_x6_describe_menyatakan_jalur_eksekusi_nyata_bukan_metadata():
    """X6: `describe()` harus jujur — tiap transport menunjuk executor konkret."""
    d = ca.describe()
    assert set(d["executors"]) == {"streamable_http", "http", "sse", "stdio"}
    for value in d["executors"].values():
        assert "_call_" in value
    assert "metadata-only" not in d["executors"]
    assert any("TIDAK diaktivasi" in r for r in d["rules"])


def test_x7_unhealthy_ditolak_meski_endpoint_valid():
    """X7: `healthy=False` adalah sinyal mutlak — jangan aktivasi."""
    entry = _glama_entry("glama-connector/sick", healthy=False)
    plan = ca.activation_plan(entry)
    assert plan["ok"] is False
    assert plan["kind"] == "unhealthy"
    assert "tidak sehat" in plan["reason"]


def test_x8_transport_layanan_pihak_ketiga_diklasifikasi_terpisah():
    """X8: composio-remote / mcp-meta-layer bukan 'unsupported' generik."""
    for tr in ca.EXTERNAL_SERVICE_TRANSPORTS:
        entry = {"id": f"{tr}/thing", "install_config": {"transport": tr, "package": ""}}
        plan = ca.activation_plan(entry)
        assert plan["ok"] is False
        assert plan["kind"] == "external"
        assert "pihak ketiga" in plan["reason"]


def test_x9_to_dict_dapat_diserialisasi_json():
    """X9: hasil aktivasi harus JSON-serializable (dipakai API layer)."""
    ledger = ca.ActivationLedger()
    res = ledger.activate(_glama_entry("glama-connector/ser"))
    payload = json.dumps(res.to_dict(), ensure_ascii=False)
    assert "glama-connector/ser" in payload
    stats = json.dumps(ledger.stats(), ensure_ascii=False)
    assert "streamable_http" in stats


def test_x10_execute_menolak_transport_tanpa_executor():
    """X10: execute() pada transport non-eksekusi -> UnsupportedTransport."""
    for tr in ("metadata-only", "composio-remote", "mcp-meta-layer", ""):
        entry = {"id": "x", "install_config": {"transport": tr, "package": ""}}
        with pytest.raises(ca.UnsupportedTransport):
            ca.execute(entry, "tool", {})


def test_x11_plan_tidak_pernah_mengembalikan_ok_tanpa_endpoint_valid():
    """X11 (invarian inti): ok=True HANYA bila endpoint lolos guard SSRF."""
    entries = [
        _glama_entry("a"), _metadata_only("b"), _stdio_entry("c"),
        _glama_entry("d", url="http://insecure-demo.com"),
        _glama_entry("e", url="https://localhost/mcp"),
        _glama_entry("f", healthy=False),
    ]
    for e in entries:
        plan = ca.activation_plan(e)
        if plan["ok"]:
            url = plan.get("endpoint_url") or ""
            if plan["transport"] != "stdio":
                assert ca.url_activatable(url)[0] is True, plan


def test_x12_stats_konsisten_dengan_isi_ledger():
    """X12: stats() harus mencerminkan ledger, bukan konstanta."""
    ledger = ca.ActivationLedger()
    for i in range(7):
        ledger.activate(_glama_entry(f"glama-connector/s{i}", tools_count=i + 1))
    ledger.activate(_metadata_only("m1"))
    ledger.activate(_metadata_only("m2"))

    s = ledger.stats()
    assert s["activated"] == 7
    assert s["skipped"] == 2
    assert s["tools_total"] == sum(range(1, 8))  # 28
    assert s["by_transport"] == {"streamable_http": 7}


# ---------------------------------------------------------------------------
# Persistensi — aktivasi harus MENGUBAH katalog, bukan hanya ledger
# ---------------------------------------------------------------------------


def test_x13_persist_membuat_executable_servers_benar_benar_bertambah(tmp_path,
                                                                    monkeypatch):
    """X13 (bukti inti TASK 1): `coverage()['executable']` harus naik.

    Tanpa test ini, "aktivasi" bisa jadi sekadar label di memori. Test ini
    menulis ledger ke katalog lalu menanyakan angka yang sama yang dilihat
    Marketplace (`executable_servers()`), serta memastikan aktivasi kedua
    idempoten (tidak menggandakan).

    Id yang dipakai HARUS ada di katalog nyata — `executable_servers()`
    mengiterasi katalog, jadi id asing tidak akan pernah menambah hitungan.
    """
    import mcp_registry as catalog

    monkeypatch.setattr(catalog, "ACTIVATION_PATH", tmp_path / "act.json")
    monkeypatch.setattr(catalog, "_ACTIVATED_IDS", None)

    # Ambil kandidat glama nyata dari katalog (bukan id karangan).
    real = [e for e in ca.load_catalog()
            if e.get("install_config", {}).get("transport") == "streamable_http"
            and ca.activation_plan(e)["ok"]]
    assert len(real) >= 25, f"katalog tidak punya cukup kandidat: {len(real)}"
    entries = real[:25]

    before = len(catalog.executable_servers())
    ledger, report = ca.activate_and_persist(entries)

    assert report["persisted"]["added"] == 25
    assert report["persisted"]["unknown_ids"] == 0
    after = len(catalog.executable_servers())
    assert after == before + 25, f"executable tidak bertambah: {before} -> {after}"

    # idempoten pada level persist
    ledger2, report2 = ca.activate_and_persist(entries)
    assert report2["persisted"]["added"] == 0
    assert len(catalog.executable_servers()) == after

    # file ledger benar-benar ada dan dapat dibaca ulang
    payload = json.loads((tmp_path / "act.json").read_text(encoding="utf-8"))
    assert payload["count"] >= 25
    assert entries[0]["id"] in payload["activated"]


def test_x14_entri_tanpa_endpoint_tidak_pernah_ikut_tersimpan(tmp_path, monkeypatch):
    """X14: persistensi tidak boleh menyelundupkan entri non-eksekusi."""
    import mcp_registry as catalog

    monkeypatch.setattr(catalog, "ACTIVATION_PATH", tmp_path / "act2.json")
    monkeypatch.setattr(catalog, "_ACTIVATED_IDS", None)

    real = [e for e in ca.load_catalog()
            if e.get("install_config", {}).get("transport") == "streamable_http"
            and ca.activation_plan(e)["ok"]]
    entries = [e for e in ca.load_catalog() if ca.activation_plan(e)["kind"] == "deferred"]
    entries += real[:3]

    ledger, report = ca.activate_and_persist(entries)

    assert report["persisted"]["added"] == 3
    payload = json.loads((tmp_path / "act2.json").read_text(encoding="utf-8"))
    assert len(payload["activated"]) == 3
    for cid in payload["activated"]:
        assert catalog._CACHE[cid]["install_config"]["transport"] == "streamable_http"


def test_x15_id_asing_dilaporkan_bukan_dihitung(tmp_path, monkeypatch):
    """X15: id yang tidak ada di katalog dilaporkan, bukan diklaim bertambah."""
    import mcp_registry as catalog

    monkeypatch.setattr(catalog, "ACTIVATION_PATH", tmp_path / "act4.json")
    monkeypatch.setattr(catalog, "_ACTIVATED_IDS", None)

    ledger = ca.ActivationLedger()
    ledger.activate(_glama_entry("glama-connector/tidak-ada-di-katalog"))
    rep = ca.persist(ledger)

    assert rep["added"] == 0
    assert rep["unknown_ids"] == 1
    assert rep["total"] == 0


def test_x16_katalog_nyata_persist_dan_coverage_naik(tmp_path, monkeypatch):
    """X16 (integrasi E2E tanpa jaringan): katalog asli -> executable naik."""
    import mcp_registry as catalog

    monkeypatch.setattr(catalog, "ACTIVATION_PATH", tmp_path / "act3.json")
    monkeypatch.setattr(catalog, "_ACTIVATED_IDS", None)

    before = len(catalog.executable_servers())
    entries = ca.load_catalog()
    ledger, report = ca.activate_and_persist(entries)
    after = len(catalog.executable_servers())

    assert after > before
    assert report["persisted"]["unknown_ids"] == 0
    # `before` bisa sudah tercemar oleh test lain dalam sesi yang sama (mereka
    # menandai `runtime_verified` di `_CACHE` bersama), jadi yang dibandingkan
    # adalah delta terhadap aktivasi ini, bukan selisih absolut.
    assert report["stats"]["activated"] == report["persisted"]["added"]
    assert after >= report["persisted"]["total"]

    # Setiap id yang tercatat di ledger memang bertransport eksekusi.
    for cid in ledger.activated:
        assert catalog._CACHE[cid]["install_config"]["transport"] == "streamable_http"
        assert catalog._CACHE[cid].get("runtime_verified") is True

    cov = catalog.coverage()
    assert cov["executable"] == after
    assert cov["metadata_only"] == cov["total"] - cov["executable"]


