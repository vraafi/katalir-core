# Audit final interaksi UI/UX — FASE 0-5 (rekap terukur)

Tanggal: 2026-09-24. Branch `level-3-experiment`.

Sumber angka: `docs/audit/uiux-interactions.md` (FASE 0-3),
`docs/audit/fase4-interactions.md` (FASE 4), `docs/audit/fase5-ai-surfaces.md`
(FASE 5), `docs/audit/fase3-verification.md` + `docs/audit/fase5-verification.md`
(bukti pendukung). Semua baris PASS punya angka yang bisa dibaca ulang dari
output tes — bukan "kelihatannya bekerja".

## Rekap per fase

| Fase | Item | PASS | Bukti utama |
|---|---|---|---|
| FASE 0-2 | Chat, shell, i18n, palette/shortcut, sidebar/lifecycle | 15 | `PERSIST_OK 3/3`, `ID_EN_PASS`, `HYDR=0` 12/12, lifecycle spec hijau |
| FASE 3 | Kanvas (14 interaksi) + sistem visual | 24 | `24/24 PASS` (`canvas-fase3` 14 + `canvas-theme` 10) |
| FASE 4 | Settings/Billing/Help + auth/i18n | 10 | `fase4-pages.spec.ts` (S1-S4, B1-B3, H1-H2, A1-A2) + `fase4-a11y` 9 |
| FASE 5 | Permukaan AI-native + onboarding + microcopy | 9 | `fase5-ai-surfaces.spec.ts` 9/9 (B1-B6) |
| FASE 5 (a11y) | Tautan lewati-konten + landmark + Lighthouse | 23 | `fase5-a11y.spec.ts` 23/23; Lighthouse 100×10 |
| **Total** | | **81** | |

## 10 interaksi FASE 4 (yang diminta misi) — semua PASS

| # | Interaksi | Status | Angka |
|---|---|---|---|
| S1 | Isi form → save → "Tersimpan" | PASS | `vault-status` memuat `Tersimpan`; daftar server +1 |
| S2 | Hapus kredensial → hilang | PASS | daftar server −1 (poll 10×1 detik) |
| S3 | Validasi error → pesan jelas | PASS | key kosong tidak menambah entri; status tetap |
| S4 | Ganti bahasa ID ↔ EN → persist | PASS | `ID_EN_PASS`; tanpa hydration error |
| B1 | Kartu pemakaian render (bar/empty) | PASS | `bars` atau empty-state jujur (tanpa data dummy) |
| B2 | Plan comparison → checkout Dodo | PASS | 5 baris; `href` checkout nyata |
| B3 | Riwayat invoice | PASS | empty-state jujur "belum ada invoice" |
| H1 | Pencarian FAQ menyaring + mengumumkan | PASS | `all=7 narrowed=1 countText="1 results"` |
| H2 | Sidebar navigasi + cheat sheet | PASS | 10 pintasan nyata terdaftar |
| A1/A2 | Auth: sesi bertahan / logout bersih | PASS | email sama setelah reload; `data-auth=out` |

## Modul terkait (dependency graph)

| Modul | Diuji oleh | Bukti |
|---|---|---|
| Chat ↔ session store | `fase4-pages` A1, `hydration`, `chat-auth` | sesi bertahan; `HYDRATION_HITS=0` |
| Vault (Fernet) | `fase4-pages` S1-S4 + `pytest tests` | round-trip + cabut; 136 pytest |
| Kanvas ↔ workflow store | `canvas-fase3` C10-C14, `builder-*` | save → reload identik; 4→5 node |
| AuthProvider (semua rute) | `routes-no-crash` 6 rute + `fase5-a11y` | 6/6 tanpa crash; axe `[]` |
| i18n (semua rute) | `fase4-pages` A3, `fase5-ai-surfaces` B6 | EN: `Connect Telegram`, tanpa sisa teks ID |

## Catatan apa adanya

* `model-filter BUG 1` masih merah karena **roster upstream** tidak menyediakan
  model berkuota besar pada saat pengukuran (`MODELS_COUNT=9`,
  `FORBIDDEN_HITS=[]` — filternya sendiri bersih). Ini kondisi lingkungan, bukan
  regresi UI; `BUG 2` dan `VALID` lulus.
* Empat interaksi ChainOfThought (B4) baru diuji pada **desktop** (default
  tertutup). Perilaku "terbuka di mobile" diverifikasi lewat kode (matchMedia)
  tetapi belum lewat tes pada device emulation — dicatat sebagai utang kecil,
  bukan PASS diam-diam.
* Audit mobile FASE 6 menemukan target sentuh < 44 px di banyak kontrol
  (28-42 px) dan itu **sudah diperbaiki** (aturan `pointer: coarse`), lalu diukur
  ulang: `tooSmall=0` di 18 kombinasi halaman×device.
