"""test_503_detail_contract.py - BUG-4 (adversarial 2026-10-07): 503 WAJIB berpesan.

Temuan BUG-4 pada `docs/security/adversarial-test-n8n-hardcore-user-2026-10-07.md`
mengklaim `POST /chat` membalas `HTTP 503` dengan body kosong. Triase
2026-10-06 membuktikan sebaliknya (FALSE POSITIVE / harness artifact):

  * server selalu mengirim `{"detail": "<pesan>"}` — FastAPI
    `HTTPException(503, "<pesan>")`, tanpa exception_handler kustom;
  * yang "kosong" hanyalah field `reply` pada harness `_adv_s1s2s5_v2.py:40`
    yang hanya mencetak `j.get("reply")`; key `detail` tidak pernah dicetak.
    Body yang benar-benar kosong justru jatuh ke cabang `raw:` (baris 47-48)
    karena `json.loads("")` gagal — log menampilkan `reply:` sehingga body
    PASTI JSON valid berisi;
  * bukti produksi langsung: `docs/chaos-test-results-2026-10-06.md`
    mencatat `503 | 7969ms | Semua kunci model ini sedang cooldown (kuota).`.

Tes ini mengunci kontrak dari dua sisi:
  1. SUMBER  — tidak ada `HTTPException(503)` tanpa argumen pesan;
  2. PERILAKU — `/chat` yang melempar 503 tetap membalas `detail` non-kosong
     (bukan body hampa) sehingga klien punya pesan untuk ditampilkan.
"""

import re

import pytest
from fastapi import HTTPException

SUMBER = ("api_server.py", "database.py")


def test_tidak_ada_http503_tanpa_pesan():
    """Setiap `raise/return HTTPException(503, ...)` di sumber punya pesan.

    Sengaja memakai prefiks `raise`/`return` supaya potongan docstring yang
    menyebut `HTTPException(503)` (mis. deskripsi `_agentic_run_direct`)
    tidak dianggap temuan.
    """
    pat = re.compile(r"^[ \t]*(?:raise|return)[ \t]+HTTPException\([ \t]*503\b",
                     re.MULTILINE)
    total = 0
    for path in SUMBER:
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        for m in pat.finditer(src):
            total += 1
            rest = src[m.end():].lstrip()
            assert rest.startswith(","), (
                f"{path} offset {m.start()}: HTTPException(503) tanpa argumen pesan"
            )
            after = rest[1:].lstrip()
            assert after and not after.startswith(")"), (
                f"{path} offset {m.start()}: HTTPException(503,) dengan pesan kosong"
            )
    assert total >= 3, (
        f"hanya {total} titik 503 terdeteksi — pola scan tidak menemui "
        "jalur 503 yang dikenal (periksa api_server.py)"
    )


# ---------------------------------------------------------------------------
# Perilaku /chat: 503 dari agen LLM harus sampai ke klien sebagai `detail`.
# ---------------------------------------------------------------------------
api_server = pytest.importorskip("api_server")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def chat_client(monkeypatch):
    """Klien /chat dengan auth + DB di-mock (tanpa Supabase, tanpa LLM)."""
    monkeypatch.setattr(api_server.security, "get_current_user",
                        lambda auth: {"email": "adv503@test.dev", "id": "uid-1"})
    monkeypatch.setattr(api_server.db, "get_or_create_user",
                        lambda *a, **k: {"email": "adv503@test.dev", "tier": "free"})
    monkeypatch.setattr(api_server.db, "find_user_message_by_request", lambda *a: None)
    monkeypatch.setattr(api_server.db, "create_session",
                        lambda *a, **k: {"id": "sess-adv503"})
    monkeypatch.setattr(api_server, "load_history", lambda *a, **k: [])
    monkeypatch.setattr(api_server.db, "add_message", lambda *a, **k: True)
    monkeypatch.setattr(api_server.db, "check_quota",
                        lambda e, m, t: (True, {"bucket": "gemma", "used": 0,
                                                "limit": 100, "remaining": 100}))
    return TestClient(api_server.app)


def test_chat_503_membawa_detail_tidak_kosong(chat_client, monkeypatch):
    """503 cooldown -> body JSON berisi `detail` pesan, BUKAN body hampa.

    Ini kontra-tes langsung atas klaim BUG-4 ("body kosong / reply: \"\"").
    """
    pesan = "Semua kunci model ini sedang cooldown (kuota). Coba lagi."

    def _cooldown(*a, **k):
        raise HTTPException(503, pesan)

    monkeypatch.setattr(api_server, "_agentic_run_direct", _cooldown)
    r = chat_client.post("/chat", json={"prompt": "halo"},
                         headers={"Authorization": "Bearer x"})
    assert r.status_code == 503, r.text
    body = r.json()  # body WAJIB JSON terurai — string kosong akan gagal di sini
    assert str(body.get("detail") or "").strip(), f"detail kosong: {r.text!r}"
    assert "cooldown (kuota)" in body["detail"]
