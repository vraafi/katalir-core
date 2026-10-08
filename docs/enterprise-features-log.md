# Implementasi 11 Fitur Enterprise n8n — Log (Okt 2026)

Standar: best practice Oktober 2026. Mode: otonom (riset → implementasi →
hard test → commit → lanjut). Setiap fitur punya bagian Research / Implementasi
/ Hard Test / Deviasi / Blocker / Next.

Ringkasan status ada di tabel akhir dokumen ini.

---

## FITUR #1: External Secrets Manager (multi-provider)

### Research
| Paket / backend | Versi | Verdict | Alasan |
|-----------------|-------|---------|--------|
| KatalirVault (existing) | — | **DIPAKAI (default)** | tabel `user_vault` + Fernet, nol dependensi baru |
| HashiCorp Vault (`hvac`) | 2.4.0 | DIPAKAI (opsional, lazy) | Apache-2.0, matang, KV v2 |
| AWS Secrets Manager (`boto3`) | resmi | DIPAKAI (opsional, lazy) | SDK resmi AWS |
| 1Password (`onepassword-sdk`) | 0.4.1 | OPSIONAL | masih 0.x, butuh libssl3+glibc2.32 |
| **Infisical** | REST v3 | **DIPAKAI (baru)** | peringkat 4 besar 2026; REST ringan, nol dependensi |
| **Doppler** | REST v3 | **DIPAKAI (baru)** | peringkat 4 besar 2026; REST ringan |

**Pilihan:** lanjutkan `secrets_provider.py` + tambah Infisical & Doppler lewat
REST `urllib` (stdlib). **Alasan:** tidak menambah dependensi berat menjelang
launch, tetap berjalan di Railway (ephemeral), dan bisa ditest dengan server tiruan.

### Implementasi
- File: `secrets_provider.py` (+~360 baris)
- Fitur baru: `InfisicalProvider`, `DopplerProvider`, `resolve_with_failover()`,
  `resolve_many()` (paralel), `rotate()` + `RotationStore`, `check_size()`
  (batas 256 KiB), `SECRET_REF_FORMATS` (10 format), `KNOWN_BACKENDS` diperbarui.
- API: `GET /secrets/backends`, `GET /secrets/formats`, `POST /secrets/rotate`,
  `GET /secrets/history` (semua di balik auth).
- UI: status backend + riwayat rotasi tersedia via API (dipakai panel settings).
- Registry `/version`: `17_secrets_enterprise`.

### Hard Test — `tests/test_secrets_enterprise.py` (31 kasus, semua PASS)
| # | Skenario | Status |
|---|----------|--------|
| 1 | KatalirVault (existing) masih works | PASS |
| 2 | Dispatch HashiCorp | PASS |
| 3 | Dispatch AWS Secrets Manager | PASS |
| 4 | Dispatch 1Password | PASS |
| 5 | Parsing 10 format referensi | PASS |
| 6 | Rotasi: versi naik + nilai baru | PASS |
| 7 | Failover (backend down → fallback) | PASS |
| 8 | Akses paralel 1000 resolve | PASS |
| 9 | Isolasi multi-tenant | PASS |
| 10 | Performa 100 resolve < 1s | PASS |
| 11 | Batas ukuran 256 KiB | PASS |
| 12 | Path traversal / karakter bahaya ditolak | PASS |
| 13 | Backend baru terdaftar | PASS |
| 14 | Referensi tanpa field → JSON provider | PASS |

Bukti raw: `31 passed in 0.99s`.

### Deviasi dari brief
- Backend 1Password hanya **read** (SDK tulis belum dipakai) — dicatat jujur.
- Rotation store default memori (dapat disuntik Supabase); riwayat tidak
  persist antar-restart pada mode default.

### Blocker
- Tidak ada.

### Next
- Fitur #2 — Advanced Scheduling.

---
