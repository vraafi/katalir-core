"""Test wrapper status /chat (BUG FIX 2026-10-05).

Wrapper di api_server.py_extract_ hanya mengambil `reply` dan `meta` dari
hasil gateway, lalu mengembalikan `status: "success"` apa adanya. Akibatnya
`requires_approval` (dan `denied`) hilang tanpa jejak: tidak ada
approval_token, tidak ada tombol Setujui, dan user melihat "success"
padahal tidak ada yang dieksekusi.

Test di bawah mengunci aturan mainnya:
  * status `success`  -> tetap success (perilaku lama tak berubah);
  * status khusus     -> diteruskan BESERTA field pendukungnya;
  * session_id milik endpoint tidak ditimpa.
"""

import re

SRC = open("api_server.py", encoding="utf-8").read()


def _wrapper_block() -> str:
    i = SRC.find('_gw_status = str(_run.get("status")')
    assert i != -1, "blok {_gw_status} tidak ditemukan"
    return SRC[i:i + 1400]


def test_wrapper_tidak_hardcode_status():
    """Tidak boleh ada `status` literal "success" di jalur ini."""
    blk = _wrapper_block()
    assert 'str(_run.get("status") or "success")' in blk


def test_requires_approval_diteruskan():
    blk = _wrapper_block()
    assert '_response["status"] = _gw_status' in blk
    assert '"approval_token"' in blk
    assert '"tool"' in blk and '"args"' in blk and '"reason"' in blk


def test_denied_ikut_diteruskan():
    blk = _wrapper_block()
    assert '"denied"' in blk or "_gw_status !=" in blk


def test_field_daftar_tidak_bolos():
    blk = _wrapper_block()
    for k in ("approval_token", "resume_token", "provider", "display_name",
              "fields", "tool", "args", "reason", "alignment",
              "connect_url", "oauth_url"):
        assert '"%s"' % k in blk, k


def test_session_id_tidak_ditimpa():
    """Frontend memakai session_id milik endpoint untuk melanjutkan chat."""
    blk = _wrapper_block()
    assert "_run" in blk
    # session_id tidak boleh masuk daftar field yang diteruskan
    assert '"session_id"' not in blk


def test_tidak_ada_return_success_lama_di_akhir():
    assert ('return {"status": "success", "reply": reply, '
            '"session_id": session_id, "meta": meta}') not in SRC


def test_frontend_tahu_status_ini():
    fe = open("nexus-frontend/src/features/chat/hooks/useChat.ts",
              encoding="utf-8").read()
    for s in ("requires_approval", "denied", "needs_spec"):
        assert 'data.status === "%s"' % s in fe, s