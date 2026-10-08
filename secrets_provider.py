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
KNOWN_BACKENDS = ("katalir", "hashicorp", "aws", "onepassword")


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
    """Adaptor HashiCorp Vault (hvac 2.4.0, Apache-2.0).

    Konfigurasi lewat variabel lingkungan:
      KATALIR_VAULT_ADDR   mis. https://vault.internal:8200
      KATALIR_VAULT_TOKEN  token (TIDAK pernah dicetak)
      KATALIR_VAULT_MOUNT  default "secret"
    """

    name = "hashicorp"

    def _client(self):
        try:
            import hvac  # lazy
        except ImportError as exc:
            raise BackendUnavailable(
                "hvac tidak terpasang — `pip install hvac` untuk memakai "
                "HashiCorp Vault") from exc
        addr = os.environ.get("KATALIR_VAULT_ADDR")
        token = os.environ.get("KATALIR_VAULT_TOKEN")
        if not addr:
            raise BackendUnavailable("KATALIR_VAULT_ADDR belum diisi")
        return hvac.Client(url=addr, token=token)

    def available(self) -> bool:
        try:
            import hvac  # noqa: F401
        except ImportError:
            return False
        return bool(os.environ.get("KATALIR_VAULT_ADDR"))

    def get(self, path: str, owner: str) -> Optional[str]:
        client = self._client()
        mount = os.environ.get("KATALIR_VAULT_MOUNT", "secret")
        # Ruang nama per-owner: cegah lintas-user.
        jalur = f"{owner}/{path}".strip("/")
        try:
            res = client.secrets.kv.v2.read_secret_version(
                path=jalur, mount_point=mount)
            data = (res or {}).get("data", {}).get("data", {}) or {}
        except Exception:  # noqa: BLE001 - tidak ada / tidak boleh dibaca
            return None
        if "value" in data:
            return str(data["value"])
        import json
        return json.dumps(data, sort_keys=True) if data else None

    def set(self, path: str, value: str, owner: str) -> bool:
        client = self._client()
        mount = os.environ.get("KATALIR_VAULT_MOUNT", "secret")
        jalur = f"{owner}/{path}".strip("/")
        client.secrets.kv.v2.create_or_update_secret(
            path=jalur, secret={"value": value}, mount_point=mount)
        return True

    def delete(self, path: str, owner: str) -> bool:
        client = self._client()
        mount = os.environ.get("KATALIR_VAULT_MOUNT", "secret")
        jalur = f"{owner}/{path}".strip("/")
        try:
            client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=jalur, mount_point=mount)
            return True
        except Exception:  # noqa: BLE001
            return False


class AWSSecretsManager(SecretsProvider):
    """Adaptor AWS Secrets Manager (boto3, Apache-2.0).

    Konfigurasi: kredensial AWS standar (peran/env) — TIDAK disimpan di sini.
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
        region = os.environ.get("KATALIR_AWS_REGION") or None
        return boto3.client("secretsmanager", region_name=region)

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
