# tests/test_retry_dlq.py — Fitur #3 (8 Okt 2026)
# =====================================================================
# Hard test retry + backoff + DLQ + circuit breaker. Min 10 skenario.
# `sleep` disuntik no-op supaya tes cepat tapi logika backoff tetap diuji
# (nilai delay diperiksa terpisah di test_03).
# =====================================================================
import uuid

import pytest

import database as db
import retry_policy as rp


@pytest.fixture()
def ctx():
    """User + workflow + eksekusi nyata untuk mengaitkan baris DLQ."""
    import psycopg2, os
    svc = db.get_write_client()
    uid = str(uuid.uuid4())
    wid = str(uuid.uuid4())
    exid = str(uuid.uuid4())
    email = f"dlq-{uid[:8]}@katalir-test.local"

    ref = db.SUPABASE_URL.split("//")[1].split(".")[0]
    pg = psycopg2.connect(host="aws-0-ap-southeast-1.pooler.supabase.com",
        port=5432, user=f"postgres.{ref}",
        password=os.environ["SUPABASE_DB_PASSWORD"], dbname="postgres",
        connect_timeout=10, sslmode="require")
    pg.autocommit = True
    pg.cursor().execute(
        "insert into auth.users (id,email,aud,role) values (%s,%s,%s,%s)",
        (uid, email, "authenticated", "authenticated"))

    svc.table("users").insert({"id": uid, "email": email,
                               "name": "DLQ", "tier": "free"}).execute()
    svc.table("workflows").insert({"id": wid, "user_id": uid,
                                   "name": "dlq-t", "flow_data": {}}).execute()
    svc.table("executions").insert({"id": exid, "workflow_id": wid,
                                    "status": "running"}).execute()

    yield {"uid": uid, "wid": wid, "exid": exid, "svc": svc, "pg": pg}

    svc.table("dead_letter_queue").delete().eq("user_id", uid).execute()
    svc.table("executions").delete().eq("id", exid).execute()
    svc.table("workflows").delete().eq("id", wid).execute()
    svc.table("users").delete().eq("id", uid).execute()
    try:
        pg.cursor().execute("delete from auth.users where id=%s", (uid,))
    except Exception:  # noqa: BLE001
        pass
    pg.close()


def _nol(_):
    """sleep no-op: jangan benar-benar menunggu di tes."""
    pass


# --- 1. retry: sukses setelah beberapa percobaan ---------------------------
def test_01_sukses_setelah_retry():
    n = {"c": 0}

    def fn():
        n["c"] += 1
        if n["c"] < 3:
            raise ConnectionError("jaringan putus")
        return "ok"

    ok, hasil, err, try_ = rp.with_retry(fn, sleep=_nol)
    assert ok and hasil == "ok" and try_ == 3, f"ok={ok} try={try_}"
    print(f"\n[1] gagal 2x lalu sukses: percobaan={try_} hasil={hasil}")


# --- 2. retry: menyerah setelah max_attempts -------------------------------
def test_02_menyerah_setelah_max():
    n = {"c": 0}

    def fn():
        n["c"] += 1
        raise TimeoutError("terus timeout")

    ok, hasil, err, try_ = rp.with_retry(fn, max_attempts=4, sleep=_nol)
    assert not ok and try_ == 4, f"try={try_}"
    assert "TimeoutError" in err, err
    print(f"\n[2] selalu gagal -> percobaan={try_} error={err[:40]}")


# --- 3. backoff: naik eksponensial + jitter --------------------------------
def test_03_backoff_eksponensial():
    d1 = rp.backoff_delay(1, base=1.0, cap=100, jitter=0)
    d2 = rp.backoff_delay(2, base=1.0, cap=100, jitter=0)
    d3 = rp.backoff_delay(3, base=1.0, cap=100, jitter=0)
    assert (d1, d2, d3) == (1.0, 2.0, 4.0), f"{d1},{d2},{d3}"
    # cap
    assert rp.backoff_delay(20, base=1.0, cap=30, jitter=0) == 30
    # jitter memberi variasi
    vals = {round(rp.backoff_delay(3, base=1.0, cap=100, jitter=0.25), 4)
            for _ in range(20)}
    assert len(vals) > 1, "jitter tidak memberi variasi"
    print(f"\n[3] backoff 1,2,4 = benar; cap=30 OK; jitter variasi={len(vals)} nilai")


# --- 4. klasifikasi error: ValueError TIDAK di-retry ----------------------
def test_04_valueerror_tidak_di_retry():
    n = {"c": 0}

    def fn():
        n["c"] += 1
        raise ValueError("input salah")

    ok, _, err, try_ = rp.with_retry(fn, max_attempts=5, sleep=_nol)
    assert not ok and try_ == 1, f"ValueError harus 1 percobaan, dapat {try_}"
    print(f"\n[4] ValueError -> percobaan={try_} (harus 1, tidak di-retry)")


# --- 5. klasifikasi error: TypeError & KeyError juga tidak di-retry -------
def test_05_error_pemrograman_tidak_di_retry():
    for exc in (TypeError("t"), KeyError("k"), AttributeError("a")):
        ok, _, _, try_ = rp.with_retry(
            lambda e=exc: (_ for _ in ()).throw(e), max_attempts=5, sleep=_nol)
        assert not ok and try_ == 1, f"{type(exc).__name__} -> {try_} percobaan"
    assert rp.is_retryable(ConnectionError()) is True
    assert rp.is_retryable(TimeoutError()) is True
    assert rp.is_retryable(ValueError()) is False
    print("\n[5] TypeError/KeyError/AttributeError -> 1 percobaan; "
          "ConnectionError/TimeoutError -> retryable")


# --- 6. circuit breaker: membuka setelah fail_max -------------------------
def test_06_sirkuit_terbuka():
    nama = f"cb-{uuid.uuid4().hex[:8]}"
    assert rp.circuit_allows(nama) is True
    for i in range(rp.CB_FAIL_MAX - 1):
        rp.circuit_failure(nama, f"gagal {i}")
    assert rp.circuit_state(nama) == "closed", "belum boleh terbuka"
    state = rp.circuit_failure(nama, "gagal terakhir")
    assert state == "open" and rp.circuit_state(nama) == "open"
    assert rp.circuit_allows(nama) is False, "sirkuit terbuka harus menolak"
    print(f"\n[6] {rp.CB_FAIL_MAX} gagal -> state={state}, "
          f"allows={rp.circuit_allows(nama)}")


# --- 7. circuit breaker: menutup lagi setelah sukses ----------------------
def test_07_sirkuit_menutup_setelah_sukses():
    nama = f"cb-{uuid.uuid4().hex[:8]}"
    for _ in range(rp.CB_FAIL_MAX):
        rp.circuit_failure(nama)
    assert rp.circuit_state(nama) == "open"
    rp.circuit_success(nama)
    assert rp.circuit_state(nama) == "closed"
    assert rp.circuit_allows(nama) is True
    print("\n[7] setelah sukses -> closed + allows=True")


# --- 8. circuit breaker: state PERSISTEN (tahan restart) ------------------
def test_08_sirkuit_persisten():
    """Ini keunggulan vs pybreaker in-memory: state ada di DB."""
    nama = f"persist-{uuid.uuid4().hex[:8]}"
    for _ in range(rp.CB_FAIL_MAX):
        rp.circuit_failure(nama, "down")
    # baca ulang dari DB lewat query segar
    rows = (db.get_write_client().table("circuit_breakers").select("*")
            .eq("name", nama).limit(1).execute()).data or []
    assert rows and rows[0]["state"] == "open", f"state di DB: {rows}"
    print(f"\n[8] state di DB = {rows[0]['state']} (tahan restart, "
          f"bukan in-memory)")


# --- 9. DLQ: node gagal masuk DLQ ----------------------------------------
def test_09_gagal_masuk_dlq(ctx):
    def fn():
        raise ConnectionError("server mati")

    hasil = rp.run_protected(
        fn, execution_id=ctx["exid"], workflow_id=ctx["wid"],
        user_id=ctx["uid"], step_id="node_x", node_type="http",
        max_attempts=3, sleep=_nol, payload={"url": "https://x"})

    assert hasil["ok"] is False and hasil["dlq"] is True
    assert hasil["attempts"] == 3
    items = rp.list_dlq(ctx["uid"])
    assert len(items) == 1, f"DLQ: {items}"
    it = items[0]
    assert it["step_id"] == "node_x" and it["attempts"] == 3
    assert it["last_error"].startswith("ConnectionError")
    assert it["payload"] == {"url": "https://x"}
    print(f"\n[9] DLQ: step={it['step_id']} attempts={it['attempts']} "
          f"status={it['status']} err={it['last_error'][:35]}")


# --- 10. DLQ: idempoten (tidak menumpuk) ---------------------------------
def test_10_dlq_idempoten(ctx):
    def fn():
        raise ConnectionError("x")

    for _ in range(3):
        rp.run_protected(fn, execution_id=ctx["exid"], workflow_id=ctx["wid"],
                         user_id=ctx["uid"], step_id="node_dup",
                         max_attempts=2, sleep=_nol)
    items = [i for i in rp.list_dlq(ctx["uid"]) if i["step_id"] == "node_dup"]
    assert len(items) == 1, f"DLQ menumpuk: {len(items)} baris"
    print(f"\n[10] 3x gagal pada node sama -> {len(items)} baris DLQ (idempoten)")


# --- 11. DLQ: sukses TIDAK masuk DLQ -------------------------------------
def test_11_sukses_tidak_masuk_dlq(ctx):
    hasil = rp.run_protected(lambda: "aman", execution_id=ctx["exid"],
                             workflow_id=ctx["wid"], user_id=ctx["uid"],
                             step_id="node_ok", sleep=_nol)
    assert hasil["ok"] is True and hasil["dlq"] is False
    assert rp.list_dlq(ctx["uid"]) == []
    print("\n[11] sukses -> dlq=False, DLQ tetap kosong")


# --- 12. DLQ: sirkuit terbuka -> fail fast TANPA memanggil fn -------------
def test_12_sirkuit_terbuka_fail_fast(ctx):
    nama = f"node:http-{uuid.uuid4().hex[:8]}"
    for _ in range(rp.CB_FAIL_MAX):
        rp.circuit_failure(nama, "down")
    assert rp.circuit_state(nama) == "open"

    dipanggil = {"n": 0}

    def fn():
        dipanggil["n"] += 1
        return "tidak boleh jalan"

    hasil = rp.run_protected(fn, execution_id=ctx["exid"],
                             workflow_id=ctx["wid"], user_id=ctx["uid"],
                             step_id="node_cb", breaker=nama,
                             max_attempts=3, sleep=_nol)
    assert hasil["ok"] is False and hasil["circuit"] == "open"
    assert dipanggil["n"] == 0, f"fn tetap dipanggil {dipanggil['n']}x (harus 0)"
    assert hasil["dlq"] is True, "fail-fast harus tetap dicatat ke DLQ"
    print(f"\n[12] sirkuit open -> fn dipanggil {dipanggil['n']}x (harus 0), "
          f"dicatat ke DLQ")


# --- 13. DLQ: klaim atomik (anti dobel-retry) ----------------------------
def test_13_klaim_dlq_atomik(ctx):
    rp.push_dlq(execution_id=ctx["exid"], workflow_id=ctx["wid"],
                user_id=ctx["uid"], step_id="node_claim",
                attempts=3, last_error="x")
    it = [i for i in rp.list_dlq(ctx["uid"]) if i["step_id"] == "node_claim"][0]

    first = rp.claim_dlq(it["id"], ctx["uid"])
    second = rp.claim_dlq(it["id"], ctx["uid"])
    assert first is not None, "klaim pertama harus berhasil"
    assert not second, f"klaim kedua harus gagal (dapat {second})"
    print(f"\n[13] klaim#1={bool(first)} klaim#2={bool(second)} "
          f"(anti dobel-retry)")


# --- 14. KEAMANAN: user lain tidak bisa lihat/klaim DLQ ------------------
def test_14_isolasi_dlq(ctx):
    rp.push_dlq(execution_id=ctx["exid"], workflow_id=ctx["wid"],
                user_id=ctx["uid"], step_id="node_secret",
                attempts=1, last_error="rahasia")
    it = [i for i in rp.list_dlq(ctx["uid"]) if i["step_id"] == "node_secret"][0]
    asing = str(uuid.uuid4())

    assert rp.list_dlq(asing) == [], "user asing melihat DLQ orang lain"
    assert rp.dlq_item(it["id"], asing) is None, "KEBOCORAN: item terbaca"
    assert rp.claim_dlq(it["id"], asing) is None, "KEBOCORAN: item terklaim"
    assert rp.discard_dlq(it["id"], asing) is False, "KEBOCORAN: item dibuang"
    # pemilik tetap bisa
    assert rp.dlq_item(it["id"], ctx["uid"]) is not None
    print("\n[14] user asing: list=[] item=None claim=None discard=False "
          "(terisolasi)")


# --- 15. statistik DLQ ----------------------------------------------------
def test_15_statistik_dlq(ctx):
    rp.push_dlq(execution_id=ctx["exid"], workflow_id=ctx["wid"],
                user_id=ctx["uid"], step_id="s1", last_error="a")
    rp.push_dlq(execution_id=ctx["exid"], workflow_id=ctx["wid"],
                user_id=ctx["uid"], step_id="s2", last_error="b")
    st = rp.dlq_stats(ctx["uid"])
    assert st.get("pending", 0) >= 2, f"stats: {st}"
    print(f"\n[15] dlq_stats={st}")


# --- 16. PERFORMA: biaya retry + DLQ -------------------------------------
def test_16_performa(ctx):
    import time
    def fn():
        raise ConnectionError("x")
    t0 = time.perf_counter()
    for i in range(10):
        rp.run_protected(fn, execution_id=ctx["exid"], workflow_id=ctx["wid"],
                         user_id=ctx["uid"], step_id=f"perf{i}",
                         max_attempts=3, sleep=_nol)
    dt = time.perf_counter() - t0
    print(f"\n[16] 10 node x 3 percobaan + DLQ = {dt:.2f}s "
          f"({dt/10*1000:.0f} ms/node)")
    assert dt < 40, f"terlalu lambat: {dt:.1f}s"
