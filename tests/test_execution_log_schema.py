# tests/test_execution_log_schema.py
"""FASE 2.5 — skema `execution_logs` harus diikuti apa adanya.

Regresi nyata: kode menulis `step_kind` + `payload`, sedangkan tabel punya
`node_type` + `output_data`. Setiap insert gagal 400 (tertelan `except`), log
hanya hidup di memori, dan `GET /executions/{id}` selamanya melaporkan "belum
ada langkah" walau workflow sudah dijalankan. Test ini mengunci nama kolom.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database as db  # noqa: E402

# Diambil langsung dari PostgREST OpenAPI Supabase (execution_logs).
REAL_COLUMNS = {"id", "execution_id", "node_id", "node_type", "status",
                "output_data", "error_message", "started_at", "finished_at"}


def test_baris_log_hanya_pakai_kolom_yang_ada():
    row = db.execution_log_row("ex-1", "n1", "mcp", "completed", {"a": 1})
    assert set(row) <= REAL_COLUMNS, set(row) - REAL_COLUMNS
    assert "step_kind" not in row and "payload" not in row


def test_pemetaan_nama_kolom():
    row = db.execution_log_row("ex-1", "n1", "mcp", "completed", {"result": "ok"})
    assert row["node_type"] == "mcp"
    assert row["output_data"] == {"result": "ok"}
    assert row["status"] == "completed"


def test_status_running_pakai_started_at_lain_finished_at():
    row = db.execution_log_row("ex-1", "n1", "agent", "running", {})
    assert "started_at" in row and "finished_at" not in row
    done = db.execution_log_row("ex-1", "n1", "agent", "completed", {})
    assert "finished_at" in done and "started_at" not in done


def test_error_dipromosikan_ke_kolom_error_message():
    row = db.execution_log_row("ex-1", "n1", "mcp", "error", {"error": "boom"})
    assert row["error_message"] == "boom"


def test_payload_bukan_dict_tidak_melempar():
    row = db.execution_log_row("ex-1", "n1", "mcp", "completed", "teks polos")
    assert row["output_data"] == {"output": "teks polos"}


def test_baris_db_dinormalkan_ke_bentuk_laporan():
    norm = db._normalize_log({
        "node_id": "n1", "node_type": "mcp", "status": "completed",
        "output_data": {"result": {"status": "error"}}, "error_message": "gagal kirim",
        "finished_at": "2026-09-19T10:00:00Z",
    })
    assert norm["node_id"] == "n1"
    assert norm["step_kind"] == "mcp"
    assert norm["payload"]["error"] == "gagal kirim"
    assert norm["ts"].endswith("Z")


def test_baris_gaya_lama_dibiarkan_apa_adanya():
    old = {"node_id": "n", "step_kind": "mcp", "status": "completed", "payload": {}}
    assert db._normalize_log(old) is old
