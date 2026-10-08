"""Fitur #8 — MCP Server Built-in: hard test (10 skenario).

Sasaran: membuktikan permukaan MCP Katalir BICARA protokol MCP yang sebenarnya
(JSON-RPC 2.0 + Streamable HTTP), bukan sekadar "endpoint yang mengembalikan
JSON mirip MCP". Karena itu mayoritas test mengirim frame JSON-RPC mentah dan
memeriksa bentuk balasannya.

Skenario (10):
  1. `initialize` mengembalikan serverInfo + protocolVersion
  2. `tools/list` mengembalikan 5 tool dengan inputSchema yang valid
  3. Tanpa API key -> 401 (initialize, tools/list, DAN tools/call)
  4. API key rusak / kedaluwarsa -> 401
  5. Dua bentuk header (X-API-Key vs Authorization: Bearer) sama-sama diterima
  6. Isolasi antar user: kunci user A tidak melihat/menyentuh workflow user B
  7. `tools/call` create_workflow -> update_workflow -> list_workflows
  8. `tools/call` execute_workflow -> get_execution_status
  9. Path `/mcp/katalir` TANPA garis miring tidak 307 (klien MCP tidak
     mengikuti redirect POST) dan berperilaku sama dengan versi bergaris miring
 10. DNS-rebinding: Host asing -> 421, host terdaftar -> 200; plus validasi
     flow_data menolak graf rusak SEBELUM menyentuh DB

HARNESS
-------
Tidak ada `pytest-asyncio` di repo ini (konvensi: `asyncio.run()` per test).
Untuk MCP itu TIDAK cukup: `FastMCP` memakai satu
`StreamableHTTPSessionManager`, dan `run()` menyalakan task group yang terikat
ke EVENT LOOP pemanggil. `asyncio.run()` membuat loop baru tiap test, jadi task
group test pertama sudah mati di test kedua — yang muncul adalah
`RuntimeError: Task group is not initialized` dari library MCP, bukan pesan
yang menunjuk harness.

Karena itu satu event loop tetap hidup di thread daemon, dan seluruh test
mengirim coroutine ke loop itu. Ini juga lebih dekat ke produksi: satu proses
uvicorn = satu loop melayani banyak request.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import threading

import pytest

# Mount MCP dibangun saat `api_server` diimpor -> kill-switch harus diset lebih
# dulu. `conftest` sudah menyetel ALLOWED_HOSTS + SCHEDULER_ENABLED=0.
os.environ.setdefault("MCP_SERVER_ENABLED", "1")
os.environ.setdefault("ALLOWED_HOSTS", "testserver,localhost,127.0.0.1")
if "testserver" not in os.environ["ALLOWED_HOSTS"]:
    os.environ["ALLOWED_HOSTS"] += ",testserver"

import httpx  # noqa: E402
from asgi_lifespan import LifespanManager  # noqa: E402

import api_server  # noqa: E402
import database as db  # noqa: E402
import mcp_server  # noqa: E402

MCP_PATH = "/mcp/katalir"
JSON_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

_INIT_PARAMS = {
    "protocolVersion": "2025-06-18",
    "capabilities": {},
    "clientInfo": {"name": "katalir-hardtest", "version": "1.0"},
}


# ---------------------------------------------------------------------------
# Event loop tetap
# ---------------------------------------------------------------------------
_LOOP = None
_LOOP_LOCK = threading.Lock()
_SESI = None


def _loop():
    global _LOOP
    with _LOOP_LOCK:
        if _LOOP is None:
            lp = asyncio.new_event_loop()
            threading.Thread(target=lp.run_forever, daemon=True,
                             name="katalir-mcp-test-loop").start()
            _LOOP = lp
    return _LOOP


def jalankan(coro, timeout: float = 90.0):
    """Jalankan coroutine di loop suite dan kembalikan hasilnya."""
    return asyncio.run_coroutine_threadsafe(coro, _loop()).result(timeout=timeout)


async def _boot():
    """Nyalakan lifespan + client SEKALI di loop suite."""
    global _SESI
    if _SESI is None:
        stack = contextlib.AsyncExitStack()
        await stack.enter_async_context(LifespanManager(api_server.app))
        transport = httpx.ASGITransport(app=api_server.app)
        client = await stack.enter_async_context(
            httpx.AsyncClient(transport=transport, base_url="http://testserver"))
        _SESI = (stack, client)
    return _SESI[1]


def teardown_module(module):
    """Tutup sesi + hentikan loop supaya tidak ada thread menggantung."""
    global _SESI, _LOOP
    if _SESI is not None:
        stack, _client = _SESI
        _SESI = None
        with contextlib.suppress(Exception):
            jalankan(stack.aclose(), timeout=15)
    if _LOOP is not None:
        _LOOP.call_soon_threadsafe(_LOOP.stop)
        _LOOP = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _rpc(method: str, req_id: int = 1, params: dict | None = None) -> dict:
    body: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


def _unwrap(resp: httpx.Response) -> dict:
    """Ambil payload JSON dari balasan MCP.

    `stateless_http=True` TETAP membalas dengan framing SSE
    (`event: message` + `data: {...}`) — bukan JSON polos. Klien MCP resmi
    memahaminya, tapi tes yang membaca `.json()` akan gagal. Helper ini
    menerima KEDUA bentuk supaya tes tidak bergantung pada detail framing yang
    bisa berubah antar versi SDK.
    """
    text = resp.text or ""
    if "data:" in text:
        for line in text.splitlines():
            if line.startswith("data:"):
                chunk = line[5:].strip()
                if chunk:
                    return json.loads(chunk)
    return json.loads(text)


class McpClient:
    """Klien MCP minimal untuk tes: initialize + tools/list + tools/call."""

    def __init__(self, client: httpx.AsyncClient, path: str = MCP_PATH, key: str = ""):
        self.c = client
        self.path = path
        self.key = key

    def _headers(self, extra: dict | None = None) -> dict:
        h = dict(JSON_HEADERS)
        if self.key:
            h["X-API-Key"] = self.key
        if extra:
            h.update(extra)
        return h

    async def post(self, body: dict, headers: dict | None = None) -> httpx.Response:
        return await self.c.post(self.path, json=body, headers=self._headers(headers))

    async def initialize(self) -> httpx.Response:
        return await self.post(_rpc("initialize", 1, _INIT_PARAMS))

    async def initialized_notification(self) -> httpx.Response:
        return await self.post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def list_tools(self) -> list[dict]:
        resp = await self.post(_rpc("tools/list", 2, {}))
        assert resp.status_code == 200, f"tools/list gagal: {resp.status_code} {resp.text[:200]}"
        return _unwrap(resp)["result"]["tools"]

    async def call_tool(self, name: str, arguments: dict, req_id: int = 3) -> dict:
        resp = await self.post(_rpc("tools/call", req_id, {"name": name, "arguments": arguments}))
        assert resp.status_code == 200, f"tools/call gagal: {resp.status_code} {resp.text[:200]}"
        payload = _unwrap(resp)["result"]
        # FastMCP membungkus nilai balik tool sebagai content[0].text berisi JSON.
        return json.loads(payload["content"][0]["text"])

    async def call_tool_raw(self, name: str, arguments: dict, req_id: int = 3) -> dict:
        """Seperti `call_tool` tapi mengembalikan payload MENTAH.

        Dipakai untuk memeriksa `isError` — FastMCP tidak melempar exception,
        ia menandai kegagalan di payload. Tes yang hanya melihat nilai balik
        akan menganggap kegagalan sebagai sukses.
        """
        resp = await self.post(_rpc("tools/call", req_id, {"name": name, "arguments": arguments}))
        assert resp.status_code == 200, f"tools/call gagal: {resp.status_code} {resp.text[:200]}"
        return _unwrap(resp)["result"]


def _key(user_id: str, email: str = "", ttl_s: int = 3600) -> str:
    return mcp_server.issue_api_key(user_id, email, ttl_s=ttl_s)


@pytest.fixture
def memori_db(monkeypatch):
    """Paksa `database` ke mode memori supaya tes tidak menyentuh produksi."""
    monkeypatch.setattr(db, "is_configured", lambda: False)
    db._LWORKFLOW.clear()
    db._L_EXEC.clear()
    yield
    db._LWORKFLOW.clear()
    db._L_EXEC.clear()


# ---------------------------------------------------------------------------
# 1. initialize
# ---------------------------------------------------------------------------
async def _t01():
    mcp_http = await _boot()
    cli = McpClient(mcp_http, key=_key("u-init", "init@example.com"))
    resp = await cli.initialize()
    assert resp.status_code == 200, resp.text[:300]
    result = _unwrap(resp)["result"]
    assert result["protocolVersion"], "protocolVersion kosong"
    info = result["serverInfo"]
    assert info["name"] == "katalir", f"serverInfo.name salah: {info}"
    caps = result["capabilities"]
    assert "tools" in caps, f"capabilities tanpa tools: {caps}"
    print(f"[1] protocolVersion={result['protocolVersion']} serverInfo={info}")
    print(f"[1] capabilities keys={sorted(caps.keys())}")
    notif = await cli.initialized_notification()
    assert notif.status_code in (200, 202), f"notifications/initialized: {notif.status_code}"


def test_01_initialize():
    jalankan(_t01())


# ---------------------------------------------------------------------------
# 2. tools/list
# ---------------------------------------------------------------------------
async def _t02():
    mcp_http = await _boot()
    cli = McpClient(mcp_http, key=_key("u-tools", "tools@example.com"))
    await cli.initialize()
    tools = await cli.list_tools()
    names = sorted(t["name"] for t in tools)
    expected = sorted([
        "create_workflow", "update_workflow", "list_workflows",
        "execute_workflow", "get_execution_status",
    ])
    assert names == expected, f"daftar tool tidak sesuai: {names}"
    for t in tools:
        assert t.get("description"), f"tool {t['name']} tanpa description"
        schema = t.get("inputSchema") or {}
        assert schema.get("type") == "object", f"{t['name']} inputSchema bukan object"
        assert isinstance(schema.get("properties"), dict), f"{t['name']} properties bukan dict"
    print(f"[2] tools={names}")
    for t in tools:
        req = (t.get("inputSchema") or {}).get("required") or []
        print(f"[2]   {t['name']:22s} required={req}")


def test_02_tools_list():
    jalankan(_t02())


# ---------------------------------------------------------------------------
# 3. tanpa API key -> 401
# ---------------------------------------------------------------------------
async def _t03():
    mcp_http = await _boot()
    cli = McpClient(mcp_http, key="")
    r1 = await cli.initialize()
    assert r1.status_code == 401, f"initialize tanpa kunci -> {r1.status_code} (harus 401)"
    assert r1.headers.get("www-authenticate"), "tanpa header WWW-Authenticate"
    err = _unwrap(r1)["error"]
    assert err["code"] == -32001, err
    r2 = await cli.post(_rpc("tools/list", 2, {}))
    assert r2.status_code == 401, f"tools/list tanpa kunci -> {r2.status_code} (harus 401)"
    # tools/call TANPA kunci juga harus 401 — kalau tidak, siapa pun bisa
    # menjalankan workflow orang lain hanya dengan menebak tool name.
    r3 = await cli.post(_rpc("tools/call", 3, {"name": "list_workflows", "arguments": {}}))
    assert r3.status_code == 401, f"tools/call tanpa kunci -> {r3.status_code} (harus 401)"
    print(f"[3] tanpa kunci: initialize={r1.status_code} tools/list={r2.status_code} "
          f"tools/call={r3.status_code}; error.code={err['code']}")
    print(f"[3] www-authenticate={r1.headers.get('www-authenticate')}")


def test_03_tanpa_api_key_ditolak():
    jalankan(_t03())


# ---------------------------------------------------------------------------
# 4. API key rusak / kedaluwarsa
# ---------------------------------------------------------------------------
async def _t04():
    mcp_http = await _boot()
    kasus = [
        ("bukan-prefix", "token-tanpa-prefix"),
        ("prefix tanpa isi", mcp_server.API_KEY_PREFIX),
        ("tanda tangan salah", mcp_server.API_KEY_PREFIX + "AAAA.BBBB"),
        ("payload diubah", mcp_server.API_KEY_PREFIX + "ZmFrZQ.BBBB"),
        ("prefix dobel", mcp_server.API_KEY_PREFIX + mcp_server.API_KEY_PREFIX + "a.b"),
        ("kosong", " "),
    ]
    for label, kunci in kasus:
        cli = McpClient(mcp_http, key=kunci)
        r = await cli.initialize()
        assert r.status_code == 401, f"{label}: {r.status_code} (harus 401)"
        print(f"[4] {label:20s} -> {r.status_code}")

    # Kedaluwarsa: TTL minimum 60s di issue_api_key, jadi uji lewat payload
    # yang exp-nya sudah lewat — dibuat langsung, bukan dengan sleep 60 detik.
    import hashlib
    import hmac
    import time as _time
    payload = {"u": "u-exp", "e": "", "l": "", "iat": 0, "exp": int(_time.time()) - 10}
    body = mcp_server._b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = mcp_server._b64e(
        hmac.new(mcp_server._signing_key(), body.encode("ascii"), hashlib.sha256).digest())
    expired = f"{mcp_server.API_KEY_PREFIX}{body}.{sig}"
    cli = McpClient(mcp_http, key=expired)
    r = await cli.initialize()
    assert r.status_code == 401, f"kunci kedaluwarsa -> {r.status_code} (harus 401)"
    pesan = _unwrap(r)["error"]["message"].lower()
    assert "kedaluwarsa" in pesan, f"pesan tidak menyebut kedaluwarsa: {pesan}"
    print(f"[4] kedaluwarsa          -> {r.status_code} ({pesan[:60]})")

    with pytest.raises(mcp_server.McpAuthError):
        mcp_server.verify_api_key("mcp-kir_rusak.rusak")
    with pytest.raises(mcp_server.McpAuthError):
        mcp_server.verify_api_key("")
    print("[4] verify_api_key menolak bentuk rusak/kosong (McpAuthError)")


def test_04_api_key_rusak_dan_kedaluwarsa():
    jalankan(_t04())


# ---------------------------------------------------------------------------
# 5. dua bentuk header auth
# ---------------------------------------------------------------------------
async def _t05():
    mcp_http = await _boot()
    key = _key("u-hdr", "hdr@example.com")
    cli = McpClient(mcp_http, key=key)
    r_x = await cli.initialize()
    assert r_x.status_code == 200, f"X-API-Key -> {r_x.status_code}"
    r_b = await mcp_http.post(MCP_PATH, json=_rpc("initialize", 1, _INIT_PARAMS),
                              headers={**JSON_HEADERS, "Authorization": f"Bearer {key}"})
    assert r_b.status_code == 200, f"Bearer -> {r_b.status_code}"
    # Header case-insensitive menurut spec.
    r_b2 = await mcp_http.post(MCP_PATH, json=_rpc("initialize", 1, _INIT_PARAMS),
                               headers={**JSON_HEADERS, "authorization": f"bearer {key}"})
    assert r_b2.status_code == 200, f"bearer lowercase -> {r_b2.status_code}"
    # X-API-Key menang atas Authorization bila keduanya ada.
    r_both = await mcp_http.post(MCP_PATH, json=_rpc("initialize", 1, _INIT_PARAMS),
                                 headers={**JSON_HEADERS, "X-API-Key": key,
                                          "Authorization": "Bearer kunci-palsu"})
    assert r_both.status_code == 200, f"X-API-Key harus menang -> {r_both.status_code}"
    print(f"[5] X-API-Key={r_x.status_code} Bearer={r_b.status_code} "
          f"bearer-kecil={r_b2.status_code} keduanya={r_both.status_code}")


def test_05_dua_bentuk_header():
    jalankan(_t05())


# ---------------------------------------------------------------------------
# 6. isolasi antar user
# ---------------------------------------------------------------------------
async def _t06():
    """Kunci user A tidak boleh melihat atau menyentuh workflow user B.

    DB nyata tidak dipakai: `database` dijalankan dalam mode memori supaya tes
    deterministik dan tidak menyentuh data produksi. Yang diuji adalah batas
    kepemilikan di lapisan tool, bukan PostgREST.
    """
    mcp_http = await _boot()
    cli_a = McpClient(mcp_http, key=_key("user-A", "a@example.com"))
    cli_b = McpClient(mcp_http, key=_key("user-B", "b@example.com"))
    await cli_a.initialize()
    await cli_b.initialize()

    wf_a = await cli_a.call_tool("create_workflow", {"name": "Milik A"})
    wf_b = await cli_b.call_tool("create_workflow", {"name": "Milik B"})
    print(f"[6] A membuat {wf_a['id']} | B membuat {wf_b['id']}")

    list_a = await cli_a.call_tool("list_workflows", {})
    list_b = await cli_b.call_tool("list_workflows", {})
    ids_a = {w["id"] for w in list_a["workflows"]}
    ids_b = {w["id"] for w in list_b["workflows"]}
    assert wf_a["id"] in ids_a and wf_b["id"] not in ids_a, f"A melihat {ids_a}"
    assert wf_b["id"] in ids_b and wf_a["id"] not in ids_b, f"B melihat {ids_b}"
    print(f"[6] list A={sorted(ids_a)} list B={sorted(ids_b)} -> tidak saling silang")

    # B tidak boleh mengubah workflow A. FastMCP mengubah exception tool menjadi
    # isError di dalam payload, jadi kegagalan dicek dari situ.
    payload = await cli_b.call_tool_raw(
        "update_workflow", {"workflow_id": wf_a["id"], "name": "DIBAJAK"})
    assert payload.get("isError") is True, "B berhasil mengubah workflow A — isolasi bocor"
    teks = payload["content"][0]["text"].lower()
    assert "tidak ditemukan" in teks, f"pesan tidak menyembunyikan keberadaan: {teks[:120]}"
    assert db._LWORKFLOW[wf_a["id"]]["name"] == "Milik A", "nama workflow A berubah"
    print("[6] B update workflow A -> isError=True, pesan menyembunyikan keberadaan")
    print(f"[6] nama workflow A tetap: {db._LWORKFLOW[wf_a['id']]['name']!r}")

    payload = await cli_b.call_tool_raw(
        "execute_workflow", {"workflow_id": wf_a["id"]})
    assert payload.get("isError") is True, "B berhasil menjalankan workflow A — isolasi bocor"
    print("[6] B execute workflow A -> isError=True")


def test_06_isolasi_antar_user(memori_db):
    jalankan(_t06())


# ---------------------------------------------------------------------------
# 7. round trip create -> update -> list
# ---------------------------------------------------------------------------
async def _t07():
    mcp_http = await _boot()
    cli = McpClient(mcp_http, key=_key("u-crud", "crud@example.com"))
    await cli.initialize()
    flow = {
        "nodes": [
            {"id": "n1", "type": "trigger", "data": {"kind": "trigger"}},
            {"id": "n2", "type": "agent", "data": {}},
        ],
        "edges": [{"source": "n1", "target": "n2"}],
    }
    dibuat = await cli.call_tool("create_workflow", {
        "name": "Alur Uji", "description": "dari hard test", "flow_data": flow})
    assert dibuat["name"] == "Alur Uji"
    assert dibuat["node_count"] == 2, dibuat
    print(f"[7] create_workflow -> id={dibuat['id']} node_count={dibuat['node_count']}")
    diubah = await cli.call_tool("update_workflow", {
        "workflow_id": dibuat["id"], "name": "Alur Uji (diubah)", "description": "v2"})
    assert diubah["name"] == "Alur Uji (diubah)", diubah
    print(f"[7] update_workflow -> {diubah['name']!r} updated={diubah['updated']}")
    daftar = await cli.call_tool("list_workflows", {})
    assert daftar["count"] >= 1
    cocok = [w for w in daftar["workflows"] if w["id"] == dibuat["id"]]
    assert cocok and cocok[0]["name"] == "Alur Uji (diubah)", daftar
    print(f"[7] list_workflows -> count={daftar['count']} "
          f"{[w['name'] for w in daftar['workflows']]}")


def test_07_create_dan_list(memori_db):
    jalankan(_t07())


# ---------------------------------------------------------------------------
# 8. round trip execute -> status
# ---------------------------------------------------------------------------
async def _t08():
    mcp_http = await _boot()
    cli = McpClient(mcp_http, key=_key("u-exec", "exec@example.com"))
    await cli.initialize()
    flow = {
        "nodes": [
            {"id": "t1", "type": "trigger", "data": {"kind": "trigger"}},
            {"id": "a1", "type": "agent", "data": {"prompt": "halo"}},
        ],
        "edges": [{"source": "t1", "target": "a1"}],
    }
    wf = await cli.call_tool("create_workflow", {"name": "Alur Jalan", "flow_data": flow})
    hasil = await cli.call_tool("execute_workflow", {"workflow_id": wf["id"]})
    assert hasil["status"] == "pending", hasil
    assert hasil["workflow_id"] == wf["id"]
    assert hasil["execution_id"], hasil
    print(f"[8] execute_workflow -> execution_id={hasil['execution_id']} status={hasil['status']}")
    status = await cli.call_tool("get_execution_status", {"execution_id": hasil["execution_id"]})
    assert status["execution_id"] == hasil["execution_id"]
    assert status["workflow_id"] == wf["id"]
    assert status["status"], status
    assert isinstance(status["steps"], list)
    print(f"[8] get_execution_status -> status={status['status']} "
          f"step_count={status['step_count']} workflow_id={status['workflow_id']}")

    # Workflow tanpa node harus ditolak dengan pesan yang jelas, bukan
    # "selesai" tanpa satu pun langkah jalan.
    kosong = await cli.call_tool("create_workflow", {"name": "Kosong"})
    payload = await cli.call_tool_raw("execute_workflow", {"workflow_id": kosong["id"]})
    assert payload.get("isError") is True, "workflow tanpa node malah dijalankan"
    print("[8] execute workflow tanpa node -> isError=True (benar)")


def test_08_execute_dan_status(memori_db):
    jalankan(_t08())


# ---------------------------------------------------------------------------
# 9. path tanpa garis miring harus bekerja (bukan 307)
# ---------------------------------------------------------------------------
async def _t09():
    mcp_http = await _boot()
    key = _key("u-slash", "slash@example.com")
    hasil = {}
    for path in ("/mcp/katalir", "/mcp/katalir/"):
        cli = McpClient(mcp_http, path=path, key=key)
        r = await cli.initialize()
        assert r.status_code != 307, (
            f"{path} -> 307 redirect; klien MCP tidak mengikuti redirect POST "
            f"(Location={r.headers.get('location')})"
        )
        assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:200]}"
        tools = await cli.list_tools()
        hasil[path] = sorted(t["name"] for t in tools)
    assert hasil["/mcp/katalir"] == hasil["/mcp/katalir/"], hasil
    print(f"[9] tanpa garis miring -> 200, tools identik "
          f"({len(hasil['/mcp/katalir'])} tool)")
    print("[9] dengan garis miring -> 200, tools identik")


def test_09_path_tanpa_garis_miring():
    jalankan(_t09())


# ---------------------------------------------------------------------------
# 10. DNS-rebinding + validasi flow_data
# ---------------------------------------------------------------------------
async def _t10():
    await _boot()
    key = _key("u-host", "host@example.com")

    # Host terdaftar -> lolos. Host asing -> DITOLAK.
    #
    # Kenapa 400 ATAU 421 (keduanya benar): permintaan melewati DUA lapis
    # proteksi host. `TrustedHostMiddleware` (api_server) menolak lebih dulu
    # dengan **400 Invalid host header**, dan MCP `TransportSecuritySettings`
    # menolak dengan **421 Misdirected Request** bila middleware itu dilonggarkan.
    # Yang penting bukan angka spesifiknya, melainkan host asing TIDAK
    # dilayani — dan host sah tetap 200.
    for host, harus_lolos in (("testserver", True), ("evil.example.com", False)):
        transport = httpx.ASGITransport(app=api_server.app)
        async with httpx.AsyncClient(transport=transport, base_url=f"http://{host}") as c:
            r = await c.post(MCP_PATH, json=_rpc("initialize", 1, _INIT_PARAMS),
                             headers={**JSON_HEADERS, "X-API-Key": key})
        if harus_lolos:
            assert r.status_code == 200, f"host {host} seharusnya lolos, dapat {r.status_code}"
        else:
            assert r.status_code in (400, 421), (
                f"host {host} harus ditolak (400 TrustedHost / 421 DNS-rebinding), "
                f"dapat {r.status_code} — host asing DILAYANI"
            )
        print(f"[10] host={host:22s} -> {r.status_code} "
              f"{'LOLOS' if harus_lolos else 'DIBLOKIR'}")

    info = mcp_server.describe()
    assert info["dns_rebinding_protection"] is True
    assert "testserver" in info["allowed_hosts"], info["allowed_hosts"]
    print(f"[10] describe(): proteksi={info['dns_rebinding_protection']} "
          f"allowlist={len(info['allowed_hosts'])} host")

    # Validasi flow_data: graf rusak ditolak SEBELUM menyentuh DB.
    kasus = [
        ("nodes bukan list", {"nodes": "x"}),
        ("edge tanpa target", {"nodes": [{"id": "n1"}], "edges": [{"source": "n1"}]}),
        ("edge ke node hantu", {"nodes": [{"id": "n1"}],
                                "edges": [{"source": "n1", "target": "ghost"}]}),
        ("node tanpa id", {"nodes": [{"type": "agent"}]}),
        ("node id duplikat", {"nodes": [{"id": "n1"}, {"id": "n1"}]}),
    ]
    for label, flow in kasus:
        with pytest.raises(ValueError):
            mcp_server._validate_flow_data(flow)
        print(f"[10] flow_data ditolak: {label}")

    sah = {"nodes": [{"id": "a"}, {"id": "b"}], "edges": [{"source": "a", "target": "b"}]}
    assert mcp_server._validate_flow_data(sah) == sah
    print("[10] flow_data sah diterima")


def test_10_dns_rebinding_dan_validasi_flow():
    jalankan(_t10())
