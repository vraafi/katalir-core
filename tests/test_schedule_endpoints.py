"""E2E endpoint test — /workflows/{id}/schedule (Fitur #1).

Mengikuti konvensi repo: `security.get_current_user` di-patch (JWT Supabase
tidak bisa dibuat di test), lalu endpoint diuji lewat FastAPI TestClient
dengan DB Supabase nyata. Semua baris yang dibuat dibersihkan di akhir.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api_server
import database as db


@pytest.fixture
def klien_dan_pasangan(monkeypatch):
    """TestClient + (workflow_id, user_id) nyata, dengan auth di-patch."""
    from fastapi.testclient import TestClient as _TC

    res = (db.get_write_client().table("workflows")
           .select("id,user_id").limit(1).execute())
    rows = res.data or []
    if not rows:
        pytest.skip("butuh workflow nyata di DB")
    wid, uid = str(rows[0]["id"]), str(rows[0]["user_id"])

    monkeypatch.setattr(api_server.security, "get_current_user",
                        lambda authorization=None: {"id": uid, "email": "qa@test.dev"})

    cli = _TC(api_server.app)
    yield cli, wid, uid

    # bersihkan jadwal yang mungkin tertinggal
    try:
        db.get_write_client().table("workflow_schedules").delete().eq(
            "workflow_id", wid).execute()
    except Exception:  # noqa: BLE001
        pass


def test_tanpa_token_ditolak_401(klien_dan_pasangan, monkeypatch):
    """Tanpa Authorization -> 401 (kontrak repo)."""
    cli, wid, _uid = klien_dan_pasangan
    # hapus patch agar auth asli berjalan
    monkeypatch.setattr(api_server.security, "get_current_user",
                        _auth_asli)
    r = cli.post(f"/workflows/{wid}/schedule", json={"cron_expression": "*/5 * * * *"})
    print("\n[E1] tanpa token ->", r.status_code, r.text[:100])
    assert r.status_code == 401


def _auth_asli(authorization=None):
    from fastapi import HTTPException
    raise HTTPException(401, "Token wajib (Authorization: Bearer <jwt>).")


def test_cron_invalid_ditolak_400(klien_dan_pasangan):
    cli, wid, _uid = klien_dan_pasangan
    r = cli.post(f"/workflows/{wid}/schedule", json={"cron_expression": "99 99 * * *"})
    print("\n[E2] cron invalid ->", r.status_code, r.text[:160])
    assert r.status_code == 400
    assert "tidak valid" in r.text.lower()


def test_timezone_invalid_ditolak_400(klien_dan_pasangan):
    cli, wid, _uid = klien_dan_pasangan
    r = cli.post(f"/workflows/{wid}/schedule",
                 json={"cron_expression": "*/5 * * * *", "timezone": "WIB"})
    print("\n[E3] tz invalid ->", r.status_code, r.text[:160])
    assert r.status_code == 400
    assert "timezone" in r.text.lower()


def test_buat_get_delete_alur_lengkap(klien_dan_pasangan):
    cli, wid, _uid = klien_dan_pasangan

    r = cli.post(f"/workflows/{wid}/schedule",
                 json={"cron_expression": "0 22 * * *", "timezone": "Asia/Jakarta"})
    print("\n[E4] create ->", r.status_code, r.text[:220])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["timezone"] == "Asia/Jakarta"
    # 22:00 WIB harus 15:00Z
    assert body["next_run_at"].startswith("2026-") or body["next_run_at"]
    nxt = body["next_run_at"]
    print("[E4] next_run_at =", nxt)
    assert "T15:00:00" in nxt, f"22:00 WIB harus 15:00Z, dapat {nxt}"

    r2 = cli.get(f"/workflows/{wid}/schedule")
    print("[E5] get ->", r2.status_code, r2.text[:220])
    assert r2.status_code == 200
    assert r2.json()["cron_expression"] == "0 22 * * *"

    r3 = cli.delete(f"/workflows/{wid}/schedule")
    print("[E6] delete ->", r3.status_code, r3.text[:120])
    assert r3.status_code == 200

    r4 = cli.get(f"/workflows/{wid}/schedule")
    print("[E7] get setelah delete ->", r4.status_code)
    assert r4.status_code == 404


def test_upsert_mengganti_jadwal_lama(klien_dan_pasangan):
    cli, wid, _uid = klien_dan_pasangan
    a = cli.post(f"/workflows/{wid}/schedule", json={"cron_expression": "*/10 * * * *"})
    assert a.status_code == 201
    b = cli.post(f"/workflows/{wid}/schedule", json={"cron_expression": "*/20 * * * *"})
    print("\n[E8] upsert kedua ->", b.status_code, b.text[:160])
    assert b.status_code == 201
    g = cli.get(f"/workflows/{wid}/schedule")
    assert g.json()["cron_expression"] == "*/20 * * * *", "harus terganti, bukan dobel"


def test_workflow_orang_lain_404(klien_dan_pasangan, monkeypatch):
    """Workflow milik user lain -> 404 (tidak membocorkan keberadaan)."""
    cli, _wid, uid = klien_dan_pasangan
    lain = str(uuid4_palsu())
    monkeypatch.setattr(api_server.security, "get_current_user",
                        lambda authorization=None: {"id": lain, "email": "x@y.z"})
    r = cli.get(f"/workflows/{_wid}/schedule")
    print("\n[E9] owner mismatch ->", r.status_code, r.text[:140])
    assert r.status_code == 404


def uuid4_palsu():
    import uuid as _u
    return _u.UUID("00000000-0000-4000-8000-000000000001")
