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

---

# UPDATE FASE 3 (2026-09-22) — canvas rebuild + multi-tema + mobile

Sumber: `tests/canvas-fase3.spec.ts` (14 interaksi) + `tests/canvas-theme.spec.ts`
(10 sistem visual) + `scripts/fase3-shots.mjs` (angka) di harness dev
(`playwright.dev.config.ts`, port 3000). **24/24 PASS** — rincian & bukti angka di
`docs/audit/fase3-verification.md`.

| # | Interaksi | Status FASE 0 | Status FASE 3 | Bukti |
|---|---|---|---|---|
| C1 | Drag palette → titik drop | PASS | **PASS** | pusat node ≤15px dari titik drop |
| C2 | Click-to-place | UNKNOWN | **PASS** | node +1, `data-kind` benar |
| C3 | Drag node | UNKNOWN | **PASS** | delta layar (120,98) = target |
| C4 | Delete node | UNKNOWN | **PASS** | node −1 + edge menempel −1 |
| C5 | Connect handle | UNKNOWN | **PASS** | `connectingto=1`, edge 3 → 4, tipe `flow` |
| C6 | Delete edge | UNKNOWN | **PASS** | edge −1, node tetap |
| C7 | Pan | UNKNOWN | **PASS** | viewport transform berubah |
| C8 | Zoom | UNKNOWN | **PASS** | skala 1 → 1.2 → 1 |
| C9 | Minimap konsisten | PASS | **PASS** | 4 node = 4 titik minimap |
| C10 | Save → reload persist | PASS | **PASS** | ID tersimpan, reload node/edge identik |
| C11 | Undo/redo | UNKNOWN (fitur belum ada) | **PASS** | tombol + Ctrl/Cmd+Z, riwayat 50 langkah |
| C12 | Mobile tap node → panel | FAIL (dugaan) | **PASS** | Sheet konfigurasi + `?n=<id>` |
| C13 | Mobile long-press | UNKNOWN | **PASS** | CDP touch: `data-armed=true` + menu |
| C14 | Bottom-sheet palette | FAIL (sidebar sempit) | **PASS** | drag-up membuka sheet, node +1 |

Tambahan FASE 3 (di luar 14): 4 tema + switcher + persist · status node 4 state
(dot/glow/indicator resmi) · Auto Layout dagre · edge animasi saat data mengalir ·
empty state + CTA.

**Catatan penting**: angka "elemen <44px" di ringkasan FASE 0 (builder=10) sekarang
**0** pada toolbar kanvas di perangkat sentuh (`@media (pointer: coarse)` → 44×44),
terukur di C14: 10 tombol, `tooSmall=0`.

