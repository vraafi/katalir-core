# FASE 5 — Permukaan AI-native + Onboarding + Microcopy (verifikasi)

Tanggal: 2026-09-24. Branch `level-3-experiment`. Harness: **dev**
(`playwright.dev.config.ts`, FE `:3000` + BE `:8000`).

> Catatan penomoran: dokumen `fase5-verification.md` adalah pekerjaan a11y +
> migration + hutang FASE 4. Dokumen INI adalah FASE 5 versi misi overhaul
> (B1-B6: permukaan AI-native, onboarding, microcopy).

## 1. Deliverable & hasil

| # | Deliverable | Status | Bukti terukur |
|---|---|---|---|
| B1 | Draf workflow dari AI → pesan inline + tombol "Buka di Kanvas" / "Jalankan Langsung" | **PASS** | `DRAFT_CARD=nodes:2 edges:1`; kartu **tidak** di dalam `[role=dialog]`; klik "Buka di Kanvas" → URL `/builder` dan `CANVAS_NODES_FROM_DRAFT=2` (draf benar-benar termuat ke kanvas) |
| B2 | Laporan eksekusi → kartu terstruktur (bukan teks polos) | **PASS** | `REPORT_STATUS=success STEPS=2` + row per node `OK trigger-1`, `OK mcp-1` + durasi `2.3 detik` + footer "Lihat di Kanvas"/"Jalankan Ulang" (`NAV_AFTER_REPORT_OPEN=/builder`); teks laporan backend tetap di DOM (`Laporan lengkap`) |
| B3 | Permintaan kredensial → form inline di bubble | **PASS** | `CRED_INLINE=provider:telegram modal:false` (bukan modal); tombol simpan disabled saat kosong → enabled setelah diisi; submit menyimpan ke Brankas lalu **mengirim ulang** prompt (`CHAT_POSTS_AFTER_CRED=2`) |
| B4 | ChainOfThought collapsible | **PASS** | default desktop `aria-expanded=false` + isi tidak dirender (`COT_DEFAULT=collapsed_desktop`); klik → `true` + isi tampil; klik lagi → `false`; **jawaban final bersih** dari blok penalaran; tidak muncul sama sekali bila model tidak mengirim penalaran (`COT_ABSENT_WHEN_NO_REASONING=true`) |
| B5 | Onboarding 3 langkah + skip + persist | **PASS** | 3 langkah berurutan (`data-step` 0→2, tiap langkah punya `onboarding-step-N`), tombol Lewati ADA di setiap langkah; selesai → localStorage `done` + `PREFS_PUTS=1` berisi `onboardingCompleted`; reload → tidak muncul lagi; "Lewati" → localStorage `skipped` + tetap tidak muncul |
| B6 | Microcopy konsisten (ID/EN) | **PASS** | locale EN → `CRED_TITLE_EN=Connect Telegram` (tidak ada sisa "Hubungkan"); string ID hardcode di kartu kredensial + kartu error + badge antrean dihapus, semua lewat i18n |

Ringkas: `tests/fase5-ai-surfaces.spec.ts` → **9/9 PASS**.

## 2. Cara angka diperoleh (dan kenapa deterministik)

Spec FASE 5 **meng-stub jaringan** (`page.route` pada origin API) sehingga tidak
bergantung kuota LLM harian. Bentuk payload yang diuji tetap bentuk KONTRAK
backend: `meta.workflow`, `{status:"needs_credential", provider}`, dan
`{execution, logs, report}` dari `GET /executions/{id}`. Jadi yang diuji adalah
RENDER + INTERAKSI milik kita di atas data yang sah, bukan kualitas jawaban model.

```
cd nexus-frontend
npx playwright test -c playwright.dev.config.ts tests/fase5-ai-surfaces.spec.ts
# screenshot: test-results/fase5-ai/*.png (8 berkas; folder test-results di-gitignore)
```

Screenshot: `b1_draft_inline.png`, `b2_report_card.png`, `b3_credential_inline.png`,
`b4_chain_of_thought.png`, `b5_onboarding_step{1,2,3}.png`, `b6_microcopy_en.png`.
Verifikasi visual dilakukan pada `b2_report_card.png` (kartu draf + kartu laporan
terlihat lengkap, tombol disabled saat eksekusi masih berjalan).

## 3. Regresi yang DITEMUKAN oleh regression suite (dan diperbaiki)

Full dev suite setelah fitur ini: **83 passed / 7 failed**. Ketujuh kegagalan
BUKAN pada spec baru, melainkan pada spec lama:

| Spec lama yang gagal | Gejala | Sebab |
|---|---|---|
| `fase4-pages` A2 (auth logout) | 1.5 menit timeout saat klik menu akun | dialog onboarding `fixed inset-0 z-50` menutupi header |
| `model-filter` BUG 2 + VALID | timeout saat klik `composer-send` | overlay yang sama menutupi composer |
| `fase4-pages` S3, S4, B1 | timeout / skeleton tak selesai | spec membuka `/` lebih dulu (helper `openPage`) → overlay menghalangi navigasi berikutnya |

**Akar masalah (bukan "flaky")**: definisi "user baru" saya hanya
"belum menandai onboarding selesai". Akibatnya user yang JELAS sudah memakai
aplikasi (punya banyak riwayat chat) tetap diberi dialog modal penuh layar.

**Perbaikan**: user baru = **TANPA riwayat chat** DAN belum menandai selesai.
`OnboardingFlow` menerima `historyKnown`/`hasHistory` dari halaman (query
`/sessions`), dan tidak merender apa pun sampai riwayat diketahui (tidak ada
kilatan dialog untuk user lama). Dikunci oleh tes baru:
`B5 onboarding: TIDAK muncul untuk user yang sudah punya riwayat chat`
(`ONB_HIDDEN_FOR_EXISTING_USER=true header_clickable=true`).

Bukti setelah perbaikan: `fase5-ai-surfaces + fase4-pages + model-filter` →
**26 passed / 1 failed**, dan satu-satunya yang merah adalah
`model-filter BUG 1` yang sudah lama merah karena roster upstream tidak
menyediakan model berkuota besar (`MODELS_COUNT=9`, `FORBIDDEN_HITS=[]`).

## 4. Batas jujur

1. **ChainOfThought belum mengukur "streaming"**: animasi buka/tutup halus
   (200 ms), tetapi penalaran tetap muncul sebagai satu blok karena backend
   tidak mengirim token penalaran secara bertahap. Yang dijamin: penalaran
   ditampilkan bila ada, dan TIDAK dikarang bila tidak ada.
2. **B4 bergantung pada delimiter model** (`<thinking>`, `<reasoning>`,
   ` ```think `). Bila provider mengirim penalaran tanpa pembungkus, teks itu
   tampil sebagai bagian jawaban biasa. Bukan bug fatal, tetapi artinya
   "penalaran rapi" hanya berlaku untuk model yang membungkusnya.
3. **Banner lama `ai-workflow-notice` masih ada** di atas composer ("Workflow
   dari AI sudah siap di kanvas"). Ia dipertahankan karena E2E Level 3 S1
   meng-assert `[data-testid="ai-workflow-notice"]`; menghapusnya akan merusak
   bukti Level 3. Duplikasi kecil dengan kartu baru dicatat sebagai utang.
4. **Onboarding memakai `/preferences`** (tabel `user_preferences` dari FASE 4).
   Bila endpoint itu gagal total (offline), status tetap tersimpan lokal dan
   dialog tidak muncul lagi di perangkat itu — tetapi tidak pindah perangkat.
5. **Belum ada tes unit** untuk `buildExecutionReport` (logika)
   dan `splitReasoning`; keduanya saat ini hanya diuji lewat E2E. Kalau mau
   cepat, dua fungsi itu kandidat terbaik untuk tes unit tanpa browser.

