# tests/test_secrets_enterprise.py — Fitur #1 hard test (12 skenario, Okt 2026)
# Deterministik, TANPA jaringan: backend eksternal disimulasikan lewat provider
# palsu yang disuntikkan ke registry. Yang diuji adalah JALUR DISPATCH nyata
# (parse_ref -> get_provider -> get) dan kontrak keamanan, bukan koneksi HTTP.
from __future__ import annotations

import time

import pytest

import secrets_provider as sp


class _FakeProvider(sp.SecretsProvider):
    """Provider in-memory: dict[(owner, path)] -> nilai."""

    def __init__(self, name: str = "fake", store: dict | None = None):
        self.name = name
        self.store: dict = store if store is not None else {}
        self.calls: list[tuple[str, str]] = []
        self.down = False

    def available(self) -> bool:
        return not self.down

    def get(self, path: str, owner: str):
        self.calls.append((path, owner))
        if self.down:
            raise RuntimeError("backend down")
        return self.store.get((owner, path))

    def set(self, path: str, value: str, owner: str) -> bool:
        sp.check_size(value)
        self.store[(owner, path)] = value
        return True


@pytest.fixture
def fake_registry(monkeypatch):
    """Ganti get_provider dengan registry palsu yang bisa dikontrol test."""
    provs: dict[str, _FakeProvider] = {}

    def _mk(name):
        if name not in provs:
            provs[name] = _FakeProvider(name)
        return provs[name]

    # Buat backend umum lebih dulu supaya test bisa menyemai nilai sebelum
    # `resolve` dipanggil (provider di-cache, jadi objeknya sama).
    for _n in ("katalir", "hashicorp", "aws", "onepassword", "infisical",
               "doppler"):
        _mk(_n)

    monkeypatch.setattr(sp, "get_provider", lambda name="katalir": _mk(name))
    monkeypatch.setattr(sp, "default_provider_name", lambda: "katalir")
    return provs


# 1. Backend Katalir (bawaan) tetap berfungsi
def test_01_katalir_backend_still_works(fake_registry):
    fake_registry["katalir"].store[("u@x.com", "gmail_imap/app_password")] = "rahasia-1"
    assert sp.resolve("secret://gmail_imap/app_password", "u@x.com") == "rahasia-1"


# 2. Dispatch ke HashiCorp Vault
def test_02_hashicorp_dispatch(fake_registry):
    fake_registry["hashicorp"].store[("u@x.com", "app/key")] = "hc-value"
    assert sp.resolve("secret://hashicorp/app/key", "u@x.com") == "hc-value"
    assert fake_registry["hashicorp"].calls == [("app/key", "u@x.com")]


# 3. Dispatch ke AWS Secrets Manager
def test_03_aws_dispatch(fake_registry):
    fake_registry["aws"].store[("u@x.com", "prod/db")] = "aws-value"
    assert sp.resolve("secret://aws/prod/db", "u@x.com") == "aws-value"


# 4. Dispatch ke 1Password
def test_04_onepassword_dispatch(fake_registry):
    fake_registry["onepassword"].store[("u@x.com", "vault/item/pass")] = "op-value"
    assert sp.resolve("secret://onepassword/vault/item/pass", "u@x.com") == "op-value"


# 5. Parsing 10 format referensi
@pytest.mark.parametrize("fmt", sp.SECRET_REF_FORMATS)
def test_05_ref_parsing_formats(fmt):
    backend, path, field = sp.parse_ref(fmt["contoh"])
    assert isinstance(backend, str) and backend
    assert isinstance(path, str) and path
    assert field is None or isinstance(field, str)


def test_05b_ref_parsing_explicit_backend():
    assert sp.parse_ref("secret://aws/prod/db/pass") == ("aws", "prod/db", "pass")
    assert sp.parse_ref("secret://gmail_imap/app_password") == (
        "katalir", "gmail_imap", "app_password")


# 6. Rotasi: versi naik, nilai baru terpakai
def test_06_rotation_bumps_version(fake_registry):
    sp.set_rotation_store(sp.RotationStore())
    fake_registry["katalir"].store[("u@x.com", "db/pass")] = "lama"
    r1 = sp.rotate("secret://db/pass", "baru-1", "u@x.com")
    assert r1["version"] == 1
    assert sp.resolve("secret://db/pass", "u@x.com") == "baru-1"
    r2 = sp.rotate("secret://db/pass", "baru-2", "u@x.com")
    assert r2["version"] == 2
    assert sp.rotation_store().current_version("u@x.com", "db/pass") == 2
    assert len(sp.rotation_store().history("u@x.com", "db/pass")) == 2


# 7. Failover: backend pertama down -> jatuh ke berikutnya
def test_07_failover_falls_back(fake_registry):
    fake_registry["hashicorp"].down = True  # backend rusak
    fake_registry["katalir"].store[("u@x.com", "app/key")] = "fallback-ok"
    nilai = sp.resolve_with_failover(
        "secret://hashicorp/app/key", "u@x.com",
        chain=["hashicorp", "katalir"])
    assert nilai == "fallback-ok"


def test_07b_failover_all_down_raises(fake_registry):
    fake_registry["hashicorp"].down = True
    with pytest.raises(sp.SecretNotFound):
        sp.resolve_with_failover("secret://hashicorp/x/y", "u@x.com",
                                 chain=["hashicorp", "katalir"])


# 8. Akses paralel 1000 resolve
def test_08_concurrent_resolve_1000(fake_registry):
    store = fake_registry["katalir"].store
    refs = [f"secret://p{i}/f" for i in range(1000)]
    for i in range(1000):
        store[("u@x.com", f"p{i}/f")] = f"v{i}"
    hasil = sp.resolve_many(refs, "u@x.com", max_workers=32)
    assert len(hasil) == 1000
    assert all(hasil[r] is not None for r in refs)
    assert hasil["secret://p500/f"] == "v500"


# 9. Isolasi multi-tenant
def test_09_multi_tenant_isolation(fake_registry):
    store = fake_registry["katalir"].store
    store[("a@x.com", "svc/key")] = "milik-A"
    store[("b@x.com", "svc/key")] = "milik-B"
    assert sp.resolve("secret://svc/key", "a@x.com") == "milik-A"
    assert sp.resolve("secret://svc/key", "b@x.com") == "milik-B"
    # user tanpa entri -> tidak menemukan
    with pytest.raises(sp.SecretNotFound):
        sp.resolve("secret://svc/key", "c@x.com")


# 10. Performa: 100 resolve < 1s
def test_10_performance_100_resolves(fake_registry):
    store = fake_registry["katalir"].store
    refs = [f"secret://q{i}/f" for i in range(100)]
    for i in range(100):
        store[("u@x.com", f"q{i}/f")] = f"v{i}"
    t0 = time.perf_counter()
    sp.resolve_many(refs, "u@x.com", max_workers=16)
    dt = time.perf_counter() - t0
    assert dt < 1.0, f"100 resolve terlalu lambat: {dt:.3f}s"


# 11. Batas ukuran rahasia 256 KiB
def test_11_secret_size_limit():
    ok = "x" * (sp.MAX_SECRET_BYTES)
    assert sp.check_size(ok) == sp.MAX_SECRET_BYTES
    with pytest.raises(sp.SecretTooLarge):
        sp.check_size("x" * (sp.MAX_SECRET_BYTES + 1))


def test_11b_rotate_rejects_oversize(fake_registry):
    with pytest.raises(sp.SecretTooLarge):
        sp.rotate("secret://db/pass", "x" * (sp.MAX_SECRET_BYTES + 1), "u@x.com")


# 12. Path traversal & karakter berbahaya ditolak
@pytest.mark.parametrize("bad", [
    "secret://../../etc/passwd",
    "secret://a/../../b",
    "secret://a/..",
    "secret://a/b\\c",
    "secret://a/b\x00c",
    "secret://a/b c",
])
def test_12_path_traversal_blocked(bad):
    with pytest.raises(sp.SecretRefError):
        sp.parse_ref(bad)


# 13. Backend baru terdaftar + dilaporkan UI
def test_13_new_backends_registered():
    assert "infisical" in sp.REGISTRY
    assert "doppler" in sp.REGISTRY
    nama = {d["backend"] for d in sp.describe_backends()}
    assert {"infisical", "doppler", "katalir"} <= nama


# 14. Referensi tanpa field mengembalikan seluruh provider (JSON)
def test_14_no_field_returns_provider_json(fake_registry):
    fake_registry["katalir"].store[("u@x.com", "svc")] = '{"a": "1", "b": "2"}'
    val = sp.resolve("secret://svc", "u@x.com")
    assert val is not None and "a" in val


# ---------------------------------------------------------------------------
# Regresi temuan hard test LIVE (3 provider nyata) — Okt 2026
# ---------------------------------------------------------------------------

# 15. BUG NYATA: `secret://backend//abs` dulu DITERIMA (segmen kosong dibuang
#     diam-diam -> referensi "absolut" berubah bentuk tanpa peringatan).
def test_15_referensi_absolut_dan_segmen_kosong_ditolak():
    for buruk in ("secret://openbao//etc/shadow",
                  "secret:///etc/shadow",
                  "secret://openbao///x",
                  "secret://aws//prod/db"):
        with pytest.raises(sp.SecretRefError):
            sp.parse_ref(buruk)
    # bentuk normal TETAP valid (tidak over-blocking)
    assert sp.parse_ref("secret://openbao/demo/db") == ("openbao", "demo", "db")
    assert sp.parse_ref("secret://aws/prod/db/pass") == ("aws", "prod/db", "pass")
    assert sp.parse_ref("secret://gmail_imap/app_password") == (
        "katalir", "gmail_imap", "app_password")


# 16. OpenBao terdaftar sebagai backend BERBEDA dari Vault (env terpisah)
def test_16_openbao_backend_terpisah_dari_vault(monkeypatch):
    assert sp.REGISTRY["openbao"] is sp.OpenBaoVault
    assert sp.REGISTRY["hashicorp"] is sp.HashiCorpVault
    assert issubclass(sp.OpenBaoVault, sp.HashiCorpVault)
    # prefiks env WAJIB berbeda supaya dua server bisa hidup berdampingan
    assert sp.OpenBaoVault.ENV_ADDR != sp.HashiCorpVault.ENV_ADDR
    monkeypatch.setenv("KATALIR_OPENBAO_ADDR", "http://127.0.0.1:8210")
    monkeypatch.setenv("KATALIR_VAULT_ADDR", "http://127.0.0.1:8200")
    assert sp.OpenBaoVault().available() is True
    assert sp.HashiCorpVault().available() is True
    # tanpa env -> tidak tersedia (bukan crash)
    monkeypatch.delenv("KATALIR_OPENBAO_ADDR", raising=False)
    assert sp.OpenBaoVault().available() is False


# 17. AWS: endpoint_url emulator dipakai HANYA bila env diisi
def test_17_aws_endpoint_url_emulator(monkeypatch):
    monkeypatch.setenv("KATALIR_AWS_ENDPOINT_URL", "http://127.0.0.1:4566")
    monkeypatch.setenv("KATALIR_AWS_REGION", "us-east-1")
    seen: dict = {}

    class _FakeBoto3:
        @staticmethod
        def client(nama, **kw):
            seen.update(kw)
            return object()

    import boto3
    monkeypatch.setattr(boto3, "client", _FakeBoto3.client)
    p = sp.AWSSecretsManager()
    p._client()
    assert seen.get("endpoint_url") == "http://127.0.0.1:4566"
    assert seen.get("region_name") == "us-east-1"
    # emulator tetap butuh kredensial bentuk-sah (SigV4)
    assert seen.get("aws_access_key_id")
    # tanpa endpoint_url -> perilaku AWS asli (tanpa override)
    monkeypatch.delenv("KATALIR_AWS_ENDPOINT_URL", raising=False)
    seen.clear()
    sp.AWSSecretsManager()._client()
    assert "endpoint_url" not in seen


# 18. `info()` tiap provider mengembalikan metadata NYATA, bukan nilai rahasia
def test_18_info_provider_tanpa_nilai_rahasia(monkeypatch):
    import json
    import urllib.request

    class _Resp:
        status = 200

        def read(self):
            return json.dumps({"version": "2.1.2", "sealed": False,
                               "cluster_name": "c1"}).encode()

    class _Op:
        def open(self, req, timeout=None):
            return _Resp()

    class _Hvac:
        class Client:
            def __init__(self, url=None, token=None):
                self.sys = self

            def read_health_status(self, method="GET"):
                return {"version": "2.1.2", "sealed": False, "cluster_name": "c1"}

    import hvac
    monkeypatch.setattr(hvac, "Client", _Hvac.Client)
    monkeypatch.setenv("KATALIR_VAULT_ADDR", "http://127.0.0.1:8200")
    monkeypatch.setenv("KATALIR_VAULT_TOKEN", "root")
    info = sp.HashiCorpVault().info()
    assert info["version"] == "2.1.2" and info["sealed"] is False
    assert "token" not in json.dumps(info).lower()
    assert "root" not in json.dumps(info)
