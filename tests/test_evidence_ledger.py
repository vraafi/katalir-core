"""Hard test TASK 3 — hash-chained evidence ledger.

12 skenario: append+hash, integritas rantai, deteksi tamper, 1000 append <1s,
verifikasi entri tunggal, verifikasi rantai penuh, verifikasi signature,
append paralel, persist+reload, reload hash sama, endpoint verify, regresi.
"""
from __future__ import annotations

import threading
import time

import pytest

import evidence_ledger as el

KEY = b"kunci-ledger-hard-test-2026"


def _ledger():
    return el.EvidenceLedger(key=KEY, store=el.MemoryEvidenceStore())


# 1. Append evidence -> hash OK -------------------------------------------
def test_01_append_hash_ok():
    led = _ledger()
    e = led.append({"test": "login", "status": "pass"})
    assert e["seq"] == 0
    assert e["prev_hash"] == el.GENESIS_HASH
    assert e["content_hash"] == el.content_hash({"test": "login", "status": "pass"})
    assert led.verify_entry(e) is True


# 2. Chain integrity check PASS -------------------------------------------
def test_02_chain_integrity():
    led = _ledger()
    for i in range(20):
        led.append({"i": i})
    res = led.verify_chain()
    assert res["ok"] is True
    assert res["length"] == 20
    assert led.head == led.get(19)["hash"]


# 3. Tamper detection: modify content -> chain break ----------------------
def test_03_tamper_content_detected():
    led = _ledger()
    for i in range(5):
        led.append({"i": i})
    rows = [dict(r) for r in led._entries]
    rows[2]["content"] = {"i": 999}   # diubah setelah dicatat
    res = led.verify_chain(rows)
    assert res["ok"] is False
    assert res["broken_at"] == 2
    assert "content" in res["reason"]


def test_03b_tamper_hash_detected():
    led = _ledger()
    for i in range(4):
        led.append({"i": i})
    rows = [dict(r) for r in led._entries]
    rows[1]["hash"] = "0" * 64
    res = led.verify_chain(rows)
    assert res["ok"] is False
    assert res["broken_at"] == 1


def test_03c_reorder_detected():
    led = _ledger()
    for i in range(4):
        led.append({"i": i})
    rows = [dict(r) for r in led._entries]
    rows[1], rows[2] = rows[2], rows[1]
    res = led.verify_chain(rows)
    assert res["ok"] is False


# 4. 1000 evidence append < 1s --------------------------------------------
def test_04_thousand_appends_fast():
    led = _ledger()
    t0 = time.perf_counter()
    for i in range(1000):
        led.append({"n": i})
    elapsed = time.perf_counter() - t0
    assert len(led) == 1000
    assert elapsed < 1.0, f"1000 append = {elapsed:.3f}s"
    assert led.verify_chain()["ok"] is True


# 5. Verify single evidence -----------------------------------------------
def test_05_verify_single():
    led = _ledger()
    e = led.append({"x": 1})
    assert led.verify_entry(e) is True
    bad = dict(e)
    bad["content"] = {"x": 2}
    assert led.verify_entry(bad) is False


# 6. Verify full chain -----------------------------------------------------
def test_06_verify_full_chain():
    led = _ledger()
    for i in range(50):
        led.append({"i": i})
    assert led.verify_chain()["ok"] is True
    # hapus satu entri -> pecah
    rows = [dict(r) for r in led._entries]
    del rows[10]
    assert led.verify_chain(rows)["ok"] is False


# 7. Signature verify ------------------------------------------------------
def test_07_signature_verify():
    led = _ledger()
    e = led.append({"a": 1})
    assert led.verify_signature(e) is True
    tampered = dict(e)
    tampered["sig"] = "deadbeef"
    assert led.verify_signature(tampered) is False
    # Kunci berbeda -> signature tidak valid.
    other = el.EvidenceLedger(key=b"kunci-lain")
    assert other.verify_signature(e) is False


# 8. Concurrent append (lock) ---------------------------------------------
def test_08_concurrent_append():
    led = _ledger()
    errors = []

    def work(n):
        try:
            led.append({"n": n})
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(led) == 100
    seqs = sorted(e["seq"] for e in led._entries)
    assert seqs == list(range(100))     # tidak ada seq duplikat/hilang
    assert led.verify_chain()["ok"] is True


# 9. Persist -> reload -> hash sama ---------------------------------------
def test_09_persist_reload_same_hash():
    store = el.MemoryEvidenceStore()
    led = el.EvidenceLedger(key=KEY, store=store)
    for i in range(10):
        led.append({"i": i})
    head = led.head
    # Ledger baru membaca store yang sama -> hash identik.
    led2 = el.EvidenceLedger(key=KEY, store=store)
    assert len(led2) == 10
    assert led2.head == head
    assert led2.verify_chain()["ok"] is True


# 10. Reload chain -> same hash -------------------------------------------
def test_10_reload_hash_stable():
    led = _ledger()
    led.append({"payload": {"k": "v"}})
    h1 = led.head
    rows = led._store.load()
    led2 = el.EvidenceLedger(key=KEY, store=el.MemoryEvidenceStore())
    for r in rows:
        led2._entries.append(r)
        led2._store.append(r)
    assert led2.head == h1


# 11. Endpoint helper /evidence/{id}/verify -------------------------------
def test_11_verify_payload_helper():
    led = _ledger()
    e = led.append({"evidence": "run-42"})
    out = el.verify_payload(led, e["id"])
    assert out["found"] is True
    assert out["valid"] is True
    assert out["chain_ok"] is True
    assert out["seq"] == 0
    missing = el.verify_payload(led, "00000000-0000-0000-0000-000000000000")
    assert missing["found"] is False
    assert missing["valid"] is False


# 12. Regresi: genesis, key wajib, canonical stabil ------------------------
def test_12_regressions():
    led = _ledger()
    assert len(led) == 0
    assert led.head == el.GENESIS_HASH
    assert led.verify_chain()["ok"] is True

    with pytest.raises(el.LedgerError):
        el.EvidenceLedger(key=b"")

    # canonical_json stabil terhadap urutan kunci
    assert el.content_hash({"a": 1, "b": 2}) == el.content_hash({"b": 2, "a": 1})
    # list bersarang juga stabil
    assert el.content_hash({"a": [1, 2, {"z": 3}]}) == el.content_hash({"a": [1, 2, {"z": 3}]})


def test_12b_get_and_find():
    led = _ledger()
    e = led.append({"z": 1})
    assert led.get(0)["id"] == e["id"]
    assert led.get(99) is None
    assert led.find(e["id"])["seq"] == 0
    assert led.find("nope") is None
