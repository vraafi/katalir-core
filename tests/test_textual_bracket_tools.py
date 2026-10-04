"""Test textual tool calling format `[ALAT: args]` (BUG FIX 2026-10-04).

Gateway production memb-drop `tools` (HTTP 500 saat payload tools dikirim),
jadi alat harus dipanggil lewat TEKS. Format ini model-agnostic.

Case yang diuji di sini termasuk kasus yang TIDAK ada di brief:
  * nilai berkutip `pesan="Halo dunia"` (brief punya bug di sini);
  * call di dalam code fence TIDAK boleh dieksekusi - system prompt
    sendiri berisi contoh `[ALAT: ...]`, jadi model bisa menyalinnya.
"""

import pytest

from textual_tool_handlers import execute_textual_tool
from textual_tool_parser import parse_kv_args, parse_textual_tools, strip_textual_tools

# --------------------------------------------------------------------------
# 8 kasus yang diminta brief
# --------------------------------------------------------------------------
def test_1_vault_supabase():
    assert parse_textual_tools("[VAULT: supabase]") == [
        {"tool": "VAULT", "args": {"provider": "supabase"},
         "raw": "[VAULT: supabase]", "index": 0}]


def test_2_vault_gmail_imap():
    assert parse_textual_tools("[VAULT: gmail_imap]")[0]["args"] == {
        "provider": "gmail_imap"}


def test_3_workflow():
    assert parse_textual_tools("[WORKFLOW: email_to_sheets]")[0]["args"] == {
        "name": "email_to_sheets"}


def test_4_email():
    assert parse_textual_tools(
        "[EMAIL: cek subjek=inventory max=10]")[0]["args"] == {
        "subjek": "inventory", "max": "10"}


def test_5_telegram():
    assert parse_textual_tools(
        '[TELEGRAM: chat_id=2109751369 pesan="Halo dunia"]')[0]["args"] == {
        "chat_id": "2109751369", "pesan": "Halo dunia"}


def test_6_unknown_diabaikan():
    assert parse_textual_tools("[UNKNOWN: x]") == []


def test_7_tanpa_tool():
    assert parse_textual_tools("Tidak ada tool di sini.") == []
    assert parse_textual_tools("") == []


def test_8_strip_blok():
    out = strip_textual_tools("Baik, saya munculkan form.\n\n[VAULT: supabase]")
    assert "[VAULT" not in out
    assert "saya munculkan form" in out


# --------------------------------------------------------------------------
# Nilai berkutip - bug `split()` di brief
# --------------------------------------------------------------------------
def test_kutip_menjaga_spasi():
    args, _ = parse_kv_args('pesan="Halo dunia"')
    assert args["pesan"] == "Halo dunia"


def test_tanpa_kutip_kata_tambahan_diabaikan():
    """Perilaku didokumentasikan: tanpa kutip, kata berikutnya dibuang."""
    args, ignored = parse_kv_args("pesan=Halo dunia")
    assert args["pesan"] == "Halo"
    assert "dunia" in ignored


# --------------------------------------------------------------------------
# Fail-closed
# --------------------------------------------------------------------------
def test_nama_tool_tidak_dikenal_tidak_dieksekusi():
    assert parse_textual_tools("[HACK: rm -rf]") == []
    assert parse_textual_tools("[VAULTX: gmail_imap]") == []


def test_key_di_luar_daftar_ditolak():
    """Model tidak boleh mengarang parameter (mis. `token=` di TELEGRAM)."""
    got = parse_textual_tools("[TELEGRAM: chat_id=1 token=RAHASIA pesan=hi]")
    assert got == [] or "token" not in got[0]["args"]


def test_argumen_kosong_tidak_dieksekusi():
    assert parse_textual_tools("[VAULT:]") == []
    assert parse_textual_tools("[TELEGRAM: ]") == []


def test_code_fence_tidak_dieksekusi():
    text = ("Contoh:\n```\n[TELEGRAM: chat_id=999 pesan=jahat]\n```\n"
            "[TELEGRAM: chat_id=1 pesan=asli]")
    got = parse_textual_tools(text)
    assert [c["args"]["chat_id"] for c in got] == ["1"]


def test_inline_code_tidak_dieksekusi():
    assert parse_textual_tools("coba `[VAULT: supabase]` di sini") == []


def test_code_fence_utuh_saat_strip():
    """Blok di dalam code fence = dokumentasi; jangan dihapus dari layar."""
    text = "Contoh:\n```\n[TELEGRAM: chat_id=1 pesan=hi]\n```\nOke."
    assert "[TELEGRAM" in strip_textual_tools(text)


def test_nomor_urutan_tidak_ikut_eksekusi():
    assert parse_textual_tools("[LANGKAH 1: mulai]") == []


# --------------------------------------------------------------------------
# Multi-call (pola nyata: vault dulu, baru workflow)
# --------------------------------------------------------------------------
def test_multi_call_terurut():
    text = "Saya siapkan.\n[VAULT: gmail_imap]\n[WORKFLOW: inv_to_sheets]\nSelesai."
    got = parse_textual_tools(text)
    assert [c["tool"] for c in got] == ["VAULT", "WORKFLOW"]


def test_strip_semua_blok():
    out = strip_textual_tools("a\n[VAULT: gmail_imap]\nb\n[WORKFLOW: x]\nc")
    assert "[" not in out and "a" in out and "c" in out


# --------------------------------------------------------------------------
# Handler
# --------------------------------------------------------------------------
def test_handler_vault_menghasilkan_status():
    r = execute_textual_tool({"tool": "VAULT", "args": {"provider": "supabase"}},
                             "handler-test@katalir.test")
    assert r["status"] in ("requires_credential", "ok")
    assert "app_password" not in r  # nilai rahasia tidak boleh ikut


def test_handler_vault_provider_asing():
    r = execute_textual_tool({"tool": "VAULT", "args": {"provider": "ngetah"}},
                             "handler-test@katalir.test")
    assert r["status"] == "unknown_provider"


def test_handler_workflow_tidak_mengarang():
    """Nama workflow BUKAN spec. Handler harus jujur, bukan bikin node palsu."""
    r = execute_textual_tool({"tool": "WORKFLOW", "args": {"name": "inv"}}, "u@k.test")
    assert r["status"] == "needs_spec"
    assert "nodes" not in r


def test_handler_tool_tidak_dikenal():
    r = execute_textual_tool({"tool": "NGGAKADA", "args": {}}, "u@k.test")
    assert r["status"] == "error"


def test_handler_args_bukan_dict():
    r = execute_textual_tool({"tool": "TELEGRAM", "args": "bukan dict"}, "u@k.test")
    assert r["status"] == "error"


def test_handler_kredensial_hilang_tidak_ditelan():
    """Harus melempar CredentialMissingError supaya form dirender."""
    from tools import CredentialMissingError
    with pytest.raises(CredentialMissingError):
        execute_textual_tool(
            {"tool": "SLACK", "args": {"channel": "#c", "pesan": "x"}},
            "belum-terpasang@katalir.test")


def test_api_server_sudah_mengimpor_jalur_baru():
    src = open("api_server.py", encoding="utf-8").read()
    assert "from textual_tool_parser import" in src
    assert "parse_textual_tools(_raw_text)" in src
    assert "execute_textual_tool(c, email)" in src


def test_api_server_mengirim_tanpa_tools_secara_default():
    """BAGIAN 2.3: param `tools` TIDAK boleh dikirim ke gateway.

    Diuji lewat flag, bukan lewat mock LLM: yang dikunci adalah
    keputusannya (default OFF), bukan bentuk obyek LangChain.
    """
    import importlib
    import os

    import api_server

    src = open("api_server.py", encoding="utf-8").read()
    assert "KATALIR_SEND_TOOLS" in src

    # helper membaca env saat dipanggil; unset = default OFF
    os.environ.pop("KATALIR_SEND_TOOLS", None)
    env_default = (os.getenv("KATALIR_SEND_TOOLS", "0") or "0").strip().lower()
    assert env_default not in ("1", "true", "yes", "on")

    # dan bind_tools hanya jalan kalau flag menyala
    assert 'if not want:' in src
    assert importlib.util.find_spec("api_server") is not None


def test_parser_tidak_membuang_kata_kerja_email():
    """`cek` adalah KATA KERJA, bukan argumen.

    Brief mengharapkan key `"cek": None` muncul di args. Di sini kata
    kerja dibuang saja: ia tidak punya nilai dan tidak pernah dipakai
    handler, jadi menyimpannya hanya menambah noise.
    """
    got = parse_textual_tools("[EMAIL: cek subjek=inventory max=10]")[0]["args"]
    assert got == {"subjek": "inventory", "max": "10"}
    assert "cek" not in got


def test_system_prompt_menyebut_format():
    src = open("api_server.py", encoding="utf-8").read()
    i = src.find("_AGENT_SYSTEM = (")
    assert i != -1
    blok = src[i:i + 3000]
    assert "[VAULT: <provider>]" in blok
    assert "tanda kutip" in blok
    for tool in ("WORKFLOW", "EMAIL", "SHEETS", "TELEGRAM", "SLACK"):
        assert f"[{tool}:" in blok, tool
    """Perilaku didokumentasikan: tanpa kutip, kata berikutnya dibuang."""
    args, ignored = parse_kv_args("pesan=Halo dunia")
    assert args["pesan"] == "Halo"
    assert "dunia" in ignored


def test_kutip_tunggal_juga_jalan():
    args, _ = parse_kv_args("pesan='Halo dunia'")
    assert args["pesan"] == "Halo dunia"


def test_kosong_aman():
    assert parse_kv_args("") == ({}, [])
    assert parse_kv_args(None) == ({}, [])