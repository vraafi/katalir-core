# Fitur #7 — External Secrets Manager

**Status:** SELESAI — 12/12 hard test PASS
**Modul:** `secrets_provider.py` (+ `tests/test_secrets_provider.py`)

---

## 1. Masalah nyata

Sebelum fitur ini, Katalir **sudah** punya `vault_broker.py` yang mengenali
referensi `secret://provider/field` dan menyelesaikannya ke
`credential_forms.load_vault_credential`. Artinya masalahnya **bukan** "belum ada
resolusi secret", melainkan:

1. **Terkunci ke satu backend.** Hanya vault internal Katalir (Fernet di DB)
   yang bisa dipakai. Tidak ada jalur ke HashiCorp / AWS / 1Password.
2. **Tidak ada kontrak abstrak.** Tidak ada `SecretsProvider` sehingga kode
   pemanggil tidak bisa netral terhadap backend.
3. **`set` dan `delete` tidak ada.** Secret hanya bisa ditulis lewat alur
   credential-form di UI, tidak programatik.
4. **Bentuk referensi ambigu.** `secret://gmail_imap/app_password` (tanpa nama
   backend) harus tetap valid untuk kompatibilitas, tapi tidak ada parser yang
   bisa membedakan "nama backend" dari "nama item".
5. **Field bersarang tidak terbaca** (lihat BUG-7a).

## 2. Research — kandidat

Kriteria: production-ready ≥ 1.0, update < 6 bulan, jalan di **Railway**
(filesystem ephemeral, container tidak berhak istimewa), ada persistensi,
lisensi permissive (MIT/Apache/BSD), dipelihara aktif.

| Paket | Versi | Verdict | Alasan |
|---|---|---|---|
| `hvac` | 2.4.0 | ✅ **dipilih (opsional)** | Apache-2.0, rilis 30 Okt 2025, 6 maintainer, 1320★, py≥3.8. Klien resmi HashiCorp Vault. |
| `boto3` | terpasang transitif | ✅ **dipilih (opsional)** | SDK resmi AWS. `AWSSecretsManager` wajib lazy-import, boto3 bukan dependensi wajib. |
| `onepassword-sdk` | 0.4.1 | ⚠️ **opsional + catatan jujur** | MIT, rilis 30 Jul 2026 — **tapi versi 0.x (pra-1.0)** dan butuh **libssl 3 + glibc 2.32** (risiko dependensi biner di Railway). |
| `vault-broker` (internal) | — | ✅ **default** | Nol dependensi baru. Sudah ada. Fernet + tabel `user_vault`. |
| `python-dotenv`-as-secret-store | — | ❌ | Bukan secret manager; tidak ada enkripsi/audit/rotasi. |
| `keyring` | — | ❌ | Bergantung OS keychain; tidak ada di container Railway. |

**Pilihan:** abstraksi `SecretsProvider` + `KatalirVault` sebagai default,
`HashiCorpVault`/`AWSSecretsManager`/`OnePasswordProvider` sebagai backend
opsional lazy-load.

**Alasan:** Katalir **tidak boleh** bertambah dependensi wajib untuk fitur yang
belum tentu dipakai. Default `katalir` memakai infrastruktur yang sudah ada
(`user_vault` + Fernet), sehingga fitur ini **hijau tanpa install apa pun**.
Backend eksternal aktif otomatis bila kredensial env tersedia, dan **jujur
melaporkan** bila tidak bisa dipakai (`available() == False`, `get()` melempar
`BackendUnavailable`) — tidak pernah memalsukan keberhasilan.

## 3. Implementasi

### Kontrak

```
SecretsProvider (ABC)
  get(path, field) -> str        # wajib
  set(path, field, value)        # wajib
  delete(path, field)            # wajib
  list_paths() -> list[str]      # opsional (default [])
  available() -> bool            # opsional (default True)
```

Exception: `SecretsError` → `SecretNotFound` / `SecretRefError` /
`BackendUnavailable`.

### Bentuk referensi

`SECRET_REF_PATTERN = ^secret://(.+)$` (case-insensitive)

Aturan penguraian: segmen pertama dianggap **nama backend hanya jika** ada di
registry (`katalir`, `hashicorp`, `vault`, `aws`, `onepassword`). Jika tidak,
seluruh path milik backend default.

| Referensi | Backend | Path | Field |
|---|---|---|---|
| `secret://gmail_imap/app_password` | `katalir` | `gmail_imap` | `app_password` |
| `secret://katalir/gmail_imap/x` | `katalir` | `gmail_imap` | `x` |
| `secret://aws/prod/db/pass` | `aws` | `prod/db` | `pass` |
| `secret://hashicorp/vault/item/field` | `hashicorp` | `vault/item` | `field` |
| `secret://gmail_imap` | `katalir` | `gmail_imap` | `None` |

### Helper

- `resolve(ref, user_email)` — satu referensi → nilai
- `resolve_in_args(obj, user_email)` — rekursif atas dict/list; hanya nilai
  string yang cocok pola yang diselesaikan
- `redact(obj)` — menyensor semua `secret://...` menjadi `***` untuk log/error
- `describe_backends()` — status `available()` tiap backend (untuk UI)

### DDL

**Tidak ada.** Fitur ini memakai tabel `user_vault` yang sudah ada.

## 4. Hard Test — 12/12 PASS

| # | Skenario | Status | Bukti (raw) |
|---|---|---|---|
| 1 | `get` dasar | PASS | nilai kembali persis |
| 2 | `set` lalu `get` | PASS | nilai baru terbaca |
| 3 | `list_paths` | PASS | path muncul sekali |
| 4 | `delete` | PASS | setelah hapus → `SecretNotFound` |
| 5 | `resolve` | PASS | `APP-PASS-999` |
| 6 | `resolve_in_args` (bersarang + list) | PASS | `b='biasa' c.d='APP-PASS-999' e[0]='APP-PASS-999'` |
| 7 | `redact` | PASS | `{'key': '***', 'biasa': 'terlihat', 'bersarang': {'d': '***'}, 'list': ['***']}` |
| 8 | Isolasi antar user | PASS | `owner='PUNYA-OWNER' asing=None`; asing → `SecretNotFound` |
| 9 | `parse_ref` (6 bentuk + invalid) | PASS | lihat tabel di atas; bentuk salah → `SecretRefError` |
| 10 | End-to-end resolve | PASS | `resolve='APP-PASS-999'`; secret tidak ada → `SecretNotFound` |
| 11 | Rahasia tidak bocor di pesan error | PASS | `Rahasia tidak ditemukan: katalir/bocor/tidak_ada` (tanpa nilai) |
| 12 | Backend eksternal jujur | PASS | `[('1password',False),('aws',True),('hashicorp',False),('katalir',True),...]`; yang `False` melempar `BackendUnavailable` |

Raw output:

```
tests/test_secrets_provider.py::test_08_isolasi_antar_user [8] owner='PUNYA-OWNER' asing=None
[8] resolve() untuk user asing -> SecretNotFound (benar)
[8] list_paths asing=[]
PASSED
tests/test_secrets_provider.py::test_09_parse_ref [9] secret://gmail_imap/app_password           -> ('katalir', 'gmail_imap', 'app_password')
[9] secret://katalir/gmail_imap/x              -> ('katalir', 'gmail_imap', 'x')
[9] secret://aws/prod/db/pass                  -> ('aws', 'prod/db', 'pass')
[9] secret://hashicorp/vault/item/field        -> ('hashicorp', 'vault/item', 'field')
[9] secret://onepassword/op/item/field         -> ('onepassword', 'op/item', 'field')
[9] secret://gmail_imap                        -> ('katalir', 'gmail_imap', None)
[9] bentuk salah ditolak (SecretRefError)
PASSED
tests/test_secrets_provider.py::test_10_resolve_end_to_end [10] resolve='APP-PASS-999'
[10] resolve_in_args -> b='biasa' c.d='APP-PASS-999' e[0]='APP-PASS-999'
[10] secret tidak ada -> SecretNotFound (benar)
PASSED
tests/test_secrets_provider.py::test_11_rahasia_tidak_bocor [11] pesan error: Rahasia tidak ditemukan: katalir/bocor/tidak_ada
[11] redact -> {'key': '***', 'biasa': 'terlihat', 'bersarang': {'d': '***'}, 'list': ['***']}
PASSED
tests/test_secrets_provider.py::test_12_backend_eksternal_jujur [12] status backend: [('1password', False), ('aws', True), ('hashicorp', False), ('katalir', True), ('onepassword', False), ('vault', False)]
[12] hashicorp: available=False
[12] hashicorp.get() -> BackendUnavailable (jujur)
[12] aws: available=True
[12] onepassword: available=False
[12] onepassword.get() -> BackendUnavailable (jujur)
[12] backend tak dikenal ditolak
PASSED

======================== 12 passed, 1 warning in 9.23s ========================
```

Catatan jujur: `aws: available=True` karena boto3 terpasang transitif di
lingkungan ini — dilaporkan apa adanya oleh `available()`, bukan dipalsukan.

## 5. Bug nyata yang ditemukan & diperbaiki

**BUG-7a — field bersarang tidak terbaca.**
`credential_forms.save_vault_credential()` memaksa **setiap** nilai dengan
`str(v)`. Akibatnya dict bersarang (`{"host": "db.internal", "password": "x"}`)
tersimpan sebagai *repr* string Python, bukan JSON — sehingga `get("db","host")`
selalu gagal.
**Perbaikan:** `_normalisasi()` (JSON-encode `dict`/`list` sebelum simpan) +
`_pulihkan()` (JSON-parse saat baca menelusuri path bersarang); `set()` sekarang
membangun path bersarang secara eksplisit alih-alih menimpa.

Bug lain yang ditemukan saat pengembangan (semua diperbaiki):
- typo identifier `jika_field` → `jalur`.
- `KeyError: 'katalir'` pada `get_provider` — `_instances()` memakai
  `global _CACHE` pada name yang belum terikat; diperbaiki dengan mendeklarasi
  `_CACHE` di atas dan mengisi bila kosong.
- `KatalirVault.available()` mengembalikan `False`; diberi implementasi
  eksplisit yang meng-import `database` + `vault_security` (keduanya sudah wajib).
- `parse_ref` regex greedy → `secret://gmail_imap/app_password` salah urai.
- `TypeError: Can't instantiate abstract class AWSSecretsManager` → `set`/`delete`
  belum diimplementasi.
- `_instances()` gagal total bila **satu** kelas gagal → tiap instansiasi dibungkus
  try/except + log; `BackendUnavailable` hanya bila **semua** gagal.

## 6. Catatan deviasi

- Lisensi backend eksternal: `boto3` (Apache-2.0) ✅, `hvac` (Apache-2.0) ✅,
  `onepassword-sdk` (MIT) ✅. Tidak ada deviasi lisensi pada fitur ini.
- `onepassword-sdk` 0.4.1 **pra-1.0** → tidak dijadikan jalur kritis; hanya
  opsional dengan peringatan jujur.
