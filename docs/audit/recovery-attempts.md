# Percobaan Recovery Workflow (2026-09-21)

Semua langkah dijalankan READ-ONLY. Tidak ada DELETE/UPDATE/INSERT/DROP.
Koneksi: PostgreSQL langsung via pooler `ap-southeast-1` (kredensial dari `.env`).
Backup awal: `docs/audit/backups/workflows-20260921T101553Z.json` (14 baris, 13.901 byte).

## Ringkasan

| # | Jalur | Hasil | Bukti |
|---|---|---|---|
| A1 | Kolom soft-delete di `workflows` | **TIDAK ADA** | `information_schema.columns` → hanya `id, name, description, flow_data, created_at, user_id` |
| A2 | Tabel history/version/audit | **TIDAK ADA** | hanya `execution_logs` & `workflows` yang cocok pola |
| A3 | `auth.audit_log_entries` | **KOSONG** | `select count(*)` = **0** (kolomnya `payload`, bukan `action`) |
| A4 | Peta identitas `verdiawanraafi@gmail.com` | **DUA ID (by design)** | `auth.users` = `4f9a4a98…` (dibuat 09-09 09:43:14, sign-in terakhir 09-12 00:13:11); `public.users` = `cb0a7aea…` (09-09 09:43:16); `auth.identities` = 1 (provider google) |
| A5 | Workflow per pemilik | **1 pemilik** | hanya `e0b848ad…` (akun uji E2E), 14 baris |
| A6 | `executions` menunjuk workflow hilang | **0** | 17 eksekusi, 14 workflow id unik, semuanya masih ada |
| A7 | PITR/backup via Management API | **TIDAK BISA** | `.env` tidak punya `SUPABASE_MANAGEMENT_TOKEN`/`SUPABASE_ACCESS_TOKEN` → butuh aksi user di dashboard |
| A8 | `pg_stat_user_tables` | **cocok dengan catatan** | `workflows`: `n_tup_ins=27`, `n_tup_del=**11**` — tepat sama dengan 11 baris yang dihapus agent (9 lalu + 2 sekarang) → **tidak ada penghapusan tak terdokumentasi** |
| A9 | Kepemilikan id lama (`cb0a7aea`) | **0 workflow**, 1 chat session | `workflows where user_id=cb0a7aea` = 0; `chat_sessions` = 1 ("kamu siapa") dengan 2 pesan |

## Detail penting

**A4 — kenapa ada dua id?** `database.get_or_create_user(email, auth_id)` hanya memakai
`id = auth.users.id` saat **INSERT baris baru**; kalau baris sudah ada (dibuat 09-09 oleh
jalur lama), id-nya dibiarkan apa adanya. Kode secara eksplisit melarang
`UPDATE users.id`:

> "JANGAN PERNAH UPDATE users.id. Mengubah PK yang dirujuk FK chat_sessions dapat
> mengunci/memacetkan request (gejala: /chat menggantung ~25-30 s lalu tanpa respons)."

Karena itu **merge id TIDAK dijalankan** (akan melanggar aturan internal repo + butuh
alter PK). Yang benar: dokumentasikan + jangan andalkan `public.users.id` sebagai
identitas. Dampak nyata: 1 chat session lama ("kamu siapa", 09-09) berada di bawah id
`cb0a7aea` dan tidak akan muncul untuk login sekarang (`4f9a4a98`).

**A5/A6/A8 — kesimpulan tentang 6 baris hilang.** Tidak ada satu pun baris di DB
(executions, chat, audit) yang menunjuk workflow yang sudah tidak ada, dan counter
`n_tup_del` sama persis dengan jumlah penghapusan yang dilakukan agent. Artinya:
tidak ada jejak isi maupun metadata enam baris itu di mana pun.

## Kesimpulan recovery

- **RECOVERED_ROWS = 0.** Enam baris bernama `Draft Workflow` (plus 2 baris probe agent,
  plus 3 baris uji ber-nama `REPRO-DUP-ID`/`REG-DUP-ID`) tidak dapat dipulihkan:
  tidak ada soft-delete, tidak ada tabel riwayat, audit log auth kosong, tidak ada
  dangling execution, PITR tidak bisa diakses, dan trace Playwright sudah terhapus.
- Rekonstruksi parsial dari `executions` juga **tidak mungkin** untuk keenam baris itu,
  karena tidak ada eksekusi yang pernah menunjuk ke mereka (A6).
- Satu-satunya pemulihan yang bisa dilakukan tanpa risiko (menampilkan kembali data
  lama user) adalah merge identitas — dan itu **dilarang oleh kode repo** serta
  berisiko memacetkan request, jadi hanya didokumentasikan (lihat A4).
