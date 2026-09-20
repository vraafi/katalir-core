# tests/test_execution_report.py
"""FASE 2.5 — laporan eksekusi untuk chat (diformat di server, diuji tanpa UI).

Yang dijaga: log mentah berisi DUA baris per node ("running" lalu status akhir),
output node bisa JSON panjang, dan kegagalan tidak boleh terlihat seperti sukses.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import execution_report as er  # noqa: E402


def test_node_yang_sama_di_collapse_jadi_satu_baris():
    logs = [
        {"node_id": "trg", "status": "running", "payload": {}},
        {"node_id": "trg", "status": "completed", "payload": {"summary": "Jadwal 09:00"}},
        {"node_id": "tg", "status": "running", "payload": {}},
        {"node_id": "tg", "status": "completed", "payload": {"summary": "Pesan terkirim"}},
    ]
    rep = er.format_execution_report({"status": "completed"}, logs)
    assert rep.count("trg") == 1 and rep.count("tg") == 1, rep
    assert "running" not in rep.lower(), rep
    assert "2 langkah berhasil, 0 gagal" in rep
    assert "1. trg — OK: Jadwal 09:00" in rep
    assert "2. tg — OK: Pesan terkirim" in rep


def test_kegagalan_tidak_disamarkan():
    logs = [
        {"node_id": "a", "status": "completed", "payload": {"result": "ok"}},
        {"node_id": "b", "status": "error", "payload": {"error": "Telegram menolak (401)"}},
    ]
    rep = er.format_execution_report({"status": "error"}, logs)
    assert "berhenti karena error" in rep
    assert "1 langkah berhasil, 1 gagal" in rep
    assert "GAGAL" in rep and "Telegram menolak (401)" in rep


def test_output_panjang_dipotong_dan_satu_baris():
    panjang = {"result": "x" * 500 + "\n\nlanjutan"}
    rep = er.format_execution_report({"status": "completed"},
                                     [{"node_id": "n", "status": "completed", "payload": panjang}])
    baris = rep.splitlines()[1]
    assert baris.endswith("…")
    assert "\n\n" not in baris
    assert len(baris) < 200, len(baris)


def test_payload_dict_tak_dikenal_diringkas_jadi_kunci_nilai():
    rep = er.format_execution_report(
        {"status": "completed"},
        [{"node_id": "n", "status": "completed", "payload": {"count": 3, "url": "https://x.id"}}])
    assert "count=3" in rep and "url=https://x.id" in rep


def test_eksekusi_tanpa_langkah_tidak_mengaku_sukses_penuh():
    rep = er.format_execution_report({"status": "completed"}, [])
    assert "belum ada langkah" in rep
    assert er.format_execution_report({"status": "running"}, []) == "Workflow sedang dijalankan…"


def test_log_kotor_tidak_menjatuhkan_laporan():
    logs = [None, "bukan-dict", {"node_id": None, "status": None}, {"node_id": "ok", "status": "completed"}]
    rep = er.format_execution_report({"status": "completed"}, logs)  # type: ignore[arg-type]
    assert "ok — OK" in rep


def test_payload_error_dihitung_gagal_walau_status_completed():
    """Bug nyata dari uji 2.5: node MCP 'completed' padahal result.status=error."""
    logs = [{"node_id": "nt", "status": "completed",
             "payload": {"type": "mcp.call", "tool": "web_search",
                         "result": {"status": "error", "message": "query pencarian kosong"}}}]
    rep = er.format_execution_report({"status": "completed"}, logs)
    assert "0 langkah berhasil, 1 gagal" in rep, rep
    assert "nt — GAGAL" in rep
    assert "berhenti karena error" in rep


def test_langkah_sukses_tetap_ok():
    logs = [{"node_id": "trg", "status": "completed",
             "payload": {"type": "trigger.fire", "result": {"status": "ok"}}}]
    rep = er.format_execution_report({"status": "completed"}, logs)
    assert "1 langkah berhasil, 0 gagal" in rep
    assert "trg — OK" in rep


def test_hasil_format_bisa_dijadikan_json_aman():
    rep = er.format_execution_report({"status": "completed"},
                                     [{"node_id": "n", "status": "completed", "payload": {"a": 1}}])
    assert json.dumps({"report": rep})  # tidak ada karakter yang merusak JSON
