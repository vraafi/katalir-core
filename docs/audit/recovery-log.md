# Log Recovery (2026-09-21)

## Status akhir

| Item | Nilai |
|---|---|
| Baris workflow SEBELUM sesi ini | 14 |
| Baris workflow SESUDAH seluruh langkah | 14 (tidak berubah — tidak ada data disentuh) |
| RECOVERED_ROWS | **0** |
| STILL_MISSING | **6** (baris `Draft Workflow` yang tidak bisa dilacak pemiliknya) + 2 baris probe agent + 3 baris uji agent = 11 total penghapusan agent |
| BACKUP_FILE | `docs/audit/backups/workflows-20260921T101553Z.json` (14 baris) |
| Cara recovery yang DICOBA | A1–A9 (lihat `recovery-attempts.md`) |
| Cara recovery yang BERHASIL | tidak ada |
| DATA_DELETED_THIS_SESSION | **0** |

## Backup

`docs/audit/backups/` di-gitignore (berisi data user, tidak boleh masuk repo).
File backup dibuat otomatis oleh `_recovery_audit.py` (langkah A10) SEBELUM langkah
lain, dan dipakai lagi oleh `scripts/cleanup_workflows.py` bila `--confirm`.

## Apa yang TIDAK dilakukan (dan alasannya)

1. **Tidak merge identitas `cb0a7aea` → `4f9a4a98`.** `database.py` melarang
   `UPDATE users.id` karena PK itu dirujuk FK `chat_sessions.user_id` dan pernah
   menyebabkan request menggantung ~25–30 s. Merge butuh pemikiran ulang skema
   (mis. backfill `chat_sessions.user_id` lalu ubah PK) = pekerjaan tersendiri.
2. **Tidak re-create 6 baris yang hilang.** Isinya tidak diketahui; membuat baris
   "kerangka" dengan nama pengganti akan menyesatkan (user akan mengira itu datanya).
3. **Tidak menghapus baris apa pun**, termasuk 1 baris sisa `Draft Workflow`
   (id `046e6be0…`, dibuat oleh satu kali run spec yang gagal sebelum perbaikan
   JSON di sesi ini). Untuk membersihkannya (owner-scoped + backup otomatis):

   ```powershell
   python scripts/cleanup_workflows.py --owner e2e.1789523141333@nexus-local.test --dry-run
   # setelah yakin, tambahkan:  --confirm --backup docs/audit/backups/cleanup-<tanggal>.json
   ```

   (script menolak jalan tanpa `--owner`, menolak `--confirm` tanpa `--backup`, dan
   default hanya dry-run)

## Pelajaran yang dikunci jadi mekanisme

| Kesalahan sesi lalu | Mekanisme pengaman sekarang |
|---|---|
| `DELETE /workflows?name=eq.…` tanpa filter pemilik | `scripts/cleanup_workflows.py` wajib `--owner`/`--owner-id`; DELETE menyertakan `id` DAN `user_id` |
| Hapus tanpa melihat dulu | default **DRY-RUN** |
| Hapus tanpa backup | `--confirm` ditolak bila `--backup` tidak diberikan |
| Data uji menumpuk karena spec tidak membersihkan | `builder.spec.ts` (c) & `builder-workflow-lifecycle.spec.ts` menghapus sendiri workflow yang dibuat |
| Simpan ulang menumpuk baris | `POST /workflows` dengan `id` = UPDATE (dites: `updated:true`, jumlah baris tetap) |
| Tidak ada cara menghapus/renama dari UI | tombol rename inline + hapus (konfirmasi) di `WorkflowSidebar` |
