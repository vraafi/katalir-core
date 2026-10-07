"""test_launch_blocker_fixes_2026_10_07.py — verifikasi "FIX 2 BUG KRITIS + 3 TEMUAN TINGGI".

Brief: *"# FIX 2 BUG KRITIS + 3 TEMUAN TINGGI — LAUNCH BLOCKER"* (7 Okt 2026).

Yang dikunci di sini, satu kelas bug per blok:

  BUG-B1  EKSEKUSI HANTU  - `_run_webhook_dag` menghitung `execution_id` tetapi
          TIDAK meneruskannya ke runner, sehingga seluruh `execution_logs`
          menempel di baris uuid lain dan baris yang di-poll klien hanya
          ber-status "completed" tanpa satu pun langkah.
  BUG-B2  KEGAGALAN SENYAP - `provider_registry.run` mengembalikan
          `{"status": "error"}` alih-alih melempar; `_exec_mcp` mengembalikannya
          apa adanya sehingga node tercatat "completed" walau tool gagal.
  F-2     KEBOCORAN JWT   - header `Authorization` (JWT ~818 karakter) dari
          webhook tersimpan sebagai teks biasa di `execution_logs.output_data`.
  F-3     METER TIDAK PERSIST - `_meter_save` menulis epoch FLOAT ke kolom
          `timestamp` (Postgres 22007) dan error-nya ditelan `except: pass`.
  F-1     KONTRADIKSI GEMBOK - tier FREE diizinkan `guard_execution` tetapi
          diblokir "Saldo habis" oleh cek `get_balance > 0` (gratis = 0.0).
  F-4     KEBOCORAN 500   - `/chat` menyisipkan `type(exc).__name__: exc`
          (mis. `ClientError: 400 INVALID_ARGUMENT`) ke body 500.

SEMUA tes OFFLINE: tidak ada jaringan, tidak menyentuh Supabase produksi.
"""

import asyncio
import json

import pytest

import database
import execution_engine as ee
import self_healing as sh
import tools


# ---------------------------------------------------------------------------
# Helper: DB tiruan (in-memory) supaya `execute_workflow_async` tidak menyentuh
# Supabase nyata dan hasilnya bisa diperiksa apa adanya.
# ---------------------------------------------------------------------------
class _MemDB:
    def __init__(self):
        self.executions: dict[str, dict] = {}
        self.logs: list[dict] = []

    def create_execution(self, execution_id, workflow_id, flow_data):
        self.executions.setdefault(
            execution_id, {"workflow_id": workflow_id, "status": "pending"})

    def append_execution_log(self, execution_id, node_id, kind, status, payload):
        self.logs.append({"execution_id": execution_id, "node_id": node_id,
                          "kind": kind, "status": status, "payload": payload})

    def update_execution_status(self, execution_id, status):
        self.executions.setdefault(execution_id, {})["status"] = status


@pytest.fixture()
def memdb(monkeypatch):
    mem = _MemDB()
    monkeypatch.setattr(ee.db, "create_execution", mem.create_execution)
    monkeypatch.setattr(ee.db, "append_execution_log", mem.append_execution_log)
    monkeypatch.setattr(ee.db, "update_execution_status", mem.update_execution_status)
    return mem


@pytest.fixture()
def fast_healing(monkeypatch):
    """Self-healing tanpa jaringan + tanpa backoff (tes deterministik)."""
    monkeypatch.setattr(sh, "TRANSIENT_DELAYS_MS", (0, 0, 0, 0, 0))
    monkeypatch.setattr(sh, "RATE_LIMIT_DELAYS_MS", (0, 0, 0, 0, 0))

    class _Fast(sh.SelfHealingAgent):
        def __init__(self, **kw):
            kw.setdefault("search_enabled", False)
            super().__init__(**kw)

    monkeypatch.setattr(ee, "SelfHealingAgent", _Fast)


# Flow: trigger -> mcp (provider "http"). Cukup untuk menguji jalur provider.
MCP_FLOW = {
    "nodes": [
        {"id": "t", "type": "trigger",
         "data": {"kind": "trigger", "config": {"event_name": "webhook"}}},
        {"id": "m", "type": "mcp-tool",
         "data": {"kind": "mcp",
                  "config": {"provider": "http", "url": "https://example.com/x"}}},
    ],
    "edges": [{"id": "e1", "source": "t", "target": "m"}],
}

AGENT_FLOW = {
    "nodes": [
        {"id": "t", "type": "trigger",
         "data": {"kind": "trigger", "config": {"event_name": "webhook"}}},
        {"id": "a", "type": "agent",
         "data": {"kind": "agent", "config": {"prompt": "halo", "model": "universal"}}},
    ],
    "edges": [{"id": "e1", "source": "t", "target": "a"}],
}


# ===========================================================================
# BUG-B1 — webhook phantom execution
# ===========================================================================
api_server = pytest.importorskip("api_server")


def _run_webhook(monkeypatch, mem=None, **kwargs):
    """Jalankan `_run_webhook_dag` dengan runner & status-recorder yang dipantau."""
    calls: list[dict] = []
    statuses: list[tuple] = []

    async def _spy(workflow_id, flow_data, trigger_input=None,
                   execution_id=None, owner_email=""):
        calls.append({"workflow_id": workflow_id, "execution_id": execution_id,
                      "owner_email": owner_email})
        return {"execution_id": execution_id, "status": "completed"}

    monkeypatch.setattr(api_server.engine, "execute_workflow_async", _spy)
    monkeypatch.setattr(api_server.db, "update_execution_status",
                        lambda eid, st: statuses.append((eid, st)))
    asyncio.run(api_server._run_webhook_dag(
        kwargs.get("workflow_id", "wf-b1"),
        kwargs.get("flow_data", {"nodes": [], "edges": []}),
        kwargs.get("trigger_input", {"_execution_id": "EX-B1"})))
    return calls, statuses


def test_b1_webhook_meneruskan_execution_id_ke_runner(monkeypatch):
    """Inti BUG-B1: id yang dibuat webhook HARUS sampai ke runner."""
    calls, statuses = _run_webhook(monkeypatch)
    assert calls and calls[0]["execution_id"] == "EX-B1", (
        "execution_id tidak diteruskan -> log akan menempel di baris hantu")
    assert statuses == [("EX-B1", "completed")], (
        "status akhir harus ditulis pada id yang SAMA")


def test_b1_temuan_f6_webhook_tidak_meneruskan_owner_email(monkeypatch):
    """F-6 (di luar brief, sengaja TIDAK diubah): webhook tidak kirim owner_email.

    Konsekuensi yang harus diketahui sebelum launch: node MCP ber-kredensial
    pada workflow webhook TIDAK bisa membaca token milik user, dan node agent
    di jalur ini TIDAK termeter (kuota free tidak terpakai). Mengubahnya adalah
    keputusan produk/billing, jadi perilakunya dikunci di sini supaya tidak
    berubah diam-diam.
    """
    calls, _ = _run_webhook(monkeypatch)
    assert calls[0]["execution_id"] == "EX-B1"
    assert not calls[0]["owner_email"], (
        "jalur webhook diharapkan tetap tanpa owner_email (lihat F-6)")


def test_b1_status_mengikuti_hasil_runner_bukan_hardcode(monkeypatch):
    """Eksekusi yang gagal TIDAK boleh ditulis "completed"."""
    statuses: list[tuple] = []

    async def _spy(*a, **k):
        return {"status": "error", "error": "boom"}

    monkeypatch.setattr(api_server.engine, "execute_workflow_async", _spy)
    monkeypatch.setattr(api_server.db, "update_execution_status",
                        lambda eid, st: statuses.append((eid, st)))
    asyncio.run(api_server._run_webhook_dag(
        "wf", {"nodes": [], "edges": []}, {"_execution_id": "EX-B1-ERR"}))
    assert statuses == [("EX-B1-ERR", "error")]


def test_b1_id_dibuat_bila_trigger_input_tidak_membawanya(monkeypatch):
    """Tanpa `_execution_id`, runner tetap menerima id yang konsisten."""
    calls, statuses = _run_webhook(
        monkeypatch, trigger_input={"headers": {}, "body": {}})
    eid = calls[0]["execution_id"]
    assert eid and statuses[0][0] == eid


def test_b1_webhook_produksi_menghasilkan_log_pada_id_yang_sama(memdb, fast_healing,
                                                                monkeypatch):
    """Regresi end-to-end: webhook -> log TIDAK nol pada id yang dikembalikan.

    Inilah bukti "3+ logs tercatat" dari brief, dijalankan lewat jalur
    `_run_webhook_dag` yang sebenarnya (runner asli, hanya DB yang di-memory).
    """
    monkeypatch.setattr(api_server.engine, "execute_workflow_async",
                        ee.execute_workflow_async)
    monkeypatch.setattr(api_server.engine.db, "create_execution", memdb.create_execution)
    monkeypatch.setattr(api_server.engine.db, "append_execution_log", memdb.append_execution_log)
    monkeypatch.setattr(api_server.engine.db, "update_execution_status", memdb.update_execution_status)

    asyncio.run(api_server._run_webhook_dag(
        "wf-b1-e2e", MCP_FLOW,
        {"_execution_id": "EX-B1-E2E", "headers": {}, "body": {"x": 1}}))

    logs = [l for l in memdb.logs if l["execution_id"] == "EX-B1-E2E"]
    assert len(logs) >= 3, f"harus >=3 log pada id yang sama, dapat {len(logs)}"
    assert {l["node_id"] for l in logs} == {"t", "m"}
    assert memdb.executions["EX-B1-E2E"]["status"] in ("completed", "error")


# ===========================================================================
# BUG-B2 — silent failure detection
# ===========================================================================
# Lima jenis kegagalan yang diminta brief, dengan teks error seperti yang
# benar-benar muncul dari penyedia/tool (lihat tools.http_request,
# provider_registry.run, mcp_gateway.client).
B2_FAILURES = {
    "http_404": "[RuntimeError] HTTP 404 dari example.com: not found",
    "http_500": "[RuntimeError] HTTP 500 dari example.com: server error",
    "timeout": "[RuntimeError] Permintaan HTTP gagal (ConnectTimeout).",
    "dns": "[RuntimeError] Permintaan HTTP gagal (ConnectError) - "
           "temporary failure in name resolution (dns)",
    "invalid_json": "[JSONDecodeError] Expecting value: line 1 column 1 (char 0)",
}


@pytest.mark.parametrize("case,error_text", sorted(B2_FAILURES.items()))
def test_b2_status_error_provider_menandai_node_dan_eksekusi_error(
        case, error_text, memdb, fast_healing, monkeypatch):
    """5 jenis kegagalan -> node `error`, eksekusi `error`, log `error`."""
    async def _fail(provider, cfg, params, email=""):
        return {"status": "error", "provider": provider,
                "tool": "http_request", "error": error_text}

    monkeypatch.setattr(ee.provider_registry, "run_async", _fail)

    res = asyncio.run(ee.execute_workflow_async(
        "wf-b2", MCP_FLOW, {}, execution_id="EX-B2"))

    assert res["status"] == "error", f"[{case}] eksekusi harus error: {res}"
    assert memdb.executions["EX-B2"]["status"] == "error", (
        f"[{case}] baris executions harus error")
    node_logs = [l for l in memdb.logs if l["node_id"] == "m"]
    assert node_logs, f"[{case}] node m tidak terlog"
    assert node_logs[-1]["status"] == "error", (
        f"[{case}] node m harus error, dapat {node_logs[-1]['status']}")


@pytest.mark.parametrize("status", ["needs_credential", "needs_configuration"])
def test_b2_status_non_sukses_lain_juga_gagal(status, memdb, fast_healing, monkeypatch):
    """Kredensial/konfigurasi kurang = kegagalan, bukan "completed"."""
    async def _fail(provider, cfg, params, email=""):
        return {"status": status, "provider": provider, "tool": "x",
                "error": f"status {status}"}

    monkeypatch.setattr(ee.provider_registry, "run_async", _fail)
    res = asyncio.run(ee.execute_workflow_async("wf", MCP_FLOW, {},
                                                execution_id="EX-B2B"))
    assert res["status"] == "error"


@pytest.mark.parametrize("text,expected", [
    ("[RuntimeError] HTTP 404 dari example.com: not found", "not_found"),
    ("[RuntimeError] HTTP 500 dari example.com: server error", "server_5xx"),
    ("[RuntimeError] Permintaan HTTP gagal (ConnectTimeout).", "network"),
    ("[RuntimeError] Permintaan HTTP gagal (ReadTimeout).", "network"),
    ("[RuntimeError] Permintaan HTTP gagal (ConnectError).", "network"),
    ("[RuntimeError] Permintaan HTTP gagal (ConnectError) - "
     "temporary failure in name resolution (dns)", "network"),
    ("[JSONDecodeError] Expecting value: line 1 column 1 (char 0)", "unknown"),
])
def test_b2_klasifikasi_healing_benar(text, expected):
    """Setiap jenis kegagalan harus dipetakan ke kategori yang tepat.

    `ConnectTimeout` (CamelCase) dulu jatuh ke `unknown` karena `\\btimeout\\b`
    tidak punya batas kata di dalam "ConnectTimeout" -> hanya 2 percobaan
    padahal jelas transien.
    """
    assert sh.classify_error(text).name == expected


def test_b2_tool_sukses_tetap_completed(memdb, fast_healing, monkeypatch):
    """Kontrol positif: jangan sampai semua node jadi merah."""
    async def _ok(provider, cfg, params, email=""):
        return {"status": "success", "provider": provider,
                "tool": "http_request", "result": "HTTP 200 dari example.com: ok"}

    monkeypatch.setattr(ee.provider_registry, "run_async", _ok)
    res = asyncio.run(ee.execute_workflow_async("wf", MCP_FLOW, {},
                                                execution_id="EX-B2-OK"))
    assert res["status"] == "completed"
    assert memdb.executions["EX-B2-OK"]["status"] == "completed"


def test_b2_http_request_menaikkan_error_pada_4xx_dan_5xx(monkeypatch):
    """`tools.http_request` dulu memulangkan string "HTTP 404 ..." sebagai SUKSES."""
    import httpx

    class _R:
        def __init__(self, code):
            self.status_code = code
            self.text = '{"error":"nope"}'

    for code in (400, 404, 500, 503):
        monkeypatch.setattr(httpx, "request", lambda *a, _c=code, **k: _R(_c))
        with pytest.raises(RuntimeError) as ei:
            tools.http_request(url="https://example.com/x", method="GET")
        assert str(code) in str(ei.value), (code, ei.value)


def test_b2_http_request_sukses_tetap_string(monkeypatch):
    import httpx

    class _R:
        status_code = 200
        text = '{"ok":true}'

    monkeypatch.setattr(httpx, "request", lambda *a, **k: _R())
    out = tools.http_request(url="https://example.com/x", method="GET")
    assert out.startswith("HTTP 200 dari example.com")


def test_b2_analytics_menghitung_error(monkeypatch):
    """/analytics membaca `executions.status`; status `error` wajib terhitung."""
    class _R:
        def __init__(self, data=None, count=None):
            self.data = data or []
            self.count = count

    class _Q:
        def __init__(self, rows):
            self._rows = rows

        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def in_(self, *a, **k):
            return self

        def order(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        def execute(self):
            return _R(self._rows, len(self._rows))

    class _C:
        def table(self, name):
            if name == "workflows":
                return _Q([{"id": "wf-1"}])
            if name == "executions":
                return _Q([{"id": "EX-1", "workflow_id": "wf-1",
                            "status": "error", "created_at": "2026-10-07"}])
            return _Q([])

    monkeypatch.setattr(database, "is_configured", lambda: True)
    monkeypatch.setattr(database, "_get_write_client", lambda: _C())
    stats = database.execution_analytics("uid-1")
    assert stats["error"] == 1 and stats["completed"] == 0, stats


# ===========================================================================
# F-2 — redaksi data sensitif di execution_logs
# ===========================================================================
JWT = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
       + "A" * 140 + "." + "B" * 60)


def test_f2_jwt_dan_authorization_header_diredaksi():
    payload = {
        "headers": {"authorization": f"Bearer {JWT}",
                    "content-type": "application/json",
                    "user-agent": "curl/8"},
        "body": {"token": JWT, "note": f"pakai {JWT} ya", "n": 7},
    }
    row = database.execution_log_row("EX", "t", "trigger", "completed", payload)
    blob = json.dumps(row)
    assert JWT not in blob, "JWT masih tersimpan apa adanya"
    assert "eyJhbGci" not in blob
    assert "[REDACTED" in blob
    # Data non-sensitif tetap utuh (redaksi tidak boleh merusak laporan).
    assert row["output_data"]["headers"]["user-agent"] == "curl/8"
    assert row["output_data"]["body"]["n"] == 7


def test_f2_error_message_ikut_diredaksi():
    row = database.execution_log_row(
        "EX", "m", "mcp", "error",
        {"error": f"gagal kirim, header Authorization: Bearer {JWT}"})
    assert JWT not in str(row.get("error_message") or "")
    assert JWT not in json.dumps(row)


def test_f2_pola_token_provider_lain():
    cases = {
        "sk-": "sk-" + "a" * 30,
        "xoxb-": "xoxb-" + "1" * 20,
        "AKIA": "AKIA" + "A" * 16,
        "ghp_": "ghp_" + "z" * 30,
        "bot": "123456789:" + "q" * 35,
        "ya29": "ya29." + "y" * 30,
    }
    for name, secret in cases.items():
        out = database.redact_sensitive({"v": f"nilai: {secret}"})
        assert secret not in out["v"], f"pola {name} tidak diredaksi"


def test_f2_redaksi_tidak_mutasi_input():
    src = {"authorization": f"Bearer {JWT}"}
    snapshot = json.dumps(src)
    database.redact_sensitive(src)
    assert json.dumps(src) == snapshot, "input tidak boleh dimutasi"


def test_f2_redact_log_row_menandai_baris_yang_berubah():
    dirty = {"id": 1, "execution_id": "EX", "node_id": "t",
             "output_data": {"headers": {"authorization": f"Bearer {JWT}"}}}
    clean = {"id": 2, "execution_id": "EX", "node_id": "m",
             "output_data": {"result": "ok"}}
    new_dirty, changed_dirty = database.redact_log_row(dirty)
    new_clean, changed_clean = database.redact_log_row(clean)
    assert changed_dirty is True and JWT not in json.dumps(new_dirty)
    assert changed_clean is False and new_clean == clean


def test_f2_tidak_ada_jalur_tulis_yang_melewatkan_redaksi(monkeypatch):
    """Log yang benar-benar ditulis mesin (Trigger webhook) tidak boleh bocor.

    Memakai `database.append_execution_log` ASLI (bukan stub) supaya yang diuji
    benar-benar titik tulis produksi: `execution_log_row` -> redaksi -> INSERT.
    """
    inserted: list[dict] = []

    class _Q:
        def insert(self, row):
            inserted.append(row)
            return self

        def execute(self):
            class _R:
                data: list = []
                count = 0
            return _R()

    class _C:
        def table(self, name):
            return _Q()

    monkeypatch.setattr(database, "is_configured", lambda: True)
    monkeypatch.setattr(database, "_get_write_client", lambda: _C())
    monkeypatch.setattr(ee.db, "create_execution", lambda *a, **k: None)
    monkeypatch.setattr(ee.db, "update_execution_status", lambda *a, **k: None)
    monkeypatch.setattr(ee.provider_registry, "run_async",
                        lambda *a, **k: {"status": "success", "provider": "http",
                                         "tool": "http_request", "result": "ok"})

    trigger_input = {"headers": {"authorization": f"Bearer {JWT}"},
                     "body": {"token": JWT}}
    asyncio.run(ee.execute_workflow_async("wf-f2", MCP_FLOW, trigger_input,
                                          execution_id="EX-F2"))

    assert inserted, "tidak ada baris execution_logs yang ditulis"
    blob = json.dumps(inserted)
    assert JWT not in blob, "payload Trigger bocor ke execution_logs"
    assert "eyJhbGci" not in blob
    assert "[REDACTED" in blob


# ===========================================================================
# F-3 — meter persist (ISO timestamp + jangan telan error)
# ===========================================================================
def test_f3_iso_dari_epoch_dan_sebaliknya():
    ts = 1_700_000_000.5
    iso = ee._iso_from_ts(ts)
    assert iso.startswith("2023-11-14") and iso.endswith("+00:00"), iso
    assert ee._ts_from_db(iso) == pytest.approx(ts)
    assert ee._iso_from_ts(None) is None
    assert ee._iso_from_ts(iso) == iso, "ISO tidak boleh dikonversi ulang"
    assert ee._ts_from_db(None) is None
    assert ee._ts_from_db("") is None
    assert ee._ts_from_db("bukan-timestamp") is None
    assert ee._ts_from_db(1_700_000_000.5) == pytest.approx(ts)


def _fake_usage_client(captured, existing=False):
    class _R:
        def __init__(self, data):
            self.data = data
            self.count = len(data)

    class _Q:
        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        def update(self, row):
            captured["op"] = "update"
            captured["row"] = row
            return self

        def insert(self, row):
            captured["op"] = "insert"
            captured["row"] = row
            return self

        def execute(self):
            return _R([{"email": "u@test.dev"}] if existing else [])

    class _C:
        def table(self, name):
            return _Q()

    return _C()


def test_f3_meter_save_menulis_iso_bukan_float(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(database, "_get_write_client",
                        lambda: _fake_usage_client(captured))
    ee._METER.clear()
    ee._METER["u@test.dev"] = {"free_count": 3, "plus_count": 0,
                               "last_reset_free": 1_700_000_000.0,
                               "last_reset_plus": None, "credit": 0.0}
    ee._meter_save("u@test.dev")
    row = captured["row"]
    assert isinstance(row["last_reset_free"], str), (
        "kolom timestamp wajib ISO 8601, bukan float epoch (22007)")
    assert row["last_reset_free"].startswith("2023-11-14")
    assert row["last_reset_plus"] is None
    assert row["free_chat_count"] == 3


def test_f3_meter_save_melempar_bukan_menelan(monkeypatch):
    def _boom():
        raise RuntimeError("22007 invalid input syntax for type timestamp")

    monkeypatch.setattr(database, "_get_write_client", _boom)
    ee._METER.clear()
    ee._METER["x@test.dev"] = {"free_count": 1, "plus_count": 0,
                               "last_reset_free": 1_700_000_000.0,
                               "last_reset_plus": None, "credit": 0.0}
    with pytest.raises(ee.MeterPersistenceError) as ei:
        ee._meter_save("x@test.dev")
    assert "22007" in str(ei.value)
    assert ei.value.email == "x@test.dev"


def test_f3_meter_load_menormalkan_iso_ke_epoch(monkeypatch):
    """Kolom timestamp dibaca balik sebagai epoch supaya `float(lr)` aman."""
    class _R:
        data = [{"free_chat_count": 4, "plus_chat_count": 1,
                 "last_reset_free": "2023-11-14T22:13:20+00:00",
                 "last_reset_plus": "2023-11-14T22:13:20.500000+00:00",
                 "credit_balance": 2.5}]

    class _Q:
        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        def execute(self):
            return _R()

    class _C:
        def table(self, name):
            return _Q()

    monkeypatch.setattr(database, "_get_client", lambda: _C())
    ee._METER.clear()
    m = ee._meter_load("u@test.dev")
    assert isinstance(m["last_reset_free"], float)
    assert m["last_reset_free"] == pytest.approx(1_700_000_000.0)
    # `guard_execution` melakukan `float(lr)` - tidak boleh meledak.
    assert float(m["last_reset_free"]) > 0
    assert m["free_count"] == 4 and m["credit"] == 2.5


# ===========================================================================
# F-1 — kontradiksi gembok tier FREE
# ===========================================================================
def test_f1_tier_free_tidak_diblokir_saldo_nol(monkeypatch):
    """User gratis (tanpa baris user_balances -> saldo 0.0) harus tetap jalan."""
    monkeypatch.setattr(ee.db, "get_balance", lambda email: 0.0)
    monkeypatch.setattr(ee.db, "vault_get", lambda *a, **k: None)
    monkeypatch.setattr(ee, "_meter_load", lambda email: ee._meter_data(email))
    monkeypatch.setattr(ee, "_meter_save", lambda email: None)

    async def _reason(prompt, ctx, config=None):
        return {"status": "success", "reply": "halo", "model": "gemma-4",
                "usage": {}, "cost_usd": 0.0}

    graph = ee.FlowGraph(**AGENT_FLOW)
    orch = ee.StatefulOrchestrator(
        graph, owner_email="gratis@test.dev", reasoner=_reason,
        healing_factory=lambda: ee.SelfHealingAgent(search_enabled=False))
    asyncio.run(orch.run())

    out = orch.outputs["a"]
    assert out.get("agent_status") != "blocked_no_balance", out
    assert orch.states["a"] == "completed", orch.states


def test_f1_tier_free_tetap_dibatasi_jendela(monkeypatch):
    """Perbaikan F-1 TIDAK menghapus batas gratis (10 chat / 22 jam)."""
    monkeypatch.setattr(
        ee, "_meter_load",
        lambda email: {"free_count": ee._FREE_LIMIT, "plus_count": 0,
                       "last_reset_free": ee._now_ts(),
                       "last_reset_plus": None, "credit": 0.0})
    allowed, code, msg = ee.guard_execution({}, "gratis@test.dev")
    assert allowed is False and code == 403, (allowed, code, msg)


def test_f1_jatah_kredit_bulanan_tier_free_terdefinisi():
    assert ee._FREE_MONTHLY_CREDIT == 100.0


# ===========================================================================
# F-4 — kebocoran detail upstream pada 500 /chat
# ===========================================================================
@pytest.fixture()
def chat_client(monkeypatch):
    """Klien /chat dengan auth + DB di-mock (pola test_chat_rate_limit)."""
    import rate_limit
    from fastapi.testclient import TestClient

    monkeypatch.setattr(api_server.security, "get_current_user",
                        lambda auth: {"email": "f4@test.dev", "id": "uid-f4"})
    monkeypatch.setattr(api_server.db, "get_or_create_user",
                        lambda *a, **k: {"email": "f4@test.dev", "tier": "free"})
    monkeypatch.setattr(api_server.db, "find_user_message_by_request", lambda *a: None)
    monkeypatch.setattr(api_server.db, "create_session", lambda *a, **k: {"id": "s-f4"})
    monkeypatch.setattr(api_server, "load_history", lambda *a, **k: [])
    monkeypatch.setattr(api_server.db, "add_message", lambda *a, **k: True)
    monkeypatch.setattr(api_server.db, "check_quota",
                        lambda e, m, t: (True, {"bucket": "gemma", "used": 0,
                                                "limit": 100, "remaining": 100}))
    monkeypatch.setattr(api_server.db, "increment_quota", lambda *a, **k: None)
    monkeypatch.setattr(api_server.db, "quota_status",
                        lambda e, t: {"used_total": 0, "limit_total": 100})
    monkeypatch.setattr(rate_limit, "chat_limiter",
                        rate_limit.SlidingWindowLimiter(50, 60))
    monkeypatch.setattr(rate_limit, "request_hourly_limiter",
                        rate_limit.SlidingWindowLimiter(50, 3600))
    return TestClient(api_server.app)


def _post_chat(client):
    return client.post("/chat", json={"prompt": "halo"},
                       headers={"Authorization": "Bearer x"})


def test_f4_500_tidak_membocorkan_detail_upstream(chat_client, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError(
            "ClientError: 400 INVALID_ARGUMENT. {'error': {'code': 400, "
            "'message': 'API key not valid', 'status': 'INVALID_ARGUMENT'}}")

    monkeypatch.setattr(api_server, "_agentic_run_direct", _boom)
    r = _post_chat(chat_client)
    assert r.status_code == 500, r.text
    detail = str(r.json().get("detail") or "")
    assert detail.strip(), "pesan harus tetap ada (bukan kosong)"
    for leak in ("INVALID_ARGUMENT", "ClientError", "RuntimeError",
                 "API key not valid", "Traceback"):
        assert leak not in detail, f"detail 500 membocorkan '{leak}': {detail!r}"


def test_f4_500_pesan_manusiawi(chat_client, monkeypatch):
    monkeypatch.setattr(api_server, "_agentic_run_direct",
                        lambda *a, **k: (_ for _ in ()).throw(
                            ValueError("boom internal")))
    r = _post_chat(chat_client)
    assert r.status_code == 500
    assert "coba lagi" in r.json()["detail"].lower()
