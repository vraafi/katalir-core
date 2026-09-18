"""test_dodo_webhook.py - Kontrak webhook Dodo Payments (temuan audit billing).

Kelas bug yang dijaga (audit 2026-09-18):
  1. **Billing mati total**: `client.webhooks.unwrap` butuh extra
     `dodopayments[webhooks]`; tanpa itu verifikasi SELALU gagal -> 401 walau
     `DODO_WEBHOOK_SECRET` benar. Railway juga tidak punya secret sama sekali.
  2. **Bayar tidak menaikkan tier**: handler lama hanya `topup_balance`.
  3. **Double-credit**: tidak ada idempotensi, padahal Dodo punya retry +
     bulk replay.
  4. **Gagal senyap**: `except: pass` di database.py -> webhook membalas SUKSES
     padahal tier/saldo tidak tersimpan.
  5. **Dev-bypass** di `billing_llm.verify_dodo_webhook` (dead code berbahaya).

Tes ini TIDAK menyentuh DB/jaringan:
  * `database.is_configured` dipaksa False -> semua jalur memori;
  * 3 tes verifikasi memakai jalur NYATA (tanpa mock) via `standardwebhooks`,
    sisanya memo `dodo_verify.verify_dodo_webhook` supaya yang diuji adalah
    perilaku handler (idempotensi, tier, refund).
"""

import base64
import hashlib
import hmac
import json
import os
import time

import pytest

api_server = pytest.importorskip("api_server")
import database as db  # noqa: E402
import dodo_verify as dv  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

URL = "/api/payments/dodo-webhook"
WSEC = (os.getenv("DODO_WEBHOOK_SECRET") or "").strip()


@pytest.fixture()
def client(monkeypatch):
    """Klien uji dengan DB dipaksa mode memori + state bersih per tes."""
    monkeypatch.setattr(db, "is_configured", lambda: False)
    db._LUSER.clear()
    db._LBAL.clear()
    db._LPAY.clear()
    return TestClient(api_server.app)


@pytest.fixture()
def signed_in(monkeypatch):
    """Verifikasi dimemo sukses -> fokus pada perilaku handler."""
    monkeypatch.setattr(dv, "verify_dodo_webhook", lambda raw, headers: True)


def _payload(email="plus@test.dev", amount=5000000, event="payment.succeeded",
             tier="plus", payment_id="pay_123"):
    return {
        "type": event,
        "data": {
            "payment_id": payment_id,
            "customer": {"email": email},
            "amount": amount,
            "metadata": ({"tier": tier} if tier is not None else {}),
        },
    }


def _post(client, body, event_id="msg_1"):
    return client.post(URL, content=json.dumps(body), headers={
        "webhook-id": event_id, "content-type": "application/json"})


def _sign(raw: bytes, msg_id: str, ts: str) -> str:
    """Tanda tangan Standard Webhooks (`id.timestamp.body`) dari secret env."""
    key = (base64.b64decode(WSEC.split("_", 1)[1] + "==")
           if WSEC.startswith("whsec_") else WSEC.encode())
    signed = ("%s.%s." % (msg_id, ts)).encode() + raw
    return base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()


# ---------------------------------------------------------------------------
def test_no_signature_returns_401(client, monkeypatch):
    """Tanpa signature: 401 — dan TIDAK menyentuh tier/saldo."""
    monkeypatch.setattr(dv, "verify_dodo_webhook", lambda raw, headers: False)
    r = _post(client, _payload())
    assert r.status_code == 401, r.text
    assert db.get_balance("plus@test.dev") == 0.0
    assert list(db._LPAY) == []


def test_wrong_signature_returns_401(client, monkeypatch):
    """Signature palsu: 401 (anti-spoof), tanpa efek samping."""
    monkeypatch.setattr(dv, "verify_dodo_webhook", lambda raw, headers: False)
    r = client.post(URL, content=json.dumps(_payload()), headers={
        "webhook-id": "msg_forged", "webhook-signature": "v1,AAAA",
        "webhook-timestamp": str(int(time.time())),
        "content-type": "application/json"})
    assert r.status_code == 401, r.text
    assert db._LPAY == {}


def test_valid_signature_real_unwrap_returns_200(client):
    """Jalur NYATA: tanda tangan sah -> 200 + tier naik (bukan mock).

    Ini sekaligus deteksi regresi `dodopayments[webhooks]` yang dulu membuat
    SEMUA webhook 401 walaupun secret benar.
    """
    if not WSEC:
        pytest.skip("DODO_WEBHOOK_SECRET tidak ada -> uji tanda tangan nyata dilewati")
    raw = json.dumps(_payload()).encode()
    ts = str(int(time.time()))
    r = client.post(URL, content=raw, headers={
        "webhook-id": "msg_real", "webhook-timestamp": ts,
        "webhook-signature": "v1," + _sign(raw, "msg_real", ts),
        "content-type": "application/json"})
    assert r.status_code == 200, r.text
    assert r.json()["tier"] == "plus"
    assert db._LUSER["plus@test.dev"]["tier"] == "plus"


def test_valid_signature_without_webhooks_extra_returns_401(client, monkeypatch):
    """Regresi: verifier yang gagal (mis. extra tidak terpasang) HARUS 401."""
    import dodo_verify as _dv

    def boom(raw, headers):
        raise RuntimeError("You need to install `dodopayments[webhooks]`")

    monkeypatch.setattr(_dv, "verify_dodo_webhook", lambda raw, headers: False)
    r = _post(client, _payload())
    assert r.status_code == 401, r.text


def test_duplicate_webhook_returns_already_processed(client, signed_in):
    """Idempotensi: webhook-id SAMA dua kali -> saldo hanya bertambah SEKALI."""
    r1 = _post(client, _payload(), event_id="msg_dup")
    assert r1.status_code == 200 and r1.json()["status"] == "success"
    saldo1 = db.get_balance("plus@test.dev")
    r2 = _post(client, _payload(), event_id="msg_dup")
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "already_processed"
    assert db.get_balance("plus@test.dev") == saldo1, "dobel-kredit terjadi!"


def test_payment_succeeded_updates_tier_and_balance(client, signed_in):
    """Inti model bisnis: bayar -> tier free->plus DAN saldo bertambah."""
    r = _post(client, _payload(email="bayar@test.dev", amount=5000000),
              event_id="msg_ok")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "success" and body["tier"] == "plus"
    assert db._LUSER["bayar@test.dev"]["tier"] == "plus"
    assert db.get_balance("bayar@test.dev") == 5000000.0


def test_refund_deducts_balance(client, signed_in):
    """Refund: saldo dipotong (event refund diakui, bukan diabaikan)."""
    _post(client, _payload(email="refund@test.dev", amount=5000000), event_id="msg_pay")
    assert db.get_balance("refund@test.dev") == 5000000.0
    r = _post(client, _payload(email="refund@test.dev", amount=2000000, event="refund"),
              event_id="msg_refund")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "refunded"
    assert db.get_balance("refund@test.dev") == 3000000.0


def test_db_failure_returns_5xx_not_silent_success(client, signed_in, monkeypatch):
    """Gagal senyap dihapus: DB gagal -> 5xx (Dodo retry), BUKAN 200 palsu.

    Dan event TIDAK ditandai selesai, sehingga retry berikutnya masih bisa
    mengkredit (uang user tidak hilang).
    """
    def boom(*a, **k):
        raise RuntimeError("db down")

    real_update_tier = db.update_tier
    monkeypatch.setattr(db, "update_tier", boom)
    r = _post(client, _payload(email="gagal@test.dev"), event_id="msg_fail")
    assert r.status_code == 500, r.text
    assert db._LPAY.get("msg_fail") == "pending", "event ditandai selesai padahal gagal"
    # "DB sehat kembali": kembalikan fungsi ASLI saja. `monkeypatch.undo()`
    # TIDAK boleh dipakai di sini -- ia juga membatalkan memo verifier
    # (`signed_in`), sehingga retry malah 401 dan tesnya menuduh hal yang salah.
    monkeypatch.setattr(db, "update_tier", real_update_tier)
    r2 = _post(client, _payload(email="gagal@test.dev"), event_id="msg_fail")
    assert r2.status_code == 200, r2.text
    assert r2.json()["tier"] == "plus"


# ---------------------------------------------------------------------------
# REGRESI PRODUKSI 2026-09-18: saldo dibaca lewat klien ANON yang kena RLS ->
# hasil selalu kosong -> saldo terbaca 0 -> topup MENIMPA (bukan menjumlah) dan
# refund menghasilkan saldo NEGATIF (5000000 - 2000000 -> -2000000).
class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, data):
        self._data = data

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def update(self, *a, **k):
        return self

    def insert(self, *a, **k):
        return self

    def execute(self):
        return _Resp(self._data)


class _FakeClient:
    def __init__(self, data):
        self._data = data

    def table(self, _name):
        return _Query(self._data)


def _force_db(monkeypatch, service_rows, anon_rows=None):
    """Paksa jalur DB: anon melihat `anon_rows` (simulasi RLS), service melihat aslinya."""
    monkeypatch.setattr(db, "is_configured", lambda: True)
    monkeypatch.setattr(db, "SUPABASE_SERVICE_KEY", "svc-key")
    monkeypatch.setattr(db, "_get_client", lambda: _FakeClient(anon_rows or []))
    monkeypatch.setattr(db, "_get_write_client", lambda: _FakeClient(service_rows))


def test_get_balance_membaca_lewat_klien_service(monkeypatch):
    """Saldo HARUS dibaca lewat klien service; klien anon (RLS) mengembalikan 0."""
    _force_db(monkeypatch, [{"credit_balance": 3000000}], anon_rows=[])
    assert db.get_balance("rls@test.dev") == 3000000.0, (
        "saldo dibaca lewat klien anon -> RLS -> 0 (regresi produksi)"
    )


def test_topup_menjumlah_bukan_menimpa(monkeypatch):
    """topup = saldo lama + nominal (bukan menimpa dengan nominal saja)."""
    _force_db(monkeypatch, [{"credit_balance": 3000000}])
    assert db.topup_balance("add@test.dev", 2000000) == 5000000.0


def test_refund_menghasilkan_saldo_sisa_positif(monkeypatch):
    """Refund 2jt dari saldo 5jt -> 3jt (bukan -2jt seperti di produksi)."""
    _force_db(monkeypatch, [{"credit_balance": 5000000}])
    assert db.deduct_balance("ref@test.dev", 2000000) == 3000000.0
