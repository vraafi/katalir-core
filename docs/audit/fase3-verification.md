# FASE 3 — Verifikasi (canvas rebuild + multi-theme + mobile)

Tanggal: 2026-09-22. Branch `level-3-experiment`. Harness: **dev** (`localhost:3000`
+ backend `127.0.0.1:8000`), config `nexus-frontend/playwright.dev.config.ts`.

## 1. Hasil ringkas

| Ukuran | Nilai |
|---|---|
| Spec FASE 3 (baru) | **24/24 PASS** (2.7 menit) — `tests/canvas-fase3.spec.ts` (14 interaksi) + `tests/canvas-theme.spec.ts` (10 sistem visual) |
| Interaksi kanvas | **14/14 PASS** |
| Rute tanpa crash | **6/6 PASS** (`routes-no-crash.spec.ts`: /, /chat, /settings, /billing, /help, /builder) |
| model-filter E2E | **BLOCKED (0/3)** — lihat §5 |
| `npx tsc --noEmit` | **0 error** |
| `npm run build` | **SUCCESS** (11/11 halaman statis, `/builder` 30.9 kB / 381 kB First Load) |
| `pytest tests` | **136 passed** |
| `pytest test_model_filter.py` (root) | **PASS** (filter logika benar di level unit) |
| Screenshot | **43 file** → 12 di antaranya wajib (3 state × 4 tema) |

Perintah reproduksi:

```powershell
cd nexus-frontend
npx playwright test -c playwright.dev.config.ts          # 24 spec FASE 3
npx playwright test -c playwright.dev.config.ts --grep "routes-no-crash|model"
node scripts/fase3-shots.mjs                              # screenshot + angka
node scripts/fase3-audit.mjs after                        # audit metrik
```

## 2. Tabel audit 14 interaksi (bukti kuantitatif)

| # | Interaksi | Status | Bukti terukur |
|---|---|---|---|
| C1 | Drag palette → titik drop | PASS | node mendarat dengan `|dx|,|dy| ≤ 15px` dari titik drop (log: `DROP … center=…`) |
| C2 | Click-to-place | PASS | jumlah node tepat +1; kartu baru `data-kind="mcp"` terlihat |
| C3 | Drag node | PASS | delta layar **=(120,98)** vs target (120,98) → mengikuti pointer (toleransi 30px) |
| C4 | Delete node | PASS | node −1 **dan** edge yang menempel ikut −1 |
| C5 | Connect handle | PASS | `connectingto=1` (handle target menyala) dan edge **3 → 4**, tipe `flow` |
| C6 | Delete edge | PASS | edge 3 → 2, node tetap 4 |
| C7 | Pan | PASS | viewport `translate(0px,0px)` → `translate(160px,-100px)` |
| C8 | Zoom | PASS | skala `1 → 1.2 → 1` (kembali ke skala awal) |
| C9 | Minimap | PASS | `nodes=4 minimapNodes=4`, 4 posisi berbeda |
| C10 | Save → reload | PASS | `Alert: Alur disimpan! ID: <uuid>`; reload `?w=<id>` → node 4→4, edge 3→3 (data uji dihapus setelah tes) |
| C11 | Undo/Redo | PASS | hapus (−1) → undo (kembali) → redo (−1) → **Ctrl+Z** (kembali) |
| C12 | Mobile tap node → panel | PASS | `[role=dialog]` muncul, `?n=demo-trigger`, `.k-config-host` terlihat, aside desktop TIDAK terlihat |
| C13 | Mobile long-press | PASS | via **CDP `Input.dispatchTouchEvent`**: `data-armed=true`, menu konteks muncul (1); sentuhan 120ms → tetap `false` |
| C14 | Bottom-sheet palette | PASS | drag-up membuka sheet, node 4 → 5; tombol toolbar mobile **44×44** (10 tombol, 0 di bawah 44px) |

## 3. Sistem visual (10 spec tambahan)

| Aspek | Status | Bukti terukur (computed style & DOM) |
|---|---|---|
| Tema Midnight | PASS | canvas `rgb(27,31,35)`, node `rgb(40,46,54)`, edge `rgb(92,157,245)`, edge mengalir `rgb(139,92,246)`, accent `#6366f1` |
| Tema Daylight | PASS | canvas `rgb(250,250,248)`, node `#fff`, edge `rgb(99,102,241)` |
| Tema Cyberpunk | PASS | canvas `rgb(10,10,15)`, node `rgb(26,26,46)`, edge `rgb(0,255,213)`, edge mengalir `rgb(255,46,99)` |
| Tema Minimal | PASS | canvas `#fff`, node `rgb(245,245,245)`, edge `rgb(161,161,170)` |
| Theme switcher | PASS | 4 preview dengan latar = canvasBg tiap tema; memilih Cyberpunk → token berubah, `localStorage["katalir.canvasTheme"]="cyberpunk"`, reload tanpa param → tetap Cyberpunk |
| Status node | PASS | initial: `rgb(139,144,154)` tanpa glow; loading: amber + `pulse=true` + animasi `node-executing-glow` + `node-status-loading`; success: glow `rgb(38,189,115) 0 0 8px` + `node-status-success`; error: glow `rgb(245,92,92) 0 0 8px` + `node-status-error` |
| Status tidak di-reset | PASS | tanpa eksekusi, keempat status contoh bertahan (`["error","initial","loading","success"]`) |
| Auto Layout (dagre) | PASS | 4 node bergerak; kolom trigger/agent sejajar (Δ≤2px); parent terpusat di antara 2 anak (Δ≤2px); jarak antar-rank **196 / 212** vs nominal **204** (toleransi 24); **0 node menumpuk** |
| Edge animasi | PASS | total 3 edge, 1 mengalir: `dash 8px,4px`, `animation edge-flow`, stroke = warna animasi tema; 2 edge diam tanpa animasi |
| Empty state | PASS | ilustrasi + 2 CTA; CTA "Tambah Node" → 1 node (`trigger-101`), empty state hilang; undo → kosong lagi → "Muat contoh" → 4 node + 3 edge |

## 4. Bug nyata yang ditemukan fase ini (dan diperbaiki)

Semuanya ditemukan oleh tes/alat ukur, bukan oleh pembacaan kode.

| # | Gejala | Akar masalah | Perbaikan | Bukti |
|---|---|---|---|---|
| B1 | Klik tombol "Hapus node"/toolbar node tidak pernah sampai; tes melaporkan `header intercepts pointer events` | `builder-inner` memakai `h-[100dvh]` di dalam Shell yang merender header **sticky z-10**; kanvas meluber ke bawah header sehingga ~56px atas kanvas tertutup | wrapper kanvas jadi `flex-1 min-h-0` (mengisi SISA ruang di bawah header) | C4 & C11 PASS (sebelumnya timeout 1,8 menit) |
| B2 | Semua request backend gagal `Failed to parse URL from http://127.0.0.1:8000 /workflows` | dev server dijalankan `set VAR=value && npm run dev` tanpa kutip → nilai env mengandung **spasi di akhir** | jalankan dengan `set "VAR=value"` | C10 PASS: `Alur disimpan! ID: <uuid>` |
| B3 | Node contoh tidak bisa diklik/digeser (klik mendarat di tombol toolbar) | toolbar kanvas `flex-wrap` → membungkus jadi 2 baris 344×122 px menutupi area besar; contoh diposisikan tepat di bawahnya | toolbar `flex-nowrap` (607×46, satu baris) + koordinat contoh digeser keluar area toolbar | C3 PASS (delta (120,98)) |
| B4 | Status contoh hilang; edge yang mengalir tidak beranimasi | efek pemetaan status menulis "semua initial" karena belum ada eksekusi | guard: lewati pemetaan bila belum ada eksekusi (`exec.status===null && logs kosong`) | spec status PASS (`dots`, `anim` terukur) |
| B5 | `?demo=1` kadang ditimpa workflow tersimpan di tengah interaksi | race: `useQueryState` baru menyediakan `demo` setelah mount, sementara query daftar workflow sudah jalan | `if (demoRequested) return;` di efek pemuatan workflow | C5 PASS (`edges 3 → 4`) |
| B6 | `Delete` tidak menghapus edge di Windows | default React Flow v12 `deleteKeyCode='Backspace'` | `deleteKeyCode={["Delete","Backspace"]}` | C6 PASS (probe: edge terseleksi=1, Delete → −1) |
| B7 | Klik pada elemen "sudah terlihat" diblokir (kasus C6) | path edge yang terlihat tertutup `.react-flow__edge-interaction` | tes menargetkan path interaksi (elemen yang memang disediakan untuk klik) | C6 PASS |
| B8 | Klik CTA empty state tidak berefek tanpa error apa pun | markup hasil render server terlihat identik dengan yang sudah dihidrasi → klik terjadi SEBELUM handler React terpasang | `HydrationReady` menulis `data-hydrated="true"` di `<html>`; spec menunggu marker itu | empty-state PASS (`counts=[1]`, `trigger-101`) |
| B9 | Handle node tidak bisa diklik di dalam suite tetapi bisa di luar suite | `devices["Desktop Chrome"]` membawa viewport 1280×720 dan `use` tingkat **project menang** atas `use` config → node contoh terjepit di luar viewport (`elementFromPoint` → `null`) | `viewport` ditulis eksplisit di level project (1440×900) | C5 PASS (`topAtSrc`/`topAtDst` = handle) |

Bug **B1, B3, B5, B6 bersifat produk** (bukan tes): B1 membuat node di dekat atas
kanvas tidak bisa dihapus, B3 membuat node di bawah toolbar tidak bisa digeser,
B5 membuat `?demo=1` kehilangan intent URL-nya, B6 membuat pengguna Windows tidak
bisa menghapus edge dengan `Delete`. B7/B8/B9 adalah cacat harness yang juga
diperbaiki (B8 menambah marker hidrasi yang bisa diamati tes).


## 5. Regresi

### 5.1 Rute (6/6 PASS)

`routes-no-crash.spec.ts` — tanpa sesi, `pageerror` harus 0 di keenam rute:
`/`, `/chat`, `/settings`, `/billing`, `/help`, `/builder` → **6 passed**.
`/builder` lulus setelah rebuild kanvas (penting: ~2.900 baris CSS/TS baru tidak
boleh membuat rute crash).

### 5.2 model-filter — BLOCKED (0/3), dengan penjelasan

**Masalah lama (handoff §F.3) SUDAH TIDAK ADA.** Handoff mencatat `model-filter 0/3`
karena `storageState` ditulis untuk `localhost:E2E_PORT` sementara app membaca `:3000`.
Dengan harness dev ini (`playwright.dev.config.ts`, port 3000 = port dev), sesi berada
di origin yang BENAR dan spec melewati guard-nya sendiri — terbukti dari output:
`SESSION_FILE=_e2e_session.refreshed.json`, `TOKEN_TTL_S=2818`,
`LS_KEY=sb-…-auth-token EMAIL=e2e.…@nexus-local.test`,
`PICK_MODEL=google/gemma-4-31b-it ROSTER_N=12`.

Kegagalan yang tersisa berbeda dan berakar di frontend:

1. `BUG 1` — tombol `aria-label='Pilih model AI'` tetap berisi **"Memuat…"** selama
   20 detik (selector belum selesai memuat).
2. `BUG 2` & `VALID` — karena model belum terpilih, tombol kirim **`disabled`** →
   `POST /chat` tidak pernah terjadi → `waitForResponse` timeout 60 detik.

Bukti arah sebaliknya (backend TIDAK salah): dengan token yang sama,
`GET http://127.0.0.1:8000/models` → **200**, 1.833 byte,
`{"status":"success","tier":"free",…}`; log backend menunjukkan **setiap** panggilan
`/models` pada jendela tes → `200 OK`. Logika filter juga hijau di unit test
(`pytest test_model_filter.py` lulus; 136 test di `tests/` lulus).

Kesimpulan: **BLOCKED, bukan regresi FASE 3.** Tidak satu pun berkas kanvas
(`features/builder/**`, `globals.css`) ikut dalam alur model selector, dan filter-nya
terbukti benar di level unit. Kandidat penyebab berikutnya: gating `useModelsQuery`
(hanya aktif setelah email terbaca dari sesi) + status loading yang tidak keluar di
dev. Masuk backlog FASE 4 (di luar lingkup canvas).

### 5.3 pytest — 1 kegagalan PRA-EXISTING

`test_fallback_reason.py::test_kode_overloaded_dikenali_dan_beda_dari_tuduhan_tier`
gagal karena mencari `case "overloaded"` di `nexus-frontend/src/app/page.tsx` yang
tidak ada. **Berkas itu TIDAK disentuh FASE 3** (`git status` bersih untuk berkas itu),
jadi kegagalan ini sudah ada sebelum fase ini — dicatat sebagai backlog, bukan
regresi kanvas. Sisa: `tests/` **136 passed**.

## 6. Bukti visual (43 file di `%TEMP%\fase3_shots\`)

| Kelompok | File |
|---|---|
| **12 wajib** (3 state × 4 tema) | `node_{loading,success,error}_{midnight,daylight,cyberpunk,minimal}.png` |
| Kanvas penuh per tema | `canvas_theme_{midnight,daylight,cyberpunk,minimal}.png` |
| Theme switcher | `theme_switcher_open.png` (4 preview), `theme_switcher_after_switch_minimal.png` |
| Auto layout | `autolayout_before.png`, `autolayout_after.png` |
| Mobile | `mobile_canvas.png`, `mobile_longpress.png`, `mobile_bottomsheet.png`, `mobile_config_sheet.png` |
| Edge mengalir / empty state | `edge_animated.png`, `empty_state.png`, `empty_state_after_cta.png` |
| Baseline SEBELUM | `before_*.png` (6) |

Angka audit sebelum/sesudah (programatik, `fase3-audit.mjs`):

| Metrik | SEBELUM | SESUDAH |
|---|---|---|
| `data-canvas-theme` | (tidak ada) | 4 nilai berbeda, terukur |
| Warna kanvas | `rgb(20,20,20)` keras | `#1b1f23` / `#fafaf8` / `#0a0a0f` / `#ffffff` |
| Token `--canvas-bg` | kosong | `#1b1f23` (Midnight) … `#ffffff` (Minimal) |
| Handle | 0 (tanpa node) | 7 handle; desktop 12×12, sentuh 20×20 (tap 44×44) |
| Tombol toolbar | 4 (Zoom/Fit/Toggle) | 10 dengan `data-testid`; 44×44 di sentuh |
| Empty state | tanpa CTA | ilustrasi + 2 CTA |
| pageerror / console error | 0 / 0 | 0 / 0 di 6 viewport |
| Lebar kanvas @1440 | 368 px (panel samping menang) | **688 px** (aside hanya saat node terpilih) |
| Target < 44px (mobile) | 15–16 | 0 pada toolbar kanvas |

## 7. Catatan kejujuran (yang TIDAK diklaim PASS)

1. **Persist tema ke Supabase profile: BELUM.** Backend tidak punya endpoint
   preferensi UI; menambah kolom = schema migration (keputusan strategis di luar
   misi). Yang ada: localStorage + URL param, keduanya teruji.
2. **"Long-press lalu geser dalam gesture yang sama": TIDAK diimplementasikan.**
   Long-press 500ms → haptic → **drag mode aktif** (teruji `data-armed=true`), lalu
   node digeser pada gesture berikutnya. Menyalakan drag di tengah gesture yang
   sama menuntut penanganan pointer manual (bypass React Flow) dan tidak diminta misi.
3. **Screenshot diambil di DEV, bukan build produksi.** `npm run build` SUCCESS
   dilaporkan terpisah; regresi visual di bundle produksi belum dijalankan karena
   harness produksi >300 detik (masalah yang sudah terdokumentasi di FASE 2).
4. **model-filter: 0/3 BLOCKED** (§5.2) — bukan hijau, dan tidak diklaim hijau.
5. **Minimap auto-hide** hanya berbasis `pointer: coarse` / lebar <768px; state
   toggle tidak dipersist.

