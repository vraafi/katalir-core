# tests/test_durable_execution.py — Fitur #2 (8 Okt 2026)
# =====================================================================
# Hard test durable execution, Supabase NYATA. Min 10 skenario.
#
# Yang diuji (semuanya butuh BUKTI, bukan asumsi):
#   1-2  basic: start/checkpoint/finish
#   3-4  replay: node sukses TIDAK dijalankan ulang
#   5-6  durability: state bertahan setelah "restart"
#   7-8  idempotency: kunci sama -> satu eksekusi
#   9-10 external signal: tunggu + bangun, idempoten
#   11   pemulihan eksekusi macet (heartbeat basi)
#   12   eksekusi MENUNGGU tidak ikut dipulihkan
#   13   keamanan: user lain tidak bisa baca
#   14   performa checkpoint
# =====================================================================
import os
import time
import uuid

import psycopg2
import pytest

import database as db
import durable_execution as de


def _pg():
    """Koneksi Postgres LANGSUNG.

    Diperlukan karena PostgREST hanya mengekspos skema `public` +
    `graphql_public` (terverifikasi: PGRST106 "Invalid schema: auth"),
    sedangkan `workflows.user_id` ber-FK ke `auth.users`.
    """
    ref = db.SUPABASE_URL.split("//")[1].split(".")[0]
    conn = psycopg2.connect(
        host="aws-0-ap-southeast-1.pooler.supabase.com", port=5432,
        user=f"postgres.{ref}", password=os.environ["SUPABASE_DB_PASSWORD"],
        dbname="postgres", connect_timeout=10, sslmode="require")
    conn.autocommit = True
    return conn


@pytest.fixture()
def ctx():
    """Buat user + workflow nyata, bersihkan setelah tes.

    PENTING — skema nyata Katalir (diverifikasi 8 Okt via pg_constraint):
      workflows.user_id          -> auth.users    (BUKAN public.users!)
      workflow_schedules.user_id -> public.users
      executions.workflow_id     -> public.workflows
    Jadi baris di KEDUA tabel users harus dibuat, kalau tidak insert
    workflow gagal dengan 23503.
    """
    svc = db.get_write_client()
    uid = str(uuid.uuid4())
    wid = str(uuid.uuid4())
    email = f"dur-{uid[:8]}@katalir-test.local"
    pg = _pg()
    cur = pg.cursor()

    # auth.users via koneksi langsung (PostgREST tidak mengekspos skema auth)
    cur.execute(
        "insert into auth.users (id, email, aud, role) values (%s,%s,%s,%s)",
        (uid, email, "authenticated", "authenticated"))
    svc.table("users").insert({
        "id": uid, "email": email, "name": "DUR", "tier": "free"}).execute()
    svc.table("workflows").insert({
        "id": wid, "user_id": uid, "name": "dur-test",
        "flow_data": {"nodes": [], "edges": []}}).execute()

    yield {"uid": uid, "wid": wid, "svc": svc, "cur": cur, "pg": pg}

    svc.table("executions").delete().eq("workflow_id", wid).execute()
    svc.table("workflows").delete().eq("id", wid).execute()
    svc.table("users").delete().eq("id", uid).execute()
    try:
        cur.execute("delete from auth.users where id=%s", (uid,))
    except Exception as exc:  # noqa: BLE001
        print(f"[cleanup] auth.users: {type(exc).__name__}: {exc}")
    pg.close()


def _ex(ctx, **kw):
    return de.start_execution(ctx["wid"], **kw)


# --- 1. basic: start membuat baris running + heartbeat ----------------------
def test_01_start_execution(ctx):
    ex = _ex(ctx)
    assert ex.get("id"), f"id kosong: {ex}"
    assert ex["status"] == "running"
    assert ex.get("heartbeat_at"), "heartbeat harus diisi saat start"
    assert ex.get("state") == {}
    print(f"\n[1] start -> id={ex['id'][:8]} status={ex['status']} "
          f"hb={'ada' if ex.get('heartbeat_at') else 'KOSONG'}")


# --- 2. basic: checkpoint tersimpan ----------------------------------------
def test_02_checkpoint_tersimpan(ctx):
    ex = _ex(ctx)
    assert de.begin_step(ex["id"], "node_a", "http", {"url": "x"}) is True
    de.finish_step(ex["id"], "node_a", {"hasil": 42})
    row = de.get_execution(ex["id"])
    assert row["state"].get("node_a") == {"hasil": 42}, f"state: {row['state']}"
    assert row["current_step_id"] == "node_a"
    print(f"\n[2] state={row['state']} step={row['current_step_id']}")


# --- 3. REPLAY: node sukses tidak dijalankan ulang -------------------------
def test_03_replay_melewati_node_sukses(ctx):
    ex = _ex(ctx)
    de.begin_step(ex["id"], "n1"); de.finish_step(ex["id"], "n1", {"v": 1})
    # percobaan kedua pada node yang sama HARUS mengembalikan False
    ulang = de.begin_step(ex["id"], "n1")
    assert ulang is False, "node sukses harus DILEWATI (replay), bukan diulang"
    print(f"\n[3] begin_step ulang pada n1 -> {ulang} (harus False = replay)")


# --- 4. REPLAY: done_steps melaporkan yang sudah selesai -------------------
def test_04_done_steps(ctx):
    ex = _ex(ctx)
    for n in ("a", "b", "c"):
        de.begin_step(ex["id"], n); de.finish_step(ex["id"], n, {"n": n})
    done = de.done_steps(ex["id"])
    assert done == {"a", "b", "c"}, f"done={done}"
    print(f"\n[4] done_steps={sorted(done)}")


# --- 5. DURABILITY: state bertahan setelah "restart" -----------------------
def test_05_state_bertahan_setelah_restart(ctx):
    """Simulasi proses mati: tidak ada state di memori, hanya DB."""
    ex = _ex(ctx)
    de.begin_step(ex["id"], "langkah1"); de.finish_step(ex["id"], "langkah1", {"a": 1})
    de.begin_step(ex["id"], "langkah2"); de.finish_step(ex["id"], "langkah2", {"b": 2})
    # "restart": instance bersih tanpa memori apa pun
    segar = de.get_execution(ex["id"])
    assert segar["state"]["langkah1"] == {"a": 1}
    assert segar["state"]["langkah2"] == {"b": 2}
    assert de.done_steps(ex["id"]) == {"langkah1", "langkah2"}
    print(f"\n[5] setelah 'restart': state={segar['state']}")


# --- 6. DURABILITY: node gagal tidak masuk done_steps ----------------------
def test_06_node_gagal_tidak_dianggap_selesai(ctx):
    ex = _ex(ctx)
    de.begin_step(ex["id"], "ok"); de.finish_step(ex["id"], "ok", {"v": 1})
    de.begin_step(ex["id"], "gagal")
    de.finish_step(ex["id"], "gagal", None, error="boom")
    done = de.done_steps(ex["id"])
    assert done == {"ok"}, f"node gagal ikut dianggap selesai: {done}"
    # node gagal BOLEH dicoba ulang
    assert de.begin_step(ex["id"], "gagal") is True
    print(f"\n[6] done={sorted(done)}; 'gagal' boleh diulang=True")


# --- 7. IDEMPOTENCY: kunci sama -> eksekusi sama ---------------------------
def test_07_idempotency_kunci_sama(ctx):
    k = "cron-run-2026-10-08T22:00"
    e1 = _ex(ctx, idempotency_key=k)
    e2 = _ex(ctx, idempotency_key=k)
    assert e1["id"] == e2["id"], f"eksekusi ganda: {e1['id']} vs {e2['id']}"
    n = len((ctx["svc"].table("executions").select("id")
             .eq("workflow_id", ctx["wid"]).execute()).data or [])
    assert n == 1, f"harus 1 baris, ada {n}"
    print(f"\n[7] kunci sama -> id sama={e1['id'][:8]} jumlah baris={n}")


# --- 8. IDEMPOTENCY: kunci beda -> eksekusi beda ---------------------------
def test_08_idempotency_kunci_beda(ctx):
    e1 = _ex(ctx, idempotency_key="run-A")
    e2 = _ex(ctx, idempotency_key="run-B")
    assert e1["id"] != e2["id"], "kunci beda harus jadi eksekusi beda"
    # dan tanpa kunci pun tetap boleh banyak (partial index)
    e3 = _ex(ctx); e4 = _ex(ctx)
    assert e3["id"] != e4["id"]
    print(f"\n[8] kunci beda -> id beda OK; tanpa kunci -> id beda OK")


# --- 9. SIGNAL: tunggu lalu dibangunkan ------------------------------------
def test_09_wait_dan_wake_signal(ctx):
    ex = _ex(ctx)
    de.wait_for_signal(ex["id"], "approval")
    row = de.get_execution(ex["id"])
    assert row["status"] == "waiting" and row["waiting_for"] == "approval"
    ok = de.wake_up_signal(ex["id"], "approval", {"oleh": "manajer"})
    assert ok is True
    row2 = de.get_execution(ex["id"])
    assert row2["status"] == "running", f"status: {row2['status']}"
    assert row2["waiting_for"] is None
    assert row2["state"]["signal:approval"] == {"oleh": "manajer"}
    print(f"\n[9] waiting -> {row['status']}/{row['waiting_for']} "
          f"-> wake -> {row2['status']}")


# --- 10. SIGNAL: idempoten (sinyal kedua diabaikan) ------------------------
def test_10_wake_signal_idempoten(ctx):
    ex = _ex(ctx)
    de.wait_for_signal(ex["id"], "approval")
    assert de.wake_up_signal(ex["id"], "approval", {"a": 1}) is True
    assert de.wake_up_signal(ex["id"], "approval", {"a": 2}) is False, \
        "sinyal kedua harus diabaikan"
    # nama sinyal tidak cocok juga diabaikan
    de.wait_for_signal(ex["id"], "lain")
    assert de.wake_up_signal(ex["id"], "bukan-ini", {}) is False
    print("\n[10] sinyal kedua -> False (idempoten); nama beda -> False")


# --- 11. RECOVERY: eksekusi macet dipulihkan -------------------------------
def test_11_recover_eksekusi_macet(ctx):
    ex = _ex(ctx)
    de.begin_step(ex["id"], "n1"); de.finish_step(ex["id"], "n1", {"v": 1})
    # paksa heartbeat jadi basi (7 menit lalu) — jam DB, bukan jam lokal
    basi = de._iso(de._now_utc() - __import__("datetime").timedelta(minutes=7))
    ctx["svc"].table("executions").update({"heartbeat_at": basi}) \
        .eq("id", ex["id"]).execute()

    ids = de.stuck_execution_ids()
    assert ex["id"] in ids, f"tidak terdeteksi macet: {ids}"
    klaim = de.recover_stuck()
    assert any(r["id"] == ex["id"] for r in klaim), "tidak terklaim"
    row = de.get_execution(ex["id"])
    assert row["status"] == "interrupted", f"status: {row['status']}"
    assert row["resumed_at"], "resumed_at harus terisi"
    # state TIDAK hilang
    assert row["state"]["n1"] == {"v": 1}
    assert de.resume_execution(ex["id"]) is True
    assert de.get_execution(ex["id"])["status"] == "running"
    print(f"\n[11] macet terdeteksi+terklaim -> interrupted -> resume=running; "
          f"state utuh={row['state']}")


# --- 12. RECOVERY: yang MENUNGGU sinyal tidak ikut dipulihkan --------------
def test_12_yang_menunggu_tidak_dipulihkan(ctx):
    ex = _ex(ctx)
    de.wait_for_signal(ex["id"], "approval")
    basi = de._iso(de._now_utc() - __import__("datetime").timedelta(minutes=30))
    ctx["svc"].table("executions").update({"heartbeat_at": basi}) \
        .eq("id", ex["id"]).execute()
    ids = de.stuck_execution_ids()
    assert ex["id"] not in ids, "eksekusi yang menunggu sinyal JANGAN dipulihkan"
    print(f"\n[12] menunggu 30 mnt -> TIDAK masuk daftar macet ({len(ids)} kandidat)")


# --- 13. KEAMANAN: user lain tidak bisa membaca ----------------------------
def test_13_isolasi_antar_user(ctx):
    ex = _ex(ctx)
    # pemilik asli boleh baca
    assert de.get_execution(ex["id"], user_id=ctx["uid"]) is not None
    # user lain TIDAK boleh
    asing = str(uuid.uuid4())
    assert de.get_execution(ex["id"], user_id=asing) is None, \
        "KEBOCORAN: user lain bisa membaca eksekusi"
    print("\n[13] pemilik=boleh, user asing=None (terisolasi)")


# --- 14. PERFORMA: checkpoint cepat ----------------------------------------
def test_14_performa_checkpoint(ctx):
    ex = _ex(ctx)
    n = 30
    t0 = time.perf_counter()
    for i in range(n):
        sid = f"p{i}"
        de.begin_step(ex["id"], sid)
        de.finish_step(ex["id"], sid, {"i": i})
    dt = time.perf_counter() - t0
    per = dt / n
    print(f"\n[14] {n} checkpoint = {dt:.2f}s (rata-rata {per*1000:.0f} ms)")
    assert per < 1.5, f"checkpoint lambat: {per*1000:.0f} ms per node"
    assert len(de.done_steps(ex["id"])) == n
