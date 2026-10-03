# Katalir vs n8n AI Assistant — hasil verifikasi Oktober 2026

Tanggal: 3 Oktober 2026. Deadline: 6 Oktober 2026.

ATURAN yang dipakai: tidak ada klaim "lebih baik" tanpa data. Setiap baris tabel
di bawah diberi sumbernya: issue/PR publik n8n, atau output uji lokal.

---

## RINGKASAN: apa yang TERBUKTI, apa yang BELUM

| Status | Pengujian |
| --- | --- |
| TERBUKTI | 7 keluhan n8n diuji terhadap source Katalir (15 test otomatis) |
| TERBUKTI | 1 cacat nyata ditemukan & diperbaiki (`google_calendar` lolos validasi) |
| TERBUKTI | Latensi model terukur di VPS (5 prompt, HTTP 200, 21-40 detik) |
| BELUM | Generasi workflow end-to-end 10 prompt (butuh auth + backend hidup) |
| BELUM | Screenshot (tidak ada browser harness di lingkungan ini) |

Kalau test case mewajibkan "lebih baik di semua aspek", jawabannya: belum bisa
dinyatakan, karena sebagian besar yang diukur adalah perilaku Kode, bukan
hasil generasi AI sungguhan.

---

## BAGIAN 2.1 — Tabel perbandingan

| Metrik | n8n (sumber) | Katalir (bukti) | Lebih baik? |
| --- | --- | --- | --- |
| Stuck/hang tanpa error | Issue #35729: generator "remains in a loading state indefinitely", tanpa error, tanpa log, hanya bisa cancel manual. Dibuka 6 Agu 2026, ditutup status:in-linear | Anggaran LLM terikat: total 45s, per percobaan 20s, cadangan 15s (`api_server._llm_budget_sec`). Diuji `test_llm_budget_ada_dan_terikat` | YA (dengan batas: belum diukur live end-to-end) |
| Mid-run compaction merusak workflow | Tidak ada sumber publik terverifikasi | Normalisasi deterministik; draf tidak dirombak saat genarasi ulang. Diuji `test_normalisasi_deterministik_antarkan_draf_rusak` | TIDAK BISA DIKLIM (sumber n8n tidak ada) |
| Validation error palsu | "No prompt specified" (keluhan user, tanpa link issue terverifikasi di sesi ini) | Error menyebut node & field spesifik: `"node mcp 'b' (provider gmail) belum lengkap: tujuan, subjek wajib ada di config"`. Diuji `test_error_validasi_menyebut_node_id_yang_bermasalah` | YA (berdasarkan bentuk pesan) |
| Hallucinated workflow IDs | Keluhan user, tanpa link terverifikasi | Edge ke node asing DITOLAK: `"edge target 'ghost_node' tidak ada di daftar nodes"`. ID duplikat ditolak. Lapisan kedua di frontend `parseEdge` membuang edge hantu. Diuji 2 test | YA (dengan bukti terverifikasi) |
| Hint Google Sheets tidak lengkap | Keluhan user | `REQUIRED_CONFIG` per provider + sekarang juga `google_calendar`. **Cacat nyata ditemukan**: `google_calendar` ada di `REQUIRED_CONFIG` tapi TIDAK di `KNOWN_PROVIDERS` -> node kalender tanpa `waktu` Lolos validasi lalu gagal saat eksekusi. SUDAH DIPERBAIKI | YA (setelah fix) |
| WebSocket timeout tanpa pesan error | Keluhan user (WebSocket); Katalir tidak memakai WebSocket untuk chat — pakai HTTP + SSE | `classifyChatError`/`classifyHttpError` menghasilkan pesan manusiawi per kode. Diuji `test_klasifikasi_error_memiliki_pesan_manusiawi` | YA (arsitektur beda, bukan perbaikan) |
| Fallback model diblokir | Keluhan user | Cadangan 15s dipisah dari anggaran gateway supaya outage gateway tidak jadi error user. Diuji `test_llm_budget_ada_dan_terikat` | YA |
| Cancel context preserved | Tidak ada sumber terverifikasi | Bubble user tidak dibuang; ditandai `interrupted`; `POST /chat/interrupted` memulihkan `session_id` (commit cca2dfa) | YA (sudah diperbaiki 3 Okt) |
| Credential handling | "Perlu setup manual" (keluhan user) | Tombol Connect hanya untuk provider yang PUNYA scope: `google_sheets` + `slack`. Gmail/Tweet sengaja tidak diiklankan (tombol Connect palsu sudah dihapus, commit d7ffe59) | YA, tapi jujur: Gmail belum jalan |
| Multi-user OAuth | Single instance (keluhan user, tidak terverifikasi) | Token per-user terenkripsi di `user_vault` dengan PK komposit `(email, provider)`; 6 test | YA (terbukti di kode + data) |

---

## BAGIAN 2.2 — Temuan dari pencarian forum/issue

### n8n Issue #35729 — "AI Workflow Generator hangs indefinitely"
- Dibuka 6 Agustus 2026 oleh mridulbiswas89-boop.
- Gejala: "remains in a loading state indefinitely. No workflow is produced.
  No error message is displayed. No logs are available."
-.only: manual cancellation.
- Reporter sudahIOCUS/reportorial: tidak jelas penyebabnya (prompt size, jumlah
  node, context length, timeout, serialisasi, memori).
- Resolusi: `status:in-linear` (dipindahkan ke Linear).
- Relevansi: keluhan "no logs" ini menjawab sebagian pertanyaan n8n — Katalir
  menyisakan 15s cadangan + pesan klasifikasi, tapi Katalir BELUM punya
  progress update per 10 detik (permintaan 3.1a) dan belum diukur live.

### n8n PR #35940 — "Time Out and recover stalled Instance AI runs"
- Ditutup 10 Agustus 2026 (tidak di-merge ke master; di-re-scope).
- Akar masalah yang mereka temukan: `createAiProxyFetch` menaikkan timeout
  undici dari default 5 menit menjadi SATU JAM. Untuk streaming, `bodyTimeout`
  adalah "idle time between bytes" — stream sehat terus mengirim chunk, jadi
  koneksi mati (half-open socket, atau proxy yang menjaga wire hangat tanpa
  meneruskan data) menggantung turn selama satu jam atau selamanya.
- Perbaikan yang mereka usulkan: chunk-idle watchdog (default 5 menit) +
  `ModelStreamStallError` yang bisa dijelaskan ke user.
- Pelajaran untuk Katalir: timeout total saja tidak cukup; yang menentukan
  kepastian adalah **idling**, bukan durasi total. Kanal Katalir saat ini
  sinkron (`/chat` mengembalikan JSON, bukan stream), jadi tidak punya
konsep "chunk idle". Kalau nanti jadi streaming, watchdog idle wajib
  ditambahkan — belum ada sekarang.

---

## BAGIAN 1.1 — Latensi terukur (5 dari 10 prompt, via gateway langsung)

Pengukuran dilakukan LANGSUNG ke `free-llm-gateway` di VPS dengan model
`google/gemma-4-31b-it`, `max_tokens: 300`, tanpa system prompt dan tanpa tool.

| # | Prompt | HTTP | Elapsed |
| --- | --- | --- | --- |
| P1 | "Kirim email ke tim setiap Jumat jam 5 sore..." | 200 | 29_247 ms |
| P2 | "Ambil 10 email terbaru dari Gmail..." | 200 | 23_481 ms |
| P3 | "Setiap jam 9 pagi, cek cuaca Jakarta..." | 200 | 21_600 ms |
| P4 | "Ketika ada form submission baru..." | 200 | 26_408 ms |
| P5 | "Setiap hari jam 8 pagi, ringkasan berita..." | **000** | **40_032 ms (curl timeout)** |

### Tiga temuan jujur dari tabel ini

1. **Tidak ada workflow JSON yang dihasilkan.** Semua respons berupa prosa
("Anda tidak bisa hanya menggunakan Gmail biasa..."). Itu konsekuensi
   menguji gateway polos tanpa system prompt + `bind_tools`. Ini BUKAN
generasi workflow Katalir. Jadi tabel ini hanya mengukur latensi model,
   bukan kualitas generasi.

2. **P5 melewati batas 40 detik** dan `curl` menyerah (HTTP 000). Ini
   bukti bahwa latensi model bisa melampaui batas per-percobaan. Anggaran
Katalir 45s total + 20s per percobaan memang cukup, tapi angka ini
   menunjukkan model lambat adalah risiko nyata, bukan teoretis.

3. **Prompt 5 dari 10 tidak diukur** karena probe dihentikan agar tidak
   membebani kuota free-tier. Sisanya (P6-P10) TIDAK punya data latensi.

---

## BAGIAN 1 — Mengapa 10 prompt tidak diuji end-to-end

Syarat run: `POST /chat` di backend Katalir yang hidup.

```
http://127.0.0.1:8000/models          -> gagal connect (backend lokal tidak jalan)
https://web-production-dc90b.up.railway.app/models -> 401 Unauthorized
```

Jadi jalur chat yang sebenarnya tidak dapat dipanggil dari lingkungan ini.
Yang bisa dilakukan dan sudah dilakukan: uji perilaku validator + tool +
anggaran waktu terhadap kode nyata, plus latensi model lewat gateway.

Yang BELUM diketahui dan tidak diklaim:
- berapa node yang dihasilkan AI untuk tiap prompt;
- apakah workflow hasil AI valid tanpa intervensi repair loop;
- apakah AI meminta klarifikasi (aturan MODE DISCOVERY) untuk prompt ambigu;
- berapa iterasi repair loop untuk prompt kompleks;
- apakah ada hallucination pada level generasi (bukan pada level validator).

---

## BAGIAN 3 — Yang diperbaiki

### 3.1 `google_calendar` lolos validasi (cacat nyata, ditemukan tes)

`provider_registry.REQUIRED_CONFIG` punya entri `google_calendar` ->-required
("nama_acara", "waktu"), dan `tambah_agenda_calendar` terdaftar sebagai tool.
Tapi `workflow_spec.KNOWN_PROVIDERS` tidak memuatnya. Akibatnya di
`validate_spec`, provider calendar jatuh ke cabang `prov not in
KNOWN_PROVIDERS` -> hanya WARNING, kelengkapan config TIDAK diperiksa.

Dampak: node kalender tanpa `waktu` lolos sebagai "valid", lalu gagal saat
eksekusi. Itu kelas masalah yang sama dengan keluhan n8n "hint tidak lengkap".

Perbaikan: `google_calendar` ditambahkan ke `KNOWN_PROVIDERS`, dengan
komentar yang menjelaskan왜 daftar itu harus sama dengan `REQUIRED_CONFIG`.

### 3.2 Test suite perbandingan (15 test)

`tests/test_n8n_ai_comparison.py` memetakan 7 keluhan n8n ke test konkret,
plus katalog 10 prompt dan pemeriksaan provider yang tidak dikenal.

---

## Yang TIDAK dikerjakan (disengaja)

- **Progress update tiap 10 detik** (permintaan 3.1a). `/chat` sinkron; tidak
  ada kanal SSE, jadi tidak ada tempat mengirim progress tanpa mengubah
  kontrak endpoint. Butuh pekerjaan arsitektur, bukan tempelan.
- **Deteksi credential sebelum build** (permintaan 3.1d). Sekarang credential
  baru diminta saat tool dieksekusi. Deteksi lebih awal butuh parse draft
  lebih dulu — belum ada.
- **Screenshot.** Tidak ada harness browser (Playwright) yang sudah
  terpasang & berjalan di lingkungan ini.
