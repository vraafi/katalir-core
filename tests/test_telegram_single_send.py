# tests/test_telegram_single_send.py
"""Regresi: SATU perintah Telegram = SATU panggilan API nyata.

KONTEKS (2026-09-20): laporan pengguna menyebut 3 pesan Telegram untuk 1
perintah. Duplikasi semacam itu biasanya lahir dari retry/loop di dalam adapter
atau pemanggilan ganda di jalur tool — bukan dari Niat pengguna. Test ini
mengunci dua hal:
  1. `kirim_telegram_message` memanggil httpx.post TEPAT SEKALI per pemanggilan
     (tidak ada retry tersembunyi di dalam adapter);
  2. setiap panggilan meninggalkan JEJAK bertahan (file) berisi message_id,
     sehingga "1 perintah = 1 pesan" bisa dibuktikan dari bukti, bukan dugaan.

Bukti nyata di browser (spec `l3-level3.spec.ts`, 3 skenario) menghasilkan
jejak `seq=1 OK message_id=15613`, `seq=2 OK message_id=15614`, `seq=3 FAIL 401`
— satu baris per perintah, tanpa duplikat.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import database as db  # noqa: E402
import provider_registry as pr  # noqa: E402
import tools  # noqa: E402


class _Resp:
    status_code = 200
    text = "ok"

    @staticmethod
    def json():
        return {"ok": True, "result": {"message_id": 4242}}


def test_satu_pemanggilan_satu_request_http(monkeypatch, tmp_path):
    calls: list[str] = []

    def fake_post(url, **kwargs):  # noqa: ARG001
        calls.append(url)
        return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(db, "get_integration",
                        lambda e, p: {"api_token": "123:RAHASIA"})
    monkeypatch.setenv("TELEGRAM_SEND_LOG", str(tmp_path / "sends.log"))

    out = tools.kirim_telegram_message("2109751369", "halo", "u@katalir.id")

    assert len(calls) == 1, f"adapter mengirim {len(calls)}x untuk 1 perintah"
    assert "id 4242" in out


def test_jejak_berkas_mencatat_satu_ok(monkeypatch, tmp_path):
    log = tmp_path / "sends.log"
    monkeypatch.setenv("TELEGRAM_SEND_LOG", str(log))
    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, **kw: _Resp())
    monkeypatch.setattr(db, "get_integration",
                        lambda e, p: {"api_token": "123:RAHASIA"})

    tools.kirim_telegram_message("2109751369", "halo", "u@katalir.id")
    lines = log.read_text(encoding="utf-8").strip().splitlines()

    assert len(lines) == 2, lines          # SEND + OK, bukan lebih
    assert "SEND" in lines[0]
    assert "OK message_id=4242" in lines[1]
    # Sidik jari dipakai, bukan isi pesan (jangan bocorkan isi ke log).
    assert "text_sha8=" in lines[0] and "halo" not in lines[0]


def test_jejak_mencatat_kegagalan_provider(monkeypatch, tmp_path):
    log = tmp_path / "sends.log"
    monkeypatch.setenv("TELEGRAM_SEND_LOG", str(log))

    class _Bad:
        status_code = 401
        text = "unauthorized"

    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, **kw: _Bad())
    monkeypatch.setattr(db, "get_integration",
                        lambda e, p: {"api_token": "123:PALSU"})

    try:
        tools.kirim_telegram_message("2109751369", "halo", "u@katalir.id")
    except RuntimeError as exc:
        assert "401" in str(exc)
    else:
        raise AssertionError("harus melempar RuntimeError")

    body = log.read_text(encoding="utf-8")
    assert "FAIL http=401" in body


def test_provider_telegram_menyentuh_fungsi_sekali(monkeypatch, tmp_path):
    """`provider_registry.run` tidak boleh memanggil tool dua kali."""
    hit: list[int] = []

    def fake(chat_id, pesan, email):  # noqa: ARG001
        hit.append(1)
        return "terkirim"

    import dataclasses
    monkeypatch.setitem(pr.PROVIDERS, "telegram",
                        dataclasses.replace(pr.PROVIDERS["telegram"], fn=fake))

    out = pr.run("telegram", {"provider": "telegram", "chat_id": "-1",
                              "pesan": "hai"}, {}, "u@katalir.id")
    assert out["status"] == "success"
    assert len(hit) == 1, f"tool dipanggil {len(hit)}x"
