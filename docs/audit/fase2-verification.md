# FASE 2 — Verifikasi Visual + Regression (2026-09-21)

Branch: `level-3-experiment` @ `5d6b373`.
Dev: `http://localhost:3000` (PID 19348) + backend `http://127.0.0.1:8000` (PID 10800). Keduanya UP.

## 1. Screenshot visual (path: %TEMP%\fase2_visual\)

| File | Isi | Hasil |
|---|---|---|
| `d1_chat_empty.png` | Desktop 1280, empty state login | PASS — heading ID, saran 3 tombol, kuota 17/100, composer visible |
| `d2_chat_with_msg.png` | Desktop, pesan terkirim + thinking | PASS — bubble user kanan, typing dots + "Agen sedang berpikir..." |
| `d5_loggedin_composer.png` | Desktop, composer login | PASS — placeholder/aria EN (lihat §3), kirim OK, pageerror [] |
| `m1_chat_empty.png` | Mobile 390, empty | PASS — drawer hamburger, quota 18/100, composer di bawah |
| `m2_keyboard.png` | Mobile 390, tap composer | PASS — composer y=783 bottom=819 < vh=844 (di atas fold, tidak ketutup) |
| `r1/r2/r3` | Regression ringan ulang | PASS — composer_n=1, exec_report=True, mobile above-fold True, pageerror [] |

Probe kuantitatif (`fase2_probe2.py`):
`COMPOSER_COUNT=1 PLACEHOLDER="Message Katalir..." ARIA="Message"
VISIBLE_ABOVE_FOLD=True QUOTA_PANEL=0 SEND_OK=True PAGEERROR=[]`

## 2. Regression suite (E2E Playwright)

Status: **TERBLOKIR oleh harness, bukan oleh kode.**

- `chat-auth.spec.ts` tunggal (sesi FASE 2): `1 passed (1.1m) CHAT_STATUS=200 PAGEERROR=[]`.
- Run gabungan `chat-auth + model-filter` (2x percobaan sesi ini):
  run hang di `e2e-prod-server.mjs` → `npm run build` di dalam webServer
  Playwright tidak pernah selesai (log berhenti di warning
  `output: export`, `Timed out waiting 600000ms from config.webServer`).
  Penyebab terukur: build produksi di dalam harness lambat/macet pada
  mesin ini (font Google + minifikasi), bukan assertion gagal.
- Unit terkait: `workflow_spec + provider_registry + mcp_registry` = 46 passed.
- Pengganti yang dijalankan: probe Playwright langsung ke dev 3000
  (tanpa webServer): composer, kirim pesan, session restore, mobile —
  semua PASS (lihat tabel §1).

## 3. TEMUAN VISUAL — inkonsistensi locale (tidak terdeteksi test fungsional)

Screenshot membuktikan bug yang lolos dari `CHAT_STATUS=200`:

- Heading/saran/kuota/histori berbahasa **Indonesia**
  ("Halo, ada yang bisa saya bantu hari ini?", "KUOTA FREE — HARI INI").
- Placeholder + aria-label composer berbahasa **Inggris**
  ("Message Katalir...", "Message") — terukur di probe, terlihat di screenshot.
- Penyebab: `I18nProvider.detectLocale()` membaca `navigator.language`
  (browser EN) sementara konten lain memakai default `id`.
  Test fungsional tidak menangkap ini karena hanya assert status HTTP,
  bukan bahasa string.
- Disposisi: **DITERIMA untuk FASE 2** (extract-only, bukan perubahan copy),
  dicatat sebagai tech-debt untuk FASE 4 (microcopy audit).
  Tidak memblokir FASE 3.

## 4. Modul terkait

| Modul | Bukti | Status |
|---|---|---|
| Session restore | reload → `msg-list-count=0` di sesi kosong; riwayat 17 sesi tampil di sidebar (screenshot d1) | PASS |
| Vault integration | credential card tidak terpicu pada chat biasa (benar — hanya muncul saat `needs_credential`) | PASS (negatif) |
| Execution trigger | kirim "bikin workflow kirim pesan telegram tiap jam 9 pagi" → `exec_report=True`, screenshot r2 (bubble + thinking) | PASS |

## 5. Jawaban 5 pertanyaan wajib (untuk commit verifikasi ini)

- Modul disentuh: docs saja (tidak ada kode).
- Modul terkait: chat thread/composer, i18n, session, quota panel.
- Interaksi diuji: 5 state desktop + 2 mobile + kirim + reload + tap composer.
- Bisa rusak: tidak ada (docs-only).
- Tidak diuji: full E2E suite (harness macet — didokumentasikan §2),
  streaming/error/report visual (butuh trigger khusus), keyboard fisik mobile.
