"""Fitur #11 — Testing Framework: test untuk framework-nya sendiri.

Termasuk **meta-test**: membuktikan harness BENAR-BENAR bisa gagal. Tanpa itu
"100% lulus" tidak bermakna (harness yang selalu bilang OK = tidak menguji apa
pun). Ini bagian dari EVIDENCE GATE brief.

Skenario (12):
   1. katalog berisi >= 100 skenario
   2. seluruh katalog lulus
   3. META: ekspektasi yang sengaja salah -> FAIL terdeteksi
   4. META: skenario error yang sengaja dibuat sukses -> FAIL terdeteksi
   5. stub provider di-restore setelah run (tidak bocor)
   6. agent benar-benar dipanggil (reasoner_calls > 0)
   7. error dilaporkan sebagai error + pesan
   8. adversarial keamanan 11/11 lulus
   9. load test 0 error
  10. registry stub tidak menyentuh jaringan (hanya StubRegistry)
  11. semua kategori terwakili
  12. temuan keamanan: bot_token Telegram teredaksi di log
"""
from __future__ import annotations

import provider_registry

import workflow_testkit as tk


# ---------------------------------------------------------------------------
def test_01_katalog_ukuran():
    cat = tk.build_catalog()
    assert len(cat) >= 100, f"katalog hanya {len(cat)} skenario (butuh >=100)"
    ids = [s.id for s in cat]
    assert len(ids) == len(set(ids)), "ID duplikat"
    print(f"[1] katalog = {len(cat)} skenario, ID unik")


def test_02_katalog_semua_lulus():
    results = tk.run_all(tk.build_catalog())
    gagal = [r for r in results if not r.passed]
    for r in gagal:
        print(f"[2] FAIL {r.scenario.id}: {r.evidence}")
    assert not gagal, f"{len(gagal)} skenario gagal"
    print(f"[2] {len(results)}/{len(results)} skenario lulus")


# ---------------------------------------------------------------------------
# META-TESTS — bukti harness tidak selalu bilang OK
# ---------------------------------------------------------------------------
def test_03_meta_ekspektasi_salah_terdeteksi():
    """Skenario yang seharusnya SUKSES tapi diharap 'error' HARUS gagal."""
    sc = tk.Scenario(
        "meta-salah", "sengaja salah", "meta",
        flow=tk._flow([tk._node("t1", "trigger", "T"),
                       tk._node("m1", "mcp", "M", {"provider": "http",
                                                   "url": "http://x"})],
                      [tk._edge("t1", "m1")]),
        expect_status="error", expect_error_substr="tidak-akan-muncul")
    res = tk.run_scenario(sc)
    assert not res.passed, "harness menerima ekspektasi yang salah — tidak menguji"
    print(f"[3] meta OK: ekspektasi salah terdeteksi ({res.evidence})")


def test_04_meta_node_status_salah_terdeteksi():
    sc = tk.Scenario(
        "meta-node", "sengaja salah node", "meta",
        flow=tk._flow([tk._node("t1", "trigger", "T"),
                       tk._node("m1", "mcp", "M", {"provider": "http",
                                                   "url": "http://x"})],
                      [tk._edge("t1", "m1")]),
        expect_node_status={"m1": "error"})   # padahal completed
    res = tk.run_scenario(sc)
    assert not res.passed, "harness tidak mendeteksi status node yang salah"
    print(f"[4] meta OK: node status salah terdeteksi ({res.evidence})")


# ---------------------------------------------------------------------------
def test_05_stub_provider_di_restore():
    asli = provider_registry.run_async
    tk.run_flow(tk._flow([tk._node("t1", "trigger", "T"),
                          tk._node("m1", "mcp", "M", {"provider": "http",
                                                      "url": "http://x"})],
                         [tk._edge("t1", "m1")]))
    assert provider_registry.run_async is asli, "stub provider BOCOR"
    assert tk._PROVIDER_RESPONSES == {}, "respons provider bocor antar-run"
    print("[5] stub provider di-restore; tidak ada state bocor")


def test_06_agent_dipanggil():
    r = tk.run_flow(
        tk._flow([tk._node("t1", "trigger", "T"),
                  tk._node("a1", "agent", "A", {"prompt": "x"})],
                 [tk._edge("t1", "a1")]),
        reasoner_replies="jawaban")
    assert r.status == "success" and r.reasoner_calls == 1, r
    assert r.outputs["a1"]["instruction"] == "jawaban"
    print(f"[6] agent dipanggil {r.reasoner_calls}x; instruction={r.outputs['a1']['instruction']!r}")


def test_07_error_dilaporkan():
    r = tk.run_flow(
        tk._flow([tk._node("t1", "trigger", "T"),
                  tk._node("m1", "mcp", "M", {"provider": "telegram",
                                              "chat_id": "1", "pesan": "x"})],
                 [tk._edge("t1", "m1")]),
        provider_responses={"telegram": {"status": "error", "error": "boom-xyz"}})
    assert r.status == "error" and "boom-xyz" in r.error, r
    print(f"[7] error dilaporkan: {r.error[:70]}")


def test_08_security_adversarial():
    res = tk.security_adversarial()
    gagal = [r for r in res if not r.passed]
    for r in gagal:
        print(f"[8] FAIL {r.scenario.id}: {r.evidence}")
    assert not gagal, f"{len(gagal)} kasus adversarial gagal"
    print(f"[8] adversarial keamanan {len(res)}/{len(res)} lulus")


def test_09_load_test():
    rows = tk.load_test(levels=(20, 50))
    for row in rows:
        print(f"[9] n={row['level']} errors={row['errors']} "
              f"p50={row['p50_ms']}ms p95={row['p95_ms']}ms "
              f"thr={row['throughput_per_s']}/s")
    assert all(r["errors"] == 0 for r in rows), "load test menghasilkan error"
    assert all(r["p50_ms"] >= 0 for r in rows)
    print("[9] load test 0 error")


def test_10_tidak_menyentuh_jaringan():
    """Registry stub dipakai — bukan MCPRegistry asli yang membuka jaringan."""
    r = tk.run_flow(
        tk._flow([tk._node("t1", "trigger", "T"),
                  tk._node("m1", "mcp", "M", {"provider": "http", "url": "http://x"})],
                 [tk._edge("t1", "m1")]),
        provider_responses={"http": {"status": "success", "ok": True}})
    assert r.status == "success"
    # StubRegistry.connect tidak melakukan apa pun; tidak ada panggilan asli.
    assert r.registry_calls == 0, "node memakai registry stub (tidak seharusnya invoke)"
    print("[10] tidak ada panggilan registry asli; stub murni")


def test_11_semua_kategori_terwakili():
    cats = {s.category for s in tk.build_catalog()}
    wajib = {"linear", "provider", "placeholder", "condition", "batch",
             "parallel", "delegation", "error", "graph", "security"}
    kurang = wajib - cats
    assert not kurang, f"kategori hilang: {kurang}"
    print(f"[11] kategori: {sorted(cats)}")


def test_12_temuan_bot_token_teredaksi():
    """Regresi temuan adversarial: key `bot_token` harus masuk _SENSITIVE_KEYS."""
    import database as db
    tg = "8912001431:AAF-0123456789abcdefghijklmnopqrstuv"
    red = db.redact_sensitive_json({"bot_token": tg, "chat_id": "42"})
    assert tg not in str(red), "bot_token BOCOR di redaksi"
    assert red["bot_token"] == "[REDACTED]"
    assert red["chat_id"] == "42", "field non-sensitif tidak boleh ikut dihapus"
    print("[12] bot_token teredaksi; chat_id tetap utuh")
