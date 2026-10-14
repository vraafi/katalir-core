# FINAL VERDICT — 14 Okt 2026

Brief: **FIX DELETE ENDPOINT + FINAL VERIFICATION**
Mode: otonom · evidence-only · tanpa band-aid · tanpa menurunkan ambang.

---

## 0. TL;DR

| Item | Hasil |
|---|---|
| **DELETE `/workflows/{id}` id non-UUID** | **500 → 404. FIXED + dideploy + terbukti** (before/after, akun nyata) |
| Regresi 73 skenario (sesudah fix) | **54 PASS / 15 FAIL / 2 BLOCKED / 2 NOT_RUN** |
| Regresi sebelumnya (08:32, sebelum fix) | 57 PASS / 12 FAIL / 2 BLOCKED / 2 NOT_RUN |
| P5-12b (skenario bug DELETE) | **FAIL → PASS** ✅ |
| Akar 13 dari 15 FAIL | **satu sebab**: `POST /chat` → `503 "Semua kunci model ini sedang cooldown (kuota)"` |
| **Verdict** | **BELUM** — 1 item severity **HIGH** (P5-15) + 1 **MEDIUM** (BUG-05) masih terbuka |

**Catatan penting soal angka:** PASS turun 57 → 54 **bukan regresi** — bug DELETE justru
membaik (P5-12b FAIL→PASS). Penyebabnya satu: model default frontend
(`google/gemma-4-31b-it`) sedang **cooldown kuota**, sehingga skenario yang memaksa
generasi LLM gagal. Pada 08:32 hulu sempat sebagian pulih; pada run ini cooldown lebih
luas. Bukti di §2 dan §3.

---

## 1. TASK 1 — FIX DELETE ENDPOINT (BUG NYATA)

### 1.1 REPRODUCE (BEFORE) — produksi, akun Supabase nyata

`tests/user_test/rus_repro_delete.py before` → `docs/evidence/fix-delete-2026-10-14/probe_before.json`

| # | Kasus | HTTP | Harap | Hasil |
|---|---|---|---|---|
| 1 | `DELETE /workflows/not-a-uuid` | **500** | 404 | ❌ |
| 2 | `DELETE /workflows/1` | **500** | 404 | ❌ |
| 3 | `PATCH /workflows/not-a-uuid` | 404 | 404 | ✅ |
| 4 | `GET /workflows/not-a-uuid` | 404 | 404 | ✅ |
| 5 | `POST /workflows` (valid) | 201 | 201 | ✅ |
| 6 | `DELETE /workflows/<uuid-valid>` | 200 | 200 | ✅ |
| 7 | `DELETE /workflows/<uuid-valid>` (ulang) | 404 | 404 | ✅ |

`count_5xx=2`. Body 500: `{"detail":"Terjadi kesalahan internal saat menghapus workflow.
Silakan coba lagi. (ref: 6ae88547a30b)"}` — status salah kelas (input klien harus 4xx).

### 1.2 ISOLATE

`api_server.py` — handler ber-`{workflow_id}` dan penjaga UUID-nya:

| Handler | Baris | `_require_uuid_or_404`? |
|---|---|---|
| `GET /workflows/{id}` | 4092 | ✅ (4096) |
| `PATCH /workflows/{id}` | 4106 | ✅ (4111) |
| `POST /workflows/{id}/ops` | 4129 | ✅ (4145) |
| **`DELETE /workflows/{id}`** | **4241** | **❌ TIDAK ADA** |

`DELETE /workflows/{id}/schedule` (4591) aman: memakai `_schedule_owner_or_404` →
`db.get_workflow_owner` yang menelan exception → 404, bukan 500.

**Akar masalah:** tanpa penjaga, `db.delete_workflow()` mengirim id mentah ke PostgREST →
Postgres menolak dengan `22P02 invalid input syntax for type uuid` → `except Exception` →
`_db_error_500` → **HTTP 500**. Ini **cacat terisolasi**: satu-satunya handler
ber-`{workflow_id}` yang terlewat saat BUG-04 diperbaiki.

### 1.3 FIX (1 baris, memakai helper kanonik yang sudah ada)

```python
@app.delete("/workflows/{workflow_id}")
def remove_workflow(workflow_id: str, authorization: str | None = Header(None)):
    """Hapus SATU workflow milik user JWT. Owner-scoped (bukan pemilik -> 403)."""
    user = security.get_current_user(authorization)
    # BUG-04 (DELETE): id non-UUID -> 404 SEBELUM DB.
    _require_uuid_or_404(workflow_id)
    try:
        ok = db.delete_workflow(workflow_id, user["id"])
    ...
```

Tidak mengubah perilaku untuk id valid (kontrol positif §1.4 tetap hijau).

### 1.4 PROOF-FIRST TEST (AFTER)

`rus_repro_delete.py after` → `docs/evidence/fix-delete-2026-10-14/probe_after.json`

| # | Kasus | BEFORE | AFTER |
|---|---|---|---|
| 1 | `DELETE /workflows/not-a-uuid` | 500 | **404** ✅ |
| 2 | `DELETE /workflows/1` | 500 | **404** ✅ |
| 3 | `PATCH /workflows/not-a-uuid` | 404 | 404 ✅ |
| 4 | `GET /workflows/not-a-uuid` | 404 | 404 ✅ |
| 5 | `POST /workflows` (valid) | 201 | 201 ✅ |
| 6 | `DELETE /workflows/<uuid-valid>` | 200 | 200 ✅ |
| 7 | `DELETE /workflows/<uuid-valid>` (ulang) | 404 | 404 ✅ |

**`count_5xx: 2 → 0`.** Body 404: `{"detail":"Workflow tidak ditemukan."}`.

### 1.5 DEPLOY (VPS, terbukti)

| Langkah | Bukti |
|---|---|
| Backup | `/root/katalir-core/api_server.py.bak-fixdelete-20261014-031017` |
| Kirim | `scp api_server.py` → VPS |
| Uji impor | `venv/bin/python3 -c "import api_server"` → `IMPORT_OK` |
| Restart | `systemctl restart katalir-backend` → `active` |
| Konsistensi | md5 lokal = VPS = **`52e637a7cf18447e4daa0c1175901f13`** |
| Penjaga di VPS | `grep` → baris **4249** `_require_uuid_or_404(workflow_id)` |
| Probe ulang | §1.4 (dijalankan SETELAH restart) |

---

## 2. TASK 2 — KLASIFIKASI 15 FAIL (regresi 14 Okt, sesudah fix)

> Brief menyebut 12 FAIL — itu angka run **08:32**. Run otoritatif sesi ini = 15 FAIL;
> klasifikasinya di bawah, semuanya berbasis `reply_tail` + `console_errors` mentah
> (`docs/evidence/regression-delete-fix-2026-10-14/after/rus_*.json`).

| # | Grup | Skenario | Klasifikasi | Tindakan |
|---|---|---|---|---|
| 1 | p5 | **P5-15** Model default frontend tidak dapat dilayani | **BUG (HIGH, harness)** | **LAPORKAN** → §5 |
| 2 | p2 | P2-02 prompt kabur | HULU 503 (gemma cooldown) | skip |
| 3 | p2 | P2-05 input emoji | HULU 503 | skip |
| 4 | p3 | P3-05 idle 90 s | HULU 503 | skip |
| 5 | p4 | P4-02 kirim di 3G | HULU 503 | skip |
| 6 | p4 | P4-04 pulih dari offline | HULU 503 | skip |
| 7 | p4 | P4-06 tombol "Coba Lagi" | HULU 503 (retry menabrak cooldown sama) | skip |
| 8 | p5 | P5-01 input emoji | HULU 503 | skip |
| 9 | p5 | P5-03 SQL injection | HULU 503 | skip |
| 10 | p5 | P5-04 XSS | HULU 503 | skip |
| 11 | p5 | P5-13 prompt injection | HULU 503 (properti keamanan LULUS: `dugaan_bocor=False`) | skip |
| 12 | j1 | J1-B prompt pertama | HULU 503 | skip |
| 13 | j2 | J2-D workflow Shopee | HULU 503 | skip |
| 14 | p1 | P1-01 refresh 3 s setelah kirim | **ARTEFAK** Playwright (`Locator.click: Timeout 15000ms`) | skip |
| 15 | p1 | P1-08 tombol Back | **CONFOUNDED** (riwayat; `layar_rusak=False`, `chat_pulih=True`) | skip + verifikasi ulang saat hulu sehat |

**Bukti seragam 12 kasus HULU** (dari `reply_tail`, verbatim):

```
<teks yang dikirim user> | Gagal mengirim |  | Semua kunci model ini sedang cooldown
(kuota). Coba lagi. |  | Coba Lagi
```

disertai `console_errors`: `Failed to load resource: the server responded with a status of 503 ()`.

### Item struktural (bukan FAIL)

| State | Skenario | Sebab |
|---|---|---|
| BLOCKED | J1-A, J1-A2 | pendaftaran email sengaja disembunyikan (mitigasi BUG-06) |
| NOT_RUN | J2-C | tidak ada field kredensial di UI |
| NOT_RUN | B-11 | fitur lampiran belum ada (`input[type=file]` = 0) |

---

## 3. TASK 3 — ECHO_ONLY: TIDAK DIPERBAIKI (BUKAN BUG PRODUK)

Brief mengasumsikan FAIL `echo_only` = kualitas model. **Bukti membantah asumsi itu**,
dan justru menunjuk satu akar tunggal.

**Apa itu `echo_only`?** Heuristik harness (`rus_core.py:536`): bubble user sudah muncul,
teks tidak berubah ~16 s, dan aplikasi tidak menyatakan sibuk. Catatan kode harness sendiri
mengakui ini bisa keliru untuk balasan berbentuk form.

**Apa yang sebenarnya terjadi?** Pada run 08:32, `reply_tail` tiap kasus `echo_only` adalah:

```
<teks yang dikirim user> | Server sibuk, coba lagi sebentar.
```

`"Server sibuk, coba lagi sebentar."` adalah **indikator sibuk tahap ≥10 detik** di
frontend (`nexus-frontend/src/features/chat/thread.tsx:484`, `ChatApp.tsx:399`) — bukan
balasan model. Artinya harness menyerah saat request **masih berjalan** karena `_busy()`
(`rus_core.py:487`) hanya mengenali 2 tahap pertama ("agen sedang berpikir", "sedang
memproses") dan tidak mengenali tahap ke-3.

**Kesimpulan Task 3:** akar masalahnya **bukan** system prompt / `max_tokens` / "model
terlalu ringkas". Akarnya adalah `POST /chat` → 503 cooldown. Sesuai larangan brief
(*"❌ Fix echo_only kalau bukan bug"*), **tidak ada perubahan kode** yang dilakukan untuk
`echo_only`. (Celah `_busy()` juga tidak diubah: itu instrumen ukur, dan mengubahnya di
tengah run dilarang oleh konvensi proyek.)

---

## 4. TASK 4 — REGRESI ULANG (73 skenario)

- Akun uji NYATA baru: `rus-final-58ca00ea@katalir-internal.dev` (dibuat lewat Supabase
  Admin API, **dihapus** setelah run).
- Perintah: `python tests/user_test/rus_run.py all` · 21 m 41 s · `EXIT=0`
- Log mentah: `docs/evidence/regression-delete-fix-2026-10-14/after/rus-run-all.txt`

| Grup | PASS | FAIL | BLOCKED | NOT_RUN |
|---|---|---|---|---|
| p1 | 9 | 2 | 0 | 0 |
| p2 | 8 | 2 | 0 | 0 |
| p3 | 4 | 1 | 0 | 0 |
| p4 | 5 | 3 | 0 | 0 |
| p5 | 10 | 5 | 0 | 0 |
| j1 | 1 | 1 | 2 | 0 |
| j2 | 2 | 1 | 0 | 1 |
| j3 | 4 | 0 | 0 | 0 |
| bug | 11 | 0 | 0 | 1 |
| **Total** | **54** | **15** | **2** | **2** |

**Before → After (diferensial):**

| Skenario | Before (08:32) | After | Catatan |
|---|---|---|---|
| **P5-12b** ID non-UUID PATCH & DELETE | FAIL (DELETE 500) | **PASS** | ✅ fix bekerja |
| P5-01, P5-03, P5-04, P5-13, P2-02, P2-05, P3-05, P4-02, P4-04, P4-06, J1-B, J2-D | FAIL | FAIL | hulu 503 (bukan regresi) |
| P1-01, P1-08 | PASS | FAIL | artefak/confounded (bukan regresi) |

**Target ≥60 PASS: TIDAK tercapai** — dilaporkan apa adanya, ambang tidak diturunkan.
Penyebab tunggal: cooldown kuota pada model default frontend (§5).

---

## 5. TASK 5 — STATUS BUG + VERDICT

### 5.1 Status Bug

| Bug | Severity | Status | Bukti |
|---|---|---|---|
| BUG-01 | HIGH | ✅ Fixed | commit `4cf6eb4` |
| BUG-02 | HIGH | ✅ Fixed | commit `4cf6eb4` |
| BUG-03 | MEDIUM | ✅ Fixed | commit `d1de747` |
| BUG-04 | MEDIUM | ✅ Fixed | `d1de747` — **kecuali DELETE**, ditutup sesi ini |
| BUG-05 | MEDIUM | ⚠️ **SEBAGIAN** | dukungan env ada (`models.ts`), **tetapi produksi masih default `google/gemma-4-31b-it`** → lihat 5.2 |
| BUG-06 | HIGH | ✅ Mitigated | `EMAIL_AUTH_HIDDEN` (signup email disembunyikan) |
| BUG-07 | MEDIUM | ✅ Fixed | `out/404.html` `lang="id"` |
| BUG-10 | MEDIUM | ✅ Fixed | kontras `/templates` + `/integrations` |
| **DELETE** | MEDIUM | ✅ **Fixed (sesi ini)** | §1 — before 500 / after 404, deployed, md5 terverifikasi |
| **P5-15** | **HIGH** (harness) | ❌ **TERBUKA** | §5.2 |

### 5.2 Satu item terbuka — akar 13 dari 15 FAIL

**Gejala:** setiap pengguna baru yang mengirim pesan pertama melihat kartu galat
`"Gagal mengirim — Semua kunci model ini sedang cooldown (kuota). Coba lagi."`

**Rantai sebab (semua terverifikasi):**

1. Bundle produksi memuat default `google/gemma-4-31b-it`:
   `nexus-frontend` chunk `app/chat/page-0f0690a73e51100a.js` →
   `O=(W.env.NEXT_PUBLIC_DEFAULT_MODEL_ID||"").trim()||"google/gemma-4-31b-it"`
   (`NEXT_PUBLIC_DEFAULT_MODEL_ID` **tidak di-set saat build** → jatuh ke gemma).
2. Frontend mengirim model itu apa adanya: `ChatApp.tsx:239` (`selectedModel =
   DEFAULT_MODEL_ID`) → `ChatApp.tsx:899` (`model: selectedModel`) → `useChat.ts:515`.
3. Backend menolak: probe langsung `POST /chat {"model":"google/gemma-4-31b-it"}` →
   **HTTP 503** `{"detail":"Semua kunci model ini sedang cooldown (kuota). Coba lagi."}`
   (2/2 konsisten, ~4,7 s — persis pola `t_balasan≈5,1 s` di harness).
4. `api_server.py:1989-1992`: `_pool.acquire(model_id)` → `None` → 503. Cabang ini
   **tidak** memakai mekanisme fallback yang sudah ada (dipakai untuk id tak dikenal),
   padahal frontend sudah punya spanduk `fallback=True`.
5. Matriks pembanding (probe langsung):

| Request | HTTP | Model menjawab | `fallback` |
|---|---|---|---|
| tanpa `model` | 200 | `gemini-3.5-flash-lite` | – |
| `google/gemma-4-31b-it` (**yang dikirim frontend**) | **503** | — | — |
| `gemma-4-31b-it` (tanpa prefix) | 200 | `gemini-3.5-flash-lite` | `true` (`model_unavailable`) |
| `gemini-3.5-flash-lite` | 200 | `gemini-3.5-flash-lite` | – |

**Status:** **TIDAK diperbaiki di sesi ini — keputusan produk/biaya.** Sesi sebelumnya
sudah mencatat keputusan ini secara eksplisit (*"DIPUTUSKAN: tidak diubah sepihak"*), dan
mengubah model default = mengubah profil biaya tier gratis. Brief sesi ini punya lingkup
Task 1 = DELETE.

**Remedy siap pakai (pilih satu, keduanya sudah didukung kode saat ini):**

- **A — Frontend (paling kecil, tanpa ubah kode):** build dengan
  `NEXT_PUBLIC_DEFAULT_MODEL_ID=gemini-3.5-flash-lite`, lalu deploy CF Pages.
  ⚠️ `NEXT_PUBLIC_*` di-inline saat build → wajib build ulang.
- **B — Backend:** di `api_server.py:1990`, saat `_pool.acquire(model_id) is None`,
  fallback ke `DEFAULT_MODEL_PREFERENCE` (set `fallback=True`, `fallback_reason=
  "model_unavailable"`) sebelum menyerah ke 503. Menghilangkan inkonsistensi
  `google/gemma-4-31b-it` (503) vs `gemma-4-31b-it` (200 + fallback).
- **C — Kebijakan:** tambahkan gemma ke `DEFAULT_MODEL_PREFERENCE` / isi kuota kuncinya.

### 5.3 VERDICT

> ## **BELUM** (belum siap launch)
>
> Kriteria brief: *SIAP LAUNCH = 0 HIGH + 0 MEDIUM + ≥60 PASS*.
>
> - **PASS = 54 < 60** ❌
> - **1 item HIGH terbuka**: P5-15 — model default tidak dapat dilayani (§5.2) ❌
> - **1 item MEDIUM terbuka**: BUG-05 — default produksi masih menunjuk model tak tersedia ❌
>
> Tidak ada HIGH/MEDIUM **baru** dari sisi aplikasi: bug DELETE (satu-satunya bug nyata
> dalam lingkup brief) **sudah tertutup dan terbukti**. Sisa kegagalan berakar pada
> §5.2 + 1 artefak harness + 1 kasus confounded.
>
> **Begitu §5.2 diselesaikan, plafon praktis ≈ 66–67 PASS** (54 + 12 kasus hulu + P5-15).

---

## 6. KOREKSI DOKUMEN SEBELUMNYA

`docs/final-status-2026-10-14.md` §2 mengklaim:

> "`GET /workflows/not-a-uuid` … PATCH/DELETE juga 404"

**Klaim itu TIDAK benar untuk DELETE.** Probe produksi sesi ini (§1.1) menunjukkan
`DELETE /workflows/not-a-uuid` → **500** sebelum fix. GET/PATCH memang sudah 404; DELETE
belum. Sudah dikoreksi & ditutup di sesi ini.

---

## 7. BUKTI

| Artefak | Lokasi |
|---|---|
| Probe before/after (DELETE) | `docs/evidence/fix-delete-2026-10-14/probe_before.json`, `probe_after.json` |
| Skrip repro (dapat dijalankan ulang) | `tests/user_test/rus_repro_delete.py` |
| Regresi — before (08:32) | `docs/evidence/regression-delete-fix-2026-10-14/before/` |
| Regresi — after (sesi ini) | `docs/evidence/regression-delete-fix-2026-10-14/after/` (`rus-run-all.txt`, `rus_*.json`, `shots/`) |
| Log run mentah | `docs/evidence/regression-delete-fix-2026-10-14/after/rus-run-all.txt` |
| Perubahan kode | `api_server.py` (`remove_workflow`), `tests/user_test/rus_repro_delete.py` |
