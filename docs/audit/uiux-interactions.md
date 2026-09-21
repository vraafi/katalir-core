# Audit interaksi UI/UX — status AWAL (FASE 0, 2026-09-21)

Sumber: screenshot Playwright 12 file (`%TEMP%/uiux_f0/shots_{desktop,mobile}_*.png`)
+ hitung programatik (pageerror, target <44px). Semua tanpa sesi (logged-out).
Legenda: PASS = bukti kuantitatif hijau; FAIL = terukur rusak; UNKNOWN = butuh sesi.

## Ringkasan ukur
- pageerror desktop+mobile 12/12 halaman = 0.
- Elemen <44px: / =8, /chat=8, /settings=7-9, /billing=4, /help=4, /builder=10
  (angka = termasuk ikon kecil/zoom control — diverifikasi per-halaman di FASE 1).

## Canvas (14)
| # | Interaksi | Status | Bukti/catatan |
|---|---|---|---|
| C1 | Drag palette -> titik drop | PASS (dipertahankan) | spec builder-drop-position 2 passed (sesi lalu) |
| C2 | Click-to-place | UNKNOWN | belum diukur sesi ini |
| C3 | Drag node existing | UNKNOWN | butuh sesi builder |
| C4 | Delete node | UNKNOWN | — |
| C5 | Connect handle | UNKNOWN | — |
| C6 | Delete edge | UNKNOWN | — |
| C7 | Pan | UNKNOWN | — |
| C8 | Zoom | UNKNOWN | — |
| C9 | Minimap konsisten | PASS (dipertahankan) | bukti sesi drop-fix |
| C10 | Save->reload persist | PASS (dipertahankan) | PERSIST_OK 3/3 sesi lalu |
| C11 | Undo/redo | UNKNOWN | cek apakah ada fitur ini |
| C12 | Mobile tap node -> panel | FAIL (dugaan) | target kecil di builder=10; ukur ulang dgn sesi |
| C13 | Mobile long-press menu | UNKNOWN | coba CDP touch, Playwright touch, manual |
| C14 | Bottom-sheet palette | FAIL | saat ini sidebar sempit, bukan sheet |

## Chat (7)
| # | Interaksi | Status | Bukti/catatan |
|---|---|---|---|
| H1 | Kirim->stream | UNKNOWN | butuh sesi + kuota LLM |
| H2 | Cancel streaming | UNKNOWN | — |
| H3 | Copy message | UNKNOWN | — |
| H4 | Reload/edit | UNKNOWN | — |
| H5 | Error manusiawi+retry | UNKNOWN | — |
| H6 | Empty state | PASS | screenshot root: ilustrasi + 3 CTA render |
| H7 | Mobile keyboard | UNKNOWN | ukur dvh/composer di FASE 2 |

## Settings/Vault (4): S1 form save UNKNOWN · S2 hapus UNKNOWN ·
## S3 validasi UNKNOWN · S4 ganti bahasa PASS (ID_EN_PASS true sesi i18n)
## Billing (3): B1 usage card UNKNOWN · B2 upgrade link PASS (href Dodo
## terverifikasi sesi lalu) · B3 invoice empty-state PASS (screenshot)
## Auth+i18n (3): A1 login UNKNOWN · A2 logout UNKNOWN · A3 switch bahasa
## tanpa hydration error PASS (12/12 HYDR=0 sesi hydration-fix)
## Palette+shortcut (3): P1 Cmd+K FAIL (belum ada) · P2 Enter FAIL ·
## P3 Esc UNKNOWN
## Sidebar/lifecycle (5): L1 create PASS · L2 save-update PASS · L3 rename
## PASS · L4 delete PASS · L5 restore PASS (sesi lifecycle 28be291 + spec hijau)
