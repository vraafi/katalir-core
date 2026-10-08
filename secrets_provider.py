# secrets_provider.py — Fitur #7 (8 Okt 2026)
# ======================================================================
# External Secrets Manager: antarmuka `SecretsProvider` yang dapat ditukar,
# dengan backend bawaan KatalirVault dan adaptor opsional untuk vault
# eksternal (HashiCorp, AWS, 1Password).
#
# RISET (docs/fitur-07-secrets-manager.md):
#   TEMUAN PENTING — Katalir SUDAH punya `vault_broker.py` yang me-resolve
#   `secret://provider/field` ke tabel `user_vault` (ciphertext Fernet).
#   Jadi Fitur #7 BUKAN membangun vault dari nol: ia MENGABSTRAKSI pola yang
#   sudah ada menjadi antarmuka backend yang dapat ditukar, supaya vault
#   eksternal bisa dipakai tanpa mengubah pemanggil.
#
#   Kandidat yang diverifikasi:
#     hvac 2.4.0            Apache-2.0, rilis 30 Okt 2025, 6 maintainer,
#                           1.320*, Py >=3.8  -> DIPAKAI (opsional)
#     boto3                 Apache-2.0, resmi AWS -> DIPAKAI (opsional, lazy)
#     onepassword-sdk 0.4.1 MIT, rilis 30 Jul 2026, tapi versi 0.x dan
#                           butuh libssl 3 + glibc 2.32 -> OPSIONAL, dicatat
#     KatalirVault          tabel `user_vault` + Fernet yang SUDAH ADA
#                           -> DEFAULT (nol dependensi baru)
#
# PRINSIP KEAMANAN (dipertahankan dari vault_broker):
#   1. Nilai rahasia TIDAK PERNAH masuk log/pesan error — selalu di-mask.
#   2. Setiap operasi WAJIB memakai identitas (email) pemilik. Tidak ada
#      jalur yang bisa membaca rahasia milik user lain.
#   3. Backend eksternal diimpor MALAS (lazy) supaya Katalir tidak menambah
#      dependensi berat menjelang launch.
# ======================================================================

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from typing import Any, Optional

#: `secret://` diikuti sisa path (dipisah sendiri supaya backend eksplisit
#: bisa dibedakan dari nama provider biasa).
SECRET_REF_PATTERN = re.compile(r"^secret://(.+)$", re.IGNORECASE)

#: Segmen path rahasia yang aman: huruf, angka, titik, garis bawah, strip.
#: (Mencegah '../', '\', NUL, dan karakter kontrol masuk ke kunci backend.)
_SEGMENT_SAFE_RE = re.compile(r"^[A-Za-z0-9._\-]+$")

MASK = "***"

#: Backend yang dikenal. `katalir` selalu tersedia; sisanya opsional.
KATALIR = "katalir"
KNOWN_BACKENDS = ("katalir", "hashicorp", "openbao", "aws", "onepassword")


class SecretsError(Exception):
    """Kesalahan umum pada lapisan secrets."""


class SecretNotFound(SecretsError):
    """Rahasia/provider tidak ada. Pesannya TIDAK memuat nilai rahasia."""


class SecretRefError(SecretsError, ValueError):
    """Referensi `secret://` tidak valid bentuknya."""


class BackendUnavailable(SecretsError):
    """Backend diminta tetapi paket/kredensialnya tidak tersedia."""


# ---------------------------------------------------------------------------
# Antarmuka
# ---------------------------------------------------------------------------

class SecretsProvider(ABC):
    """Antarmuka backend secrets.

    Implementasi WAJIB mematuhi:
      - `get(path)`: kembalikan nilai (str) atau None bila tidak ada.
      - Tidak pernah memasukkan nilai rahasia ke pesan error/log.
    """

    name: str = "?"

    @abstractmethod
    def get(self, path: str, owner: str) -> Optional[str]:
        """Ambil satu nilai rahasia. `owner` = identitas pemilik (email)."""

    @abstractmethod
    def set(self, path: str, value: str, owner: str) -> bool:
        """Simpan nilai rahasia. Return True bila berhasil."""

    def delete(self, path: str, owner: str) -> bool:
        """Hapus rahasia. Default: tidak didukung."""
        raise NotImplementedError(f"backend {self.name} tidak mendukung delete")

    def list_paths(self, owner: str) -> list[str]:
        """Daftar nama path milik owner. Default: tidak didukung."""
        raise NotImplementedError(f"backend {self.name} tidak mendukung list")

    def available(self) -> bool:
        """True bila backend siap dipakai (paket + konfigurasi ada)."""
        return True


# ---------------------------------------------------------------------------
# Backend DEFAULT — KatalirVault (nol dependensi baru)
# ---------------------------------------------------------------------------

def _normalisasi(data: dict) -> dict:
    """Siapkan dict untuk `save_vault_credential`.

    `save_vault_credential` memaksa setiap nilai jadi `str(v)`, sehingga dict
    bersarang akan menjadi repr Python (bukan JSON valid) dan tidak bisa
    dibaca ulang. Di sini dict/list bersarang di-JSON-kan lebih dulu agar
    tetap dapat dipulihkan.
    """
    import json
    out: dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, (dict, list)):
            out[str(k)] = json.dumps(v, ensure_ascii=False)
        else:
            out[str(k)] = "" if v is None else str(v)
    return out


def _pulihkan(cred: dict) -> dict:
    """Kebalikan `_normalisasi`: urai nilai yang berupa string JSON."""
    import json
    out: dict[str, Any] = {}
    for k, v in cred.items():
        if isinstance(v, str):
            t = v.strip()
            if t[:1] in ("{", "["):
                try:
                    out[k] = json.loads(t)
                    continue
                except json.JSONDecodeError:
                    pass
        out[k] = v
    return out


class KatalirVault(SecretsProvider):
    """Vault bawaan Katalir: tabel `user_vault` (ciphertext Fernet).

    Satu baris per (email, provider); nilainya dict field yang di-JSON lalu
    dienkripsi. Tidak ada dependensi baru — memakai ulang
    `credential_forms.save_vault_credential` / `load_vault_credential`.
    """

    name = KATALIR

    def available(self) -> bool:
        """Selalu tersedia: memakai tabel `user_vault` yang sudah ada.

        Dependensinya (Supabase + cryptography) sudah wajib bagi Katalir,
        jadi tidak ada paket baru yang perlu ada.
        """
        try:
            import database  # noqa: F401
            import vault_security  # noqa: F401
            return True
        except Exception:  # noqa: BLE001
            return False

    def _pecah(self, path: str) -> tuple[str, Optional[str]]:
        """`provider/field` -> ("provider", "field"). Field boleh kosong."""
        path = (path or "").strip().strip("/")
        if not path:
            raise SecretRefError("path rahasia kosong")
        bagian = path.split("/", 1)
        provider = bagian[0].lower()
        field = bagian[1] if len(bagian) > 1 else None
        return provider, field

    def get(self, path: str, owner: str) -> Optional[str]:
        import json

        from credential_forms import load_vault_credential  # lazy: hindari siklus

        provider, field = self._pecah(path)
        cred = load_vault_credential(owner, provider)
        if not cred:
            return None
        if field is None:
            # Tanpa field: kembalikan JSON kanonik (bukan repr acak).
            return json.dumps(_pulihkan(cred), sort_keys=True)
        # Dukung field bersarang "a.b" — termasuk sub-objek yang tersimpan
        # sebagai string JSON.
        nilai: Any = cred
        for bagian in field.split("."):
            if isinstance(nilai, str):
                try:
                    nilai = json.loads(nilai)
                except json.JSONDecodeError:
                    return None
            if isinstance(nilai, dict) and bagian in nilai:
                nilai = nilai[bagian]
            else:
                return None
        if isinstance(nilai, (dict, list)):
            return json.dumps(nilai, sort_keys=True)
        return str(nilai)

    def set(self, path: str, value: str, owner: str) -> bool:
        from credential_forms import (load_vault_credential,
                                      save_vault_credential)

        provider, field = self._pecah(path)
        if field is None:
            # Simpan seluruh provider dari JSON.
            import json
            try:
                data = json.loads(value)
            except json.JSONDecodeError as exc:
                raise SecretRefError(
                    f"tanpa field, nilai harus JSON objek: {exc.msg}") from exc
            if not isinstance(data, dict):
                raise SecretRefError("JSON harus berupa objek")
            save_vault_credential(owner, provider, _normalisasi(data))
            return True

        # Simpan/gabung satu field. PENTING: dukung field BERSARANG ("a.b").
        # `save_vault_credential` memaksa setiap nilai jadi str, jadi objek
        # bersarang HARUS disimpan sebagai sub-objek, bukan string.
        ada = dict(load_vault_credential(owner, provider) or {})
        bagian = field.split(".")
        if len(bagian) == 1:
            ada[field] = value
        else:
            # bangun/merge jalur bersarang
            kursor = ada
            for b in bagian[:-1]:
                sub = kursor.get(b)
                if isinstance(sub, str):
                    # mungkin JSON tersimpan sebagai string -> coba urai
                    try:
                        import json as _j
                        sub = _j.loads(sub)
                    except Exception:  # noqa: BLE001
                        sub = {}
                if not isinstance(sub, dict):
                    sub = {}
                kursor[b] = sub
                kursor = sub
            kursor[bagian[-1]] = value
        save_vault_credential(owner, provider, _normalisasi(ada))
        return True

    def delete(self, path: str, owner: str) -> bool:
        import database as db

        provider, field = self._pecah(path)
        if field is None:
            return bool(db.vault_delete(owner, provider)) \
                if hasattr(db, "vault_delete") else False
        from credential_forms import (load_vault_credential,
                                      save_vault_credential)
        ada = dict(load_vault_credential(owner, provider) or {})
        if field not in ada:
            return False
        ada.pop(field)
        if ada:
            save_vault_credential(owner, provider, ada)
        else:
            if hasattr(db, "vault_delete"):
                db.vault_delete(owner, provider)
        return True

    def list_paths(self, owner: str) -> list[str]:
        """Daftar provider yang dimiliki owner (tanpa mengungkap nilainya)."""
        import database as db
        try:
            rows = (db.get_write_client().table("user_vault")
                    .select("provider").eq("email", owner).execute()).data or []
            return sorted({r["provider"] for r in rows})
        except Exception:  # noqa: BLE001 - daftar kosong lebih baik daripada 500
            return []


# ---------------------------------------------------------------------------
# Backend OPSIONAL — diimpor malas, hanya bila diminta
# ---------------------------------------------------------------------------

class HashiCorpVault(SecretsProvider):
    """Adaptor HashiCorp Vault (hvac 2.4.0, Apache-2.0) — API KV v2 NYATA.

    Konfigurasi lewat variabel lingkungan:
      KATALIR_VAULT_ADDR   mis. http://127.0.0.1:8200
      KATALIR_VAULT_TOKEN  token (TIDAK pernah dicetak)
      KATALIR_VAULT_MOUNT  default "secret"

    Riset Okt 2026: Vault **2.1.2** (build 2026-10-06) menjalankan dev server
    dengan `vault server -dev` tanpa akun/kartu kredit; `hvac` 2.4.0 adalah
    klien resmi Python (Apache-2.0). Subkelas `OpenBaoVault` memakai ulang
    kelas ini dengan prefiks env berbeda.
    """

    name = "hashicorp"
    ENV_ADDR = "KATALIR_VAULT_ADDR"
    ENV_TOKEN = "KATALIR_VAULT_TOKEN"
    ENV_MOUNT = "KATALIR_VAULT_MOUNT"

    def _client(self):
        try:
            import hvac  # lazy
        except ImportError as exc:
            raise BackendUnavailable(
                "hvac tidak terpasang — `pip install hvac` untuk memakai "
                "HashiCorp Vault") from exc
        addr = os.environ.get(self.ENV_ADDR)
        token = os.environ.get(self.ENV_TOKEN)
        if not addr:
            raise BackendUnavailable(f"{self.ENV_ADDR} belum diisi")
        return hvac.Client(url=addr, token=token)

    def available(self) -> bool:
        try:
            import hvac  # noqa: F401
        except ImportError:
            return False
        return bool(os.environ.get(self.ENV_ADDR))

    def _mount(self) -> str:
        return os.environ.get(self.ENV_MOUNT, "secret")

    def get(self, path: str, owner: str) -> Optional[str]:
        client = self._client()
        mount = self._mount()
        # Ruang nama per-owner: cegah lintas-user.
        jalur = f"{owner}/{path}".strip("/")
        try:
            res = client.secrets.kv.v2.read_secret_version(
                path=jalur, mount_point=mount, raise_on_deleted_version=True)
            data = (res or {}).get("data", {}).get("data", {}) or {}
        except Exception:  # noqa: BLE001 - tidak ada / tidak boleh dibaca
            return None
        if "value" in data:
            return str(data["value"])
        import json
        return json.dumps(data, sort_keys=True) if data else None

    def set(self, path: str, value: str, owner: str) -> bool:
        client = self._client()
        mount = self._mount()
        jalur = f"{owner}/{path}".strip("/")
        client.secrets.kv.v2.create_or_update_secret(
            path=jalur, secret={"value": value}, mount_point=mount)
        return True

    def delete(self, path: str, owner: str) -> bool:
        client = self._client()
        mount = self._mount()
        jalur = f"{owner}/{path}".strip("/")
        try:
            client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=jalur, mount_point=mount)
            return True
        except Exception:  # noqa: BLE001
            return False

    def list_paths(self, owner: str) -> list[str]:
        """Daftar path MILIK owner (KV v2 LIST pada prefiks owner)."""
        client = self._client()
        try:
            res = client.secrets.kv.v2.list_secrets(
                path=owner, mount_point=self._mount())
            return sorted(res.get("data", {}).get("keys", []) or [])
        except Exception:  # noqa: BLE001
            return []

    def info(self) -> dict:
        """Info server NYATA (versi/seal) — bukti binding, bukan klaim."""
        client = self._client()
        h = client.sys.read_health_status(method="GET")
        return {"addr": os.environ.get(self.ENV_ADDR),
                "version": h.get("version"),
                "sealed": h.get("sealed"),
                "cluster_name": h.get("cluster_name")}


class OpenBaoVault(HashiCorpVault):
    """Adaptor OpenBao (fork Vault oleh Linux Foundation) — API KV v2 NYATA.

    OpenBao adalah produk BERBEDA dari Vault (rilis sendiri: v2.7.1,
    2026-10-01, MIT) namun kompatibel API, sehingga memakai ulang logika
    `HashiCorpVault` hanya dengan prefiks env berbeda:
      KATALIR_OPENBAO_ADDR / _TOKEN / _MOUNT
    """

    name = "openbao"
    ENV_ADDR = "KATALIR_OPENBAO_ADDR"
    ENV_TOKEN = "KATALIR_OPENBAO_TOKEN"
    ENV_MOUNT = "KATALIR_OPENBAO_MOUNT"


class AWSSecretsManager(SecretsProvider):
    """Adaptor AWS Secrets Manager (boto3, Apache-2.0) — API NYATA.

    Konfigurasi:
      - Kredensial AWS standar (peran/env) untuk AWS asli, ATAU
      - **emulator lokal** (MiniStack/LocalStack) lewat:
          KATALIR_AWS_ENDPOINT_URL = http://127.0.0.1:4566
          KATALIR_AWS_ACCESS_KEY_ID / KATALIR_AWS_SECRET_ACCESS_KEY (dummy)
        Kredensial dummy diperlukan karena emulator tetap menandatangani
        SigV4; nilainya tidak dipakai untuk autentikasi nyata.

    Riset Okt 2026: LocalStack **menghapus tier gratisnya (Maret 2026)**;
    penggantinya yang gratis/MIT adalah **MiniStack** (`pip install ministack`,
    port 4566, 60+ layanan, kompatibel boto3) — lihat link di laporan.
    Nama rahasia diberi prefiks owner untuk isolasi antar-user.
    """

    name = "aws"

    def _client(self):
        try:
            import boto3  # lazy
        except ImportError as exc:
            raise BackendUnavailable(
                "boto3 tidak terpasang — `pip install boto3` untuk memakai "
                "AWS Secrets Manager") from exc
        region = os.environ.get("KATALIR_AWS_REGION") or "us-east-1"
        endpoint = os.environ.get("KATALIR_AWS_ENDPOINT_URL") or None
        kw: dict = {"region_name": region}
        if endpoint:
            kw["endpoint_url"] = endpoint
            # emulator butuh kredensial bentuk-sah (SigV4), bukan kredensial asli
            kw["aws_access_key_id"] = (os.environ.get("KATALIR_AWS_ACCESS_KEY_ID")
                                       or "katalir-local")
            kw["aws_secret_access_key"] = (os.environ.get("KATALIR_AWS_SECRET_ACCESS_KEY")
                                           or "katalir-local")
        return boto3.client("secretsmanager", **kw)

    def available(self) -> bool:
        try:
            import boto3  # noqa: F401
        except ImportError:
            return False
        return True

    def get(self, path: str, owner: str) -> Optional[str]:
        import json
        client = self._client()
        nama = f"katalir/{owner}/{path}".strip("/")
        try:
            res = client.get_secret_value(SecretId=nama)
        except Exception:  # noqa: BLE001
            return None
        rahasia = res.get("SecretString")
        if rahasia is None:
            return None
        try:
            data = json.loads(rahasia)
            if isinstance(data, dict) and "value" in data:
                return str(data["value"])
        except json.JSONDecodeError:
            pass
        return str(rahasia)

    def set(self, path: str, value: str, owner: str) -> bool:
        import json
        client = self._client()
        nama = f"katalir/{owner}/{path}".strip("/")
        payload = json.dumps({"value": value})
        try:
            client.create_secret(Name=nama, SecretString=payload)
        except Exception:  # noqa: BLE001 - sudah ada -> perbarui
            client.put_secret_value(SecretId=nama, SecretString=payload)
        return True

    def delete(self, path: str, owner: str) -> bool:
        client = self._client()
        nama = f"katalir/{owner}/{path}".strip("/")
        try:
            client.delete_secret(SecretId=nama, ForceDeleteWithoutRecovery=True)
            return True
        except Exception:  # noqa: BLE001
            return False

    def list_paths(self, owner: str) -> list[str]:
        client = self._client()
        prefiks = f"katalir/{owner}/"
        try:
            daftar = client.list_secrets().get("SecretList", []) or []
        except Exception:  # noqa: BLE001
            return []
        return sorted(s["Name"][len(prefiks):] for s in daftar
                      if str(s.get("Name", "")).startswith(prefiks))

    def info(self) -> dict:
        """Info NYATA: jumlah rahasia + endpoint yang dipakai (bukti binding)."""
        client = self._client()
        try:
            n = len(client.list_secrets().get("SecretList", []) or [])
        except Exception:  # noqa: BLE001
            n = -1
        return {"endpoint": os.environ.get("KATALIR_AWS_ENDPOINT_URL") or "aws",
                "region": os.environ.get("KATALIR_AWS_REGION") or "us-east-1",
                "secret_count": n}


class OnePasswordProvider(SecretsProvider):
    """Adaptor 1Password (onepassword-sdk, versi 0.4.1).

    CATATAN JUJUR: SDK ini masih **versi 0.x** (pra-1.0) dan
    `pip install`-nya membutuhkan **libssl 3 + glibc 2.32**. Di base image
    Railway yang lebih tua, impor bisa gagal — karena itu backend ini
    dilaporkan `available() == False` dan bukan dijadikan default.
    """

    name = "onepassword"

    def available(self) -> bool:
        try:
            import onepassword  # noqa: F401
        except Exception:  # noqa: BLE001 - bisa ImportError atau OSError libssl
            return False
        return True

    def get(self, path: str, owner: str) -> Optional[str]:
        try:
            import asyncio

            from onepassword.client import Client
        except Exception as exc:  # noqa: BLE001
            raise BackendUnavailable(
                f"onepassword-sdk tidak siap: {type(exc).__name__}") from exc
        token = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN")
        if not token:
            raise BackendUnavailable("OP_SERVICE_ACCOUNT_TOKEN belum diisi")
        # `path` diharapkan sudah bentuk op://vault/item/field
        ref = path if path.startswith("op://") else f"op://{path}"

        async def _ambil() -> str:
            client = await Client.authenticate(
                auth=token, integration_name="Katalir",
                integration_version="v1.0.0")
            return await client.secrets.resolve(ref)

        try:
            return str(asyncio.run(_ambil()))
        except Exception:  # noqa: BLE001
            return None

    def set(self, path: str, value: str, owner: str) -> bool:
        raise BackendUnavailable(
            "1Password SDK untuk menulis item belum dipakai di jalur ini; "
            "tulis lewat aplikasi 1Password lalu baca dengan secret://")


# ---------------------------------------------------------------------------
# Registry + pemilihan backend
# ---------------------------------------------------------------------------

REGISTRY: dict[str, type[SecretsProvider]] = {
    KATALIR: KatalirVault,
    "hashicorp": HashiCorpVault,
    "vault": HashiCorpVault,        # alias
    "openbao": OpenBaoVault,        # fork Vault (Linux Foundation)
    "aws": AWSSecretsManager,
    "onepassword": OnePasswordProvider,
    "1password": OnePasswordProvider,
}


_CACHE: dict[str, SecretsProvider] = {}


def _instances() -> dict[str, SecretsProvider]:
    """Instans backend (dibuat malas, di-cache).

    Catatan bug: versi pertama memakai `global _CACHE` di dalam blok
    try/except dan `_CACHE` dideklarasikan SETELAH fungsi -> cache terisi
    tapi nama global tidak pernah terikat pada pemanggilan pertama,
    sehingga `get_provider()` melempar KeyError. Sekarang `_CACHE`
    dideklarasikan di atas dan diisi dengan jelas.
    """
    if not _CACHE:
        gagal: list[str] = []
        for nama, cls in REGISTRY.items():
            try:
                _CACHE[nama] = cls()
            except Exception as exc:  # noqa: BLE001 - satu backend rusak
                # tidak boleh mematikan semua backend lain
                print(f"[secrets] backend {nama} gagal dibuat: "
                      f"{type(exc).__name__}: {exc}")
                gagal.append(nama)
        if gagal and not _CACHE:
            raise BackendUnavailable(
                f"tidak ada backend secrets yang bisa dipakai (gagal: {gagal})")
    return _CACHE


def get_provider(name: str = KATALIR) -> SecretsProvider:
    """Ambil backend berdasarkan nama. Default: KatalirVault."""
    kunci = (name or KATALIR).strip().lower()
    if kunci not in REGISTRY:
        raise BackendUnavailable(
            f"backend tidak dikenal: {name!r} (pilih {sorted(set(REGISTRY))})")
    return _instances()[kunci]


def default_provider_name() -> str:
    """Backend default. `KATALIR_SECRETS_BACKEND` boleh menimpanya."""
    return os.environ.get("KATALIR_SECRETS_BACKEND", KATALIR).strip().lower()


def describe_backends() -> list[dict]:
    """Status tiap backend — untuk UI/observabilitas. Tidak mengungkap nilai."""
    hasil = []
    for nama, cls in sorted(set(REGISTRY.items())):
        try:
            inst = get_provider(nama)
            ok = inst.available()
        except Exception:  # noqa: BLE001
            ok = False
        hasil.append({"backend": nama, "available": bool(ok),
                      "class": cls.__name__})
    return hasil


# ---------------------------------------------------------------------------
# Resolusi referensi `secret://`
# ---------------------------------------------------------------------------

def parse_ref(ref: str) -> tuple[str, str, Optional[str]]:
    """`secret://<a>/<b>[/<c>]` -> (backend, path, field).

    Bentuk yang diterima:
      secret://gmail_imap/app_password      -> (default, "gmail_imap", "app_password")
      secret://katalir/gmail_imap/x         -> ("katalir", "gmail_imap", "x")
      secret://aws/prod/db                  -> ("aws", "prod", "db")
      secret://aws/prod/db/pass             -> ("aws", "prod/db", "pass")

    Aturan: bila segmen PERTAMA adalah nama backend yang dikenal
    (hashicorp/aws/onepassword/katalir), ia diperlakukan sebagai backend;
    sisanya path/field. Kalau tidak, semuanya bagian dari path provider.
    """
    if not isinstance(ref, str):
        raise SecretRefError("referensi harus teks")
    teks = ref.strip()
    m = SECRET_REF_PATTERN.match(teks)
    if not m:
        raise SecretRefError(f"Format secret:// tidak valid: {teks[:40]!r}")

    sisa = m.group(1).strip("/")
    bagian = [b for b in sisa.split("/") if b]
    if not bagian:
        raise SecretRefError("path rahasia kosong")

    # --- Hardening (temuan hard test #9) ----------------------------------
    # `secret://openbao//etc/shadow` dulu DITERIMA: segmen kosong dibuang
    # diam-diam sehingga referensi "absolut" berubah bentuk tanpa peringatan.
    # Tanda `/` ganda (atau `/` tepat setelah `secret://`) menandakan path
    # absolut/malformed -> tolak eksplisit supaya tidak ada normalisasi
    # tersembunyi pada backend yang memetakan path ke berkas/nama.
    mentah = m.group(1)
    if mentah.startswith("/") or "//" in mentah:
        raise SecretRefError(
            f"referensi rahasia tidak boleh absolut / bersegmen kosong: "
            f"{mentah[:40]!r}")

    # --- Hardening (temuan hard test) -------------------------------------
    # Dulu `secret://../../etc/passwd` DITERIMA apa adanya dan menghasilkan
    # path '../../etc'. Pada backend Katalir path ini dipakai sebagai KUNCI DB
    # (bukan path berkas), jadi traversal tidak bisa menyentuh filesystem —
    # tapi menerimanya adalah kejutan yang tidak perlu dan berisiko begitu ada
    # backend yang memetakan path ke berkas. Tolak segmen traversal/absolut.
    for seg in bagian:
        if seg in (".", "..") or "/" in seg or "\\" in seg or "\x00" in seg:
            raise SecretRefError(
                f"segmen path rahasia tidak valid: {seg[:40]!r}")
        if not _SEGMENT_SAFE_RE.match(seg):
            raise SecretRefError(
                f"karakter tidak diizinkan di path rahasia: {seg[:40]!r}")
    if len(sisa) > 512:
        raise SecretRefError("path rahasia terlalu panjang (>512 karakter)")

    kepala = bagian[0].lower()

    if kepala in REGISTRY and len(bagian) >= 2:
        # Backend eksplisit: secret://<backend>/<path...>/<field>
        backend = kepala
        ekor = bagian[1:]
        if len(ekor) >= 2:
            return backend, "/".join(ekor[:-1]), ekor[-1]
        return backend, ekor[0], None

    # Tanpa backend eksplisit -> backend default.
    # Di sini segmen terakhir = field, sisanya = path provider.
    backend = default_provider_name()
    if len(bagian) >= 2:
        return backend, "/".join(bagian[:-1]), bagian[-1]
    return backend, bagian[0], None


def resolve(ref: str, owner: str,
            provider_name: Optional[str] = None) -> str:
    """Resolve `secret://…` -> nilai asli.

    Raises SecretRefError, SecretNotFound, BackendUnavailable.
    """
    backend, path, field = parse_ref(ref)
    if provider_name:
        backend = provider_name
    if backend not in REGISTRY:
        backend = KATALIR
    prov = get_provider(backend)
    jalur = f"{path}/{field}" if field else path
    nilai = prov.get(jalur, owner)
    if nilai is None:
        raise SecretNotFound(
            f"Rahasia tidak ditemukan: {backend}/{path}"
            + (f"/{field}" if field else ""))
    return nilai


def redact(value: Any) -> Any:
    """Ganti semua referensi `secret://` dengan mask (aman untuk log)."""
    if isinstance(value, str):
        return MASK if value.strip().lower().startswith("secret://") else value
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def resolve_in_args(args: dict, owner: str,
                    provider_name: Optional[str] = None) -> dict:
    """Resolve SEMUA `secret://` di dalam dict/list bersarang."""
    if not isinstance(args, dict):
        return args
    out: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str) and value.strip().lower().startswith("secret://"):
            out[key] = resolve(value, owner, provider_name)
        elif isinstance(value, dict):
            out[key] = resolve_in_args(value, owner, provider_name)
        elif isinstance(value, list):
            out[key] = [
                resolve(v, owner, provider_name)
                if isinstance(v, str) and v.strip().lower().startswith("secret://")
                else (resolve_in_args(v, owner, provider_name)
                      if isinstance(v, dict) else v)
                for v in value
            ]
        else:
            out[key] = value
    return out


def is_secret_ref(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower().startswith("secret://")


# ===========================================================================
# FITUR #1 (lanjutan) — Enterprise Secrets Manager, Okt 2026
# ===========================================================================
# RISET (Okt 2026):
#   Peringkat tools secrets 2026 (briandetering, fairdevs, envtools, ciphers):
#     HashiCorp Vault, AWS Secrets Manager, Doppler, Infisical = 4 besar.
#   Infisical  -> REST `/api/v3/secrets/raw/{name}` + Bearer token; SDK resmi
#                 python tersedia tapi REST lebih ringan (nol dependensi baru).
#   Doppler    -> REST `https://api.doppler.com/v3/configs/config/secret`,
#                 auth Basic base64(token:) ; SDK `doppler-sdk` ada.
#   KEPUTUSAN: pakai REST via `urllib` (stdlib) -> TIDAK menambah dependensi,
#   berjalan di Railway ephemeral, dan tetap bisa ditest dengan server tiruan.
# ===========================================================================

import base64 as _b64
import json as _json
import threading as _threading
import time as _time
import urllib.error as _urlerr
import urllib.parse as _urlparse
import urllib.request as _urlreq
from concurrent.futures import ThreadPoolExecutor as _TPE

#: Batas ukuran nilai rahasia (256 KiB) — mencegah penyalahgunaan vault
#: sebagai penyimpanan objek besar (biaya + latensi + potensi DoS).
MAX_SECRET_BYTES = 256 * 1024


class SecretTooLarge(SecretsError):
    """Nilai rahasia melebihi `MAX_SECRET_BYTES`."""


def check_size(value: Any) -> int:
    """Kembalikan ukuran byte nilai; raise SecretTooLarge bila > batas."""
    raw = value if isinstance(value, bytes) else str(value or "").encode("utf-8")
    n = len(raw)
    if n > MAX_SECRET_BYTES:
        raise SecretTooLarge(
            f"rahasia terlalu besar: {n} byte > {MAX_SECRET_BYTES} byte")
    return n


# ---------------------------------------------------------------------------
# Backend OPSIONAL tambahan — Infisical & Doppler (REST, stdlib)
# ---------------------------------------------------------------------------

class _HttpJsonProvider(SecretsProvider):
    """Dasar untuk backend berbasis REST JSON. Tidak pernah mencetak token."""

    timeout: float = 10.0

    def _request(self, method: str, url: str, headers: dict,
                 body: Optional[bytes] = None) -> Optional[dict]:
        req = _urlreq.Request(url, data=body, method=method)
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with _urlreq.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except Exception:  # noqa: BLE001 — jaringan/HTTP apa pun -> None
            return None
        if not raw:
            return {}
        try:
            return _json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None


class InfisicalProvider(_HttpJsonProvider):
    """Adaptor Infisical (REST v3). Konfigurasi via env:
        KATALIR_INFISICAL_TOKEN       service token (TIDAK pernah dicetak)
        KATALIR_INFISICAL_PROJECT_ID  workspace id
        KATALIR_INFISICAL_ENV         default "prod"
        KATALIR_INFISICAL_HOST        default https://app.infisical.com
    """

    name = "infisical"

    def available(self) -> bool:
        return bool(os.environ.get("KATALIR_INFISICAL_TOKEN")
                    and os.environ.get("KATALIR_INFISICAL_PROJECT_ID"))

    def _cfg(self) -> tuple[str, str, str, str]:
        host = (os.environ.get("KATALIR_INFISICAL_HOST")
                or "https://app.infisical.com").rstrip("/")
        token = os.environ.get("KATALIR_INFISICAL_TOKEN") or ""
        project = os.environ.get("KATALIR_INFISICAL_PROJECT_ID") or ""
        env = os.environ.get("KATALIR_INFISICAL_ENV") or "prod"
        if not token or not project:
            raise BackendUnavailable("Infisical: token/project belum diisi")
        return host, token, project, env

    def _name(self, path: str, owner: str) -> str:
        # Ruang nama per-owner supaya satu project tidak bocor antar-user.
        return f"{owner}__{path}".replace("/", "__")

    def get(self, path: str, owner: str) -> Optional[str]:
        host, token, project, env = self._cfg()
        name = self._name(path, owner)
        qs = _urlparse.urlencode({
            "workspaceId": project, "environment": env,
            "secretPath": "/", "type": "shared"})
        url = f"{host}/api/v3/secrets/raw/{_urlparse.quote(name)}?{qs}"
        data = self._request("GET", url, {"Authorization": f"Bearer {token}"})
        if not data:
            return None
        secret = (data.get("secret") or {}).get("secretValue")
        return str(secret) if secret is not None else None

    def set(self, path: str, value: str, owner: str) -> bool:
        check_size(value)
        host, token, project, env = self._cfg()
        name = self._name(path, owner)
        payload = _json.dumps({
            "workspaceId": project, "environment": env, "secretPath": "/",
            "secretValue": value, "type": "shared"}).encode()
        # Coba update dulu; kalau 404 -> create.
        url = f"{host}/api/v3/secrets/raw/{_urlparse.quote(name)}"
        r = self._request("PATCH", url, {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"}, payload)
        if r is None:
            r = self._request("POST", url, {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"}, payload)
        return r is not None


class DopplerProvider(_HttpJsonProvider):
    """Adaptor Doppler (REST v3). Konfigurasi via env:
        KATALIR_DOPPLER_TOKEN    token (TIDAK pernah dicetak)
        KATALIR_DOPPLER_PROJECT  project slug
        KATALIR_DOPPLER_CONFIG   config slug, default "prd"
    """

    name = "doppler"

    def available(self) -> bool:
        return bool(os.environ.get("KATALIR_DOPPLER_TOKEN")
                    and os.environ.get("KATALIR_DOPPLER_PROJECT"))

    def _cfg(self) -> tuple[str, str, str, str]:
        token = os.environ.get("KATALIR_DOPPLER_TOKEN") or ""
        project = os.environ.get("KATALIR_DOPPLER_PROJECT") or ""
        config = os.environ.get("KATALIR_DOPPLER_CONFIG") or "prd"
        host = (os.environ.get("KATALIR_DOPPLER_HOST")
                or "https://api.doppler.com").rstrip("/")
        if not token or not project:
            raise BackendUnavailable("Doppler: token/project belum diisi")
        return host, token, project, config

    def _auth(self) -> dict:
        _, token, _, _ = self._cfg()
        basic = _b64.b64encode(f"{token}:".encode()).decode()
        return {"Authorization": f"Basic {basic}"}

    def _name(self, path: str, owner: str) -> str:
        return f"{owner}__{path}".replace("/", "__").upper()

    def get(self, path: str, owner: str) -> Optional[str]:
        host, _, project, config = self._cfg()
        name = self._name(path, owner)
        qs = _urlparse.urlencode({
            "project": project, "config": config, "name": name})
        data = self._request("GET",
                             f"{host}/v3/configs/config/secret?{qs}",
                             self._auth())
        if not data:
            return None
        val = (data.get("value") or {}).get("raw")
        return str(val) if val is not None else None

    def set(self, path: str, value: str, owner: str) -> bool:
        check_size(value)
        host, _, project, config = self._cfg()
        name = self._name(path, owner)
        payload = _json.dumps({
            "project": project, "config": config,
            "name": name, "value": value}).encode()
        headers = dict(self._auth())
        headers["Content-Type"] = "application/json"
        r = self._request("POST", f"{host}/v3/configs/config/secrets",
                          headers, payload)
        return r is not None


# Daftarkan backend baru (tanpa menghapus yang lama).
REGISTRY["infisical"] = InfisicalProvider
REGISTRY["doppler"] = DopplerProvider
KNOWN_BACKENDS = tuple(sorted(set(REGISTRY)))


# ---------------------------------------------------------------------------
# Failover + resolve paralel
# ---------------------------------------------------------------------------

def resolve_with_failover(ref: str, owner: str,
                          chain: Optional[list[str]] = None) -> str:
    """Resolve `secret://` dengan RANTAI backend; backend pertama yang
    mengembalikan nilai menang. `chain` default: backend di ref + katalir.

    Raises SecretNotFound bila SEMUA backend gagal.
    """
    backend, path, field = parse_ref(ref)
    urutan: list[str] = []
    if chain:
        urutan.extend(chain)
    if backend not in urutan:
        urutan.insert(0, backend)
    if KATALIR not in urutan:
        urutan.append(KATALIR)
    dicoba: list[str] = []
    for nama in urutan:
        if nama not in REGISTRY:
            continue
        dicoba.append(nama)
        try:
            prov = get_provider(nama)
            if not prov.available():
                continue
            jalur = f"{path}/{field}" if field else path
            nilai = prov.get(jalur, owner)
        except Exception:  # noqa: BLE001 — backend rusak -> coba berikutnya
            continue
        if nilai is not None:
            return nilai
    raise SecretNotFound(
        f"Rahasia tidak ditemukan di backend mana pun: {dicoba}")


def resolve_many(refs: list[str], owner: str, max_workers: int = 16
                 ) -> dict[str, Optional[str]]:
    """Resolve banyak `secret://` secara PARALEL. Nilai gagal -> None.

    Dipakai untuk mengambil 1000 referensi tanpa latensi serial.
    """
    unik = list(dict.fromkeys(refs))
    hasil: dict[str, Optional[str]] = {}
    if not unik:
        return hasil
    workers = max(1, min(max_workers, len(unik)))

    def _satu(r: str) -> tuple[str, Optional[str]]:
        try:
            return r, resolve(r, owner)
        except Exception:  # noqa: BLE001
            return r, None

    with _TPE(max_workers=workers) as pool:
        for r, v in pool.map(_satu, unik):
            hasil[r] = v
    return hasil


# ---------------------------------------------------------------------------
# Rotasi rahasia (version history) — store dapat disuntik (test tanpa DB)
# ---------------------------------------------------------------------------

class RotationStore:
    """Riwayat rotasi. Backend memori (default) atau Supabase (opsional)."""

    def __init__(self) -> None:
        self._lock = _threading.Lock()
        self._versi: dict[tuple[str, str], int] = {}
        self._riwayat: list[dict] = []

    def next_version(self, owner: str, path: str) -> int:
        with self._lock:
            kunci = (owner, path)
            v = self._versi.get(kunci, 0) + 1
            self._versi[kunci] = v
            return v

    def record(self, owner: str, path: str, version: int) -> None:
        with self._lock:
            self._riwayat.append({
                "owner": owner, "path": path, "version": version,
                "rotated_at": _time.time()})

    def history(self, owner: str, path: str) -> list[dict]:
        with self._lock:
            return [r for r in self._riwayat
                    if r["owner"] == owner and r["path"] == path]

    def current_version(self, owner: str, path: str) -> int:
        with self._lock:
            return self._versi.get((owner, path), 0)


_ROTATION = RotationStore()


def set_rotation_store(store: RotationStore) -> None:
    """Suntik store rotasi (dipakai test / integrasi DB)."""
    global _ROTATION
    _ROTATION = store


def rotation_store() -> RotationStore:
    return _ROTATION


def rotate(ref_or_path: str, new_value: str, owner: str,
           provider_name: Optional[str] = None) -> dict:
    """Rotasi rahasia: tulis nilai BARU + naikkan versi.

    Menerima `secret://...` atau path polos ("provider/field").
    Return dict {path, backend, version, bytes, rotated_at}.
    Raises SecretTooLarge / BackendUnavailable / SecretsError.
    """
    check_size(new_value)
    if ref_or_path.strip().lower().startswith("secret://"):
        backend, path, field = parse_ref(ref_or_path)
    else:
        backend = (provider_name or default_provider_name())
        bagian = ref_or_path.strip("/").split("/", 1)
        path = bagian[0]
        field = bagian[1] if len(bagian) > 1 else None
    if provider_name:
        backend = provider_name
    if backend not in REGISTRY:
        raise BackendUnavailable(f"backend tidak dikenal: {backend!r}")
    prov = get_provider(backend)
    if not prov.available():
        raise BackendUnavailable(f"backend {backend} tidak tersedia")
    jalur = f"{path}/{field}" if field else path
    if not prov.set(jalur, new_value, owner):
        raise SecretsError(f"rotasi gagal untuk {backend}/{jalur}")
    versi = _ROTATION.next_version(owner, jalur)
    _ROTATION.record(owner, jalur, versi)
    return {"path": jalur, "backend": backend, "version": versi,
            "bytes": check_size(new_value), "rotated_at": _time.time()}


# ---------------------------------------------------------------------------
# Dokumentasi 10 format referensi (dipakai endpoint + test)
# ---------------------------------------------------------------------------

SECRET_REF_FORMATS: list[dict] = [
    {"format": "secret://provider/field", "contoh": "secret://gmail_imap/app_password",
     "backend": "default"},
    {"format": "secret://provider/sub/field", "contoh": "secret://db/prod/password",
     "backend": "default"},
    {"format": "secret://provider (tanpa field)",
     "contoh": "secret://gmail_imap", "backend": "default"},
    {"format": "secret://katalir/provider/field",
     "contoh": "secret://katalir/db/pass", "backend": "katalir"},
    {"format": "secret://hashicorp/path/field",
     "contoh": "secret://hashicorp/app/key", "backend": "hashicorp"},
    {"format": "secret://aws/path/field", "contoh": "secret://aws/prod/db",
     "backend": "aws"},
    {"format": "secret://onepassword/op/item/field",
     "contoh": "secret://onepassword/vault/item/pass", "backend": "onepassword"},
    {"format": "secret://infisical/path/field",
     "contoh": "secret://infisical/api/token", "backend": "infisical"},
    {"format": "secret://doppler/path/field",
     "contoh": "secret://doppler/api/key", "backend": "doppler"},
    {"format": "secret://provider/a.b.c (field bersarang)",
     "contoh": "secret://oauth/google/client_secret", "backend": "default"},
]
