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

## FITUR #2: Advanced Scheduling

### Research
| Paket | Versi | Verdict | Alasan |
|-------|-------|---------|--------|
| croniter (existing) | stabil | **DIPAKAI** | pure-python, sudah dipakai scheduler_manager |
| APScheduler | 4.x pre | DITOLAK | masih pre-release |
| fastscheduler | 0.2.x | DITOLAK | terlalu muda (v0.x) |
| dateparser/parsedatetime | — | DITOLAK | berat & ambigu untuk cron |

**Pilihan:** `advanced_scheduling.py` (murni) + croniter. **Alasan:** nol
dependensi baru, DST diuji nyata, dan NL parser kecil sendiri (EN + ID).

### Implementasi
- File: `advanced_scheduling.py` (baru, ~330 baris, MURNI tanpa DB/jaringan)
- Fungsi: `build_cron` (builder visual), `natural_to_cron` (EN/ID),
  `next_fire`/`next_fires` (DST-safe), `evaluate_condition` (tanpa `eval`),
  `decide` (fire + alasan), `build_workflow_schedules` (multiple),
  `validate_spec`, `COMMON_TIMEZONES` (50).
- Integrasi: `scheduler_manager.advanced_gate()` dipanggil di `tick()` —
  kondisi + dependency dihormati; jadwal yang di-skip TIDAK di-claim.
- DDL: `migrations/2026_advanced_scheduling.sql` → kolom `condition`,
  `depends_on`, `label` (diterapkan ke Supabase: **5/5 OK**).
- API: `GET /schedules/timezones`, `POST /schedules/build`,
  `POST /schedules/parse`, `POST /schedules/preview`, `POST /schedules/validate`.
- Registry `/version`: `18_advanced_scheduling`.

### Hard Test — `tests/test_advanced_scheduling.py` (26 kasus, PASS)
| # | Skenario | Status |
|---|----------|--------|
| 1 | Builder visual → cron valid + tolak invalid | PASS |
| 2 | Natural EN → cron (8 frasa) | PASS |
| 3 | Natural ID → cron (6 frasa) | PASS |
| 4 | DST spring-forward: 09:00 lokal tetap 09:00 | PASS |
| 5 | DST fall-back: 09:00 lokal tetap 09:00 | PASS |
| 6 | Multiple schedule per workflow | PASS |
| 7 | Conditional schedule | PASS |
| 8 | Dependency (A selesai → B) | PASS |
| 9 | 50 timezone valid | PASS |
| 10 | Validasi ekspresi (tolak 4/6 field) | PASS |
| 11 | Performa 1000 next_fire < 2s | PASS |
| 12 | Alasan fire/skip untuk log | PASS |
| 13 | Deret next_fires menaik | PASS |

Bukti raw: `26 passed in 0.70s` + `66 passed` (seluruh tes scheduler).

### Deviasi dari brief
- **BUG DITEMUKAN & DIPERBAIKI:** croniter dengan base tz-aware menghasilkan
  waktu spurious (08:00) pada hari spring-forward DST. Diperbaiki dengan
  iterasi pada dinding jam lokal (naive) lalu lokalisasi.

### Blocker
- Tidak ada.

### Next
- Fitur #3 — Advanced Monitoring & Alerting.

---

## FITUR #3: Advanced Monitoring & Alerting

### Research
| Paket | Verdict | Alasan |
|-------|---------|--------|
| prometheus_client | DITOLAK | menambah dependensi; eksposisi teks cukup ditulis sendiri |
| Grafana Agent / OTel SDK | OPSIONAL | berat untuk jalur launch; tracing in-house cukup |
| stdlib `urllib` (notifier) | **DIPAKAI** | nol dependensi, transport disuntik untuk test |

**Pilihan:** `monitoring.py` (murni) + eksposisi Prometheus 0.0.4 buatan sendiri.
**Alasan:** bisa di-scrape Prometheus/Grafana tanpa klien berat; notifikasi
diuji tanpa jaringan lewat transport yang disuntik.

### Implementasi
- File: `monitoring.py` (baru, ~420 baris)
- Komponen: `Metrics` (+`render_prometheus`), `evaluate_rules` (mesin aturan),
  `AlertManager` (dedup + silence), notifier `Webhook/Slack/Telegram/Email`,
  `redact` (cegah bocor), `LogIndex` (agregasi), `Trace`/`Span`,
  `dashboard_summary`.
- API: `GET /metrics` (Prometheus, numerik saja), `GET /monitoring/summary`,
  `POST /monitoring/silence`, `GET /monitoring/logs`.
- Registry `/version`: `19_monitoring`.

### Hard Test — `tests/test_monitoring.py` (13 kasus, PASS)
| # | Skenario | Status |
|---|----------|--------|
| 1 | Metrik → eksposisi Prometheus bisa di-scrape | PASS |
| 2 | Aturan error rate > 5% → fire | PASS |
| 3 | Notifikasi Slack diterima | PASS |
| 4 | Notifikasi Email diterima | PASS |
| 5 | Dashboard muat < 2s (5000 observasi) | PASS |
| 6 | Trace: span per node | PASS |
| 7 | Agregasi log: pencarian OK | PASS |
| 8 | Dedup alert | PASS |
| 9 | Silence (maintenance) | PASS |
| 10 | Performa 1000 aturan < 1s | PASS |
| 11 | Benchmark latensi evaluasi alert | PASS |
| 12 | Keamanan: isi alert tidak bocorkan rahasia | PASS |

Bukti raw: `13 passed in 0.33s`.

### Deviasi dari brief
- Sumber nilai metrik (`_monitor_values`) saat ini konservatif (0/1); hook ke
  `insights`/engine dapat diperkaya tanpa mengubah kontrak.
- Notifier `_send_http` tidak diuji jaringan (transport disuntik) — perilaku
  produksi memakai stdlib `urllib`.

### Blocker
- Tidak ada.

### Next
- Fitur #4 — Multi-Environment.

---
