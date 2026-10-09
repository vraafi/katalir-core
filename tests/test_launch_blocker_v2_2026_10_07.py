"""test_launch_blocker_v2_2026_10_07.py — verifikasi brief lanjutan.

Brief: *"# FIX BUG-B3 (AGENT SILENT FAILURE) + S8 (HEALING SPEED) +
STABILKAN GATEWAY"* (7 Okt 2026).

Satu kelas bug per blok:

  BUG-B3  KEGAGALAN SENYAP JALUR AGENT - `_exec_agent` mengembalikan payload
          `agent_status` apa adanya saat LLM gagal, sehingga `_run_node`
          mencatat node "completed" (kanvas hijau, `/analytics` errors:0,
          laporan "berhasil ... 0 gagal"). Kelas bug yang SAMA dengan BUG-B2,
          tetapi pada jalur agent (bukan tool/MCP).

  S8      HEALING TERLALU LAMA - endpoint mati di-retry 5x dengan timeout 20s
          + backoff (0,1,2,4,8)s -> node masih `retrying` setelah 420s dan
          eksekusi menggantung `pending`. Sekarang: maks 3 percobaan, backoff
          1s/2s/4s, timeout 10s, anggaran wall-clock 30s, `connection refused`
          berhenti di 2 percobaan.

  GATEWAY Opsi C - ketika gateway self-hosted terkonfigurasi, `candidates`
          HANYA berisi kandidat gateway -> gateway turun = 0/5 agent sukses.
          Sekarang ada rantai cadangan: gateway -> Gemini pool -> provider
          langsung (groq/nvidia/github) -> raise.

  F-6     WEBHOOK OWNER_EMAIL (Opsi A) - jalur webhook meneruskan email
          pemilik workflow supaya node MCP ber-kredensial bisa resolve token.
"""
from __future__ import annotations

import asyncio

import pytest

import agent_reasoner as ar
import api_server
import database
import execution_engine as ee
import self_healing as sh
import tools


# ---------------------------------------------------------------------------
# DB tiruan (in-memory)
# ---------------------------------------------------------------------------
class _MemDB:
    def __init__(self):
        self.executions: dict[str, dict] = {}
        self.logs: list[dict] = []

    def create_execution(self, execution_id, workflow_id, flow_data):
        self.executions.setdefault(
            execution_id, {"workflow_id": workflow_id, "status": "pending"})

    def append_execution_log(self, execution_id, node_id, kind, status,
                            payload, **kwargs):
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
    monkeypatch.setattr(sh, "REFUSED_DELAYS_MS", (0, 0))

    class _Fast(sh.SelfHealingAgent):
        def __init__(self, **kw):
            kw.setdefault("search_enabled", False)
            super().__init__(**kw)

    monkeypatch.setattr(ee, "SelfHealingAgent", _Fast)


def _agent_flow(config: dict | None = None, nid: str = "a") -> dict:
    return {
        "nodes": [
            {"id": "t", "type": "trigger",
             "data": {"kind": "trigger", "config": {"event_name": "webhook"}}},
            {"id": nid, "type": "agent",
             "data": {"kind": "agent",
                      "config": config or {"prompt": "halo", "model": "universal"}}},
        ],
        "edges": [{"id": "e1", "source": "t", "target": nid}],
    }


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


def _run_agent_with(reasoner, config=None, owner=""):
    orch = ee.StatefulOrchestrator(
        ee.FlowGraph(**_agent_flow(config)), owner_email=owner,
        reasoner=reasoner,
        healing_factory=lambda: ee.SelfHealingAgent(search_enabled=False))
    return orch, asyncio.run(orch.run())


# ===========================================================================
# BUG-B3 — kegagalan senyap jalur AGENT
# ===========================================================================
# Lima jenis kegagalan agent yang diminta brief, dengan bentuk hasil yang
# benar-benar dikembalikan `agent_reasoner.run_agent`.
B3_AGENT_FAILURES = {
    "http_500": {"status": "error",
                 "error": "[InternalServerError] Internal Server Error"},
    "content_null": {"status": "error",
                     "error": "respons Gemini kosong (content:null)"},
    "timeout": {"status": "error",
                "error": "[ReadTimeout] Permintaan ke LLM timeout"},
    "error_field": {"status": "error", "error": "ClientError: 400 INVALID_ARGUMENT"},
    "malformed_json": {"status": "error",
                       "error": "[JSONDecodeError] Expecting value: line 1 col 1"},
}


@pytest.mark.parametrize("case,result", sorted(B3_AGENT_FAILURES.items()))
def test_b3_agent_gagal_menandai_node_dan_eksekusi_error(
        case, result, memdb, fast_healing):
    """5 jenis kegagalan agent -> node `error`, eksekusi `error`, log `error`."""
    async def _reason(prompt, ctx, config=None):
        return dict(result)

    res = _b3_run(memdb, fast_healing, _reason, "EX-B3")

    assert res["status"] == "error", f"[{case}] eksekusi harus error: {res}"
    assert memdb.executions["EX-B3"]["status"] == "error", (
        f"[{case}] baris executions harus error")
    node_logs = [l for l in memdb.logs if l["node_id"] == "a"]
    assert node_logs, f"[{case}] node a tidak terlog"
    assert node_logs[-1]["status"] == "error", (
        f"[{case}] node a harus error, dapat {node_logs[-1]['status']}")


def _b3_run(memdb, fast_healing, reasoner, eid):
    """Jalankan `execute_workflow_async` dengan reasoner yang disuntikkan.

    `execute_workflow_async` membangun orkestrator sendiri tanpa `reasoner`,
    jadi subclass kecil di bawah dipakai supaya LLM-nya bisa di-stub (tanpa
    jaringan) TANPA mengubah jalur produksi.
    """
    orig = ee.StatefulOrchestrator

    class _Orch(orig):  # type: ignore[misc, valid-type]
        def __init__(self, graph, trigger_input=None, owner_email="", **kw):
            kw["reasoner"] = reasoner
            kw.setdefault("healing_factory",
                          lambda: ee.SelfHealingAgent(search_enabled=False))
            super().__init__(graph, trigger_input=trigger_input,
                             owner_email=owner_email, **kw)

    ee.StatefulOrchestrator = _Orch
    try:
        return asyncio.run(ee.execute_workflow_async(
            "wf-b3", _agent_flow(), {}, execution_id=eid))
    finally:
        ee.StatefulOrchestrator = orig


def test_b3_agent_sukses_tetap_completed(memdb, fast_healing):
    """Kontrol positif: agent sukses JANGAN ikut memerah."""
    async def _ok(prompt, ctx, config=None):
        return {"status": "success", "reply": "halo", "model": "gemini-2.5-flash",
                "usage": {}, "cost_usd": 0.0}

    res = _b3_run(memdb, fast_healing, _ok, "EX-B3-OK")
    assert res["status"] == "completed", res
    assert memdb.executions["EX-B3-OK"]["status"] == "completed"


def test_b3_error_dinaikkan_sebagai_AgentExecutionError():
    """Exception harus bertipe `AgentExecutionError` (bisa diklasifikasi)."""
    async def _err(prompt, ctx, config=None):
        return {"status": "error", "error": "[InternalServerError] boom"}

    orch = ee.StatefulOrchestrator(
        ee.FlowGraph(**_agent_flow()), reasoner=_err,
        healing_factory=lambda: ee.SelfHealingAgent(search_enabled=False))
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(orch.run())
    # `run()` membungkus kegagalan node jadi RuntimeError; tipe aslinya ada di
    # `__cause__` (raise ... from res) dan itu yang dibaca self-healing.
    cause = ei.value.__cause__
    assert isinstance(cause, ee.AgentExecutionError), (
        f"dapat {type(cause).__name__}: {cause}")
    # Pesan WAJIB memuat teks error asli supaya klasifikasi healing tepat.
    assert "InternalServerError" in str(cause)
    assert orch.states["a"] == "error"


def test_b3_skipped_tanpa_key_juga_gagal(memdb, fast_healing):
    """`status: skipped` (tanpa API key) = kegagalan, bukan "completed"."""
    async def _skip(prompt, ctx, config=None):
        return {"status": "skipped", "error": "Tidak ada API key AI di environment."}

    res = _b3_run(memdb, fast_healing, _skip, "EX-B3-SKIP")
    assert res["status"] == "error", res


def test_b3_saldo_habis_juga_error(memdb, fast_healing, monkeypatch):
    """Gembok saldo Plus = kegagalan node, bukan payload diam-diam."""
    monkeypatch.setattr(ee.db, "get_balance", lambda email: 0.0)
    monkeypatch.setattr(ee.db, "vault_get", lambda *a, **k: None)

    async def _ok(prompt, ctx, config=None):
        return {"status": "success", "reply": "x", "usage": {}, "cost_usd": 0.0}

    res = _b3_run(memdb, fast_healing, _ok, "EX-B3-BAL")
    # Model universal -> cek saldo tidak berlaku (hanya Plus/deepseek-flash),
    # jadi ini harus SUKSES. Bukti F-1 tidak regresi.
    assert res["status"] == "completed", res


def test_b3_supervisor_gagal_juga_error():
    """Supervisor yang gagal ber-LLM TIDAK boleh "completed"."""
    async def _err(prompt, ctx, config=None):
        return {"status": "error", "error": "[InternalServerError] boom"}

    flow = _agent_flow({"prompt": "koordinasi", "role": "supervisor",
                        "delegates": []})
    orch = ee.StatefulOrchestrator(
        ee.FlowGraph(**flow), reasoner=_err,
        healing_factory=lambda: ee.SelfHealingAgent(search_enabled=False))
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(orch.run())
    assert isinstance(ei.value.__cause__, ee.AgentExecutionError), (
        f"dapat {type(ei.value.__cause__).__name__}")
    assert orch.states["a"] == "error"


def test_b3_sub_agent_gagal_tidak_membatalkan_supervisor():
    """Delegasi yang gagal dicatat jujur, supervisor tetap lanjut."""
    calls = {"n": 0}

    async def _reason(prompt, ctx, config=None):
        calls["n"] += 1
        if "SUPERVISOR" in prompt or "supervisor" in prompt.lower():
            # Putaran 1: minta delegasi; putaran 2: jawaban akhir.
            if calls["n"] <= 1:
                return {"status": "success",
                        "reply": '[DELEGATE: agent_id=sub task="cek"]'}
            return {"status": "success", "reply": "selesai", "usage": {}}
        return {"status": "error", "error": "[InternalServerError] sub mati"}

    flow = {
        "nodes": [
            {"id": "t", "type": "trigger",
             "data": {"kind": "trigger", "config": {}}},
            {"id": "sup", "type": "agent",
             "data": {"kind": "agent",
                      "config": {"prompt": "SUPERVISOR koordinasi",
                                 "role": "supervisor", "delegates": ["sub"]}}},
            {"id": "sub", "type": "agent",
             "data": {"kind": "agent", "config": {"prompt": "sub"}}},
        ],
        # sub HARUS punya predecessor sup: node tanpa pred dianggap siap di
        # gelombang pertama (akan jalan sendiri di luar delegasi).
        "edges": [{"id": "e1", "source": "t", "target": "sup"},
                  {"id": "e2", "source": "sup", "target": "sub"}],
    }
    orch = ee.StatefulOrchestrator(
        ee.FlowGraph(**flow), reasoner=_reason,
        healing_factory=lambda: ee.SelfHealingAgent(search_enabled=False))
    asyncio.run(orch.run())
    # Sub-agent gagal -> node-nya jujur `error` (bukan "completed").
    assert orch.states["sub"] == "error", orch.states
    assert orch.outputs["sub"].get("status") == "error"


def test_b3_analytics_menghitung_error(monkeypatch):
    """`/analytics` errors bertambah ketika eksekusi `error` (BUG-B3)."""
    class _R:
        def __init__(self, rows):
            self.data = rows
            self.count = len(rows)

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
            return _R(self._rows)

    class _C:
        def table(self, name):
            if name == "workflows":
                return _Q([{"id": "wf-1"}])
            if name == "executions":
                return _Q([{"id": "EX-B3", "workflow_id": "wf-1",
                            "status": "error", "created_at": "2026-10-07"}])
            return _Q([])

    monkeypatch.setattr(database, "is_configured", lambda: True)
    monkeypatch.setattr(database, "_get_write_client", lambda: _C())
    stats = database.execution_analytics("uid-1")
    assert stats["error"] == 1 and stats["completed"] == 0, stats


# ===========================================================================
# S8 — healing endpoint mati harus cepat (<60s)
# ===========================================================================
def test_s8_connection_refused_fast_fail_kurang_dari_60s():
    """Endpoint menolak koneksi -> node `error` jauh di bawah 60s."""
    import time as _t

    calls = {"n": 0}

    async def _dead(orch, node, inp):
        calls["n"] += 1
        raise RuntimeError(
            "Permintaan HTTP gagal (connection refused: ConnectError).")

    orch = ee.StatefulOrchestrator(
        ee.FlowGraph(**_agent_flow()), owner_email="",
        healing_factory=lambda: ee.SelfHealingAgent(search_enabled=False))
    orch.EXECUTORS = dict(orch.EXECUTORS)      # jangan mutasi dict kelas
    orch.EXECUTORS[ee.NodeKind.AGENT] = _dead

    t0 = _t.monotonic()
    with pytest.raises(Exception):
        asyncio.run(orch.run())
    elapsed = _t.monotonic() - t0

    assert calls["n"] == 3, f"harap 2 percobaan + 1 escalate, dapat {calls['n']}"
    assert orch.states["a"] == "error"
    assert elapsed < 60, f"harus <60s, terukur {elapsed:.1f}s"


def test_s8_anggaran_wall_clock_menghentikan_retry(monkeypatch):
    """Bila anggaran healing habis, JANGAN menggantung: paksa escalate."""
    monkeypatch.setenv("HEALING_BUDGET_SEC", "0")
    calls = {"n": 0}

    async def _dead(orch, node, inp):
        calls["n"] += 1
        raise RuntimeError("503 Service Unavailable")

    orch = ee.StatefulOrchestrator(
        ee.FlowGraph(**_agent_flow()), owner_email="",
        healing_factory=lambda: ee.SelfHealingAgent(search_enabled=False))
    orch.EXECUTORS = dict(orch.EXECUTORS)      # jangan mutasi dict kelas
    orch.EXECUTORS[ee.NodeKind.AGENT] = _dead

    with pytest.raises(Exception):
        asyncio.run(orch.run())
    # Anggaran 0 -> tidak ada percobaan ulang sama sekali.
    assert calls["n"] == 1, f"harap 1 percobaan, dapat {calls['n']}"
    assert orch.states["a"] == "error"


def test_s8_tiga_jenis_endpoint_mati_semua_cepat():
    """connection refused / DNS / timeout -> semuanya <60s & node `error`."""
    import time as _t

    cases = {
        "connection_refused": "Permintaan HTTP gagal (connection refused: ConnectError).",
        "dns": "Permintaan HTTP gagal (ConnectError). name resolution",
        "timeout": "Permintaan HTTP gagal (ConnectTimeout).",
    }
    for name, msg in cases.items():
        calls = {"n": 0}

        async def _dead(orch, node, inp, _m=msg):
            calls["n"] += 1
            raise RuntimeError(_m)

        orch = ee.StatefulOrchestrator(
            ee.FlowGraph(**_agent_flow()), owner_email="",
            healing_factory=lambda: ee.SelfHealingAgent(search_enabled=False))
        orch.EXECUTORS = dict(orch.EXECUTORS)  # jangan mutasi dict kelas
        orch.EXECUTORS[ee.NodeKind.AGENT] = _dead
        t0 = _t.monotonic()
        with pytest.raises(Exception):
            asyncio.run(orch.run())
        elapsed = _t.monotonic() - t0
        assert orch.states["a"] == "error", name
        assert elapsed < 60, f"{name}: {elapsed:.1f}s >= 60s"


def test_s8_klasifikasi_connection_refused():
    """`connection refused` punya kategori & batas sendiri (2 percobaan)."""
    rule = sh.classify_error("Permintaan HTTP gagal (connection refused: ConnectError).")
    assert rule.name == "connection_refused", rule.name
    assert rule.max_attempts == 2, rule.max_attempts


def test_s8_http_tool_timeout_10s_default(monkeypatch):
    """Timeout per percobaan `http_request` = 10s (dulu 20s)."""
    import httpx

    seen: dict = {}

    class _R:
        status_code = 200
        text = "ok"

    def _req(verb, url, content=None, timeout=None, headers=None):
        seen["timeout"] = timeout
        return _R()

    monkeypatch.setattr(httpx, "request", _req)
    monkeypatch.delenv("HTTP_TOOL_TIMEOUT", raising=False)
    tools.http_request("https://example.com")
    assert seen["timeout"] == 10.0, seen


def test_s8_connection_refused_tidak_membocorkan_url(monkeypatch):
    """Pesan error TIDAK boleh memuat URL lengkap (bisa berisi token)."""
    import httpx

    def _req(*a, **k):
        raise httpx.ConnectError("[Errno 111] Connection refused")

    monkeypatch.setattr(httpx, "request", _req)
    with pytest.raises(RuntimeError) as ei:
        tools.http_request("https://api.telegram.org/bot123:SECRET/sendMessage")
    msg = str(ei.value)
    assert "connection refused" in msg.lower()
    assert "SECRET" not in msg and "telegram" not in msg, msg
    assert sh.classify_error(msg).name == "connection_refused"


# ===========================================================================
# GATEWAY Opsi C — rantai cadangan multi-provider
# ===========================================================================
def test_opsic_fallback_chain_memuat_pool_dan_provider(monkeypatch):
    """Rantai cadangan = Gemini pool + provider langsung dari .env."""
    chain = ar._fallback_chain("groq")
    kinds = [c[0] for c in chain]
    assert "gemini_pool" in kinds, kinds
    assert kinds[0] == "gemini_pool", "pool harus dicoba lebih dulu"
    # Groq/NVIDIA/GitHub terisi di .env -> minimal satu provider langsung ada.
    assert any(k in kinds for k in ("groq", "nvidia", "github", "google")), kinds


def test_opsic_gateway_gagal_fallback_ke_pool(monkeypatch):
    """Gateway turun -> agent TETAP sukses lewat jalur cadangan."""
    monkeypatch.setattr(ar, "gateway_config",
                        lambda: ("https://gw.invalid", "master-key"))
    monkeypatch.setattr(ar, "gateway_models", lambda: ["model-gw"])
    monkeypatch.setattr(ar, "detect_provider", lambda: ("groq", "k"))

    import langchain_openai

    class _Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("503 gateway down")

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", _Boom)

    async def _pool(system_prompt, user_msg, model_name):
        return {"reply": "jawaban-pool", "model": "gemini-2.5-flash"}

    monkeypatch.setattr(ar, "_gemini_pool_reply", _pool)

    res = asyncio.run(ar.run_agent("sys", {"context": {}},
                                   config={"model": "universal"}))
    assert res["status"] == "success", res
    assert res["provider"] == "gemini_pool", res
    assert res["reply"] == "jawaban-pool"


def test_opsic_gateway_sukses_tidak_pakai_cadangan(monkeypatch):
    """Jalur utama tetap diprioritaskan: gateway sukses -> pool TIDAK dipakai."""
    monkeypatch.setattr(ar, "gateway_config",
                        lambda: ("https://gw.ok", "master-key"))
    monkeypatch.setattr(ar, "gateway_models", lambda: ["model-gw"])
    monkeypatch.setattr(ar, "detect_provider", lambda: ("groq", "k"))

    used = {"pool": 0}

    async def _pool(system_prompt, user_msg, model_name):
        used["pool"] += 1
        return {"reply": "pool", "model": "gemini-2.5-flash"}

    monkeypatch.setattr(ar, "_gemini_pool_reply", _pool)

    class _Resp:
        content = "jawaban-gateway"
        usage_metadata = {"input_tokens": 1, "output_tokens": 2}

    class _Model:
        def __init__(self, *a, **k):
            pass

        async def ainvoke(self, messages):
            return _Resp()

    class _Bound:
        async def ainvoke(self, messages):
            return _Resp()

    class _Chat:
        def __init__(self, *a, **k):
            pass

        def bind_tools(self, *a, **k):
            return self

        async def ainvoke(self, messages):
            return _Resp()

    import langchain_openai
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", _Chat)

    res = asyncio.run(ar.run_agent("sys", {"context": {}},
                                   config={"model": "universal"}))
    assert res["status"] == "success", res
    assert res["provider"] == "gateway", res
    assert used["pool"] == 0, "cadangan tidak boleh dipakai saat gateway sehat"


def test_opsic_konten_kosong_dianggap_gagal_lalu_cadangan(monkeypatch):
    """`content: null` dari gateway = kegagalan kandidat, BUKAN "success".

    Dulu respons kosong dikembalikan sebagai sukses berisi placeholder,
    sehingga kandidat berikutnya tidak pernah dicoba dan node agent tercatat
    "completed" dengan jawaban kosong (kelas kegagalan senyap BUG-B3).
    """
    monkeypatch.setattr(ar, "gateway_config", lambda: ("https://gw.ok", "k"))
    monkeypatch.setattr(ar, "gateway_models", lambda: ["m-null"])
    monkeypatch.setattr(ar, "detect_provider", lambda: ("groq", "k"))

    import langchain_openai

    class _Resp:
        content = None
        usage_metadata = {}

    class _Chat:
        def __init__(self, *a, **k):
            pass

        def bind_tools(self, *a, **k):
            return self

        async def ainvoke(self, messages):
            return _Resp()

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", _Chat)

    async def _pool(*a, **k):
        return {"reply": "dari-pool", "model": "gemini-2.5-flash"}

    monkeypatch.setattr(ar, "_gemini_pool_reply", _pool)

    res = asyncio.run(ar.run_agent("sys", {"context": {}},
                                   config={"model": "universal"}))
    assert res["status"] == "success", res
    assert res["provider"] == "gemini_pool", res
    assert res["reply"] == "dari-pool", res


def test_opsic_anggaran_gateway_habis_langsung_cadangan(monkeypatch):
    """Anggaran fase gateway habis -> kandidat gateway dilewati, pakai cadangan."""
    monkeypatch.setattr(ar, "gateway_config", lambda: ("https://gw.ok", "k"))
    monkeypatch.setattr(ar, "gateway_models", lambda: ["a", "b", "c"])
    monkeypatch.setattr(ar, "detect_provider", lambda: ("groq", "k"))
    monkeypatch.setenv("LLM_GATEWAY_BUDGET_SEC", "0")

    import langchain_openai
    seen = {"gw": 0}

    class _Chat:
        def __init__(self, *a, **k):
            seen["gw"] += 1
            raise RuntimeError("gateway seharusnya dilewati")

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", _Chat)

    async def _pool(*a, **k):
        return {"reply": "pool", "model": "gemini-2.5-flash"}

    monkeypatch.setattr(ar, "_gemini_pool_reply", _pool)

    res = asyncio.run(ar.run_agent("sys", {"context": {}},
                                   config={"model": "universal"}))
    assert res["provider"] == "gemini_pool", res
    assert seen["gw"] == 0, "kandidat gateway harus dilewati saat anggaran habis"


def test_opsic_semua_kandidat_gagal_raise_dengan_error_terakhir(monkeypatch):
    """Semua jalur gagal -> status `error` (tidak diam-diam "success")."""
    monkeypatch.setattr(ar, "gateway_config", lambda: (None, None))
    monkeypatch.setattr(ar, "detect_provider", lambda: ("groq", "k"))

    import langchain_openai

    class _Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("semua mati")

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", _Boom)

    async def _pool(*a, **k):
        raise RuntimeError("pool juga mati")

    monkeypatch.setattr(ar, "_gemini_pool_reply", _pool)

    class _G:
        def __init__(self, *a, **k):
            raise RuntimeError("groq mati")

    monkeypatch.setattr(ar, "build_model", lambda p, m: _G())

    res = asyncio.run(ar.run_agent("sys", {"context": {}},
                                   config={"model": "universal"}))
    assert res["status"] == "error", res
    assert res.get("error"), res


# ===========================================================================
# F-6 — webhook meneruskan owner_email (Opsi A)
# ===========================================================================
def test_f6_webhook_meneruskan_email_pemilik_ke_runner(monkeypatch):
    calls: list[dict] = []

    async def _spy(workflow_id, flow_data, trigger_input=None,
                   execution_id=None, owner_email=""):
        calls.append({"owner_email": owner_email})
        return {"status": "completed"}

    monkeypatch.setattr(api_server.engine, "execute_workflow_async", _spy)
    monkeypatch.setattr(api_server.db, "update_execution_status", lambda *a: None)
    asyncio.run(api_server._run_webhook_dag(
        "wf", {"nodes": [], "edges": []},
        {"_execution_id": "EX-F6"}, "pemilik@test.dev"))
    assert calls[0]["owner_email"] == "pemilik@test.dev", calls


def test_f6_mcp_webhook_menerima_email_pemilik(memdb, fast_healing, monkeypatch):
    """Node MCP ber-kredensial pada jalur webhook bisa resolve token user."""
    seen: dict = {}

    async def _run(provider, cfg, params, email=""):
        seen["email"] = email
        return {"status": "success", "tool": "http_request",
                "result": {"ok": True}}

    monkeypatch.setattr(ee.provider_registry, "run_async", _run)
    monkeypatch.setattr(api_server.engine, "execute_workflow_async",
                        ee.execute_workflow_async)

    asyncio.run(api_server._run_webhook_dag(
        "wf-f6", MCP_FLOW, {"_execution_id": "EX-F6-MCP"}, "pemilik@test.dev"))
    assert seen.get("email") == "pemilik@test.dev", seen


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
