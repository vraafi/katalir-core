# tests/test_subworkflow.py — Fitur #4 (8 Okt 2026)
# =====================================================================
# Hard test sub-workflow. Min 8 skenario.
#
# Fokus khusus: SIKLUS (A->B->A) — persis kasus yang TIDAK ditangani
# desain referensi (tg-flow mengizinkan kedalaman tak terbatas).
# =====================================================================
import os
import uuid

import psycopg2
import pytest

import database as db
import durable_execution as de
import subworkflow as sw


def _pg():
    ref = db.SUPABASE_URL.split("//")[1].split(".")[0]
    c = psycopg2.connect(host="aws-0-ap-southeast-1.pooler.supabase.com",
        port=5432, user=f"postgres.{ref}",
        password=os.environ["SUPABASE_DB_PASSWORD"], dbname="postgres",
        connect_timeout=10, sslmode="require")
    c.autocommit = True
    return c


@pytest.fixture()
def ctx():
    """Satu user + 3 workflow (induk, anak, cucu) milik user yang sama."""
    svc = db.get_write_client()
    uid = str(uuid.uuid4())
    wf_parent = str(uuid.uuid4())
    wf_child = str(uuid.uuid4())
    wf_grand = str(uuid.uuid4())
    email = f"sub-{uid[:8]}@katalir-test.local"

    pg = _pg()
    pg.cursor().execute(
        "insert into auth.users (id,email,aud,role) values (%s,%s,%s,%s)",
        (uid, email, "authenticated", "authenticated"))
    svc.table("users").insert({"id": uid, "email": email,
                               "name": "SUB", "tier": "free"}).execute()
    for wf, nm in ((wf_parent, "induk"), (wf_child, "anak"), (wf_grand, "cucu")):
        svc.table("workflows").insert({"id": wf, "user_id": uid, "name": nm,
                                       "flow_data": {}}).execute()

    ex = de.start_execution(wf_parent)

    yield {"uid": uid, "svc": svc, "pg": pg, "ex": ex["id"],
           "wf_parent": wf_parent, "wf_child": wf_child, "wf_grand": wf_grand}

    svc.table("subworkflow_invocations").delete() \
        .eq("parent_execution_id", ex["id"]).execute()
    svc.table("workflow_call_chain").delete() \
        .eq("execution_id", ex["id"]).execute()
    svc.table("executions").delete().eq("workflow_id", wf_parent).execute()
    svc.table("executions").delete().eq("workflow_id", wf_child).execute()
    svc.table("executions").delete().eq("workflow_id", wf_grand).execute()
    for wf in (wf_parent, wf_child, wf_grand):
        svc.table("workflows").delete().eq("id", wf).execute()
    svc.table("users").delete().eq("id", uid).execute()
    try:
        pg.cursor().execute("delete from auth.users where id=%s", (uid,))
    except Exception:  # noqa: BLE001
        pass
    pg.close()


# --- 1. pemanggilan dasar -------------------------------------------------
def test_01_panggil_subworkflow(ctx):
    hasil = sw.invoke_subworkflow(
        parent_execution_id=ctx["ex"], step_id="s1",
        child_workflow_id=ctx["wf_child"], user_id=ctx["uid"],
        input_data={"x": 1}, runner=lambda wf, inp, d: {"balik": inp["x"] * 2})

    assert hasil["ok"] is True, hasil
    assert hasil["output"] == {"balik": 2}, hasil
    assert hasil["depth"] == 1
    print(f"\n[1] ok={hasil['ok']} output={hasil['output']} depth={hasil['depth']}")


# --- 2. eksekusi anak benar-benar dibuat ---------------------------------
def test_02_eksekusi_anak_dibuat(ctx):
    hasil = sw.invoke_subworkflow(
        parent_execution_id=ctx["ex"], step_id="s2",
        child_workflow_id=ctx["wf_child"], user_id=ctx["uid"],
        runner=lambda wf, inp, d: "selesai")

    anak = de.get_execution(hasil["child_execution_id"])
    assert anak is not None
    assert anak["parent_execution_id"] == ctx["ex"], "parent harus terhubung"
    assert anak["depth"] == 1
    assert anak["status"] == "success", anak["status"]
    print(f"\n[2] anak: parent terhubung, depth={anak['depth']}, "
          f"status={anak['status']}")


# --- 3. rantai 3 level (batas) -------------------------------------------
def test_03_rantai_tiga_level(ctx):
    """induk -> anak -> cucu. depth cucu harus 2, dan masih diizinkan."""
    h1 = sw.invoke_subworkflow(
        parent_execution_id=ctx["ex"], step_id="l1",
        child_workflow_id=ctx["wf_child"], user_id=ctx["uid"],
        runner=lambda wf, inp, d: None)
    assert h1["ok"] and h1["depth"] == 1

    h2 = sw.invoke_subworkflow(
        parent_execution_id=h1["child_execution_id"], step_id="l2",
        child_workflow_id=ctx["wf_grand"], user_id=ctx["uid"],
        runner=lambda wf, inp, d: None)
    assert h2["ok"], f"level 2 harus boleh: {h2}"
    assert h2["depth"] == 2
    print(f"\n[3] induk(depth0) -> anak(depth{h1['depth']}) -> "
          f"cucu(depth{h2['depth']}) — 3 level OK")


# --- 4. kedalaman ke-4 DITOLAK -------------------------------------------
def test_04_kedalaman_keempat_ditolak(ctx):
    """Naikkan kedalaman dengan workflow BERBEDA tiap level supaya yang diuji
    benar-benar batas KEDALAMAN, bukan siklus.

    Catatan (temuan tes, 8 Okt): versi pertama tes ini memakai `wf_child`
    dua kali dalam satu rantai -> pemeriksaan SIKLUS yang lebih dulu menangkap
    dan menolak, sehingga batas kedalaman tidak pernah teruji. Kode benar;
    tesnya yang keliru. Diperbaiki dengan membuat workflow baru per level.
    """
    svc, pg = ctx["svc"], ctx["pg"]
    wfs = []
    for i in range(5):                     # cukup untuk melewati batas 3
        wf = str(uuid.uuid4())
        svc.table("workflows").insert({"id": wf, "user_id": ctx["uid"],
                                       "name": f"lvl-{i}",
                                       "flow_data": {}}).execute()
        wfs.append(wf)

    ids = [ctx["ex"]]
    ditolak = None
    for i, wf in enumerate(wfs):
        h = sw.invoke_subworkflow(
            parent_execution_id=ids[-1], step_id=f"lvl{i}",
            child_workflow_id=wf, user_id=ctx["uid"],
            runner=lambda a, b, c: None)
        if not h["ok"]:
            ditolak = h
            break
        ids.append(h["child_execution_id"])

    try:
        assert ditolak is not None, (
            f"batas kedalaman tidak pernah tercapai; ids={len(ids)-1} level")
        assert ditolak["reason"] == "depth_or_cycle", ditolak
        assert "kedalaman" in ditolak["error"].lower(), ditolak["error"]
        assert ditolak["depth"] == 4, f"depth harus 4: {ditolak['depth']}"
        print(f"\n[4] level tertinggi yang diizinkan = depth {len(ids)-1}; "
              f"depth 4 ditolak: {ditolak['error'][:55]}")
    finally:
        svc.table("executions").delete().in_("workflow_id", wfs).execute()
        for wf in wfs:
            svc.table("workflows").delete().eq("id", wf).execute()


# --- 5. SIKLUS A->B->A DITOLAK (kasus yang luput di referensi) -----------
def test_05_siklus_ditolak(ctx):
    """induk memanggil anak; anak memanggil induk LAGI -> harus ditolak."""
    h1 = sw.invoke_subworkflow(
        parent_execution_id=ctx["ex"], step_id="cyc1",
        child_workflow_id=ctx["wf_child"], user_id=ctx["uid"],
        runner=lambda a, b, c: None)
    assert h1["ok"], h1

    # dari eksekusi ANAK, coba panggil workflow INDUK -> siklus
    h2 = sw.invoke_subworkflow(
        parent_execution_id=h1["child_execution_id"], step_id="cyc2",
        child_workflow_id=ctx["wf_parent"], user_id=ctx["uid"],
        runner=lambda a, b, c: None)
    assert h2["ok"] is False, f"SIKLUS HARUS DITOLAK tapi lolos: {h2}"
    assert "siklus" in h2["error"].lower(), h2["error"]
    print(f"\n[5] SIKLUS ditolak: {h2['error'][:60]} (reason={h2['reason']})")


# --- 6. idempotensi: step sama tidak memanggil anak dua kali ------------
def test_06_idempoten_per_step(ctx):
    panggilan = {"n": 0}

    def runner(wf, inp, d):
        panggilan["n"] += 1
        return "hasil"

    h1 = sw.invoke_subworkflow(
        parent_execution_id=ctx["ex"], step_id="idem",
        child_workflow_id=ctx["wf_child"], user_id=ctx["uid"], runner=runner)
    h2 = sw.invoke_subworkflow(
        parent_execution_id=ctx["ex"], step_id="idem",
        child_workflow_id=ctx["wf_child"], user_id=ctx["uid"], runner=runner)

    assert h1["ok"] and h2["ok"]
    assert panggilan["n"] == 1, f"runner dipanggil {panggilan['n']}x (harus 1)"
    assert h2["child_execution_id"] == h1["child_execution_id"]
    print(f"\n[6] 2x invoke step sama -> runner dipanggil {panggilan['n']}x, "
          f"anak sama={h2['child_execution_id'] == h1['child_execution_id']}")


# --- 7. KEAMANAN: tidak bisa memanggil workflow milik user lain --------
def test_07_tolak_workflow_user_lain(ctx):
    # workflow milik user lain
    lain = str(uuid.uuid4())
    email2 = f"other-{lain[:8]}@katalir-test.local"
    ctx["pg"].cursor().execute(
        "insert into auth.users (id,email,aud,role) values (%s,%s,%s,%s)",
        (lain, email2, "authenticated", "authenticated"))
    ctx["svc"].table("users").insert({"id": lain, "email": email2,
                                      "name": "X", "tier": "free"}).execute()
    wf_lain = str(uuid.uuid4())
    ctx["svc"].table("workflows").insert(
        {"id": wf_lain, "user_id": lain, "name": "milik-orang-lain",
         "flow_data": {}}).execute()
    try:
        hasil = sw.invoke_subworkflow(
            parent_execution_id=ctx["ex"], step_id="steal",
            child_workflow_id=wf_lain, user_id=ctx["uid"],
            runner=lambda a, b, c: "BOCOR")
        assert hasil["ok"] is False, f"harus ditolak: {hasil}"
        assert hasil["reason"] == "forbidden", hasil
        print(f"\n[7] workflow user lain ditolak: reason={hasil['reason']}")
    finally:
        ctx["svc"].table("workflows").delete().eq("id", wf_lain).execute()
        ctx["svc"].table("users").delete().eq("id", lain).execute()
        try:
            ctx["pg"].cursor().execute("delete from auth.users where id=%s", (lain,))
        except Exception:  # noqa: BLE001
            pass


# --- 8. anak gagal -> induk tahu, dicatat failed ------------------------
def test_08_anak_gagal_dicatat(ctx):
    def runner(wf, inp, d):
        raise RuntimeError("anak meledak")

    hasil = sw.invoke_subworkflow(
        parent_execution_id=ctx["ex"], step_id="gagal",
        child_workflow_id=ctx["wf_child"], user_id=ctx["uid"], runner=runner)

    assert hasil["ok"] is False
    assert "meledak" in hasil["error"], hasil["error"]
    anak = de.get_execution(hasil["child_execution_id"])
    assert anak["status"] == "failed", anak["status"]
    inv = sw.list_invocations(ctx["ex"], ctx["uid"])
    baris = [i for i in inv if i["step_id"] == "gagal"][0]
    assert baris["status"] == "failed" and "meledak" in (baris["error"] or "")
    print(f"\n[8] anak gagal -> ok=False, anak.status={anak['status']}, "
          f"invokasi tercatat failed")


# --- 9. jejak rantai tercatat (observabilitas + dasar deteksi siklus) ----
def test_09_rantai_tercatat(ctx):
    sw.invoke_subworkflow(
        parent_execution_id=ctx["ex"], step_id="chain1",
        child_workflow_id=ctx["wf_child"], user_id=ctx["uid"],
        runner=lambda a, b, c: None)
    rantai = sw.call_chain(ctx["ex"], ctx["uid"])
    assert len(rantai) >= 1, f"rantai kosong: {rantai}"
    assert rantai[0]["child_workflow_id"] == ctx["wf_child"]
    # user lain tidak boleh melihat
    assert sw.call_chain(ctx["ex"], str(uuid.uuid4())) == []
    print(f"\n[9] rantai tercatat={len(rantai)} baris; user asing -> []")


# --- 10. keamanan: list_invocations hanya untuk pemilik ------------------
def test_10_isolasi_invokasi(ctx):
    sw.invoke_subworkflow(
        parent_execution_id=ctx["ex"], step_id="iso",
        child_workflow_id=ctx["wf_child"], user_id=ctx["uid"],
        runner=lambda a, b, c: None)
    assert len(sw.list_invocations(ctx["ex"], ctx["uid"])) >= 1
    assert sw.list_invocations(ctx["ex"], str(uuid.uuid4())) == []
    print("\n[10] pemilik melihat invokasi; user asing -> []")


# --- 11. perf: overhead sub-workflow ------------------------------------
def test_11_performa(ctx):
    import time
    t0 = time.perf_counter()
    for i in range(10):
        sw.invoke_subworkflow(
            parent_execution_id=ctx["ex"], step_id=f"perf{i}",
            child_workflow_id=ctx["wf_child"], user_id=ctx["uid"],
            runner=lambda a, b, c: "x")
    dt = time.perf_counter() - t0
    print(f"\n[11] 10 sub-workflow = {dt:.2f}s ({dt/10*1000:.0f} ms/invoke)")
    assert dt < 60, f"terlalu lambat: {dt:.1f}s"
