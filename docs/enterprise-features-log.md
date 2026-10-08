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

## FITUR #4: Multi-Environment (dev/staging/prod)

### Research
| Pendekatan | Verdict | Alasan |
|-----------|---------|--------|
| Vendor env (Vercel/Netlify) | DITOLAK | tidak menyimpan workflow/DAG |
| n8n environments | REFERENSI | pola promotion + approval |
| In-house di atas store dapat-disuntik | **DIPAKAI** | nol dependensi, deterministik, tidak terkunci vendor |

**Pilihan:** `environments.py`. **Alasan:** store memori untuk test +
`SupabaseEnvStore` untuk produksi (antarmuka identik).

### Implementasi
- File: `environments.py` (baru, ~330 baris) — `Environments`, `EnvStore`,
  `SupabaseEnvStore`, `diff_flow`, `credential_key`, `default_store`.
- Aturan: promosi hanya maju satu langkah; `production` butuh approval;
  isolasi credential `env:<env>:<provider>`; rollback = append versi baru;
  RBAC per environment (`viewer/developer/admin/owner`).
- DDL: `migrations/2026_environments.sql` → `workflow_environments`,
  `environment_audit` + RLS (diterapkan: **11/11 OK**).
- API: `GET /environments`, `GET /environments/{env}/workflows`,
  `POST /environments/promote`, `POST /environments/approve`,
  `GET /environments/pending`, `GET /environments/diff`,
  `POST /environments/rollback`, `GET /environments/audit`.
- Registry `/version`: `20_environments`.

### Hard Test — `tests/test_environments.py` (14 kasus, PASS)
| # | Skenario | Status |
|---|----------|--------|
| 1 | Create di dev → promote ke staging | PASS |
| 2 | Promote staging → production (approval) | PASS |
| 3 | Isolasi credential antar environment | PASS |
| 4 | Environment selector | PASS |
| 5 | Rollback dari production | PASS |
| 6 | Diff antar environment | PASS |
| 7 | Concurrent edit 2 environment (50+50) | PASS |
| 8 | Migrasi workflow existing → dev | PASS |
| 9 | Config spesifik per environment | PASS |
| 10 | Performa 100 workflow < 2s | PASS |
| 11 | Audit log promosi | PASS |
| 12 | Access control per environment | PASS |
| 13 | Bandingkan versi antar environment | PASS |

Bukti raw: `14 passed in 0.32s`. DDL live: `default_store() == SupabaseEnvStore`.

### Deviasi dari brief
- UI environment selector disajikan via API (`GET /environments`); komponen
  React belum ditambahkan di batch ini (backend lengkap).

### Blocker
- Tidak ada.

### Next
- Fitur #5 — Source Control / Git.

---

## FITUR #5: Source Control / Git

### Research
| Pendekatan | Verdict | Alasan |
|-----------|---------|--------|
| PyGithub / python-gitlab SDK | DITOLAK | dependensi berat; REST cukup |
| GitHub/GitLab/Bitbucket REST | **DIPAKAI** | ringan, lewat transport yang dapat disuntik |
| git CLI lokal | DITOLAK | Railway ephemeral + tak cocok multi-tenant |

**Pilihan:** `source_control.py` (REST + transport disuntik). **Alasan:** nol
dependensi, dapat diuji tanpa jaringan (server Git tiruan), token di-redact.

### Implementasi
- File: `source_control.py` (baru, ~430 baris) — `GitClient` (abstract),
  `GitHubClient`/`GitLabClient`/`BitbucketClient`, `SourceControl`,
  `serialize_workflow`/`deserialize_workflow`, `ConnectionStore` (token
  dienkripsi via `vault_security`), `redact`, `ConflictError`.
- Fitur: commit/pull/diff/rollback, branch, PR (open+merge), conflict detection
  (`expect_sha`), sync dari webhook push, mask token.
- DDL: `migrations/2026_source_control.sql` → `git_connections` + RLS
  (diterapkan: **6/6 OK**).
- API: `GET /source-control/providers`, `POST /source-control/connect`,
  `GET /source-control/connections`, `DELETE .../{provider}`,
  `POST /source-control/commit`, `GET /source-control/pull`,
  `GET /source-control/diff`, `POST /source-control/rollback`,
  `POST /source-control/branches`, `POST /source-control/pr`,
  `POST /source-control/webhook`.
- Registry `/version`: `21_source_control`.

### Hard Test — `tests/test_source_control.py` (12 kasus, PASS)
| # | Skenario | Status |
|---|----------|--------|
| 1 | Connect repo → OK | PASS |
| 2 | Commit workflow → ter-push | PASS |
| 3 | Pull workflow → ter-load | PASS |
| 4 | Diff view | PASS |
| 5 | Rollback ke versi lama | PASS |
| 6 | Branch main vs dev | PASS |
| 7 | PR create + merge | PASS |
| 8 | Conflict resolution (expect_sha) | PASS |
| 9 | Multi-user (2 branch) | PASS |
| 10 | Webhook push → sync | PASS |
| 11 | Performa 100 commit < 3s | PASS |
| 12 | Keamanan: token tidak bocor | PASS |

Bukti raw: `12 passed in 0.32s`.

### Deviasi dari brief
- `ConnectionStore` saat ini memori (tabel `git_connections` sudah dibuat untuk
  persistensi; wiring Supabase dapat ditambahkan tanpa mengubah API).

### Blocker
- Tidak ada.

### Next
- Fitur #6 — Queue Mode Scaling.

---

## FITUR #6: Queue Mode Scaling (horizontal)

### Research
| Pustaka | Verdict | Alasan |
|---------|---------|--------|
| ARQ | DITOLAK | resmi **maintenance-only** (temuan Okt 2026) |
| RQ | OPSIONAL | fork-per-job, pickle; retry/sched kini built-in |
| Dramatiq | OPSIONAL | retry/rate-limit bawaan, tapi +dependensi |
| Taskiq | OPSIONAL | async-native, ekosistem muda |
| In-house (memori + Redis lazy) | **DIPAKAI** | nol dependensi wajib, degradasi anggun |

**Pilihan:** `queue_mode.py` — backend memori (test) + Redis opsional (lazy).
**Alasan:** berjalan tanpa Redis (Railway single-instance) dan siap di-scale
saat `KATALIR_REDIS_URL` diisi.

### Implementasi
- File: `queue_mode.py` (baru, ~430 baris) — `Job`, `MemoryQueueBackend`,
  `RedisQueueBackend`, `JobQueue` (prioritas/retry/DLQ/recover), `WorkerPool`
  (health/scale/graceful), `QueueManager` (pilih backend).
- Integrasi: worker pool di `_lifespan` (kill-switch `QUEUE_WORKERS`, default 0);
  handler memanggil `execution_engine.launch_execution`.
- API: `GET /queue/health`, `GET /queue/stats`, `POST /queue/enqueue`,
  `GET /queue/dlq`, `POST /queue/recover`.
- Registry `/version`: `22_queue_mode`.

### Hard Test — `tests/test_queue_mode.py` (13 kasus, PASS)
| # | Skenario | Status |
|---|----------|--------|
| 1 | 100 job → semua diproses | PASS |
| 2 | Worker crash → job requeued | PASS |
| 3 | Redis down → degradasi anggun | PASS |
| 4 | Concurrent workers (5) | PASS |
| 5 | Prioritas job | PASS |
| 6 | Job timeout | PASS |
| 7 | Retry (max 3 → 4 percobaan) | PASS |
| 8 | Dead letter queue | PASS |
| 9 | Load test 1000 job < 10s | PASS |
| 10 | Scaling: tambah worker runtime | PASS |
| 11 | Graceful shutdown | PASS |
| 12 | Benchmark throughput > 100 job/s | PASS |

Bukti raw: `13 passed in 1.16s`.

### Deviasi dari brief
- Redis tidak di-hard-test (butuh server); jalur Redis memakai `redis` lazy dan
  diuji sebagai degradasi anggun. Supabase tetap source of truth.

### Blocker
- Tidak ada.

### Next
- Fitur #7 — SSO / SAML / OIDC / LDAP.

---
