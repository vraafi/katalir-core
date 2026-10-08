# tests/test_secrets_provider.py — Fitur #7 (8 Okt 2026)
# =====================================================================
# Hard test External Secrets Manager. 12 skenario (brief minta min 8).
#
# Yang diuji (BUKTI raw output):
#   1   KatalirVault: set + get satu field
#   2   KatalirVault: set multi-field lalu ambil salah satu
#   3   KatalirVault: field bersarang (a.b)
#   4   KatalirVault: set dari JSON (tanpa field) lalu baca field
#   5   get field yang tidak ada -> None (bukan exception)
#   6   delete field -> hilang; delete provider -> hilang
#   7   list_paths hanya provider milik owner
#   8   ISOLASI: user lain tidak bisa membaca rahasia (kebocoran = GAGAL)
#   9   parse_ref: semua bentuk (`secret://p/f`, `secret://katalir/p/f`,
#       `secret://aws/v/i/f`) benar
#   10  resolve() end-to-end + SecretNotFound bila tidak ada
#   11  KEAMANAN: nilai rahasia TIDAK muncul di pesan error & redact() benar
#   12  Backend eksternal: dilaporkan available=False secara jujur
#       (bukan crash), dan backend tak dikenal ditolak
# =====================================================================
import json
import os
import uuid

import pytest

import database as db
import secrets_provider as sp


@pytest.fixture()
def owner():
    """Email unik per tes; bersihkan baris user_vault setelahnya."""
    email = f"sec-{uuid.uuid4().hex[:10]}@katalir-test.local"
    yield email
    try:
        svc = db.get_write_client()
        svc.table("user_vault").delete().eq("email", email).execute()
    except Exception as exc:  # noqa: BLE001
        print(f"[cleanup] {exc}")


def _clear_cache():
    """Bersihkan cache vault supaya baca ulang menyentuh DB."""
    try:
        import vault_cache
        if hasattr(vault_cache, "clear"):
            vault_cache.clear()
        elif hasattr(vault_cache, "invalidate"):
            vault_cache.invalidate()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# 1. set + get satu field
# ---------------------------------------------------------------------------
def test_01_set_dan_get_satu_field(owner):
    p = sp.get_provider("katalir")
    ok = p.set("demo_provider/api_key", "RAHASIA-123", owner)
    _clear_cache()
    nilai = p.get("demo_provider/api_key", owner)
    print(f"[1] set={ok} get={nilai!r}")
    assert ok is True
    assert nilai == "RAHASIA-123"


# ---------------------------------------------------------------------------
# 2. multi-field: simpan dua, ambil masing-masing
# ---------------------------------------------------------------------------
def test_02_multi_field(owner):
    p = sp.get_provider("katalir")
    p.set("multi/user", "budi", owner)
    p.set("multi/pass", "sandi#9", owner)
    _clear_cache()
    print(f"[2] user={p.get('multi/user', owner)!r} "
          f"pass={p.get('multi/pass', owner)!r}")
    assert p.get("multi/user", owner) == "budi"
    assert p.get("multi/pass", owner) == "sandi#9"
    # set field kedua TIDAK menghapus field pertama (penggabungan)
    assert p.get("multi/user", owner) == "budi"


# ---------------------------------------------------------------------------
# 3. field bersarang "a.b"
# ---------------------------------------------------------------------------
def test_03_field_bersarang(owner):
    p = sp.get_provider("katalir")
    # simpan sebagai JSON dengan objek bersarang
    p.set("nest", json.dumps({"db": {"host": "db.internal",
                                     "port": "5432"}}), owner)
    _clear_cache()
    print(f"[3] db.host={p.get('nest/db.host', owner)!r} "
          f"db.port={p.get('nest/db.port', owner)!r}")
    assert p.get("nest/db.host", owner) == "db.internal"
    assert p.get("nest/db.port", owner) == "5432"


# ---------------------------------------------------------------------------
# 4. set dari JSON (tanpa field) lalu baca field
# ---------------------------------------------------------------------------
def test_04_set_json_tanpa_field(owner):
    p = sp.get_provider("katalir")
    p.set("jsonprov", json.dumps({"token": "T-1", "refresh": "R-2"}), owner)
    _clear_cache()
    print(f"[4] token={p.get('jsonprov/token', owner)!r}")
    assert p.get("jsonprov/token", owner) == "T-1"
    assert p.get("jsonprov/refresh", owner) == "R-2"
    # JSON tanpa field -> seluruh isi sebagai JSON kanonik
    semua = p.get("jsonprov", owner)
    print(f"[4] seluruh provider = {semua}")
    assert json.loads(semua)["token"] == "T-1"


# ---------------------------------------------------------------------------
# 5. field tak ada -> None
# ---------------------------------------------------------------------------
def test_05_field_tidak_ada_none(owner):
    p = sp.get_provider("katalir")
    p.set("ada/x", "v", owner)
    _clear_cache()
    tidak_ada = p.get("ada/tidak_ada", owner)
    provider_tidak_ada = p.get("belum_pernah", owner)
    print(f"[5] field hilang={tidak_ada!r} provider hilang={provider_tidak_ada!r}")
    assert tidak_ada is None
    assert provider_tidak_ada is None


# ---------------------------------------------------------------------------
# 6. delete
# ---------------------------------------------------------------------------
def test_06_delete(owner):
    p = sp.get_provider("katalir")
    p.set("hapus/a", "1", owner)
    p.set("hapus/b", "2", owner)
    _clear_cache()
    assert p.get("hapus/a", owner) == "1"
    hapus = p.delete("hapus/a", owner)
    _clear_cache()
    print(f"[6] delete field={hapus} a={p.get('hapus/a', owner)!r} "
          f"b={p.get('hapus/b', owner)!r}")
    assert hapus is True
    assert p.get("hapus/a", owner) is None
    assert p.get("hapus/b", owner) == "2"      # field lain tetap
    # delete provider penuh
    hapus2 = p.delete("hapus", owner)
    _clear_cache()
    print(f"[6] delete provider={hapus2} b={p.get('hapus/b', owner)!r}")
    assert hapus2 is True
    assert p.get("hapus/b", owner) is None


# ---------------------------------------------------------------------------
# 7. list_paths milik owner
# ---------------------------------------------------------------------------
def test_07_list_paths(owner):
    p = sp.get_provider("katalir")
    p.set("p_daftar/x", "1", owner)
    _clear_cache()
    daftar = p.list_paths(owner)
    print(f"[7] list_paths={daftar}")
    assert "p_daftar" in daftar


# ---------------------------------------------------------------------------
# 8. ISOLASI antar-user
# ---------------------------------------------------------------------------
def test_08_isolasi_antar_user(owner):
    p = sp.get_provider("katalir")
    p.set("rahasia/api_key", "PUNYA-OWNER", owner)
    _clear_cache()

    # owner bisa baca
    assert p.get("rahasia/api_key", owner) == "PUNYA-OWNER"

    # user asing TIDAK bisa
    asing = f"asing-{uuid.uuid4().hex[:10]}@katalir-test.local"
    nilai_asing = p.get("rahasia/api_key", asing)
    print(f"[8] owner={p.get('rahasia/api_key', owner)!r} asing={nilai_asing!r}")
    assert nilai_asing is None, "KEBOCORAN: user asing membaca rahasia!"

    # resolve() juga harus gagal untuk user asing
    with pytest.raises(sp.SecretNotFound):
        sp.resolve("secret://rahasia/api_key", asing)
    print("[8] resolve() untuk user asing -> SecretNotFound (benar)")

    # list_paths user asing tidak memuat provider owner
    daftar_asing = p.list_paths(asing)
    print(f"[8] list_paths asing={daftar_asing}")
    assert "rahasia" not in daftar_asing


# ---------------------------------------------------------------------------
# 9. parse_ref semua bentuk
# ---------------------------------------------------------------------------
def test_09_parse_ref():
    kasus = [
        ("secret://gmail_imap/app_password", ("katalir", "gmail_imap", "app_password")),
        ("secret://katalir/gmail_imap/x", ("katalir", "gmail_imap", "x")),
        ("secret://aws/prod/db/pass", ("aws", "prod/db", "pass")),
        ("secret://hashicorp/vault/item/field", ("hashicorp", "vault/item", "field")),
        ("secret://onepassword/op/item/field", ("onepassword", "op/item", "field")),
        ("secret://gmail_imap", ("katalir", "gmail_imap", None)),
    ]
    for ref, harap in kasus:
        dapat = sp.parse_ref(ref)
        print(f"[9] {ref:42} -> {dapat}")
        assert dapat == harap, f"{ref}: dapat {dapat}, harap {harap}"

    # bentuk salah ditolak
    for buruk in ["", "bukan-secret://x/y", "secret://"]:
        with pytest.raises(sp.SecretRefError):
            sp.parse_ref(buruk)
    print("[9] bentuk salah ditolak (SecretRefError)")


# ---------------------------------------------------------------------------
# 10. resolve() end-to-end
# ---------------------------------------------------------------------------
def test_10_resolve_end_to_end(owner):
    p = sp.get_provider("katalir")
    p.set("gmail/app_pass", "APP-PASS-999", owner)
    _clear_cache()
    nilai = sp.resolve("secret://gmail/app_pass", owner)
    print(f"[10] resolve={nilai!r}")
    assert nilai == "APP-PASS-999"

    # resolve_in_args rekursif
    args = {"a": "secret://gmail/app_pass", "b": "biasa",
            "c": {"d": "secret://gmail/app_pass"}, "e": ["secret://gmail/app_pass", 1]}
    hasil = sp.resolve_in_args(args, owner)
    print(f"[10] resolve_in_args -> b={hasil['b']!r} c.d={hasil['c']['d']!r} "
          f"e[0]={hasil['e'][0]!r}")
    assert hasil["a"] == "APP-PASS-999"
    assert hasil["b"] == "biasa"
    assert hasil["c"]["d"] == "APP-PASS-999"
    assert hasil["e"][0] == "APP-PASS-999"

    # tidak ada -> SecretNotFound
    with pytest.raises(sp.SecretNotFound):
        sp.resolve("secret://gmail/tidak_ada", owner)
    print("[10] secret tidak ada -> SecretNotFound (benar)")


# ---------------------------------------------------------------------------
# 11. KEAMANAN: rahasia tidak bocor ke pesan error; redact() benar
# ---------------------------------------------------------------------------
def test_11_rahasia_tidak_bocor(owner):
    p = sp.get_provider("katalir")
    NILAI = "SUPER-SECRET-JANGAN-BOCOR-42"
    p.set("bocor/api", NILAI, owner)
    _clear_cache()

    # pesan error SecretNotFound TIDAK boleh memuat nilai
    try:
        sp.resolve("secret://bocor/tidak_ada", owner)
        raise AssertionError("seharusnya SecretNotFound")
    except sp.SecretNotFound as exc:
        pesan = str(exc)
        print(f"[11] pesan error: {pesan}")
        assert NILAI not in pesan, "KEBOCORAN: nilai rahasia di pesan error!"
        assert "bocor" in pesan           # nama path (bukan nilai) boleh

    # redact() menutupi referensi
    arg = {"key": "secret://bocor/api", "biasa": "terlihat",
           "bersarang": {"d": "secret://bocor/api"}, "list": ["secret://x/y"]}
    merah = sp.redact(arg)
    print(f"[11] redact -> {merah}")
    assert merah["key"] == sp.MASK
    assert merah["biasa"] == "terlihat"
    assert merah["bersarang"]["d"] == sp.MASK
    assert merah["list"][0] == sp.MASK
    assert NILAI not in json.dumps(merah)


# ---------------------------------------------------------------------------
# 12. Backend eksternal dilaporkan jujur; backend tak dikenal ditolak
# ---------------------------------------------------------------------------
def test_12_backend_eksternal_jujur():
    status = sp.describe_backends()
    print(f"[12] status backend: {[(b['backend'], b['available']) for b in status]}")
    katalir = next(b for b in status if b["backend"] == "katalir")
    assert katalir["available"] is True, "KatalirVault harus selalu tersedia"

    # backend eksternal yang paketnya tidak terpasang: available False, TIDAK crash
    for nama in ("hashicorp", "aws", "onepassword"):
        ada = next(b for b in status if b["backend"] == nama)["available"]
        print(f"[12] {nama}: available={ada}")
        prov = sp.get_provider(nama)
        assert prov.available() == ada
        if not ada:
            with pytest.raises(sp.BackendUnavailable):
                prov.get("x/y", "a@b.c")
            print(f"[12] {nama}.get() -> BackendUnavailable (jujur)")

    # backend tak dikenal ditolak
    with pytest.raises(sp.BackendUnavailable):
        sp.get_provider("tidak_ada_backend")
    print("[12] backend tak dikenal ditolak")
