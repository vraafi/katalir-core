# tests/test_sandbox_production.py — fitur #6 DISAMBUNGKAN KE PRODUKSI (8 Okt 2026)
# =====================================================================
# MENGAPA BERKAS INI ADA
#   `code_sandbox.py` sudah ada dan lulus hard test (tests/test_code_sandbox.py),
#   tetapi TIDAK ADA satu pun jalur eksekusi yang memanggilnya. `/version`
#   melaporkan fitur #6 "ada" karena modulnya bisa diimpor, padahal user tidak
#   bisa memakainya sama sekali (temuan #17 di docs/hard-test-limits.md).
#
#   Berkas ini menguji PENYAMBUNGANNYA, bukan sandbox-nya lagi:
#     A. node CODE di execution_engine (StatefulOrchestrator) + output shape
#     B. perilaku sandbox yang bergantung pada jalur baru (input_data)
#     C. integrasi workflow: berurutan, gagal, isolasi cabang paralel
#     D. tool MCP `execute_code` lewat protokol MCP sungguhan
#     E. keamanan: vektor escape, injeksi lewat data, isolasi antar-tenant
#     F. klasifikasi self-healing (kode gagal TIDAK boleh di-retry)
#     G. permukaan `/version`
#
# PRINSIP: setiap klaim punya bukti angka. `print()` di setiap tes adalah
# bagian dari bukti (dijalankan dengan `-s`).
# =====================================================================
from __future__ import annotations

import asyncio
import json
import time

import pytest

import code_sandbox as CS
import execution_engine as ee
import self_healing as sh

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
FAST_FLOW_TIMEOUT = 90


@pytest.fixture()
def fast_healing(monkeypatch):
    """Self-healing tanpa jaringan + tanpa backoff (tes deterministik).

    Tanpa ini, satu node code yang gagal akan mencoba menghubungi LLM/forum
    dan tes menjadi bergantung jaringan.
    """
    monkeypatch.setattr(sh, "TRANSIENT_DELAYS_MS", (0, 0, 0, 0, 0))
    monkeypatch.setattr(sh, "RATE_LIMIT_DELAYS_MS", (0, 0, 0, 0, 0))
    monkeypatch.setattr(sh, "REFUSED_DELAYS_MS", (0, 0))

    class _Fast(sh.SelfHealingAgent):
        def __init__(self, **kw):
            kw.setdefault("search_enabled", False)
            super().__init__(**kw)

    monkeypatch.setattr(ee, "SelfHealingAgent", _Fast)
    return _Fast


def n(nid: str, kind: str, config: dict | None = None) -> dict:
    return {"id": nid, "type": kind, "position": {"x": 0, "y": 0},
            "data": {"kind": kind, "label": nid, "config": config or {}}}


def flow(nodes: list[dict], edges: list[tuple[str, str]]) -> ee.FlowGraph:
    return ee.FlowGraph.model_validate({
        "nodes": nodes,
        "edges": [{"source": a, "target": b} for a, b in edges],
    })


def run_flow(nodes, edges, *, trigger_input=None, healing_factory=None):
    orch = ee.StatefulOrchestrator(
        flow(nodes, edges), trigger_input=trigger_input or {},
        owner_email="uji@local", healing_factory=healing_factory)
    steps = asyncio.run(orch.run())
    return orch, steps


def run_flow_catch(nodes, edges, *, trigger_input=None, healing_factory=None):
    """Sama, tapi menangkap kegagalan alur.

    `StatefulOrchestrator.run()` MENAIKKAN RuntimeError ketika ada node gagal
    (`raise RuntimeError(f"Nodo {nid} fallo: {res}")`), jadi `states` tidak bisa
    diperiksa tanpa menangkapnya lebih dulu.
    """
    orch = ee.StatefulOrchestrator(
        flow(nodes, edges), trigger_input=trigger_input or {},
        owner_email="uji@local", healing_factory=healing_factory)
    try:
        return orch, asyncio.run(orch.run()), None
    except Exception as exc:  # noqa: BLE001 - justru itu yang diuji
        return orch, [], exc


def by_id(steps):
    return {s.node_id: s for s in steps}


# =====================================================================
# A. NODE CODE DI EXECUTION ENGINE
# =====================================================================
def test_a1_nodekind_code_terdaftar_di_executors():
    """NodeKind baru WAJIB punya executor — kalau tidak, KeyError saat jalan."""
    kinds = [k.value for k in ee.NodeKind]
    executors = [k.value for k in ee.StatefulOrchestrator.EXECUTORS]
    print(f"[A1] NodeKind={kinds}")
    print(f"[A1] EXECUTORS={executors}")
    assert "code" in kinds
    assert "code" in executors, "kind 'code' tidak punya executor"
    assert set(executors) == set(kinds), \
        "ada NodeKind tanpa executor (atau sebaliknya)"


def test_a2_python_print_ke_stdout(fast_healing):
    """Skenario brief 1: print('hello') -> stdout berisi 'hello'."""
    _, steps = run_flow(
        [n("t1", "trigger", {"event_name": "manual"}),
         n("c1", "code", {"language": "python",
                          "code": 'print("hello")\nresult = "selesai"'})],
        [("t1", "c1")])
    out = by_id(steps)["c1"].output
    print(f"[A2] stdout={out['stdout']!r} result={out['result']!r}")
    assert out["type"] == "code.run"
    assert "hello" in out["stdout"], "print tidak tertangkap"
    assert out["result"] == "selesai"
    # stdout HARUS hanya keluaran user, bukan JSON internal runner.
    assert "os_limits" not in out["stdout"], \
        "JSON internal runner bocor ke stdout user"


def test_a3_python_menghitung_dan_mengembalikan(fast_healing):
    """Skenario brief 2: hitung, kembalikan lewat `result`."""
    _, steps = run_flow(
        [n("t1", "trigger", {}),
         n("c1", "code", {"code": "result = 1 + 1"})],
        [("t1", "c1")])
    out = by_id(steps)["c1"].output
    print(f"[A3] result={out['result']!r} duration_ms={out['duration_ms']}")
    assert out["result"] == 2
    assert out["language"] == "python"
    assert isinstance(out["duration_ms"], int) and out["duration_ms"] >= 0


def test_a4_javascript_menghitung(fast_healing):
    """Skenario brief 3: JavaScript lewat node code."""
    if not CS.capabilities()["javascript_available"]:
        pytest.skip("runtime node tidak tersedia")
    _, steps = run_flow(
        [n("t1", "trigger", {}),
         n("c1", "code", {"language": "javascript", "code": "result = 1 + 1;"})],
        [("t1", "c1")])
    out = by_id(steps)["c1"].output
    print(f"[A4] language={out['language']} result={out['result']!r}")
    assert out["result"] == 2
    assert out["language"] == "javascript"


def test_a5_list_comprehension(fast_healing):
    """Skenario brief 4: comprehension (butuh `_getiter_` RestrictedPython)."""
    _, steps = run_flow(
        [n("t1", "trigger", {}),
         n("c1", "code", {"code": "result = sum([x * x for x in range(10)])"})],
        [("t1", "c1")])
    out = by_id(steps)["c1"].output
    print(f"[A5] result={out['result']!r}")
    assert out["result"] == 285


def test_a6_default_language_adalah_python(fast_healing):
    """`config.language` kosong -> python (bukan error)."""
    _, steps = run_flow(
        [n("t1", "trigger", {}), n("c1", "code", {"code": "result = 7"})],
        [("t1", "c1")])
    out = by_id(steps)["c1"].output
    print(f"[A6] language={out['language']} result={out['result']}")
    assert out["language"] == "python" and out["result"] == 7


def test_a7_timeout_s_dijepit_ke_30(fast_healing):
    """`timeout_s: 600` TIDAK boleh memberi 600 detik.

    Dibuktikan lewat pesan error sandbox, bukan dengan menunggu 30 detik:
    kalau jepitan bekerja, pesannya menyebut 30s.
    """
    orch, _, exc = run_flow_catch(
        [n("t1", "trigger", {}),
         n("c1", "code", {"timeout_s": "600", "code": "while True:\n    pass"})],
        [("t1", "c1")], healing_factory=fast_healing)
    print(f"[A7] states={orch.states}")
    print(f"[A7] exc={str(exc)[:200]}")
    assert orch.states["c1"] == "error"
    assert exc is not None and "30s" in str(exc), \
        "jepitan 30s tidak terlihat di pesan error"


def test_a8_code_gagal_menandai_node_error_bukan_completed(fast_healing):
    """Anti 'kegagalan senyap' (kelas bug BUG-B2/BUG-B3)."""
    orch, _, exc = run_flow_catch(
        [n("t1", "trigger", {}),
         n("c1", "code", {"code": "import os\nresult = 1"})],
        [("t1", "c1")], healing_factory=fast_healing)
    print(f"[A8] states={orch.states}")
    print(f"[A8] exc={str(exc)[:160]}")
    assert orch.states["c1"] == "error", "kode gagal tapi node 'completed'"
    assert exc is not None and "CodeExecutionError" in str(exc)


def test_a9_config_code_kosong_ditolak_jujur(fast_healing):
    for cfg in ({}, {"code": ""}, {"code": "   "}, {"code": 123}):
        with pytest.raises(Exception) as exc:
            run_flow([n("t1", "trigger", {}), n("c1", "code", cfg)],
                     [("t1", "c1")], healing_factory=fast_healing)
        assert "CodeExecutionError" in str(exc.value), (cfg, str(exc.value))
    print("[A9] config.code kosong/bukan-string -> CodeExecutionError (4 bentuk)")


def test_a10_bahasa_tidak_didukung_ditolak(fast_healing):
    with pytest.raises(Exception) as exc:
        run_flow([n("t1", "trigger", {}),
                  n("c1", "code", {"language": "ruby", "code": "result = 1"})],
                 [("t1", "c1")], healing_factory=fast_healing)
    print(f"[A10] {str(exc.value)[:120]}")
    assert "CodeExecutionError" in str(exc.value)
    assert "ruby" in str(exc.value)


def test_a11_timeout_s_bukan_angka_ditolak(fast_healing):
    with pytest.raises(Exception) as exc:
        run_flow([n("t1", "trigger", {}),
                  n("c1", "code", {"timeout_s": "dua menit", "code": "result = 1"})],
                 [("t1", "c1")], healing_factory=fast_healing)
    print(f"[A11] {str(exc.value)[:120]}")
    assert "CodeExecutionError" in str(exc.value)


# =====================================================================
# B. DATA WORKFLOW -> `input_data` (VARIABEL, BUKAN SUBSTITUSI TEKS)
# =====================================================================
def test_b1_input_data_berisi_output_predesesor(fast_healing):
    _, steps = run_flow(
        [n("t1", "trigger", {"event_name": "webhook"}),
         n("c1", "code", {"code":
             'result = {"dari": input_data["from"],'
             ' "kunci": sorted(input_data["input"].keys()),'
             ' "event": input_data["input"]["t1"]["event"]}'})],
        [("t1", "c1")])
    out = by_id(steps)["c1"].output
    print(f"[B1] result={out['result']}")
    assert out["result"]["dari"] == "t1"
    assert out["result"]["kunci"] == ["t1"]
    assert out["result"]["event"] == "webhook"


def test_b2_payload_trigger_sampai_ke_kode(fast_healing):
    _, steps = run_flow(
        [n("t1", "trigger", {}),
         n("c1", "code", {"code":
             'result = input_data["input"]["t1"]["webhook_payload"]["nilai"] * 3'})],
        [("t1", "c1")], trigger_input={"nilai": 14})
    out = by_id(steps)["c1"].output
    print(f"[B2] payload 14 * 3 = {out['result']}")
    assert out["result"] == 42


def test_b3_placeholder_tidak_disubstitusi_di_dalam_kode(fast_healing):
    """KUNCI KEAMANAN: `{{...}}` di `config.code` dibiarkan apa adanya.

    Semua executor lain mengganti `{{akar.jalur}}` dengan nilai dari output
    node hulu. Untuk `code` itu SENGAJA tidak dilakukan: `_resolve_text`
    menyisipkan nilai string TANPA kutip, jadi data tak tepercaya akan menjadi
    TEKS KODE.

    Bukti: `{{trigger.tidak_ada}}` yang tidak bisa diresolv TIDAK melempar
    PlaceholderResolutionError (seperti pada node lain) dan tetap literal.
    """
    _, steps = run_flow(
        [n("t1", "trigger", {}),
         n("c1", "code", {"code": 'result = "{{trigger.tidak_ada}}"',
                          "language": "python"})],
        [("t1", "c1")])
    out = by_id(steps)["c1"].output
    print(f"[B3] result={out['result']!r} (harus literal)")
    assert out["result"] == "{{trigger.tidak_ada}}"


def test_b4_node_lain_TETAP_meresolv_placeholder(monkeypatch):
    """Kontrol untuk B3: node MCP masih meresolv `{{...}}` seperti sebelumnya.

    Tanpa kontrol ini, B3 tidak membuktikan apa pun — bisa saja resolusi
    placeholder memang sedang rusak.
    """
    terlihat: dict = {}

    async def _run(provider, cfg, params, email=""):
        terlihat["pesan"] = cfg.get("pesan")
        return {"status": "success", "tool": "telegram"}

    monkeypatch.setattr(ee.provider_registry, "run_async", _run)
    _, steps = run_flow(
        [n("t1", "trigger", {}),
         n("c1", "code", {"code": "result = 6 * 7"}),
         n("m1", "mcp", {"provider": "telegram", "chat_id": "1",
                         "pesan": "hasil={{c1.result}}"})],
        [("t1", "c1"), ("c1", "m1")])
    print(f"[B4] pesan yang diterima provider = {terlihat.get('pesan')!r}")
    assert terlihat.get("pesan") == "hasil=42", terlihat


def test_b5_data_di_dalam_input_data_adalah_DATA_bukan_KODE(fast_healing):
    """Nilai yang tampak seperti kode harus tetap berupa string.

    Ini yang membedakan injeksi variabel (aman) dari substitusi teks (tidak):
    pada substitusi teks, `input_data["x"]` bernilai `"1; import os"` akan
    menjadi baris kode `1; import os`.
    """
    jahat = {
        "a": "1; import os",
        "b": "__import__('os').system('echo PWNED')",
        "c": '"); import os #',
        "d": "0x" + "0" * 40,
        "e": {"nested": "result = 999"},
    }
    r = CS.execute(
        'result = [input_data["a"], input_data["b"], input_data["c"],'
        ' input_data["e"]["nested"]]',
        vars=jahat)
    print(f"[B5] ok={r['ok']} result={r['result']}")
    assert r["ok"] is True, r["error"]
    assert r["result"] == [jahat["a"], jahat["b"], jahat["c"],
                           jahat["e"]["nested"]]


def test_b6_kunci_data_aneh_tidak_hilang(fast_healing):
    """Kunci payload nyata (`@timestamp`, `user-id`, `_meta`) harus selamat."""
    r = CS.execute("result = sorted(input_data.keys())",
                   vars={"@timestamp": "t", "user-id": 7, "_meta": True,
                         "a": None})
    print(f"[B6] kunci={r['result']}")
    assert r["result"] == ["@timestamp", "_meta", "a", "user-id"]


def test_b7_objek_non_json_dibuang_tidak_menjadi_string():
    """Sanitizer: objek Python TIDAK boleh masuk namespace sandbox.

    Dibuang, bukan diubah `str(obj)` — `str()` memanggil `__repr__` milik
    objek itu, yang pada objek tak dikenal bisa menjalankan kode.
    """
    class _ReprJahat:
        def __repr__(self):
            return "REPR-DIPANGGIL"

    bersih = CS.sanitize_vars({"baik": 1, "jahat": _ReprJahat(),
                               "modul": json})
    print(f"[B7] hasil sanitasi = {bersih}")
    assert bersih == {"baik": 1}, bersih
    assert "REPR-DIPANGGIL" not in json.dumps(bersih)


def test_b8_data_terlalu_besar_ditolak():
    besar = {"x": "a" * (CS.CODE_MAX_VARS_BYTES + 1000)}
    with pytest.raises(CS.SandboxError) as exc:
        CS.sanitize_vars(besar)
    print(f"[B8] {exc.value}")
    assert "terlalu besar" in str(exc.value)


def test_b9_jalur_javascript_memakai_nama_variabel_yang_sama():
    """Python dan JS harus memakai SATU nama variabel (`input_data`)."""
    if not CS.capabilities()["javascript_available"]:
        pytest.skip("runtime node tidak tersedia")
    r = CS.execute("result = input_data.a + input_data.b", "javascript",
                   vars={"a": 20, "b": 22})
    print(f"[B9] js input_data -> {r['result']}")
    assert r["ok"] is True and r["result"] == 42
    assert CS.VARS_NAME == "input_data"


def test_b10_prototype_pollution_lewat_data_ditolak():
    """JS: kunci `__proto__` di data TIDAK boleh mengubah prototipe."""
    if not CS.capabilities()["javascript_available"]:
        pytest.skip("runtime node tidak tersedia")
    r = CS.execute("result = (input_data.polluted === undefined)",
                   "javascript", vars={"__proto__": {"polluted": 1}, "ok": 2})
    print(f"[B10] polluted undefined? {r['result']}")
    assert r["ok"] is True and r["result"] is True


# =====================================================================
# C. INTEGRASI WORKFLOW
# =====================================================================
def test_c1_tiga_node_code_berurutan(fast_healing):
    """Skenario brief 16: 3 code node berurutan, semua jalan, data mengalir."""
    _, steps = run_flow(
        [n("t1", "trigger", {}),
         n("c1", "code", {"code": 'result = 10'}),
         n("c2", "code", {"code": 'result = input_data["input"]["c1"]["result"] + 5'}),
         n("c3", "code", {"code": 'result = input_data["input"]["c2"]["result"] * 2'})],
        [("t1", "c1"), ("c1", "c2"), ("c2", "c3")])
    b = by_id(steps)
    print(f"[C1] " + " | ".join(
        f"{k}={b[k].output.get('result')}" for k in ("c1", "c2", "c3")))
    assert [b[k].status for k in ("c1", "c2", "c3")] == ["completed"] * 3
    assert b["c1"].output["result"] == 10
    assert b["c2"].output["result"] == 15
    assert b["c3"].output["result"] == 30


def test_c2_code_node_gagal_di_tengah_rantai(fast_healing):
    """Skenario brief 17: error handling — node gagal menghentikan alur."""
    orch, _, exc = run_flow_catch(
        [n("t1", "trigger", {}),
         n("c1", "code", {"code": "result = 1"}),
         n("c2", "code", {"code": "result = 1 / 0"}),
         n("c3", "code", {"code": "result = 3"})],
        [("t1", "c1"), ("c1", "c2"), ("c2", "c3")],
        healing_factory=fast_healing)
    print(f"[C2] states={orch.states}")
    print(f"[C2] exc={str(exc)[:160]}")
    assert orch.states["c1"] == "completed"
    assert orch.states["c2"] == "error"
    assert orch.states.get("c3", "pending") != "completed", \
        "suksesor node gagal tetap dieksekusi"
    assert exc is not None
    pesan = str(exc)
    assert "ZeroDivisionError" in pesan or "division by zero" in pesan, pesan


def test_c3_cabang_paralel_terisolasi(fast_healing):
    """Skenario brief 18: dua cabang paralel, tiap node hanya melihat hulunya."""
    _, steps = run_flow(
        [n("t1", "trigger", {}),
         # cabang A
         n("a1", "code", {"code": 'result = "A1"'}),
         n("a2", "code", {"code":
             'result = {"dari": input_data["from"],'
             ' "kunci": sorted(input_data["input"].keys()),'
             ' "nilai": input_data["input"]["a1"]["result"]}'}),
         # cabang B
         n("b1", "code", {"code": 'result = "B1"'}),
         n("b2", "code", {"code":
             'result = {"dari": input_data["from"],'
             ' "kunci": sorted(input_data["input"].keys()),'
             ' "nilai": input_data["input"]["b1"]["result"]}'})],
        [("t1", "a1"), ("a1", "a2"), ("t1", "b1"), ("b1", "b2")])
    b = by_id(steps)
    print(f"[C3] a2={b['a2'].output['result']}")
    print(f"[C3] b2={b['b2'].output['result']}")
    assert b["a2"].output["result"] == {"dari": "a1", "kunci": ["a1"],
                                        "nilai": "A1"}
    assert b["b2"].output["result"] == {"dari": "b1", "kunci": ["b1"],
                                        "nilai": "B1"}
    assert all(b[k].status == "completed" for k in ("a1", "a2", "b1", "b2"))


def test_c4_cabang_paralel_tidak_saling_memblokir(fast_healing):
    """Paralelisme NYATA: 2 node code dengan beban CPU serupa.

    Kalau `code_sandbox` dipanggil langsung di coroutine (bukan lewat
    `asyncio.to_thread`), subprocess yang memblokir akan membekukan event loop
    dan kedua node berjalan BERURUTAN. Jadi total waktu dinding harus lebih
    kecil daripada JUMLAH durasi kedua node — itulah bukti tumpang tindih.

    CATATAN: nama variabel TIDAK boleh berawalan `_` (ditolak RestrictedPython
    sebagai "invalid variable name"). Versi pertama tes ini memakai `_x`/`_i`
    dan gagal — bukan karena paralelismenya salah, tapi karena kodenya ditolak
    sebelum berjalan.
    """
    sibuk = ("x = 0\n"
             "for i in range(2000000):\n"
             "    x += i\n"
             "result = x % 7\n")
    t0 = time.monotonic()
    _, steps = run_flow(
        [n("t1", "trigger", {}),
         n("a1", "code", {"code": sibuk}),
         n("b1", "code", {"code": sibuk})],
        [("t1", "a1"), ("t1", "b1")])
    total = time.monotonic() - t0
    b = by_id(steps)
    durasi = [b[k].output["duration_ms"] for k in ("a1", "b1")]
    print(f"[C4] durasi per node (ms) = {durasi}; total dinding = {total:.2f}s")
    assert b["a1"].status == "completed" and b["b1"].status == "completed"
    # Kalau benar paralel, total dinding < jumlah durasi (ada tumpang tindih).
    assert total < (sum(durasi) / 1000.0), (
        f"total {total:.2f}s >= jumlah durasi {sum(durasi)/1000:.2f}s -> "
        f"eksekusi TIDAK paralel (event loop terblokir)")


def test_c7_nama_variabel_berawalan_underscore_ditolak():
    """Temuan saat menulis tes ini: `_x = 1` DITOLAK RestrictedPython.

    Konsekuensinya nyata dan mudah menjebak: kode yang sepenuhnya sah menurut
    Python ditolak sandbox, dan pesannya ("invalid variable name because it
    starts with '_'") tidak menyebut aturan itu di UI. Dicatat di sini supaya
    perilakunya terkunci (kalau kelak dilonggarkan, tes ini memberi tahu).
    """
    r = CS.execute("_x = 1\nresult = _x")
    print(f"[C7] ok={r['ok']} error={str(r['error'])[:150]}")
    assert r["ok"] is False
    assert "invalid variable name" in str(r["error"])
    # Tanpa garis bawah, jalan seperti biasa.
    r2 = CS.execute("x = 1\nresult = x")
    print(f"[C7] tanpa '_' -> ok={r2['ok']} result={r2['result']}")
    assert r2["ok"] is True and r2["result"] == 1


def test_c5_trigger_code_telegram_rantai_penuh(monkeypatch, fast_healing):
    """Skenario brief 13: trigger -> code -> telegram, hasil kode ikut terkirim."""
    terlihat: dict = {}

    async def _run(provider, cfg, params, email=""):
        terlihat["provider"] = provider
        terlihat["pesan"] = cfg.get("pesan")
        terlihat["email"] = email
        return {"status": "success", "tool": "telegram",
                "result": {"message_id": 1}}

    monkeypatch.setattr(ee.provider_registry, "run_async", _run)
    _, steps = run_flow(
        [n("t1", "trigger", {}),
         n("c1", "code", {"code":
             'n = input_data["input"]["t1"]["webhook_payload"]["n"]\n'
             'result = "total=" + str(n * n)'}),
         n("m1", "mcp", {"provider": "telegram", "chat_id": "999",
                         "pesan": "{{c1.result}}"})],
        [("t1", "c1"), ("c1", "m1")], trigger_input={"n": 7})
    b = by_id(steps)
    print(f"[C5] provider={terlihat.get('provider')} pesan={terlihat.get('pesan')!r}")
    assert terlihat["provider"] == "telegram"
    assert terlihat["pesan"] == "total=49", terlihat
    assert terlihat["email"] == "uji@local", "email pemilik tidak diteruskan"
    assert b["m1"].status == "completed"


def test_c6_kondisi_if_masih_bekerja_untuk_node_code(fast_healing):
    """`config.condition` berlaku juga untuk node code (gerbang kondisi)."""
    _, steps = run_flow(
        [n("t1", "trigger", {}),
         n("c1", "code", {"condition": "{{data.status}} == 200",
                          "code": "result = 'jalan'"})],
        [("t1", "c1")], trigger_input={"status": 500})
    st = by_id(steps)["c1"]
    print(f"[C6] status={st.status} output={json.dumps(st.output, default=str)[:120]}")
    assert st.status == "skipped"


# =====================================================================
# D. TOOL MCP `execute_code`
# =====================================================================
@pytest.fixture()
def mcp_server(monkeypatch):
    monkeypatch.setenv("KATALIR_MCP_SIGNING_KEY", "uji-signing-key-0123456789")
    import mcp_server as MS
    return MS


def _call(MS, nama, args, *, user="user-uji"):
    srv = MS.build_server()
    tok = MS._current_key.set({"user_id": user, "email": f"{user}@local"})
    try:
        res = asyncio.run(srv.call_tool(nama, args))
    finally:
        MS._current_key.reset(tok)
    # FastMCP membungkus hasil sebagai list blok teks berisi JSON.
    teks = res[0].text if res else ""
    try:
        return json.loads(teks)
    except Exception:
        return {"_raw": teks}


def test_d1_tool_terdaftar_dengan_annotasi_benar(mcp_server):
    srv = mcp_server.build_server()
    tools = asyncio.run(srv.list_tools())
    nama = [t.name for t in tools]
    ec = [t for t in tools if t.name == "execute_code"][0]
    print(f"[D1] tools={nama}")
    print(f"[D1] annotations readonly={ec.annotations.readOnlyHint} "
          f"destructive={ec.annotations.destructiveHint} "
          f"idempotent={ec.annotations.idempotentHint} "
          f"openworld={ec.annotations.openWorldHint}")
    assert "execute_code" in nama
    assert ec.annotations.readOnlyHint is False
    assert ec.annotations.destructiveHint is True
    assert ec.annotations.idempotentHint is False
    assert ec.annotations.openWorldHint is False
    props = set((ec.inputSchema or {}).get("properties", {}))
    print(f"[D1] inputSchema={sorted(props)} required="
          f"{(ec.inputSchema or {}).get('required')}")
    assert props == {"code", "language", "timeout_s"}
    assert (ec.inputSchema or {}).get("required") == ["code"]


def test_d2_panggilan_python_lewat_protokol_mcp(mcp_server):
    r = _call(mcp_server, "execute_code", {"code": "result = sum([1,2,3,4])"})
    print(f"[D2] {json.dumps(r)}")
    assert r["ok"] is True and r["result"] == 10
    assert r["language"] == "python" and r["memory_limit_mb"] == 128


def test_d3_panggilan_javascript_lewat_protokol_mcp(mcp_server):
    if not CS.capabilities()["javascript_available"]:
        pytest.skip("runtime node tidak tersedia")
    r = _call(mcp_server, "execute_code",
              {"code": "result = 6 * 7;", "language": "javascript"})
    print(f"[D3] {json.dumps(r)}")
    assert r["ok"] is True and r["result"] == 42


def test_d4_tanpa_api_key_ditolak(mcp_server):
    """Eksekusi kode TIDAK boleh anonim."""
    srv = mcp_server.build_server()
    with pytest.raises(Exception) as exc:
        asyncio.run(srv.call_tool("execute_code", {"code": "result = 1"}))
    print(f"[D4] {type(exc.value).__name__}: {str(exc.value)[:120]}")
    assert "API key" in str(exc.value) or "401" in str(exc.value)


def test_d5_masukan_buruk_dilaporkan_bukan_crash(mcp_server):
    """Dua lapis penolakan, dan keduanya sah:
      1. tipe salah (`timeout_s="dua"`) ditolak SKEMA MCP sebelum fungsi jalan;
      2. nilai salah (kode kosong, bahasa tak didukung) dikembalikan sebagai
         `ok=false` + `error` supaya agen bisa memperbaiki sendiri.
    """
    from mcp.server.fastmcp.exceptions import ToolError

    # 1. Validasi skema MCP: tipe yang salah tidak pernah sampai ke fungsi.
    with pytest.raises(ToolError) as exc:
        _call(mcp_server, "execute_code", {"code": "result = 1",
                                           "timeout_s": "dua"})
    print(f"[D5] timeout_s='dua' -> ToolError: {str(exc.value)[:110]}")
    assert "timeout_s" in str(exc.value)

    # 2. Nilai yang salah -> error yang bisa ditindaklanjuti, bukan crash.
    kasus = [
        ({"code": ""}, "code wajib"),
        ({"code": "result = 1", "language": "ruby"}, "tidak didukung"),
    ]
    for args, harap in kasus:
        r = _call(mcp_server, "execute_code", args)
        print(f"[D5] {args} -> ok={r['ok']} error={r['error']!r}")
        assert r["ok"] is False and harap in r["error"]


def test_d6_timeout_dijepit_di_mcp(mcp_server):
    r = _call(mcp_server, "execute_code", {"code": "result = 1", "timeout_s": 600})
    print(f"[D6] timeout_s diminta=600 dipakai={r['timeout_s']}")
    assert r["ok"] is True
    assert r["timeout_s"] == CS.CODE_TIMEOUT_S == 30


def test_d7_describe_memuat_tool_baru(mcp_server):
    d = mcp_server.describe()
    nama = [t["name"] for t in d["tools"]]
    print(f"[D7] {nama}")
    assert "execute_code" in nama and len(nama) == 6
    assert d["tools"][-1]["args"] == ["code", "language", "timeout_s"]


# =====================================================================
# E. KEAMANAN
# =====================================================================
#: Vektor escape (brief: 20 vektor, 0 bocor). Dibagi dua bahasa.
VEKTOR_PYTHON = [
    "import os",
    "from os import system",
    '__import__("os")',
    'eval("1+1")',
    'exec("x=1")',
    'compile("1", "<s>", "eval")',
    'open("/etc/passwd")',
    "(1).__class__",
    "(1).__class__.__mro__",
    "(1).__class__.__base__.__subclasses__()",
    'getattr(1, "__class__")',
    '"{0.__class__}".format(1)',
    '"{0." + "__class__" + "}".format(1)',
    '"".join(["__","class","__"])',
    "globals()",
    "locals()",
    "type(1).__mro__",
    "(lambda: 0).__globals__",
    "print.__self__",
    "[].__class__.__mro__[1].__subclasses__()",
]

VEKTOR_JAVASCRIPT = [
    'require("fs")',
    "process.env",
    'eval("1+1")',
    'Function("return 1")()',
    "globalThis",
    "constructor[",
    "Reflect.get",
    "Proxy(",
    "Symbol(",
    "module.exports",
    "__proto__",
]

#: Penanda bahwa sandbox BENAR-BENAR bocor. Dipilih agar TIDAK muncul pada
#: pesan penolakan yang sah (mis. "import tidak diizinkan: subprocess" juga
#: memuat kata 'subprocess', jadi kata itu bukan penanda).
PENANDA_BOCOR = (
    "<class ", "0x", "__main__", "built-in", "posix.", "nt.",
    "/bin/", "os.environ", "module 'os'", "module 'sys'",
)


def test_e1_dua_puluh_vektor_escape_python_nol_bocor():
    """Skenario brief 19 (bagian Python)."""
    bocor: list[tuple[str, dict]] = []
    for v in VEKTOR_PYTHON:
        r = CS.execute(v)
        jejak = json.dumps({"stdout": r.get("stdout"), "stderr": r.get("stderr"),
                            "error": r.get("error"), "result": r.get("result")},
                           default=str)
        ada = [p for p in PENANDA_BOCOR if p in jejak]
        print(f"[E1] {'BLOCKED' if not r['ok'] else 'OK   '} "
              f"jejak={('BOCOR ' + str(ada)) if ada else 'bersih'} :: {v[:46]}")
        if ada:
            bocor.append((v, {"penanda": ada, "jejak": jejak[:200]}))
    assert not bocor, f"{len(bocor)} vektor bocor: {bocor}"
    print(f"[E1] total {len(VEKTOR_PYTHON)} vektor Python, bocor = 0")


def test_e2_sebelas_vektor_escape_javascript_nol_bocor():
    """Skenario brief 19 (bagian JavaScript)."""
    if not CS.capabilities()["javascript_available"]:
        pytest.skip("runtime node tidak tersedia")
    bocor: list[tuple[str, dict]] = []
    for v in VEKTOR_JAVASCRIPT:
        r = CS.execute(v, "javascript")
        jejak = json.dumps({"stdout": r.get("stdout"), "stderr": r.get("stderr"),
                            "error": r.get("error"), "result": r.get("result")},
                           default=str)
        ada = [p for p in PENANDA_BOCOR if p in jejak]
        print(f"[E2] {'BLOCKED' if not r['ok'] else 'OK   '} "
              f"jejak={('BOCOR ' + str(ada)) if ada else 'bersih'} :: {v[:40]}")
        if ada:
            bocor.append((v, {"penanda": ada, "jejak": jejak[:200]}))
    assert not bocor, f"{len(bocor)} vektor bocor: {bocor}"
    print(f"[E2] total {len(VEKTOR_JAVASCRIPT)} vektor JS, bocor = 0")


def test_e3_vektor_rakitan_lewat_data_juga_nol_bocor():
    """Vektor yang DIRAKIT saat runtime dan diumpankan lewat `input_data`.

    Dua jalur sekaligus: (a) perakitan string menghindari pemindaian literal
    AST, (b) jalur data baru. Keduanya harus tetap bersih.
    """
    rakitan = [
        '"".join(["__", "class", "__"])',
        '"__" + "class" + "__"',
        "chr(95) * 2 + 'class' + chr(95) * 2",
        '"__sub" + "classes__"',
    ]
    bocor = []
    for rakit in rakitan:
        kode = f"result = {rakit}"
        r = CS.execute(kode, vars={"pemicu": rakit})
        jejak = json.dumps(r, default=str)
        ada = [p for p in PENANDA_BOCOR if p in jejak]
        print(f"[E3] {'BOCOR' if ada else 'bersih'} :: {rakit}")
        if ada:
            bocor.append(rakit)
    assert not bocor, bocor


def test_e4_isolasi_antar_tenant_tidak_ada_kanal_data():
    """Skenario brief 20: kode user A tidak bisa menjangkau data user B.

    Dibuktikan dengan MENUNJUKKKAN TIDAK ADA KANALNYA, bukan dengan mencoba
    "membobol" sesuatu yang tidak ada:

      1. sandbox tidak menerima data user sama sekali di jalur MCP
         (`vars={}`), jadi `input_data` selalu `{}`;
      2. hasil untuk dua user BERBEDA identik — tidak ada satu bit pun yang
         bergantung pada identitas;
      3. tidak ada jalur filesystem/jaringan/kredensial untuk mengambilnya.
    """
    import mcp_server as MS

    kode = ("result = {"
            "'kunci_data': sorted(input_data.keys()),"
            "'panjang': len(input_data)}")
    a = _call(MS, "execute_code", {"code": kode}, user="user-A")
    b = _call(MS, "execute_code", {"code": kode}, user="user-B")
    print(f"[E4] user-A -> {json.dumps(a.get('result'))}")
    print(f"[E4] user-B -> {json.dumps(b.get('result'))}")
    assert a["ok"] and b["ok"]
    assert a["result"] == {"kunci_data": [], "panjang": 0}, a["result"]
    assert b["result"] == a["result"], "hasil bergantung pada identitas user"

    # Tidak ada jalan keluar untuk mengambil data user: import, jaringan,
    # filesystem — semuanya ditolak SEBELUM kode berjalan.
    for vektor in ('import os', 'open("/proc/self/environ")',
                   'import socket', 'import sqlite3'):
        r = CS.execute(vektor)
        print(f"[E4] {vektor!r} -> ok={r['ok']} err={str(r['error'])[:60]}")
        assert r["ok"] is False, vektor


def test_e5_vektor_javascript_tidak_bisa_menembus_lewat_data():
    """Data yang diinjeksi tidak boleh menjadi kode di jalur JS."""
    if not CS.capabilities()["javascript_available"]:
        pytest.skip("runtime node tidak tersedia")
    jahat = {"x": 'require("fs").readFileSync("/etc/passwd","utf8")'}
    r = CS.execute('result = input_data.x;', "javascript", vars=jahat)
    print(f"[E5] ok={r['ok']} result={r['result']!r}")
    assert r["ok"] is True
    assert r["result"] == jahat["x"], "nilai data dieksekusi sebagai kode"


# =====================================================================
# F. SELF-HEALING: KODE GAGAL TIDAK BOLEH DI-RETRY
# =====================================================================
def test_f1_kode_gagal_diklasifikasi_abort():
    """Tanpa rule khusus, pesan 'timeout' sandbox cocok rule `network` -> retry 3x.

    Satu infinite loop akan membakar ~90 detik (3 x 30s) untuk hasil yang pasti
    sama. Rule `code_execution` harus menangkapnya lebih dulu.
    """
    pesan = ("CodeExecutionError: node 'c1' kode python gagal: "
             "timeout: eksekusi dihentikan setelah 30s")
    rule = sh.classify_error(pesan)
    print(f"[F1] rule={rule.name} action={rule.action} max_attempts={rule.max_attempts}")
    assert rule.name == "code_execution", \
        f"pesan sandbox jatuh ke rule {rule.name!r} -> akan di-retry"
    assert rule.action == "abort" and rule.max_attempts == 0


@pytest.mark.parametrize("pesan", [
    "CodeExecutionError: node 'c1' config.code wajib diisi (string tidak kosong)",
    "CodeExecutionError: node 'c1' bahasa 'ruby' tidak didukung",
    "CodeExecutionError: node 'c1' kode python gagal: import tidak diizinkan: os",
    "CodeExecutionError: node 'c1' kode python gagal: timeout: eksekusi "
    "dihentikan setelah 30s",
    "CodeExecutionError: node 'c1' config.timeout_s bukan angka: 'x'",
])
def test_f2_semua_pesan_code_abort(pesan):
    rule = sh.classify_error(pesan)
    print(f"[F2] {rule.name} / {rule.action} :: {pesan[:70]}")
    assert rule.name == "code_execution" and rule.action == "abort"


def test_f3_plan_healing_untuk_kode_adalah_abort(fast_healing):
    """`handle_failure` harus mengembalikan abort pada percobaan PERTAMA."""
    agen = fast_healing()
    plan = asyncio.run(agen.handle_failure(
        node_id="c1", attempt=1,
        error="CodeExecutionError: node 'c1' kode python gagal: "
              "timeout: eksekusi dihentikan setelah 30s"))
    print(f"[F3] action={plan.action} category={plan.category} "
          f"max_attempts={plan.max_attempts} delay_ms={plan.delay_ms}")
    assert plan.action == "abort"
    assert plan.max_attempts == 0
    assert plan.delay_ms == 0


def test_f4_rule_lain_tidak_ikut_berubah():
    """Kontrol: menambah rule pertama tidak boleh menelan rule lama."""
    kasus = {
        "PlaceholderResolutionError: akar 'x' tidak ada": "placeholder_invalid",
        "401 token expired": "oauth_token_expired",
        "429 rate limit": "rate_limited",
        "503 service unavailable": "server_5xx",
        "ETIMEDOUT connecting": "network",
        "404 not found": "not_found",
        "error aneh tanpa pola": "unknown",
    }
    salah = []
    for pesan, harap in kasus.items():
        dapat = sh.classify_error(pesan).name
        print(f"[F4] {dapat:20s} (harap {harap}) :: {pesan[:44]}")
        if dapat != harap:
            salah.append((pesan, harap, dapat))
    assert not salah, salah


# =====================================================================
# G. PERMUKAAN `/version`
# =====================================================================
def test_g1_version_mengekspos_code_sandbox():
    import api_server
    info = api_server._limits_info()
    cs_info = info.get("code_sandbox")
    print(f"[G1] code_sandbox={json.dumps(cs_info)}")
    assert cs_info is not None, "/version tidak mengekspos code_sandbox"
    assert cs_info["enabled"] is True
    assert cs_info["languages"] == ["python", "javascript"]
    assert cs_info["max_timeout_s"] == 30
    assert cs_info["memory_limit_mb"] == 128
    assert cs_info["memory_enforced"] is True
    assert cs_info["endpoints"] == ["code_node", "mcp_execute_code"]


def test_g2_version_mengekspos_tool_mcp_yang_benar_benar_terdaftar():
    import api_server
    info = api_server._limits_info()
    print(f"[G2] mcp_tools={info.get('mcp_tools')}")
    assert "execute_code" in info.get("mcp_tools", []), \
        "tool MCP tidak terdaftar di /version"


def test_g3_fitur_06_masih_terhitung_ada():
    import api_server
    feats = api_server._feature_status()
    print(f"[G3] 06_code_sandbox={feats.get('06_code_sandbox')} "
          f"total={sum(1 for v in feats.values() if v)}/{len(feats)}")
    assert feats.get("06_code_sandbox") is True
    assert all(feats.values()), feats


# =====================================================================
# H. BATAS YANG DITEGAKKAN (memori, timeout, keluaran)
# =====================================================================
def test_h1_timeout_membunuh_proses_pada_batas_nyata():
    """Batas keras 30 detik — diukur, bukan diasumsikan."""
    t0 = time.monotonic()
    r = CS.execute("while True:\n    pass")
    durasi = time.monotonic() - t0
    print(f"[H1] ok={r['ok']} killed={r['killed']} error={r['error']!r} "
          f"durasi_nyata={durasi:.1f}s")
    assert r["ok"] is False and r["killed"] is True
    assert "30s" in r["error"]
    assert 28 <= durasi <= 45, f"durasi di luar dugaan: {durasi:.1f}s"


def test_h2_memory_bomb_2gb_gagal_dan_proses_selamat():
    """Skenario brief 10: alokasi 2GB harus ditolak, proses induk tetap hidup.

    Nama variabel TIDAK boleh berawalan `_` (ditolak RestrictedPython). Versi
    pertama tes ini memakai `_b` dan "lulus" karena alasan yang salah — kodenya
    ditolak sebagai nama variabel tidak sah, bukan karena batas memori.
    """
    r = CS.execute("blok = bytes(2 * 1024 * 1024 * 1024)\nresult = len(blok)")
    jejak = json.dumps(r, default=str)
    print(f"[H2] ok={r['ok']} os_limits={r['os_limits']} "
          f"error={str(r['error'])[:110]}")
    assert r["ok"] is False, "alokasi 2GB BERHASIL -> batas memori tidak berlaku"
    assert "invalid variable name" not in jejak, \
        "gagal karena nama variabel, bukan karena batas memori"
    assert ("MemoryError" in jejak or "memory limit" in jejak
            or "watchdog" in jejak), jejak[:250]


def test_h3_loop_alokasi_512mb_gagal():
    r = CS.execute("kotak = []\nfor i in range(512):\n"
                   "    kotak.append(bytes(1024 * 1024))\nresult = len(kotak)")
    jejak = json.dumps(r, default=str)
    print(f"[H3] ok={r['ok']} os_limits={r['os_limits']} "
          f"error={str(r['error'])[:110]}")
    assert r["ok"] is False, "512MB berhasil dialokasikan -> batas tidak berlaku"
    assert "invalid variable name" not in jejak, \
        "gagal karena nama variabel, bukan karena batas memori"


def test_h4_output_besar_dipotong():
    """Skenario brief 15: keluaran besar harus dipotong, bukan membanjiri API.

    Batas berlaku pada stdout/stderr/error. `result` sendiri dikembalikan utuh
    sebagai nilai terstruktur — itu keputusan sadar: pemotongan di tengah JSON
    akan menghasilkan data yang tidak bisa dipakai. Yang WAJIB dibatasi adalah
    teks bebas (stdout/stderr/error) yang bisa dicetak tak terbatas.
    """
    r = CS.execute("print('B' * 200000)\nresult = 1")
    print(f"[H4] stdout setelah print 200KB = {len(r['stdout'])} byte "
          f"(batas {CS.CODE_MAX_OUTPUT_BYTES})")
    assert r["ok"] is True
    assert len(r["stdout"]) < CS.CODE_MAX_OUTPUT_BYTES + 200, \
        "stdout tidak dipotong"
    assert "dipotong" in r["stdout"]
    # Keluaran kecil TIDAK dipotong (kontrol).
    r2 = CS.execute("print('kecil')\nresult = 1")
    print(f"[H4] stdout kecil = {r2['stdout']!r}")
    assert "dipotong" not in r2["stdout"]


def test_h5_memory_terlalu_besar_tidak_ditulis_ke_disk():
    """`open()` diblokir SEBELUM kode berjalan (batas filesystem)."""
    r = CS.execute("result = open('bukti.txt', 'w')")
    print(f"[H5] ok={r['ok']} error={r['error']}")
    assert r["ok"] is False and "open" in str(r["error"])


def test_h6_jaringan_diblokir():
    """Skenario brief 11: akses jaringan harus BLOCKED."""
    vektor = ["import socket", "import urllib.request",
              "import http.client", "import requests"]
    for v in vektor:
        r = CS.execute(v)
        print(f"[H6] {v!r} -> ok={r['ok']} err={str(r['error'])[:60]}")
        assert r["ok"] is False, v


def test_h7_import_builtin_juga_ditolak_bukan_diizinkan():
    """Skenario brief 5: `import math`/`json` — jawabannya: DITOLAK.

    Ini penting dicatat jujur: kebijakan sandbox adalah TANPA impor sama
    sekali, bukan allowlist modul. Fitur yang tidak butuh impor tetap bisa
    memakai operasi bawaan (list/dict/str/range/…).
    """
    for v in ("import math", "import json", "import random", "import re"):
        r = CS.execute(v)
        print(f"[H7] {v!r} -> ok={r['ok']} err={str(r['error'])[:60]}")
        assert r["ok"] is False
    # Sebagai gantinya, matematika dasar tetap bisa tanpa impor:
    r = CS.execute("result = (2 ** 10) % 7 + abs(-3) + round(3.6)")
    print(f"[H7] tanpa impor: (2**10)%7 + abs(-3) + round(3.6) = {r['result']}")
    assert r["ok"] is True and r["result"] == 2 + 3 + 4
