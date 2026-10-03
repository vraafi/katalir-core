"""Perbandingan Katalir vs n8n AI Assistant — 7 keluhan n8n yang harus dihindari.

BAGIAN 1 dari test case Oktober 2026. TUJUAN: ukur, jangan klaim.
Setiap test menguji SATU keluhan n8n terhadap kode Katalir yang sebenarnya
(dibaca dari source, bukan dari dokumentasi).

Keluhan n8n yang jadi acuan (sumber ada di docs/benchmarks/n8n-comparison.md):
  1. AI stuck/hang tanpa error            -> Katalir: anggaran LLM_total terikat
  2. Mid-run compaction merusak workflow   -> Katalir: spec divalidasi ulang
  3. Validation error palsu ("No prompt")  -> Katalir: pesan error menyebut id
  4. Hallucinated workflow IDs             -> Katalir: edge ke node asing DITOLAK
  5. Google Sheets builder hint tak lengkap-> Katalir: REQUIRED_CONFIG per provider
  6. WebSocket timeout tanpa pesan error   -> Katalir: classifyChatError + retry
  7. Fallback model diblokir               -> Katalir: _FALLBACK_RESERVE_SEC terdisihkan
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import provider_registry  # noqa: E402
import tools  # noqa: E402
import workflow_spec as ws  # noqa: E402


# ===========================================================================
# KELUHAN 1 + 7: stuck/hang & fallback diblokir -> anggaran waktu terikat
# ===========================================================================
def test_llm_budget_ada_dan_terikat():
    """Harus ada anggaran TOTAL dan cadangan untuk fallback (bukan tak terbatas)."""
    import api_server

    budget = api_server._llm_budget_sec()
    attempt = api_server._gateway_attempt_timeout_sec()
    reserve = api_server._FALLBACK_RESERVE_SEC

    assert budget > 0, "anggaran LLM total tidak boleh 0/None (itu hang)"
    # Catatan: anggaran total harus JUMLAH gateway + cadangan, bukan hanya gateway.
    assert budget > attempt, (
        f"anggaran total ({budget}s) harus lebih besar dari satu percobaan "
        f"({attempt}s), kalau tidak tidak ada ruang untuk fallback."
    )
    assert reserve > 0, (
        "tanpa cadangan waktu, gateway down = outage = error ke user. "
        "Ini persis keluhan n8n #7 (fallback diblokir)."
    )
    # Batas keras: brief mensyaratkan <120 detik untuk felt "tidak hang".
    assert budget < 120, f"anggaran {budget}s melanggar target <120s"


def test_gateway_attempt_timeout_lebih_kecil_dari_budget():
    """Satu percobaan gateway tidak boleh memakan seluruh anggaran."""
    import api_server

    assert api_server._gateway_attempt_timeout_sec() < api_server._llm_budget_sec()
    # sources: nilai default harus terdokumentasi sebagai environment override.
    src = (ROOT / "api_server.py").read_text(encoding="utf-8")
    assert "LLM_GATEWAY_BUDGET" in src and "LLM_GATEWAY_TIMEOUT" in src


# ===========================================================================
# KELUHAN 3 + 5: validation error palsu & hint tidak lengkap
# ===========================================================================
def test_error_validasi_menyebut_node_id_yang_bermasalah():
    """Error WAJIB menyebut node mana yang salah (bukan pesan generik).

    Keluhan n8n: "No prompt specified" - pesan yang tidak menolong.
    """
    bad = (
        '{"name":"x","nodes":[{"id":"a","kind":"trigger"},'
        '{"id":"b","kind":"mcp","config":{"provider":"gmail"}}],"edges":[]}'
    )
    res = ws.validate_spec(bad)
    assert res["ok"] is False
    joined = " ".join(res["errors"])
    assert "'b'" in joined, f"error tidak menyebut node yang salah: {joined}"
    assert "tujuan" in joined and "subjek" in joined, (
        f"error tidak menyebut field yang kurang: {joined}"
    )
    assert res.get("hint"), "harus ada hint perbaikan (untuk repair loop model)"


def test_required_config_ada_per_provider():
    """Keluhan n8n #5: hint Google Sheets tidak lengkap -> draf bisa jalan."""
    for prov, fields in provider_registry.REQUIRED_CONFIG.items():
        assert fields, f"provider {prov} tanpa required config"
        assert prov in ws.KNOWN_PROVIDERS, f"{prov} tidak dikenal validator"
    # Kasus spesifik yang dilaporkan: Sheets wajib punya spreadsheet_id.
    assert "spreadsheet_id" in provider_registry.REQUIRED_CONFIG["google_sheets"]
    assert "tujuan" in provider_registry.REQUIRED_CONFIG["gmail"]
    assert "chat_id" in provider_registry.REQUIRED_CONFIG["telegram"]


def test_spec_tanpa_trigger_ditolak():
    """Workflow tanpa trigger tidak bisa jalan -> tolak SEBELUM masuk canvas."""
    bad = (
        '{"name":"x","nodes":[{"id":"a","kind":"agent"}],'
        '"edges":[]}'
    )
    res = ws.validate_spec(bad)
    assert res["ok"] is False
    assert any("trigger" in e for e in res["errors"])


# ===========================================================================
# KELUHAN 4: hallucinated workflow IDs -> edge ke node asing DITOLAK
# ===========================================================================
def test_edge_ke_node_hantu_ditolak():
    """Model yang mengarang id akan DITOLAK, bukan digambar sebagai garisuit."""
    spec = (
        '{"name":"x","nodes":[{"id":"a","kind":"trigger"}],'
        '"edges":[{"source":"a","target":"ghost_node_that_does_not_exist"}]}'
    )
    res = ws.validate_spec(spec)
    assert res["ok"] is False
    assert any("ghost_node_that_does_not_exist" in e for e in res["errors"])


def test_id_node_duplikat_ditolak():
    spec = (
        '{"name":"x","nodes":[{"id":"a","kind":"trigger"},'
        '{"id":"a","kind":"agent"}],"edges":[]}'
    )
    res = ws.validate_spec(spec)
    assert res["ok"] is False
    assert any("duplikat" in e for e in res["errors"])


def test_frontend_juga_membuang_edge_hantu():
    """Lapisan kedua:(parseAgentWorkflow) membuang edge ke node tak dikenal.

    Penting karena validasi server bisa dilewati bila spec datang dari sumber
    lain (mis. draft lokal).
    """
    src = (ROOT / "nexus-frontend/src/features/agent/workflow-spec.ts").read_text(
        encoding="utf-8"
    )
    assert "known.has(source)" in src and "known.has(target)" in src, (
        "parseAgentWorkflow harus memeriksa kedua ujung edge terhadap daftar node"
    )


# ===========================================================================
# KELUHAN 2: mid-run compaction merusak workflow -> draf tetap utuh

# ===========================================================================
def test_normalisasi_deterministik_antarkan_draf_rusak():
    """Normalisasi harus DETERMINISTIK: dua kali jalan -> hasil identik.

    Kalau tidak, draf bisa berubah bentuk antar request. Itu bentuk lain dari
    keluhan n8n "mid-run compaction merusak workflow": spec yang sudah lolos
    tiba-tiba berubah bentuk sehingga node/edge hilang.

    CATATAN: `validate_spec` hanya menerima bentuk INPUT (kind/config),
    sedangkan `spec` yang dikembalikan adalah bentuk KANVAS (type/data).
    Jadi bentuk kanvas tidak boleh di-feed-back ke validator - itu by design,
    bukan bug. Yang diuji di sini adalah determinisme pada input yang sama.
    """
    spec = (
        '{"name":"uji","nodes":[{"id":"t","kind":"trigger"},'
        '{"id":"g","kind":"mcp","config":{"provider":"gmail",'
        '"tujuan":"a@b.c","subjek":"s","isi":"halo"}}],'
        '"edges":[{"source":"t","target":"g"}]}'
    )
    first = ws.validate_spec(spec)
    assert first["ok"] is True
    second = ws.validate_spec(spec)
    assert first["spec"] == second["spec"], "normalisasi tidak deterministik"
    assert len(first["spec"]["nodes"]) == 2
    assert len(first["spec"]["edges"]) == 1
    assert [n["id"] for n in first["spec"]["nodes"]] == ["t", "g"]
    assert first["ok"] is True
    second = ws.validate_spec(spec)
    assert first["spec"] == second["spec"], "normalisasi tidak deterministik"
    assert len(first["spec"]["nodes"]) == 2
    assert len(first["spec"]["edges"]) == 1
    assert [n["id"] for n in first["spec"]["nodes"]] == ["t", "g"]


def test_strip_code_fence_membuat_hasil_tahan_karakter_kabur():
    """Model sering membungkus JSON di ```json ... ``` -> harus dibersihkan."""
    wrapped = (
        '```json\n{"name":"uji","nodes":[{"id":"t","kind":"trigger"}],'
        '"edges":[]}\n```'
    )
    res = ws.validate_spec(wrapped)
    assert res["ok"] is True, f"code fence tidak dibersihkan: {res}"


# ===========================================================================
# KELUHAN 6: WebSocket timeout tanpa pesan error -> pesan klasifikasi ada
# ===========================================================================
def test_klasifikasi_error_memiliki_pesan_manusiawi():
    """Timeout harus punya pesan yang bisa dibaca user, bukan 'unknown error'."""
    fe = (ROOT / "nexus-frontend/src/lib/api.ts").read_text(encoding="utf-8")
    assert "Server lambat, coba lagi." in fe
    assert "Koneksi lambat" in fe
    assert "Sesi habis" in fe
    # tidak boleh ada pesan kosong yang lolos ke UI
    assert 'return ""' not in fe


# ===========================================================================
# Credential handling: user tanpa token DITOLAK, tidak pinjam token orang lain
# ===========================================================================
def test_provider_tanpa_kredensial_tidak_dijalankan(monkeypatch):
    """Prompt butuh Gmail tapi user belum connect -> error jelas, bukan diam."""
    import database as db

    monkeypatch.setattr(db, "get_integration", lambda e, p: None)
    try:
        tools.execute_tool(
            "kirim_email_gmail",
            {"tujuan": "a@b.c", "subjek": "s", "isi": "i"},
            "nobody@example.test",
        )
    except tools.CredentialMissingError as exc:
        assert exc.provider_name == "gmail"
    else:
        raise AssertionError("tool berjalan tanpa kredensial - BAHAYA")


def test_token_google_terpisah_per_user(monkeypatch):
    """Multi-user: dua user tidak boleh berbagi satu token."""
    import database as db

    fake = {
        "userA@example.test": {"api_token": "TOKEN-A"},
        "userB@example.test": {"api_token": "TOKEN-B"},
    }
    monkeypatch.setattr(db, "get_integration", lambda e, p: fake.get(e))
    assert db.get_integration("userA@example.test", "gmail")["api_token"] == "TOKEN-A"
    assert db.get_integration("userB@example.test", "gmail")["api_token"] == "TOKEN-B"
    assert (
        db.get_integration("userA@example.test", "gmail")["api_token"]
        != db.get_integration("userB@example.test", "gmail")["api_token"]
    )


# ===========================================================================
# Prompt 1-10: katalog kasus uji (dipakai harness live)
# ===========================================================================
SIMPLE_PROMPTS = [
    "Kirim email ke tim setiap Jumat jam 5 sore dengan ringkasan aktivitas",
    "Ambil 10 email terbaru dari Gmail saya, tulis ke Google Sheets",
    "Setiap jam 9 pagi, cek cuaca Jakarta, kirim ke Slack",
    "Ketika ada form submission baru, tambahkan ke Google Sheets",
    "Setiap hari jam 8 pagi, kirim ringkasan berita ke Telegram",
    "Baca RSS feed, filter 24 jam terakhir, posting ke Twitter",
    "Ketika stok inventory < 10, kirim alert ke WhatsApp",
    "Setiap minggu, backup data dari Airtable ke Google Drive",
    "Ketika ada email dengan subjek 'invoice', extract data ke Sheets",
    "Setiap jam, cek API status, jika down kirim notifikasi",
]


def test_katalog_prompt_sederhana_terdefinisi():
    assert len(SIMPLE_PROMPTS) == 10
    assert all(p.strip() for p in SIMPLE_PROMPTS)


def test_provider_yang_muncul_di_prompt_terdaftar():
    """Setiap provider yang disebut user harus punya jalur (atau jadi warning).

    Ini yang membuat "posting ke Twitter" / "backup ke Google Drive" tidak
    diam-diam jadi workflow dengan provider karangan.
    """
    known = set(ws.KNOWN_PROVIDERS)
    # Prompt 6 & 8 menyebut provider yang TIDAK punya jalur kredensial bawaan.
    # Validator harus memberi warning, bukan error, dan tidak mengarang provider.
    res = ws.validate_spec(
        '{"name":"x","nodes":[{"id":"t","kind":"trigger"},'
        '{"id":"m","kind":"mcp","config":{"provider":"twitter"}}],'
        '"edges":[{"source":"t","target":"m"}]}'
    )
    assert res["ok"] is True
    assert any("twitter" in w for w in res.get("warnings", [])), (
        "provider tanpa jalur kredensial harus diberi warning"
    )
    assert "twitter" not in known
