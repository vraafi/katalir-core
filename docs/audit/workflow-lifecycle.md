# Audit Lifecycle Workflow (2026-09-21)

Semua temuan di bawah dari query READ-ONLY ke Supabase + pembacaan kode +
browser nyata. **Tidak ada data yang diubah/dihapus dalam audit ini.**

## 1. Fakta dari database (read-only)

| Pertanyaan | Hasil |
|---|---|
| Jumlah workflow di DB saat audit | **14** (semuanya milik satu akun: `e0b848ad…` = akun uji E2E) |
| Jumlah workflow milik akun user (`verdiawanraafi@gmail.com`, auth id `4f9a4a98…`) | **0** |
| Jumlah chat_sessions milik akun user | **0** |
| Baris `user_usage` (kuota harian) untuk email user | **0** |
| Baris bernama `Draft Workflow` (nama yang dipakai tombol "Simpan Alur") | **0** (semuanya sudah terhapus) |
| Histogram nama yang tersisa | 6× `L3 auto-run probe`, 4× `Kirim Laporan Harian Telegram`, 1× `Kirim Pesan Telegram Harian`, 1× `Kirim pesan Telegram tiap jam 9 pagi`, 1× `L3 S1 execute`, 1× `diag` |
| `executions` menunjuk workflow yang sudah tidak ada | **0** (semua eksekusi menunjuk workflow yang masih ada) |

Catatan penting: ada **dua identitas untuk orang yang sama**.
`auth.users` menyimpan `verdiawanraafi@gmail.com` dengan id `4f9a4a98-…`,
sementara `public.users` menyimpan email yang sama dengan id `cb0a7aea-…`
(id ini **tidak ada** di `auth.users`; 49 akun di auth.users, 56 baris di public.users).
Satu-satunya chat session milik `cb0a7aea` berjudul "kamu siapa" dibuat
2026-09-09T09:43:25, hanya 11 detik setelah akun dibuat — jejak uji pertama.
Backend memakai `user["id"]` dari JWT (`security.get_current_user`), jadi data
BARU tersimpan di bawah `4f9a4a98`, sedangkan data lama (Sep 9) ada di bawah
`cb0a7aea` dan karena itu tidak akan pernah muncul di UI lagi.

## 2. Jalur list TIDAK rusak (dibuktikan di browser)

Akun E2E (punya 14 baris) membuka `/builder`:

```
GET /workflows -> 200  {"status":"success","workflows":[…]}
sidebar item_count = 14  == jumlah baris di DB
empty_state = false
```

Artinya: sidebar menampilkan **persis** apa yang dimiliki akun itu. Sidebar user
kosong ("Belum ada alur") karena akun itu memang **0 baris**, bukan karena bug render.

## 3. Yang menghapus data (harus diakui)

Skrip pembersihan milik agent (`_clean_seed_wf.py`) menghapus baris **BERDASARKAN NAMA**
dengan service key (melewati RLS, tanpa filter pemilik, tanpa backup):
`DELETE /workflows?name=eq.Draft Workflow`. Dijalankan **dua kali**:

| Kapan | Sebelum | Sesudah | Baris terhapus |
|---|---|---|---|
| Sesi duplicate-key (sebelum fix drop-position) | 23 | 14 | 9 = 1 `REPRO-DUP-ID` + 2 `REG-DUP-ID` + **6 `Draft Workflow`** |
| Sesi drop-position (setelah verifikasi persist) | 16 | 14 | 2 = **2 `Draft Workflow`** (keduanya dari probe "Simpan Alur" milik agent sendiri) |

Total **8 baris bernama `Draft Workflow` terhapus**. Dua yang paling akhir dapat
dipastikan milik akun uji E2E (dibuat oleh probe agent). Enam yang lebih awal
berumur lebih tua dari 2026-09-20T07:00 dan **kepemilikannya tidak dapat
dibuktikan lagi** dari DB. Tidak ada audit trail/backup yang bisa diakses
(tanpa token manajemen Supabase; trace Playwright sudah terhapus).

## 4. Tabel lifecycle (status SETELAH perbaikan FASE B)

| # | Interaksi | Status | Bukti |
|---|---|---|---|
| 1 | Create workflow → tersimpan di DB | **PASS** | `POST /workflows` → 201 `updated:false`; spec UI: baris langsung muncul di sidebar (`SIDEBAR 15 → 16`) |
| 2 | List workflow → metadata saja, per user, urut `created_at desc` | **PASS** | `GET /workflows` → 200 tanpa `flow_data`; pytest `test_1_create_dan_list_metadata` menolak kemunculan `flow_data` |
| 3 | Load/restore → node + edge + posisi benar | **PASS** | `GET /workflows/{id}` → detail; spec UI: `NODES_AFTER_LOAD=4` setelah reload; `PERSIST_OK=true` (sesi drop-position) |
| 4 | Save (update existing) → tidak membuat duplikat | **PASS (DIPERBAIKI)** | `POST /workflows` dengan `id` → `updated:true`, jumlah baris tetap (spec UI: `SAVE2`; pytest `test_3_...`) |
| 5 | Delete workflow | **PASS (BARU)** | `DELETE /workflows/{id}` → 200; baris hilang dari sidebar + DB; bukan pemilik → 403 |
| 6 | Rename | **PASS (BARU)** | `PATCH /workflows/{id}` → 200; nama berubah dan bertahan setelah reload; body kosong → 400 |
| 7 | Duplicate | **BELUM ADA** (dinilai tidak perlu: "Alur Baru" + Simpan sudah memberi workflow baru; duplikasi bisa ditambahkan bila diminta) | — |
| 8 | Restore after reload | **PASS** | spec UI: setelah reload nama tetap & graf termuat (`NODES_AFTER_LOAD=4`) |

Ringkas: **7/8 PASS**, 1 fitur yang memang belum pernah ada (duplicate) sengaja tidak
ditambah tanpa permintaan.

## 5. Bug lifecycle yang DIPERBAIKI di sesi ini

1. **Save selalu INSERT** → sekarang `id` opsional: `POST` = UPDATE bila pemilik cocok.
   Bukti: `SAVE: status=201 updated=false` lalu `SAVE2: status=201 updated=true` (id sama).
2. **Tidak ada delete** → `DELETE /workflows/{id}` owner-scoped + tombol hapus
   (konfirmasi) di sidebar.
3. **Tidak ada rename** → `PATCH /workflows/{id}` + rename inline (Enter/cek/Escape).
4. **List mengirim `flow_data` semua workflow** → sekarang metadata saja; graf diambil
   per-workflow lewat `GET /workflows/{id}`.
5. **Cleanup berbahaya** → `scripts/cleanup_workflows.py` (dry-run default, wajib
   `--owner`, wajib `--backup` sebelum `--confirm`).
6. **`get_workflow_owner` selalu `None` di jalur memori** → akses lintas user dilaporkan
   404 padahal harus 403; sekarang mengembalikan pemilik sebenarnya (temuan uji).
7. **`builder.spec.ts` (c) adalah tes kosong** (`expect(status=0).not.toBe(500)`) dan
   berjalan TANPA sesi → SAVE sebenarnya dibalas **401**; sekarang sesi disuntikkan dan
   status di-assert 201 + baris uji dibersihkan sendiri.

## 6. Temuan yang BELUM diperbaiki (dilaporkan, bukan disembunyikan)

1. **Dua identitas** (`4f9a4a98` auth vs `cb0a7aea` public.users) — merge dilarang oleh
   komentar kode (`UPDATE users.id` memacetkan request). Data lama di bawah id kedua
   tidak akan muncul lagi. Butuh keputusan skema.
2. **`node_count` tidak ada di list**: menghitungnya butuh membaca `flow_data` (yang
   justru dibuang) atau kolom generated (perubahan skema) — sengaja dilewati.
3. **Tidak ada halaman riwayat/versioning workflow.**
4. Baris sisa uji `046e6be0…` (dari run spec yang gagal) masih ada; cara membersihkan
   ada di `docs/audit/recovery-log.md` (sengaja tidak dihapus: izin hapus tidak ada).

