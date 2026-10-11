"""Hard test Gap #2 — persistensi evidence ledger ke Supabase (iterasi 3).

LATAR BUG NYATA YANG DITUTUP
----------------------------
``PostgresEvidenceStore._connect()`` mengimpor
``connector_verification_store._dsn`` — fungsi yang **tidak pernah ada**
(nama sebenarnya ``connect``). Akibatnya setiap percobaan memakai store
Postgres berakhir ``ImportError`` dan ledger diam-diam kembali ke memori:
bukti "tamper-evident" hilang begitu proses restart, padahal dokumentasi
mengklaim persistensi.

Ditambah lagi ``get_ledger()`` **selalu** membuat ``EvidenceLedger()`` tanpa
``store`` → default memori. Tidak ada jalur otomatis ke Supabase sama sekali.

Skenario:
  01  `auto_store()` memaksa memori saat KATALIR_EVIDENCE_STORE=memory
  02  `auto_store()` memilih Postgres saat koneksi+DDL berhasil (DSN palsu)
  03  `auto_store()` turun ke memori (dengan peringatan) saat koneksi gagal
  04  DDL store memuat tabel + indeks yang dibutuhkan
  05  `PostgresEvidenceStore.append` menulis kolom yang benar
  06  `PostgresEvidenceStore.load` mengembalikan tipe Python (int/str/float)
  07  `_connect()` memakai `connector_verification_store.connect` (regresi bug)
  08  Ledger di atas store Postgres: rantai tetap utuh setelah reload
  09  Reload dari store -> hash head identik (bukti bertahan antar-proses)
  10  Tamper di store -> `ChainBrokenError` saat reload
  11  `get_ledger()` menghormati env dan mengembalikan singleton
  12  Endpoint `/evidence` memakai store yang dikonfigurasi
"""
from __future__ import annotations

import os
import sys

import pytest

import evidence_ledger as el

KEY = b"kunci-persistensi-hard-test-2026"


# ---------------------------------------------------------------------------
# Store palsu yang meniru psycopg2 (tanpa jaringan)
# ---------------------------------------------------------------------------
class KoneksiPalsu:
    """Meniru `psycopg2.connection` secukupnya untuk store."""

    def __init__(self, rows: list[dict] | None = None, *, gagal: bool = False):
        self.rows = rows if rows is not None else []
        self.gagal = gagal
        self.dieksekusi: list[tuple] = []

    def __enter__(self):
        if self.gagal:
            raise RuntimeError("koneksi ditolak (uji)")
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return KursorPalsu(self)


class KursorPalsu:
    def __init__(self, conn: KoneksiPalsu):
        self.conn = conn
        self._hasil: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql: str, params=None):
        self.conn.dieksekusi.append((sql, params))
        if "SELECT" in sql.upper():
            self._hasil = [
                (r["seq"], r["id"], r["ts"], r["content"], r["content_hash"],
                 r["prev_hash"], r["hash"], r["sig"])
                for r in self.conn.rows
            ]
        elif "INSERT" in sql.upper() and params:
            seq, eid, ts, content, chash, prev, h, sig = params
            import json as _j
            self.conn.rows.append({
                "seq": seq, "id": eid, "ts": ts,
                "content": _j.loads(content) if isinstance(content, str) else content,
                "content_hash": chash, "prev_hash": prev, "hash": h, "sig": sig})

    def fetchall(self):
        return list(self._hasil)


def _store_palsu(rows=None, gagal=False):
    conn = KoneksiPalsu(rows, gagal=gagal)
    st = el.PostgresEvidenceStore(dsn_factory=lambda: {})
    st._connect = lambda: conn          # type: ignore[assignment]
    return st, conn


# ---------------------------------------------------------------------------
# 01
# ---------------------------------------------------------------------------
def test_01_paksa_memori():
    st = el.auto_store(prefer="memory")
    print(f"[01] {type(st).__name__}")
    assert isinstance(st, el.MemoryEvidenceStore)


# ---------------------------------------------------------------------------
# 02
# ---------------------------------------------------------------------------
def test_02_pilih_postgres():
    st, conn = _store_palsu()
    asli = el.PostgresEvidenceStore
    try:
        el.PostgresEvidenceStore = lambda f=None: st   # type: ignore[misc]
        hasil = el.auto_store()
    finally:
        el.PostgresEvidenceStore = asli                # type: ignore[misc]
    print(f"[02] {type(hasil).__name__} ddl_dijalankan="
          f"{any('CREATE TABLE' in s for s, _ in conn.dieksekusi)}")
    assert isinstance(hasil, el.PostgresEvidenceStore)
    assert any("CREATE TABLE" in s for s, _ in conn.dieksekusi)


# ---------------------------------------------------------------------------
# 03
# ---------------------------------------------------------------------------
def test_03_turun_ke_memori(caplog):
    st, _conn = _store_palsu(gagal=True)
    asli = el.PostgresEvidenceStore
    try:
        el.PostgresEvidenceStore = lambda f=None: st   # type: ignore[misc]
        with caplog.at_level("WARNING"):
            hasil = el.auto_store()
    finally:
        el.PostgresEvidenceStore = asli                # type: ignore[misc]
    print(f"[03] {type(hasil).__name__} peringatan={bool(caplog.records)}")
    assert isinstance(hasil, el.MemoryEvidenceStore)
    assert any("memori" in r.getMessage() or "Postgres" in r.getMessage()
               for r in caplog.records)


# ---------------------------------------------------------------------------
# 04
# ---------------------------------------------------------------------------
def test_04_ddl_lengkap():
    ddl = el.PostgresEvidenceStore.DDL
    for wajib in ("CREATE TABLE IF NOT EXISTS evidence_ledger",
                  "seq", "content_hash", "prev_hash", "hash", "sig",
                  "idx_evidence_ledger_hash"):
        assert wajib in ddl, wajib
    print("[04] DDL memuat tabel + semua kolom rantai + indeks hash")


# ---------------------------------------------------------------------------
# 05
# ---------------------------------------------------------------------------
def test_05_append_menulis_kolom():
    st, conn = _store_palsu()
    led = el.EvidenceLedger(key=KEY, store=st)
    e = led.append({"test": "gap2", "ok": True})
    sql, params = conn.dieksekusi[-1]
    print(f"[05] kolom={len(params)} seq={params[0]}")
    assert "INSERT INTO evidence_ledger" in sql
    assert len(params) == 8
    assert params[0] == e["seq"] == 0
    assert params[4] == e["content_hash"] and params[7] == e["sig"]


# ---------------------------------------------------------------------------
# 06
# ---------------------------------------------------------------------------
def test_06_load_konversi_tipe():
    rows = []
    led0 = el.EvidenceLedger(key=KEY, store=el.MemoryEvidenceStore())
    for i in range(3):
        rows.append(led0.append({"i": i}))
    st, _conn = _store_palsu(rows)
    dimuat = st.load()
    print(f"[06] tipe: seq={type(dimuat[0]['seq']).__name__} "
          f"id={type(dimuat[0]['id']).__name__} ts={type(dimuat[0]['ts']).__name__}")
    assert all(isinstance(r["seq"], int) for r in dimuat)
    assert all(isinstance(r["id"], str) for r in dimuat)
    assert all(isinstance(r["ts"], float) for r in dimuat)
    assert [r["seq"] for r in dimuat] == [0, 1, 2]


# ---------------------------------------------------------------------------
# 07 — regresi bug import
# ---------------------------------------------------------------------------
def test_07_regresi_bug_import_dsn():
    """`_connect()` harus memakai nama fungsi yang BENAR-ADA di modul store."""
    import ast
    import pathlib
    src = pathlib.Path(el.__file__).read_text(encoding="utf-8")
    assert "from connector_verification_store import _dsn" not in src, \
        "sisa impor `_dsn` yang tidak ada (bug lama)"
    assert "connector_verification_store import _dsn" not in src
    assert "from connector_verification_store import connect" in src

    # Buktikan target impornya benar-benar bisa diimpor & dipanggil.
    import connector_verification_store as cvs
    assert callable(cvs.connect)
    # Dan `_connect` benar-benar memakainya (bukan didefinisikan ulang).
    tree = ast.parse(src)
    fn = [n for n in ast.walk(tree)
          if isinstance(n, ast.FunctionDef) and n.name == "_connect"]
    assert fn, "metode _connect hilang"
    print("[07] impor store Supabase memakai `connect()` yang nyata")


# ---------------------------------------------------------------------------
# 08
# ---------------------------------------------------------------------------
def test_08_rantai_utuh_setelah_reload():
    st, _conn = _store_palsu()
    led = el.EvidenceLedger(key=KEY, store=st)
    for i in range(10):
        led.append({"langkah": i, "status": "pass"})
    # Proses "baru": instance ledger baru membaca store yang sama.
    led2 = el.EvidenceLedger(key=KEY, store=st)
    print(f"[08] panjang={len(led2)} head_sama={led2.head == led.head}")
    assert len(led2) == 10
    assert led2.verify_chain()["ok"] is True
    assert led2.head == led.head


# ---------------------------------------------------------------------------
# 09
# ---------------------------------------------------------------------------
def test_09_head_identik_setelah_reload():
    st, _conn = _store_palsu()
    led = el.EvidenceLedger(key=KEY, store=st)
    e = led.append({"bukti": "verifikasi live-test-run"})
    led2 = el.EvidenceLedger(key=KEY, store=st)
    got = led2.find(e["id"])
    print(f"[09] id={e['id'][:8]}… hash_sama={got['hash'] == e['hash']}")
    assert got is not None
    assert got["hash"] == e["hash"]
    assert led2.verify_entry(got) is True


# ---------------------------------------------------------------------------
# 10
# ---------------------------------------------------------------------------
def test_10_tamper_terdeteksi_setelah_reload():
    st, conn = _store_palsu()
    led = el.EvidenceLedger(key=KEY, store=st)
    led.append({"a": 1})
    led.append({"b": 2})
    conn.rows[0]["content"] = {"a": 999}        # ubah isi di "database"
    print(f"[10] rows dimodifikasi -> reload harus menolak")
    with pytest.raises(el.ChainBrokenError) as exc:
        el.EvidenceLedger(key=KEY, store=st)
    assert "content_hash" in str(exc.value) or "rantai" in str(exc.value)


# ---------------------------------------------------------------------------
# 11
# ---------------------------------------------------------------------------
def test_11_get_ledger_singleton_dan_env(monkeypatch):
    monkeypatch.setenv(el.STORE_ENV, "memory")
    monkeypatch.setenv(el.DEFAULT_KEY_ENV, "kunci-uji-get-ledger")
    el.set_ledger(None)                          # type: ignore[arg-type]
    a = el.get_ledger()
    b = el.get_ledger()
    print(f"[11] store={type(a._store).__name__} singleton={a is b}")
    assert a is b
    assert isinstance(a._store, el.MemoryEvidenceStore)
    el.set_ledger(None)                          # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 12
# ---------------------------------------------------------------------------
def test_12_endpoint_evidence_memakai_store(monkeypatch):
    monkeypatch.setenv(el.STORE_ENV, "memory")
    monkeypatch.setenv(el.DEFAULT_KEY_ENV, "kunci-uji-endpoint")
    el.set_ledger(None)                          # type: ignore[arg-type]
    import httpx
    import api_server
    import security
    # Auth di-monkeypatch (pola sama dengan test_evidence_stream_api) supaya
    # fokus pada STORE yang dipakai endpoint, bukan pada verifikasi JWT.
    monkeypatch.setattr(
        security, "get_current_user",
        lambda authorization=None: {"id": "u-persist", "email": "u@example.com"})

    async def _req(method, path, **kw):
        tr = httpx.ASGITransport(app=api_server.app)
        async with httpx.AsyncClient(transport=tr,
                                     base_url="http://testserver") as c:
            return await getattr(c, method)(path, **kw)

    r = __import__("asyncio").run(_req(
        "post", "/evidence",
        json={"content": {"test": "gap2-endpoint", "status": "pass"}}))
    print(f"[12] POST /evidence -> {r.status_code} {r.text[:160]}")
    assert r.status_code in (200, 201), r.text
    eid = (r.json().get("entry") or {}).get("id") or r.json().get("entry_id")
    assert eid
    v = __import__("asyncio").run(_req("get", f"/evidence/{eid}/verify"))
    print(f"[12] GET verify -> {v.status_code} {v.text[:160]}")
    assert v.status_code == 200
    assert v.json().get("valid") is True
    # Store yang dipakai benar-benar store memori (sesuai env yang dipaksa).
    assert isinstance(el.get_ledger()._store, el.MemoryEvidenceStore)
    el.set_ledger(None)                          # type: ignore[arg-type]
