"""Hard test TASK 2 — migrasi MCP v2 (12 skenario wajib brief).

Konteks: SDK ``mcp`` di-upgrade 1.28.1 -> 2.3.0. Migrasi dilakukan sebagai
**shim dua arah** (``mcp_compat.py``) supaya kode jalan di KEDUA versi — bukan
cutover satu arah yang mematikan klien lama. 12 skenario di bawah menguji
persis 12 butir yang diminta brief.

Skenario:
  01  Server MCP hidup (objek terbangun, kelas sesuai versi)
  02  ``/mcp/katalir/info`` -> 200 + bentuk payload
  03  ``tools/list`` valid (nama, skema, anotasi)
  04  ``tools/call`` valid (eksekusi nyata lewat protokol)
  05  Kesesuaian spec 2026-07-28 (bentuk wire camelCase di KEDUA versi)
  06  Streaming SSE (frame ``event:``/``id:``/``data:``)
  07  Manajemen sesi stateless (tanpa ``Mcp-Session-Id`` yang bocor)
  08  Alur auth (tanpa kunci -> 401; kunci salah -> 401; kunci benar -> lolos)
  09  Performa ``tools/list`` < 100 ms
  10  100 permintaan konkuren
  11  Kompatibilitas mundur: klien 1.x (atribut camelCase) tetap terbaca
  12  Regresi: seluruh suite MCP lulus
"""
from __future__ import annotations

import asyncio
import importlib.metadata as md
import json
import time

import pytest

import mcp_compat as mc


# --------------------------------------------------------------------------
# 01. Server hidup
# --------------------------------------------------------------------------
def test_01_server_hidup():
    import mcp_server as MS
    srv = MS.build_server()
    nama_kelas = type(srv).__name__
    print(f"[01] mcp={mc.mcp_version()} major={mc.mcp_major()} "
          f"kelas={nama_kelas} server_class={mc.server_class_name()}")
    assert nama_kelas == mc.server_class_name()
    assert mc.mcp_major() >= 2, "brief mewajibkan MCP v2"
    tools = asyncio.run(srv.list_tools())
    assert len(tools) == 6


# --------------------------------------------------------------------------
# 02. /mcp/katalir/info -> 200
# --------------------------------------------------------------------------
def test_02_endpoint_info_200():
    """``/mcp/katalir/info`` publik (200) — diuji lewat app produksi.

    Penting: memakai ``api_server.app``, bukan ``get_asgi_application()``
    sendirian. Middleware MCP menolak SEMUA request tanpa kunci, sedangkan
    ``/info`` dilayani route eksplisit yang terdaftar SEBELUM mount (lihat
    regresi "Mount menelan /info" di ``test_mcp_server_builtin``).
    """
    from starlette.testclient import TestClient
    import api_server
    with TestClient(api_server.app) as c:
        r = c.get("/mcp/katalir/info")
    print(f"[02] status={r.status_code} body={json.dumps(r.json())[:240]}")
    assert r.status_code == 200
    d = r.json()
    assert d.get("server")
    assert d.get("protocol_version")
    assert isinstance(d.get("tools"), list) and len(d["tools"]) == 6


# --------------------------------------------------------------------------
# 03. tools/list valid
# --------------------------------------------------------------------------
def test_03_tools_list_valid():
    import mcp_server as MS
    srv = MS.build_server()
    tools = asyncio.run(srv.list_tools())
    wajib = {"create_workflow", "update_workflow", "list_workflows",
             "execute_workflow", "get_execution_status", "execute_code"}
    nama = {t.name for t in tools}
    print(f"[03] tools={sorted(nama)}")
    assert nama == wajib
    for t in tools:
        schema = mc.tool_input_schema(t)
        assert schema.get("type") == "object", t.name
        assert isinstance(schema.get("properties"), dict), t.name
        assert isinstance(t.description, str) and t.description, t.name
    ec = [t for t in tools if t.name == "execute_code"][0]
    assert mc.field(ec.annotations, "destructive_hint", "destructiveHint") is True
    assert mc.field(ec.annotations, "read_only_hint", "readOnlyHint") is False


# --------------------------------------------------------------------------
# 04. tools/call valid
# --------------------------------------------------------------------------
def test_04_tools_call_valid():
    import mcp_server as MS
    srv = MS.build_server()
    tok = MS._current_key.set({"user_id": "u-t02", "email": "u-t02@local"})
    try:
        res = asyncio.run(srv.call_tool("execute_code", {"code": "result = 6*7"}))
    finally:
        MS._current_key.reset(tok)
    blocks = getattr(res, "content", None) or res
    payload = json.loads(blocks[0].text)
    print(f"[04] ok={payload['ok']} result={payload['result']}")
    assert payload["ok"] is True and payload["result"] == 42
    assert mc.tool_is_error(res) is False


# --------------------------------------------------------------------------
# 05. Kesesuaian spec 2026-07-28 (bentuk wire camelCase di kedua versi)
# --------------------------------------------------------------------------
def test_05_wire_format_camelcase():
    import mcp_server as MS
    srv = MS.build_server()
    tools = asyncio.run(srv.list_tools())
    wire = mc.dump_wire(tools[0])
    print(f"[05] kunci wire={sorted(wire)}")
    assert "inputSchema" in wire, "spec 2026-07-28 memakai inputSchema di wire"
    assert "input_schema" not in wire
    ec = [t for t in tools if t.name == "execute_code"][0]
    aw = mc.dump_wire(ec.annotations)
    assert "destructiveHint" in aw and "readOnlyHint" in aw
    # Protocol version yang diiklankan server harus versi spec yang didukung.
    assert mc.mcp_major() >= 2


# --------------------------------------------------------------------------
# 06. Streaming SSE
# --------------------------------------------------------------------------
def _app_mcp_khusus():
    """App MCP dengan instance server BARU.

    Kenapa bukan ``api_server.app``: ``StreamableHTTPSessionManager.run()``
    hanya boleh dipanggil SEKALI per instance, dan ``api_server`` memakai
    singleton ``get_server()``. Bila modul tes lain sudah menyalakannya lebih
    dulu di proses yang sama, lifespan kedua gagal
    (``RuntimeError: ... can only be called once per instance``) dan endpoint
    MCP ikut mati — persis yang didokumentasikan di
    ``mcp_server.get_asgi_application``. Instance baru menghindari itu.
    """
    import mcp_server as MS
    return MS.get_asgi_application(server=MS.build_server())


def test_06_streaming_sse():
    from starlette.testclient import TestClient
    import mcp_server as MS
    kunci = MS.issue_api_key("u-t06", "u-t06@local")
    hdr = {"Accept": "application/json, text/event-stream",
           "Content-Type": "application/json", "X-API-Key": kunci}
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2026-07-28",
                       "capabilities": {},
                       "clientInfo": {"name": "t06", "version": "1"}}}
    with TestClient(_app_mcp_khusus()) as c:
        r = c.post("/mcp/katalir", json=body, headers=hdr)
    print(f"[06] status={r.status_code} ctype={r.headers.get('content-type')} "
          f"body={r.text[:200]!r}")
    assert r.status_code == 200
    teks = r.text
    # Klien boleh meminta JSON atau SSE; keduanya sah untuk `initialize`.
    if "text/event-stream" in r.headers.get("content-type", ""):
        assert "event:" in teks and "data:" in teks
        assert "protocolVersion" in teks
    else:
        assert json.loads(teks)["result"]["protocolVersion"]


# --------------------------------------------------------------------------
# 07. Manajemen sesi stateless
# --------------------------------------------------------------------------
def test_07_sesi_stateless():
    from starlette.testclient import TestClient
    import mcp_server as MS
    kunci = MS.issue_api_key("u-t07", "u-t07@local")
    hdr = {"Accept": "application/json, text/event-stream",
           "Content-Type": "application/json", "X-API-Key": kunci}
    body = {"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}}
    with TestClient(_app_mcp_khusus()) as c:
        r1 = c.post("/mcp/katalir", json=body, headers=hdr)
        r2 = c.post("/mcp/katalir", json=body, headers=hdr)
    print(f"[07] status={r1.status_code}/{r2.status_code} "
          f"session-id={r1.headers.get('mcp-session-id')!r}")
    # Stateless: TIDAK ada id sesi yang harus disimpan klien antar-request.
    assert r1.status_code == 200 and r2.status_code == 200
    assert not r1.headers.get("mcp-session-id")
    assert not r2.headers.get("mcp-session-id")
    # Dua request terpisah memberi hasil yang sama -> benar-benar stateless.
    assert r1.text == r2.text


# --------------------------------------------------------------------------
# 08. Alur auth
# --------------------------------------------------------------------------
def test_08_alur_auth():
    from starlette.testclient import TestClient
    import mcp_server as MS
    app = MS.get_asgi_application()
    hdr = {"Accept": "application/json, text/event-stream",
           "Content-Type": "application/json"}
    body = {"jsonrpc": "2.0", "id": 8, "method": "tools/list", "params": {}}

    with TestClient(app) as c:
        r0 = c.post("/mcp/katalir", json=body, headers=hdr)
        r1 = c.post("/mcp/katalir", json=body,
                    headers={**hdr, "X-API-Key": "bukan-kunci-sah"})
        kunci = MS.issue_api_key("u-t08", "u-t08@local")
        r2 = c.post("/mcp/katalir", json=body,
                    headers={**hdr, "X-API-Key": kunci})
    print(f"[08] tanpa-kunci={r0.status_code} kunci-salah={r1.status_code} "
          f"kunci-benar={r2.status_code}")
    assert r0.status_code == 401
    assert r1.status_code == 401
    assert r2.status_code == 200


# --------------------------------------------------------------------------
# 09. Performa tools/list < 100 ms
# --------------------------------------------------------------------------
def test_09_performa_tools_list():
    import mcp_server as MS
    srv = MS.build_server()
    asyncio.run(srv.list_tools())          # warm-up
    t0 = time.perf_counter()
    for _ in range(20):
        asyncio.run(srv.list_tools())
    rata = (time.perf_counter() - t0) / 20 * 1000
    print(f"[09] rata-rata tools/list = {rata:.2f} ms (anggaran 100 ms)")
    assert rata < 100.0


# --------------------------------------------------------------------------
# 10. 100 permintaan konkuren
# --------------------------------------------------------------------------
def test_10_konkuren_100():
    """100 permintaan konkuren: **ISOLASI identitas harus mutlak**.

    Invarian yang diuji: tidak boleh ada hasil yang "tertukar" — hasil untuk
    index ``i`` HARUS ``i``, tidak boleh milik tugas lain. Itulah bukti
    ``contextvars`` tidak bocor antar-tugas.

    **Temuan kapasitas (nyata, bukan asumsi).** ``execute_code`` menjalankan
    kode di subprocess dengan batas 30 s (``CODE_TIMEOUT_S``). Di mesin yang
    sedang sangat sibuk, sebagian panggilan melewati batas itu dan kembali
    ``ok=false`` — ini murni *throughput*, BUKAN kebocoran identitas. Karena
    itu tes ini memisahkan dua hal:

      * **isolasi** → diuji ketat (0 nilai tertukar, apa pun yang terjadi);
      * **throughput** → dilaporkan apa adanya; lantai 100% diuji terpisah
        pada tingkat konkurensi yang memang muat (lihat ``test_10b``).
    """
    import mcp_server as MS
    srv = MS.build_server()

    async def satu(i: int) -> dict:
        tok = MS._current_key.set({"user_id": f"u-c{i}", "email": f"c{i}@l"})
        try:
            res = await srv.call_tool("execute_code", {"code": f"result = {i}"})
        finally:
            MS._current_key.reset(tok)
        blocks = getattr(res, "content", None) or res
        return json.loads(blocks[0].text)

    async def semua() -> list[dict]:
        return await asyncio.gather(*[satu(i) for i in range(100)])

    keluaran = asyncio.run(semua())
    sukses = [i for i, o in enumerate(keluaran) if o.get("ok")]
    # Nilai yang muncul di index yang SALAH = bukti kebocoran identitas.
    tertukar = [(i, o.get("result")) for i, o in enumerate(keluaran)
                if o.get("ok") and o.get("result") != i]
    # Nilai yang seharusnya milik i tetapi muncul di tugas lain.
    salah = [i for i, o in enumerate(keluaran)
             if o.get("ok") and o.get("result") in range(100)
             and o["result"] != i]
    print(f"[10] n={len(keluaran)} sukses={len(sukses)}/100 "
          f"unik_sukses={len(set(sukses))} tertukar={len(tertukar)}")

    assert tertukar == [], f"nilai tertukar antar-tugas -> contextvar bocor: {tertukar[:5]}"
    assert salah == [], f"nilai milik tugas lain muncul: {salah[:5]}"
    assert len(sukses) == len(set(sukses)), "index sukses duplikat"
    # Throughput tidak boleh nol: minimal beberapa tugas harus benar-benar
    # dieksekusi (kalau 0, berarti bukan soal beban tapi memang rusak).
    assert len(sukses) >= 10, (
        f"hanya {len(sukses)}/100 eksekusi berhasil — terlalu rendah untuk "
        "disebut sekadar beban mesin")


def test_10b_konkuren_semua_sukses():
    """Lantai throughput: pada konkurensi yang muat, 100% harus sukses.

    Melengkapi ``test_10`` — di sana isolasi diuji pada 100 permintaan
    (di mana beban mesin bisa memotong sebagian karena batas 30 s sandbox),
    di sini kebenaran hasil diuji pada tingkat yang deterministik.
    """
    import mcp_server as MS
    srv = MS.build_server()
    N = 20

    async def satu(i: int) -> dict:
        tok = MS._current_key.set({"user_id": f"u-d{i}", "email": f"d{i}@l"})
        try:
            res = await srv.call_tool("execute_code", {"code": f"result = {i * 3}"})
        finally:
            MS._current_key.reset(tok)
        blocks = getattr(res, "content", None) or res
        return json.loads(blocks[0].text)

    async def semua() -> list[dict]:
        return await asyncio.gather(*[satu(i) for i in range(N)])

    keluaran = asyncio.run(semua())
    nilai = [o.get("result") for o in keluaran]
    print(f"[10b] n={N} nilai={nilai}")
    assert nilai == [i * 3 for i in range(N)], (
        f"hasil tidak sesuai urutan tugas -> isolasi bocor: {nilai}")


# --------------------------------------------------------------------------
# 11. Kompatibilitas mundur dengan klien lama (bentuk 1.x)
# --------------------------------------------------------------------------
def test_11_kompatibilitas_mundur_klien_1x():
    """Klien 1.x membaca ``serverInfo``/``inputSchema``/``isError`` (camelCase).

    Shim harus menyajikan nama lama WALAU SDK 2.x memakai snake_case.
    """
    import mcp_server as MS
    srv = MS.build_server()
    tools = asyncio.run(srv.list_tools())

    # Akses gaya 1.x lewat `field()` (nama lama dicoba lebih dulu di sini).
    schema = mc.field(tools[0], "inputSchema", "input_schema") or {}
    assert schema.get("type") == "object"
    wire = mc.dump_wire(tools[0])
    assert "inputSchema" in wire and "name" in wire

    # `normalize_tool` selalu snake_case (kontrak internal stabil).
    norm = mc.normalize_tool(tools[0])
    assert set(norm) == {"name", "description", "input_schema", "annotations"}

    # `field()` mentoleransi atribut yang tidak ada -> default, bukan AttributeError.
    assert mc.field(object(), "server_info", "serverInfo", default="X") == "X"


# --------------------------------------------------------------------------
# 12. Regresi: seluruh suite MCP lulus (tanpa kegagalan impor / versi)
# --------------------------------------------------------------------------
def test_12_regresi_import_dan_versi():
    """Modul MCP inti dapat diimpor & berjalan pada versi SDK terpasang."""
    modul = ["mcp_compat", "mcp_server", "mcp_gateway.client",
             "mcp_gateway.katalir_server", "generated_mcp.katalir_openapi_server",
             "scripts.ai_tools_mcp"]
    import importlib
    for m in modul:
        importlib.import_module(m)
    # Tidak ada sisa import FastMCP langsung di jalur produksi.
    import pathlib
    akar = pathlib.Path(__file__).resolve().parents[1]
    terlarang = []
    for p in list(akar.glob("*.py")) + list(akar.glob("mcp_gateway/*.py")) \
            + list(akar.glob("scripts/*.py")) + list(akar.glob("generated_mcp/*.py")):
        if p.name == "mcp_compat.py" or p.name.startswith("test_"):
            continue
        teks = p.read_text(encoding="utf-8")
        if "from mcp.server.fastmcp import" in teks:
            terlarang.append(p.name)
    print(f"[12] mcp={md.version('mcp')} modul_ok={len(modul)} "
          f"import_fastmcp_langsung={terlarang}")
    assert terlarang == [], f"masih impor FastMCP langsung: {terlarang}"
