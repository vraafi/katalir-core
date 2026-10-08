# Fitur #10 — Workflow Templates

**Status:** ✅ HIJAU — 15/15 hard test PASS + verifikasi LIVE Supabase
**Permukaan:** `GET /templates`, `GET /templates/info`, `GET /templates/{id}`,
`POST /templates`, `POST /templates/{id}/use`, `DELETE /templates/{id}`

## Masalah yang diselesaikan

Sebelum fitur ini setiap user memulai dari kanvas **kosong**. Tidak ada titik
awal yang bisa dipakai langsung → time-to-first-working-workflow tinggi dan
user pemula tidak tahu node apa yang harus disusun.

## Research

| Paket / Pendekatan | Verdict | Alasan |
|---|---|---|
| `n8n`-style template registry (JSON eksternal) | ❌ | Butuh file/DB tambahan; tidak perlu untuk 10 template. |
| Tabel DB saja untuk semua template | ❌ | Template bawaan hilang bila Supabase down. |
| **Konstanta Python (bawaan) + tabel DB (kustom)** | ✅ **dipakai** | Bawaan selalu tersedia (nol DB); kustom owner-scoped + RLS. |
| `cookiecutter` / `jinja` untuk scaffolding | ❌ | Overkill; template = flow_data JSON, bukan kode. |

**Pilihan:** template bawaan = konstanta Python; template kustom = tabel
`workflow_templates` (RLS owner-scoped).
**Alasan:** nol dependency baru, tahan-Supabase-down, dan instantiate memakai
`database.create_workflow` (sumber kebenaran yang sama dengan POST /workflows).

## Implementasi

- **File baru:** `workflow_templates.py`,
  `migrations/2026-10-08-workflow-templates.sql`,
  `tests/test_workflow_templates.py`.
- **File diubah:** `api_server.py` (import + 6 endpoint + 2 model request).
- **DDL:** tabel `workflow_templates` (uuid pk, `user_id uuid`, `name`,
  `description`, `category`, `tags text[]`, `flow_data jsonb`, timestamps),
  3 index (user+created, category, tags GIN), RLS + 4 policy `auth.uid()`,
  trigger `updated_at`. **Diterapkan LIVE** via pooler (15 statement + fungsi/trigger).

### Template bawaan (10)

| ID | Nama | Kategori |
|---|---|---|
| `tpl-email-ke-sheets` | Email masuk → Google Sheets | data |
| `tpl-rss-ke-slack` | RSS → Slack | notification |
| `tpl-telegram-digest-harian` | Digest Harian → Telegram | notification |
| `tpl-webhook-ke-http` | Webhook → API HTTP | integration |
| `tpl-tanya-jawab-ai` | Tanya Jawab AI | ai |
| `tpl-laporan-sheets-bulanan` | Laporan Bulanan → Google Sheets | data |
| `tpl-form-ke-email` | Form → Email | notification |
| `tpl-agenda-ke-calendar` | Pesan → Google Calendar | ops |
| `tpl-monitoring-http` | Monitoring Endpoint → Telegram | ops |
| `tpl-whatsapp-broadcast` | Broadcast → WhatsApp | marketing |

Placeholder isi-user (`{{chat_id}}`, `{{spreadsheet_id}}`, …) SENGAJA dibiarkan
utuh agar user mengisinya di kanvas (konsisten dengan perilaku mesin).

## Hard Test — 15/15 PASS

```
tests/test_workflow_templates.py ............... [100%]  15 passed in 3.00s
```

| # | Skenario | Status | Bukti |
|---|---|---|---|
| 1 | template bawaan tersedia & sah | ✅ | 10 template, semua lolos `validate_flow_data` |
| 2 | filter kategori | ✅ | notification/data/ops non-kosong; kategori asing = 0 |
| 3 | pencarian nama/deskripsi/tag | ✅ | "telegram", "SHEETS" (case-insensitive) |
| 4 | detail + id tak dikenal | ✅ | `get_template` → dict / `None` |
| 5 | instantiate → workflow nyata | ✅ | flow_data identik, muncul di `list_workflows` |
| 6 | CRUD kustom | ✅ | create → list → delete → hilang |
| 7 | isolasi antar user | ✅ | B tidak lihat/hapus template A |
| 8 | validasi flow rusak | ✅ | 6 bentuk ditolak (`TemplateError`) |
| 9 | bawaan tidak bisa dihapus | ✅ | `delete_custom_template` → False |
| 10 | kategori invalid + nama kosong | ✅ | `TemplateError` |
| 11 | endpoint GET list + info | ✅ | `count>=10`, `/templates/info` |
| 12 | endpoint POST use | ✅ | 201 + workflow; tak dikenal → 404 |
| 13 | endpoint POST dari workflow_id | ✅ | 201; wf tak dikenal → 404; flow rusak → 400 |
| 14 | endpoint 404 | ✅ | `/templates/tpl-nope` → 404 |
| 15 | endpoint DELETE bawaan/kustom | ✅ | bawaan → 400; kustom → 200 lalu 404 |

### Verifikasi LIVE (Supabase nyata, `_tpl_live.py`)

```
is_configured = True
CREATE id = 3fdb6ce8-… node_count = 1
LIST count = 11 custom = ['3fdb6ce8-…']
GET name = LIVE TPL
ISOLASI (user lain lihat custom) = False
DELETE = True      SETELAH DELETE get = None
INSTANTIATE workflow id = 3b6278cc-…  flow_data identik = True
muncul di list_workflows = True       CLEANUP = True
```

## Blocker
- Tidak ada. Satu temuan: `instantiate` ke user_id acak ditolak FK
  (`workflows_user_id_fkey`) — benar & diharapkan (user harus nyata); endpoint
  memakai id dari JWT sehingga selalu valid.

## Next
Fitur #11 (Testing Framework).
