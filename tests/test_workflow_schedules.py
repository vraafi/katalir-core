# tests/test_workflow_schedules.py — Fitur #1 Scheduled Trigger (cron)
# =====================================================================
# Evidence-driven test (8 Okt 2026). Menyentuh Supabase NYATA via service
# client: membuat user+workflow TEMPorer (id uuid acak, email khusus test)
# dan menghapusnya di teardown. Tidak ada credential dicetak.
#
# Kover:
#   - validasi cron 5-field + timezone IANA (unit, tanpa DB)
#   - next_fire_utc Jakarta 22:00 -> 15:00 UTC (tanpa DB)
#   - API POST/GET/DELETE /workflows/{id}/schedule (TestClient, auth dipatch)
#   - tick: tembak jadwal due + claim optimistis anti double-fire
#   - recovery: NULL / overdue >24h / jadwal sehat
#   - multi-jadwal: 5 jadwal due -> 5 tembakan
# =====================================================================
import asyncio
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone

import pytest

import database as db
import scheduler_manager


# ---------------------------------------------------------------------------
# Fixtures DB temporer (user auth + mirror public.users + workflow)
# ---------------------------------------------------------------------------
# PENTING: workflows.user_id -> auth.users (BUKAN public.users), sedangkan
# workflow_schedules/agent_memory -> public.users. Jadi test membuat user
# auth sungguhan via Admin API (service key), memastikan mirror public.users
# ada, dan membersihkan semuanya di teardown.

import httpx


def _auth_admin(method: str, path: str, payload=None):
    url = db.SUPABASE_URL.rstrip("/")
    key = db.SUPABASE_SERVICE_KEY
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json"}
    r = httpx.request(method, f"{url}/auth/v1/admin{path}", headers=headers,
                      json=payload, timeout=25)
    r.raise_for_status()
    return r.json() if r.content else {}


@pytest.fixture(scope="module")
def svc():
    return db.get_write_client()


@pytest.fixture(scope="module")
def temp_user_and_workflow(svc):
    email = f"cron-test-{uuid.uuid4().hex[:8]}@katalir-test.local"
    # GoTrue yang men-generate id -> WAJIB pakai id dari respons, bukan uuid lokal
    created = _auth_admin("POST", "/users",
                          {"email": email, "password": uuid.uuid4().hex + "Aa1!",
                           "email_confirm": True})
    uid = created["id"]
    # mirror public.users (trigger Supabase mungkin sudah membuatnya)
    mirror = svc.table("users").select("id").eq("id", uid).execute()
    if not mirror.data:
        svc.table("users").insert(
            {"id": uid, "email": email, "name": "CRON TEST", "tier": "free"}
        ).execute()
    wid = str(uuid.uuid4())
    # Idempoten: bersihkan sisa baris id yang sama bila run sebelumnya
    # terputus di tengah (mis. full suite dihentikan) -> hindari 23505.
    svc.table("workflow_schedules").delete().eq("workflow_id", wid).execute()
    svc.table("workflows").delete().eq("id", wid).execute()
    svc.table("workflows").insert(
        {"id": wid, "user_id": uid, "name": "CRON-TEST workflow",
         "description": "temp", "flow_data": {"nodes": [], "edges": []}}
    ).execute()
    yield {"user_id": uid, "email": email, "workflow_id": wid}
    # teardown: urutan aman terhadap FK
    svc.table("workflow_schedules").delete().eq("workflow_id", wid).execute()
    svc.table("workflows").delete().eq("id", wid).execute()
    svc.table("users").delete().eq("id", uid).execute()
    try:
        _auth_admin("DELETE", f"/users/{uid}")
    except Exception:  # noqa: BLE001 - cleanup best-effort
        pass


def _insert_schedule(svc, wf, cron, tz="Asia/Jakarta", enabled=True, nfa=None):
    row = {
        "workflow_id": wf["workflow_id"],
        "user_id": wf["user_id"],
        "cron_expression": cron,
        "timezone": tz,
        "enabled": enabled,
        "next_fire_at": nfa,
    }
    res = svc.table("workflow_schedules").insert(row).execute()
    return (res.data or [{}])[0]


@pytest.fixture()
def temp_workflow(svc, temp_user_and_workflow):
    """Workflow FRESH per test — constraint DB: satu jadwal per workflow,
    jadi test yang memasang >1 jadwal butuh workflow sendiri-sendiri."""
    wid = str(uuid.uuid4())
    svc.table("workflows").insert(
        {"id": wid, "user_id": temp_user_and_workflow["user_id"],
         "name": "CRON-TEST workflow (per-test)", "description": "temp",
         "flow_data": {"nodes": [], "edges": []}}
    ).execute()
    yield {**temp_user_and_workflow, "workflow_id": wid}
    svc.table("workflow_schedules").delete().eq("workflow_id", wid).execute()
    svc.table("workflows").delete().eq("id", wid).execute()


# ---------------------------------------------------------------------------
# Unit: validasi & perhitungan waktu
# ---------------------------------------------------------------------------

def test_cron_validation_matrix():
    assert scheduler_manager.is_valid_cron("*/1 * * * *")
    assert scheduler_manager.is_valid_cron("0 22 * * *")
    assert scheduler_manager.is_valid_cron("30 4 1,15 * *")
    assert scheduler_manager.is_valid_cron("0 9 * * 1-5")
    # invalid
    assert not scheduler_manager.is_valid_cron("")
    assert not scheduler_manager.is_valid_cron("99 99 * * *")     # brief 1C.4
    assert not scheduler_manager.is_valid_cron("*/1 * * *")        # 4 field
    assert not scheduler_manager.is_valid_cron("* * * * * *")      # 6 field (detik)
    assert not scheduler_manager.is_valid_cron(None)
    assert not scheduler_manager.is_valid_cron("abc * * * *")


def test_timezone_validation():
    assert scheduler_manager.is_valid_timezone("Asia/Jakarta")
    assert scheduler_manager.is_valid_timezone("UTC")
    assert scheduler_manager.is_valid_timezone("Europe/Berlin")
    assert not scheduler_manager.is_valid_timezone("WIB")        # bukan IANA
    assert not scheduler_manager.is_valid_timezone("Not/Zone")
    assert not scheduler_manager.is_valid_timezone("")
    assert not scheduler_manager.is_valid_timezone(None)


def test_next_fire_jakarta_22_is_utc_15():
    """Brief 1C.3: '0 22 * * *' Asia/Jakarta HARUS 22:00 WIB = 15:00 UTC."""
    base = datetime(2026, 10, 8, 9, 0, 0, tzinfo=dt_timezone(timedelta(hours=7)))
    nxt = scheduler_manager.next_fire_utc("0 22 * * *", "Asia/Jakarta", base=base)
    assert nxt.utcoffset() == timedelta(0)
    assert (nxt.hour, nxt.minute) == (15, 0)   # 22:00 WIB == 15:00 UTC
    assert nxt.day == 8


def test_next_fire_every_minute_advances():
    base = datetime(2026, 10, 8, 3, 0, 30, tzinfo=dt_timezone.utc)
    nxt = scheduler_manager.next_fire_utc("*/1 * * * *", "UTC", base=base)
    assert (nxt.hour, nxt.minute, nxt.second) == (3, 1, 0)


# ---------------------------------------------------------------------------
# API endpoints (auth dipatch — pola test_katalir_mcp_external.py)
# ---------------------------------------------------------------------------

@pytest.fixture()
def client_with_auth(monkeypatch, temp_user_and_workflow, svc):
    from fastapi.testclient import TestClient
    import api_server
    wf = temp_user_and_workflow
    # Constraint uq_schedules_workflow: satu jadwal per workflow. Fixture ini
    # memakai workflow milik fixture `scope="module"`, jadi baris dari test
    # sebelumnya harus dibersihkan dulu — kalau tidak, endpoint POST
    # (upsert on_conflict=workflow_id) balapan dengan sisa baris.
    svc.table("workflow_schedules").delete().eq(
        "workflow_id", wf["workflow_id"]).execute()
    monkeypatch.setattr(
        api_server.security, "get_current_user",
        lambda auth: {"id": wf["user_id"], "email": wf["email"], "name": "CRON TEST"})
    # Tanpa context manager: lifespan tidak perlu untuk endpoint schedule,
    # dan SCHEDULER_ENABLED=0 dari conftest sudah menutup kemungkinan loop.
    klien = TestClient(api_server.app)
    yield klien
    # jangan tinggalkan jadwal untuk test berikutnya
    svc.table("workflow_schedules").delete().eq(
        "workflow_id", wf["workflow_id"]).execute()


def _mk_workflow(svc, uid: str, tag: str) -> str:
    wid = str(uuid.uuid4())
    svc.table("workflows").insert(
        {"id": wid, "user_id": uid, "name": f"CRON-TEST {tag}",
         "description": "temp", "flow_data": {"nodes": [], "edges": []}}
    ).execute()
    return wid


def test_api_schedule_full_flow(client_with_auth, temp_user_and_workflow):
    client = client_with_auth
    wid = temp_user_and_workflow["workflow_id"]
    # CREATE
    r = client.post(f"/workflows/{wid}/schedule",
                    json={"cron_expression": "*/1 * * * *",
                          "timezone": "Asia/Jakarta"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["schedule_id"] and body["cron_expression"] == "*/1 * * * *"
    assert body["enabled"] is True and body["next_run_at"]
    # GET
    r = client.get(f"/workflows/{wid}/schedule")
    assert r.status_code == 200
    assert r.json()["cron_expression"] == "*/1 * * * *"
    # REPLACE (upsert, tetap satu baris)
    r = client.post(f"/workflows/{wid}/schedule",
                    json={"cron_expression": "0 22 * * *",
                          "timezone": "Asia/Jakarta"})
    assert r.status_code == 201
    r = client.get(f"/workflows/{wid}/schedule")
    assert r.json()["cron_expression"] == "0 22 * * *"
    # timezone hasil hitung: 22:00 WIB = 15:00 UTC
    nfa = r.json()["next_run_at"]
    assert "T15:00" in nfa, f"next_run_at salah zona: {nfa}"
    # DELETE
    assert client.delete(f"/workflows/{wid}/schedule").status_code == 200
    assert client.get(f"/workflows/{wid}/schedule").status_code == 404
    assert client.delete(f"/workflows/{wid}/schedule").status_code == 404


def test_api_invalid_cron_rejected(client_with_auth, temp_user_and_workflow):
    wid = temp_user_and_workflow["workflow_id"]
    r = client_with_auth.post(f"/workflows/{wid}/schedule",
                              json={"cron_expression": "99 99 * * *"})
    assert r.status_code == 400
    assert "tidak valid" in r.json()["detail"].lower()


def test_api_invalid_timezone_rejected(client_with_auth, temp_user_and_workflow):
    wid = temp_user_and_workflow["workflow_id"]
    r = client_with_auth.post(f"/workflows/{wid}/schedule",
                              json={"cron_expression": "*/1 * * * *",
                                    "timezone": "WIB"})
    assert r.status_code == 400
    assert "timezone" in r.json()["detail"].lower()


def test_api_workflow_of_other_user_404(monkeypatch, temp_user_and_workflow):
    from fastapi.testclient import TestClient
    import api_server
    wid = temp_user_and_workflow["workflow_id"]
    stranger = {"id": str(uuid.uuid4()),
                "email": f"stranger-{uuid.uuid4().hex[:6]}@katalir-test.local"}
    monkeypatch.setattr(api_server.security, "get_current_user",
                        lambda auth: stranger)
    client = TestClient(api_server.app)
    assert client.get(f"/workflows/{wid}/schedule").status_code == 404
    assert client.post(f"/workflows/{wid}/schedule",
                       json={"cron_expression": "*/1 * * * *"}).status_code == 404
    assert client.delete(f"/workflows/{wid}/schedule").status_code == 404


# ---------------------------------------------------------------------------
# Tick / claim / recovery (DB nyata, engine_launch di-record)
# ---------------------------------------------------------------------------

@pytest.fixture()
def fired_recorder(monkeypatch):
    calls = []

    def _fake_launch(workflow_id, flow_data, trigger_input, owner_email=""):
        # last_execution_id di DB bertipe uuid -> recorder harus uuid asli
        fake_id = str(uuid.uuid4())
        calls.append({"workflow_id": workflow_id, "trigger": trigger_input,
                      "owner_email": owner_email, "execution_id": fake_id})
        return fake_id

    monkeypatch.setattr(scheduler_manager, "engine_launch", _fake_launch)
    return calls


def test_tick_fires_due_schedule_once(svc, temp_workflow, fired_recorder):
    wf = temp_workflow
    now = scheduler_manager.utc_now()
    sched = _insert_schedule(svc, wf, "*/1 * * * *",
                             nfa=scheduler_manager.iso_utc(now - timedelta(seconds=5)))
    try:
        fired = asyncio.run(scheduler_manager.tick(user_id=wf["user_id"]))
        assert fired == 1, "jadwal due harus ditembak sekali"
        assert len(fired_recorder) == 1
        assert fired_recorder[0]["workflow_id"] == wf["workflow_id"]
        assert fired_recorder[0]["trigger"]["trigger"] == "cron"
        assert fired_recorder[0]["trigger"]["schedule_id"] == sched["id"]
        # baris ter-update: last_fired_at + next_fire_at maju
        row = (svc.table("workflow_schedules").select("*")
               .eq("id", sched["id"]).single().execute()).data
        assert row["last_execution_id"] == fired_recorder[0]["execution_id"]
        nfa = datetime.fromisoformat(row["next_fire_at"].replace("Z", "+00:00"))
        assert nfa > now, "next_fire_at harus maju ke masa depan"
        # tick kedua SEGERA: tidak boleh menembak lagi (anti double-fire)
        assert asyncio.run(scheduler_manager.tick(user_id=wf["user_id"])) == 0
        assert len(fired_recorder) == 1
    finally:
        svc.table("workflow_schedules").delete().eq("id", sched["id"]).execute()


def test_claim_is_optimistic(svc, temp_workflow):
    wf = temp_workflow
    now = scheduler_manager.utc_now()
    sched = _insert_schedule(svc, wf, "*/1 * * * *",
                             nfa=scheduler_manager.iso_utc(now - timedelta(seconds=1)))
    try:
        row = (svc.table("workflow_schedules").select("*")
               .eq("id", sched["id"]).single().execute()).data
        first = scheduler_manager.claim_schedule(row, now)
        assert first, "claim pertama harus sukses"
        second = scheduler_manager.claim_schedule(row, now)
        assert second is None, "claim kedua dengan expected lama HARUS gagal"
    finally:
        svc.table("workflow_schedules").delete().eq("id", sched["id"]).execute()


def test_recovery_null_and_overdue(svc, temp_workflow):
    uid = temp_workflow["user_id"]
    now = scheduler_manager.utc_now()
    # constraint DB: satu jadwal per workflow -> 3 workflow terpisah
    w_null = _mk_workflow(svc, uid, "recovery-null")
    w_old = _mk_workflow(svc, uid, "recovery-old")
    w_ok = _mk_workflow(svc, uid, "recovery-ok")
    s_null = _insert_schedule(svc, {"workflow_id": w_null, "user_id": uid},
                              "*/1 * * * *", nfa=None)
    s_old = _insert_schedule(svc, {"workflow_id": w_old, "user_id": uid},
                             "0 22 * * *",
                             nfa=scheduler_manager.iso_utc(now - timedelta(hours=48)))
    s_ok = _insert_schedule(svc, {"workflow_id": w_ok, "user_id": uid},
                            "0 22 * * *",
                            nfa=scheduler_manager.iso_utc(now + timedelta(hours=2)))
    try:
        fixed = scheduler_manager.recover_on_startup()
        assert fixed >= 2
        r_null = (svc.table("workflow_schedules").select("next_fire_at")
                  .eq("id", s_null["id"]).single().execute()).data
        assert r_null["next_fire_at"], "NULL harus diisi (due)"
        r_old = (svc.table("workflow_schedules").select("next_fire_at")
                 .eq("id", s_old["id"]).single().execute()).data
        nfa_old = datetime.fromisoformat(r_old["next_fire_at"].replace("Z", "+00:00"))
        assert nfa_old > now, "overdue >24h harus di-majukan tanpa menembak"
        r_ok = (svc.table("workflow_schedules").select("next_fire_at")
                .eq("id", s_ok["id"]).single().execute()).data
        assert r_ok["next_fire_at"] == s_ok["next_fire_at"], "jadwal sehat tak disentuh"
    finally:
        for wid in (w_null, w_old, w_ok):
            svc.table("workflow_schedules").delete().eq("workflow_id", wid).execute()
            svc.table("workflows").delete().eq("id", wid).execute()


def test_tick_five_concurrent_schedules(svc, temp_workflow, fired_recorder):
    """Brief 1C.5: 5 jadwal berbeda -> semuanya ditembak pada tick yang sama."""
    uid = temp_workflow["user_id"]
    now = scheduler_manager.utc_now()
    wids, sids = [], []
    try:
        for i, cron in enumerate(("*/1 * * * *", "0 22 * * *", "30 4 1,15 * *",
                                  "0 9 * * 1-5", "15 12 * * *")):
            wid = _mk_workflow(svc, uid, f"concurrent-{i}")
            wids.append(wid)
            row = _insert_schedule(svc, {"workflow_id": wid, "user_id": uid}, cron,
                                   nfa=scheduler_manager.iso_utc(now - timedelta(seconds=3)))
            sids.append(row["id"])
        fired = asyncio.run(scheduler_manager.tick(user_id=uid))
        assert fired == 5, f"harus 5 tembakan, dapat {fired}"
        assert len(fired_recorder) == 5
    finally:
        for wid in wids:
            svc.table("workflow_schedules").delete().eq("workflow_id", wid).execute()
            svc.table("workflows").delete().eq("id", wid).execute()


def test_tick_disabled_schedule_ignored(svc, temp_workflow, fired_recorder):
    wf = temp_workflow
    now = scheduler_manager.utc_now()
    sched = _insert_schedule(svc, wf, "*/1 * * * *", enabled=False,
                             nfa=scheduler_manager.iso_utc(now - timedelta(seconds=5)))
    try:
        assert asyncio.run(scheduler_manager.tick(user_id=wf["user_id"])) == 0
        assert len(fired_recorder) == 0
    finally:
        svc.table("workflow_schedules").delete().eq("id", sched["id"]).execute()
