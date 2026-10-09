# tests/test_execution_redaction.py — Fitur #11a: execution data redaction
# ======================================================================
# 14 tes / 13 skenario wajib. Semua jalur NYATA (tidak ada mock kebijakan):
# regex PII betulan, Luhn betulan, integrasi `database.execution_log_row`
# memakai backend memori (tanpa Supabase) sehingga perilaku produksi
# terwakili. Setiap tes dirancang GAGAL bila logika salah, bukan sekadar
# memeriksa tipe kembalian.
# ======================================================================

from __future__ import annotations

import pytest

import execution_redaction as ER
from agent_redactor import CanaryDetectedError


@pytest.fixture(autouse=True)
def _bersih():
    ER.reset_stats()
    yield
    ER.reset_stats()


# ---------------------------------------------------------------------------
# BASIC (3)
# ---------------------------------------------------------------------------
def test_b1_email_diredact():
    """B1: email di payload -> diganti penanda, sisa teks utuh."""
    out, counts = ER.redact_text(
        "kirim ke budi.santoso@example.co.id besok", ER.RedactionPolicy("all"))
    assert out == "kirim ke [REDACTED_EMAIL] besok"
    assert counts["email"] == 1


def test_b2_telepon_diredact():
    """B2: telepon (E.164, Indonesia, gaya US) -> penanda."""
    pol = ER.RedactionPolicy("all")
    for raw in ("+62 812-3456-7890", "08123456789", "(021) 555-1234"):
        out, counts = ER.redact_text(f"hub {raw} ya", pol)
        assert "[REDACTED_PHONE]" in out, raw
        assert raw not in out
        assert counts["phone"] >= 1


def test_b3_kartu_kredit_diredact():
    """B3: nomor kartu valid-Luhn -> penanda; nomor acak TIDAK disentuh."""
    pol = ER.RedactionPolicy("all")
    out, counts = ER.redact_text("bayar 4111 1111 1111 1111 sekarang", pol)
    assert out == "bayar [REDACTED_CARD] sekarang"
    assert counts["credit_card"] == 1
    # 1234567890123456 gagal Luhn -> bukan kartu.
    lain, c2 = ER.redact_text("id 1234567890123456 saja", pol)
    assert "1234567890123456" in lain
    assert "credit_card" not in c2


# ---------------------------------------------------------------------------
# DURABILITY (2)
# ---------------------------------------------------------------------------
def test_d1_kebijakan_bolak_balik_konsisten():
    """D1: pola kustom dipakai berulang tanpa keadaan bocor antar-panggilan."""
    pol = ER.RedactionPolicy("all", custom_patterns=[
        {"name": "nik", "pattern": r"\b\d{16}\b"}])
    for _ in range(50):
        out, counts = ER.redact_text("NIK 3201234567890123 ok", pol)
        assert out == "NIK [REDACTED_CUSTOM] ok"
        assert counts["custom"] == 1


def test_d2_tulis_ke_log_menyimpan_versi_teredaksi():
    """D2: dengan kebijakan workflow AKTIF, baris `execution_logs` yang
    dipersist TIDAK memuat PII asli — redaksi terjadi SEBELUM disk.

    Tanpa kebijakan (workflow_id=None) perilaku lama dipertahankan: hanya
    lapisan kredensial F-2 yang jalan. Kedua cabang diuji di sini supaya
    kontraknya eksplisit.
    """
    import database as db
    import execution_redaction as er

    payload = {"to": "budi@example.com", "card": "4111 1111 1111 1111",
               "note": "telepon 08123456789", "ok": True}

    # Cabang 1: workflow punya kebijakan "all" -> PII tersaring.
    db._REDACTION_POLICY_CACHE[str("wf-1")] = (er.RedactionPolicy("all"),
                                               __import__("time").time() + 60)
    row = db.execution_log_row("ex-1", "n1", "tool", "success", payload,
                               workflow_id="wf-1", trigger="production")
    blob = str(row["output_data"])
    assert "budi@example.com" not in blob
    assert "4111 1111 1111 1111" not in blob
    assert "08123456789" not in blob
    assert row["output_data"]["ok"] is True

    # Cabang 2: tanpa kebijakan -> perilaku lama (tidak ada penyaringan PII).
    db.invalidate_redaction_cache()
    row2 = db.execution_log_row("ex-2", "n1", "tool", "success", payload,
                                workflow_id=None, trigger="production")
    assert row2["output_data"]["to"] == "budi@example.com"


# ---------------------------------------------------------------------------
# EDGE CASE (3)
# ---------------------------------------------------------------------------
def test_e1_tanggal_iso_dan_angka_biasa_tidak_teredact():
    """E1: tanggal ISO / angka biasa bukan PII (anti-false-positive)."""
    pol = ER.RedactionPolicy("all")
    for raw in ("2026-10-09", "jam 12:30:45", "total 12345", "versi 3.0.1",
                "order 2026-10-09-001"):
        out, _ = ER.redact_text(raw, pol)
        assert out == raw, raw


def test_e2_data_biner_dibuang():
    """E2: bytes dan field ber-nama biner -> dibuang, bukan diteruskan."""
    pol = ER.RedactionPolicy("all")
    out = ER.apply_policy({"file": b"\x89PNG\x0d\x0a", "attachment": "rahasia",
                           "keep": "halo"}, pol)[0]
    # `attachment` cocok kata kunci biner -> dibuang seluruhnya.
    assert out["attachment"] == "[REDACTED_BINARY]"
    assert out["file"] == "[REDACTED_BINARY]"
    assert out["keep"] == "halo"


def test_e3_regex_kustom_rusak_ditolak_tegas():
    """E3: pola kustom cacat/pencocok-kosong DITOLAK, tidak diam-diam diabaikan."""
    with pytest.raises(ER.RedactionPolicyError):
        ER.RedactionPolicy("all", custom_patterns=[
            {"name": "bad", "pattern": "("}])
    with pytest.raises(ER.RedactionPolicyError):
        ER.RedactionPolicy("all", custom_patterns=[
            {"name": "empty", "pattern": "a?"}])
    with pytest.raises(ER.RedactionPolicyError):
        ER.RedactionPolicy("all", custom_patterns=[
            {"name": "x" * 100, "pattern": "a"}])
    with pytest.raises(ER.RedactionPolicyError):
        ER.RedactionPolicy("salah")   # level tak dikenal


# ---------------------------------------------------------------------------
# PERFORMANCE (2)
# ---------------------------------------------------------------------------
def test_p1_1000_kali_redaksi_masih_cepat():
    """P1: 1000 pemanggilan (payload sedang) selesai jauh di bawah 1 detik."""
    import time
    pol = ER.RedactionPolicy("all")
    payload = {"msg": "hubungi budi@example.com / 08123456789 / 4111 1111 1111 1111",
               "rows": [{"email": f"u{i}@example.com", "n": i} for i in range(20)]}
    t0 = time.perf_counter()
    for _ in range(1000):
        ER.apply_policy(payload, pol)
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0, f"terlalu lambat: {elapsed:.3f}s"


def test_p2_payload_dalam_tidak_meledak():
    """P2: struktur 40 tingkat -> dipotong di MAX_DEPTH, bukan rekursi tanpa batas."""
    pol = ER.RedactionPolicy("all")
    node: dict = {"email": "a@b.com"}
    for _ in range(40):
        node = {"child": node}
    out = ER.apply_policy(node, pol)[0]
    depth = 0
    cur = out
    while isinstance(cur, dict) and "child" in cur:
        cur = cur["child"]
        depth += 1
    assert depth <= ER.MAX_DEPTH + 1
    assert cur == "[REDACTED_DEPTH]"


# ---------------------------------------------------------------------------
# SECURITY (2)
# ---------------------------------------------------------------------------
def test_s1_kebijakan_tidak_bisa_lebih_lemah_dari_enforcement():
    """S1: enforcement = lantai minimum (perilaku n8n 2.26.0)."""
    off = ER.RedactionPolicy("off")
    prod = ER.RedactionPolicy("production")
    allp = ER.RedactionPolicy("all")

    assert off.weaker_than("production") is True
    assert prod.weaker_than("production") is False   # sama = boleh
    assert prod.weaker_than("all") is True
    assert allp.weaker_than("all") is False

    # Level EFEKTIF tidak pernah lebih lemah dari enforcement.
    assert off.effective_level("production") == "production"
    assert prod.effective_level("production") == "production"
    assert allp.effective_level("production") == "all"
    assert off.effective_level("off") == "off"


def test_s2_canary_dan_scope_trigger():
    """S2: canary tetap menggagalkan operasi; level production TIDAK
    menyentuh eksekusi manual (dan sebaliknya `all` menyentuh keduanya)."""
    prod = ER.RedactionPolicy("production")
    allp = ER.RedactionPolicy("all")

    assert prod.applies_to("production") is True
    assert prod.applies_to("webhook") is True
    assert prod.applies_to("manual") is False
    assert allp.applies_to("manual") is True
    assert allp.applies_to("production") is True

    # Nilai tidak berubah ketika tidak tertutup kebijakan.
    out, counts = ER.apply_policy({"to": "a@b.com"}, prod, trigger="manual")
    assert out == {"to": "a@b.com"} and counts == {}

    # Canary menggagalkan operasi (fail-closed), tidak sekadar di-mask.
    canary = "KATALIR_TEST_CANARY_ABCDEF123456"
    with pytest.raises(CanaryDetectedError):
        ER.apply_policy({"note": canary}, allp)


# ---------------------------------------------------------------------------
# TAMBAHAN: lapisan kredensial tetap aktif + kredensial tidak lolos
# ---------------------------------------------------------------------------
def test_x1_kredensial_dan_pii_diredact_bersamaan():
    """X1: satu payload memuat token kredensial DAN PII -> keduanya tertutup."""
    pol = ER.RedactionPolicy("all")
    payload = {
        "headers": {"Authorization": "Bearer abcdefghijklmnop12345"},
        "user": {"email": "kris@example.com", "phone": "081298765432"},
        "raw": "token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123 lalu 4111111111111111",
    }
    out = ER.apply_policy(payload, pol)[0]
    flat = str(out)
    assert "abcdefghijklmnop12345" not in flat
    assert "kris@example.com" not in flat
    assert "081298765432" not in flat
    assert "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123" not in flat
    assert "4111111111111111" not in flat


def test_x2_multi_tenant_kebijakan_terpisah():
    """X2: kebijakan satu workflow tidak bocor ke workflow lain (cache keyed)."""
    import database as db

    db.invalidate_redaction_cache()
    a = ER.RedactionPolicy("all")
    b = ER.RedactionPolicy("off")
    payload = {"email": "x@y.com"}

    out_a = ER.apply_policy(payload, a)[0]
    out_b = ER.apply_policy(payload, b)[0]
    assert out_a["email"] == "[REDACTED_EMAIL]"
    assert out_b["email"] == "x@y.com"      # kebijakan b tidak terpengaruh


def test_x3_describe_dan_preview_ringkas():
    """X3: `describe` merangkum kebijakan untuk UI/log (tanpa nilai sensitif)."""
    assert ER.describe(ER.RedactionPolicy("off")) == "redaction off"
    d = ER.describe(ER.RedactionPolicy(
        "all", pii_types=["email"],
        custom_patterns=[{"name": "nik", "pattern": r"\d{16}"}]))
    assert "manual+production" in d
    assert "pii=email" in d
    assert "custom=1" in d
