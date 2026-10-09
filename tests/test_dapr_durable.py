"""tests/test_dapr_durable.py — TASK 6 / Fitur #9 hard tests.

12 uji wajib: 2 basic, 2 edge, 2 error, 2 performance, 1 security, 1 E2E.
Semua memakai LocalStore + activity bersih (autouse fixture) agar deterministik.
"""
from __future__ import annotations

import importlib
import threading
import time
import uuid

import pytest

import dapr_durable as dd


@pytest.fixture(autouse=True)
def _bersih():
    """Registry + store bersih per uji. Backend dipaksa 'local' agar tidak
    menyentuh Supabase (uji unit harus hermetis)."""
    dd.reset_activities()
    yield
    dd.reset_activities()


@pytest.fixture
def store():
    return dd.LocalStore()


# ---------------------------------------------------------------------------
# B1 — basic: workflow 3 langkah berjalan berurutan
# ---------------------------------------------------------------------------

def B1():
    jejak = []

    dd.activity("b1_a")(lambda x: (jejak.append("a"), 1)[1])
    dd.activity("b1_b")(lambda x: (jejak.append("b"), x + 1)[1])
    dd.activity("b1_c")(lambda x: (jejak.append("c"), x * 2)[1])

    hasil = dd.run_workflow(
        [("s1", "b1_a"), ("s2", "b1_b"), ("s3", "b1_c")],
        name="B1", store=dd.LocalStore())

    assert jejak == ["a", "b", "c"], jejak
    assert hasil["executed"] == ["s1", "s2", "s3"]
    assert hasil["status"] == dd.STATUS_COMPLETED
    assert hasil["output"] == 4


# ---------------------------------------------------------------------------
# B2 — basic: output langkah N menjadi input langkah N+1
# ---------------------------------------------------------------------------

def B2():
    dd.activity("b2_gandakan")(lambda x: (x or 1) * 2)
    dd.activity("b2_tambah")(lambda x: x + 10)

    hasil = dd.run_workflow(
        [("s1", "b2_gandakan"), ("s2", "b2_tambah")],
        name="B2", store=dd.LocalStore())

    # 1*2=2, lalu 2+10=12
    assert hasil["output"] == 12, hasil


# ---------------------------------------------------------------------------
# E1 — edge: REPLAY. Langkah yang sudah sukses tidak dijalankan ulang.
# ---------------------------------------------------------------------------

def E1():
    jalan = []

    dd.activity("e1_a")(lambda x: (jalan.append("a"), "A")[1])
    dd.activity("e1_b")(lambda x: (jalan.append("b"), "B")[1])

    st = dd.LocalStore()
    ex = str(uuid.uuid4())

    p1 = dd.run_workflow([("s1", "e1_a"), ("s2", "e1_b")], name="E1",
                         execution_id=ex, store=st)
    assert p1["executed"] == ["s1", "s2"]
    assert jalan == ["a", "b"]

    # jalankan ulang id yang sama -> SEMUA langkah di-replay
    p2 = dd.run_workflow([("s1", "e1_a"), ("s2", "e1_b")], name="E1",
                         execution_id=ex, store=st)

    assert jalan == ["a", "b"], f"langkah terulang: {jalan}"
    assert p2["replayed"] == ["s1", "s2"], p2
    assert p2["executed"] == [], p2


# ---------------------------------------------------------------------------
# E2 — edge: RESUME dari tengah. Langkah 1 sudah sukses, 2 & 3 dieksekusi.
# ---------------------------------------------------------------------------

def E2():
    jalan = []

    dd.activity("e2_a")(lambda x: (jalan.append("a"), 1)[1])
    dd.activity("e2_b")(lambda x: (jalan.append("b"), x + 1)[1])
    dd.activity("e2_c")(lambda x: (jalan.append("c"), x + 1)[1])

    st = dd.LocalStore()
    ex = str(uuid.uuid4())
    langkah = [("s1", "e2_a"), ("s2", "e2_b"), ("s3", "e2_c")]

    # Simulasikan: s1 sudah sukses sebelumnya, sisanya belum.
    st.put_execution({"id": ex, "workflow_id": "E2", "status": "RUNNING",
                      "state": {}})
    st.put_step(ex, "s1", {"node_type": "e2_a", "status": "success",
                           "output": 1})

    hasil = dd.run_workflow(langkah, name="E2", execution_id=ex, store=st)

    assert hasil["replayed"] == ["s1"], hasil
    assert hasil["executed"] == ["s2", "s3"], hasil
    assert jalan == ["b", "c"], f"a seharusnya TIDAK jalan: {jalan}"
    assert hasil["output"] == 3      # 1 + 1 + 1


# ---------------------------------------------------------------------------
# X1 — error: activity gagal -> kompensasi langkah sebelumnya (urutan TERBALIK)
# ---------------------------------------------------------------------------

def X1():
    urutan = []

    dd.activity("x1_bayar", compensate=lambda o: urutan.append("batal-bayar"))(
        lambda x: (urutan.append("bayar"), "PAY-1")[1])
    dd.activity("x1_stok", compensate=lambda o: urutan.append("batal-stok"))(
        lambda x: (urutan.append("stok"), "STOK-1")[1])

    def _gagal(_):
        urutan.append("kirim")
        raise RuntimeError("kurir tidak tersedia")

    dd.activity("x1_kirim")(_gagal)

    hasil = dd.run_workflow(
        [("s1", "x1_bayar"), ("s2", "x1_stok"), ("s3", "x1_kirim")],
        name="X1", store=dd.LocalStore())

    assert hasil["status"] == dd.STATUS_COMPENSATED, hasil
    assert hasil["compensated"] == ["s2", "s1"], hasil["compensated"]
    # kompensasi HARUS terbalik: stok dulu, baru bayar
    assert urutan == ["bayar", "stok", "kirim", "batal-stok", "batal-bayar"], urutan


# ---------------------------------------------------------------------------
# X2 — error: kompensasi yang gagal dikumpulkan, tidak menelan error asli
# ---------------------------------------------------------------------------

def X2():
    def _batal_meledak(_):
        raise RuntimeError("rollback pun gagal")

    dd.activity("x2_bayar", compensate=_batal_meledak)(lambda x: "PAY")
    dd.activity("x2_gagal")(lambda x: (_ for _ in ()).throw(ValueError("boom")))

    hasil = dd.run_workflow(
        [("s1", "x2_bayar"), ("s2", "x2_gagal")],
        name="X2", store=dd.LocalStore())

    assert "boom" in (hasil["error"] or ""), hasil
    assert len(hasil["compensation_errors"]) == 1, hasil
    assert "rollback pun gagal" in hasil["compensation_errors"][0]
    assert hasil["compensated"] == [], hasil


# ---------------------------------------------------------------------------
# P1 — performance: 200 langkah selesai cepat
# ---------------------------------------------------------------------------

def P1():
    for i in range(200):
        dd.activity(f"p1_{i}")(lambda x: (x or 0) + 1)

    langkah = [(f"s{i}", f"p1_{i}") for i in range(200)]
    t0 = time.time()
    hasil = dd.run_workflow(langkah, name="P1", store=dd.LocalStore())
    durasi = time.time() - t0

    assert hasil["status"] == dd.STATUS_COMPLETED
    assert len(hasil["executed"]) == 200
    assert durasi < 5.0, f"terlalu lambat: {durasi:.2f}s"


# ---------------------------------------------------------------------------
# P2 — performance: replay 200 langkah jauh lebih murah daripada eksekusi
# ---------------------------------------------------------------------------

def P2():
    panggilan = []

    def _buat(i):
        def _fn(x):
            panggilan.append(i)
            return (x or 0) + 1
        return _fn

    for i in range(200):
        dd.activity(f"p2_{i}")(_buat(i))

    langkah = [(f"s{i}", f"p2_{i}") for i in range(200)]
    st = dd.LocalStore()
    ex = str(uuid.uuid4())

    dd.run_workflow(langkah, name="P2", execution_id=ex, store=st)
    n_setelah_eksekusi = len(panggilan)
    assert n_setelah_eksekusi == 200

    t0 = time.time()
    ulang = dd.run_workflow(langkah, name="P2", execution_id=ex, store=st)
    durasi = time.time() - t0

    assert len(panggilan) == 200, "replay memanggil activity lagi!"
    assert len(ulang["replayed"]) == 200
    assert durasi < 2.0, f"replay terlalu lambat: {durasi:.2f}s"


# ---------------------------------------------------------------------------
# S1 — security: ledger idempotensi mencegah efek samping terjadi dua kali
# ---------------------------------------------------------------------------

def S1():
    tagihan = []

    dd.activity("s1_tagih")(lambda x: (tagihan.append(1), "CHARGE-1")[1])
    dd.activity("s1_lanjut")(lambda x: "OK")

    st = dd.LocalStore()
    ex = str(uuid.uuid4())
    langkah = [("s1", "s1_tagih"), ("s2", "s1_lanjut")]

    dd.run_workflow(langkah, name="S1", execution_id=ex, store=st)
    assert len(tagihan) == 1

    # Hapus checkpoint langkah (mensimulasikan crash setelah efek samping
    # terjadi TAPI sebelum status node tercatat) — inilah kasus nyata dari
    # artikel Diagrid. Ledger harus menyelamatkan.
    st.steps.pop((ex, "s1"), None)

    ulang = dd.run_workflow(langkah, name="S1", execution_id=ex, store=st)

    assert len(tagihan) == 1, f"kartu ditagih {len(tagihan)}x — ledger gagal!"
    assert "s1" in ulang["replayed"], ulang
    assert ulang["status"] == dd.STATUS_COMPLETED


# ---------------------------------------------------------------------------
# I1 — E2E: crash & recover. Langkah 1-2 tidak terulang, hanya 3 jalan.
# ---------------------------------------------------------------------------

def I1():
    jejak = []

    dd.activity("i1_a")(lambda x: (jejak.append("LANGKAH-1"), "P1")[1])
    dd.activity("i1_b")(lambda x: (jejak.append("LANGKAH-2"), "P2")[1])
    dd.activity("i1_c")(lambda x: (jejak.append("LANGKAH-3"), "SELESAI")[1])

    st = dd.LocalStore()
    ex = str(uuid.uuid4())
    langkah = [("s1", "i1_a"), ("s2", "i1_b"), ("s3", "i1_c")]

    # FASE 1 — proses "mati" setelah langkah 2 (checkpoint s1,s2 tertulis,
    # s3 belum).
    terdahulu = dd.WorkflowRunner(store=st)
    wf = dd.Workflow(name="I1", steps=langkah[:2])
    r1 = terdahulu.run(wf, execution_id=ex)
    assert r1.executed == ["s1", "s2"]
    assert jejak == ["LANGKAH-1", "LANGKAH-2"]
    assert st.get_execution(ex) is not None

    # FASE 2 — RECOVER: jalankan workflow penuh dengan execution_id sama.
    r2 = dd.run_workflow(langkah, name="I1", execution_id=ex, store=st)

    assert jejak == ["LANGKAH-1", "LANGKAH-2", "LANGKAH-3"], \
        f"efek samping terulang: {jejak}"
    assert r2["replayed"] == ["s1", "s2"], r2
    assert r2["executed"] == ["s3"], r2
    assert r2["status"] == dd.STATUS_COMPLETED


# ---------------------------------------------------------------------------
# Pembungkus pytest — supaya tiap fungsi di atas jadi satu test case.
# ---------------------------------------------------------------------------

def test_B1_basic_urutan():
    B1()


def test_B2_basic_data_chain():
    B2()


def test_E1_edge_replay_tidak_ulang():
    E1()


def test_E2_edge_resume_dari_tengah():
    E2()


def test_X1_error_kompensasi_terbalik():
    X1()


def test_X2_error_kompensasi_gagal_dikumpulkan():
    X2()


def test_P1_perf_200_langkah():
    P1()


def test_P2_perf_replay_200_langkah():
    P2()


def test_S1_security_ledger_idempoten():
    S1()


def test_I1_e2e_crash_dan_recover():
    I1()


# ---------------------------------------------------------------------------
# Validasi tambahan (bagian dari error handling)
# ---------------------------------------------------------------------------

def test_X3_activity_tak_terdaftar_ditolak():
    with pytest.raises(dd.WorkflowValidationError):
        dd.Workflow(name="X3", steps=[("s1", "tidak_ada")])


def test_X4_step_id_duplikat_ditolak():
    dd.activity("x4_a")(lambda x: x)
    with pytest.raises(dd.WorkflowValidationError):
        dd.Workflow(name="X4", steps=[("s1", "x4_a"), ("s1", "x4_a")])


def test_X5_workflow_tanpa_langkah_ditolak():
    with pytest.raises(dd.WorkflowValidationError):
        dd.Workflow(name="X5", steps=[])


def test_activity_duplikat_ditolak():
    dd.activity("dup")(lambda x: x)
    with pytest.raises(dd.WorkflowValidationError):
        dd.activity("dup")(lambda x: x)


def test_backend_status_jujur():
    st = dd.backend_status()
    assert st["selected"] in dd.BACKENDS
    assert "dapr" in st["available"]
    # Dapr tidak boleh diklaim tersedia bila modulnya tidak ada.
    assert st["available"]["dapr"] == dd._module_available("dapr.ext.workflow")


def test_describe_kontrak():
    d = dd.describe()
    assert d["status"] == "success"
    assert d["max_steps"] == dd.MAX_STEPS_PER_WORKFLOW
    assert len(d["statuses"]) == 6
    assert len(d["principles"]) == 5


def test_idempotency_key_stabil():
    k1 = dd.idempotency_key("wf", "ex", "s1")
    k2 = dd.idempotency_key("wf", "ex", "s1")
    k3 = dd.idempotency_key("wf", "ex", "s2")
    assert k1 == k2 and k1 != k3


# ---------------------------------------------------------------------------
# I2 — E2E: store Supabase NYATA + proses Linux terpisah (bila terkonfigurasi).
# Dilewati (skip) dengan jujur bila Supabase tidak dikonfigurasi.
# ---------------------------------------------------------------------------

def test_I2_supabase_lintas_proses():
    import subprocess
    import sys

    try:
        import database as db
        if not db.is_configured():
            pytest.skip("Supabase tidak dikonfigurasi")
        wfs = (db.get_write_client().table("workflows")
               .select("id").limit(1).execute()).data
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Supabase tidak siap: {type(exc).__name__}")
    if not wfs:
        pytest.skip("tidak ada workflow untuk diuji")

    wf_id = wfs[0]["id"]
    store = dd.default_store()
    # Lewati bila store bukan adapter Supabase.
    if not hasattr(store, "ensure_execution"):
        pytest.skip("store bukan adapter Supabase")

    ex = str(uuid.uuid4())
    dd.reset_activities()
    jejak: list[str] = []
    dd.activity("i2_a")(lambda x: (jejak.append("L1"), "P1")[1])
    dd.activity("i2_b")(lambda x: (jejak.append("L2"), "P2")[1])
    dd.activity("i2_c")(lambda x: (jejak.append("L3"), "OK")[1])

    r1 = dd.WorkflowRunner(store=store).run(
        dd.Workflow(name="I2", steps=[("s1", "i2_a"), ("s2", "i2_b")],
                    workflow_uuid=wf_id), execution_id=ex)
    assert r1.executed == ["s1", "s2"]

    # Proses TERPISAH: tidak ada state memori yang dibagi.
    kode = (
        "from dotenv import load_dotenv;"
        "load_dotenv(dotenv_path='C:/Users/user/Proyek_AI/.env');"
        "import dapr_durable as dd;"
        "dd.activity('i2_c')(lambda x:'OK');"
        "dd.activity('i2_a')(lambda x:'P1');"
        "dd.activity('i2_b')(lambda x:'P2');"
        "r=dd.WorkflowRunner(store=dd.default_store()).run("
        "dd.Workflow(name='I2',steps=[('s1','i2_a'),('s2','i2_b'),('s3','i2_c')],"
        f"workflow_uuid='{wf_id}'),execution_id='{ex}');"
        "print(len(r.replayed), len(r.executed), r.status)"
    )
    proc = subprocess.run([sys.executable, "-c", kode], capture_output=True,
                          text=True, cwd="C:/Users/user/Proyek_AI", timeout=120)
    assert proc.returncode == 0, proc.stderr[-800:]

    # Proses-1 hanya menjalankan s1,s2. Maka proses-2 harus me-replay 2
    # langkah itu dan mengeksekusi HANYA langkah baru (s3).
    assert proc.stdout.strip() == f"2 1 {dd.STATUS_COMPLETED}", proc.stdout

    import durable_execution as de
    de._svc().table("executions").delete().eq("id", ex).execute()


def test_I3_workflow_uuid_wajib_untuk_supabase():
    """Store Supabase harus MENOLAK checkpoint tanpa workflow_uuid (FK)."""
    import database as db

    if not db.is_configured():
        pytest.skip("Supabase tidak dikonfigurasi")
    store = dd.default_store()
    if not hasattr(store, "ensure_execution"):
        pytest.skip("store bukan adapter Supabase")

    dd.activity("i3_a")(lambda x: x)
    with pytest.raises(dd.DurableError):
        dd.WorkflowRunner(store=store).run(
            dd.Workflow(name="I3", steps=[("s1", "i3_a")]))
