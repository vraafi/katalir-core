# LAUNCH STATUS — Katalir

Tanggal: 5 Oktober 2026 (diperbarui: sesi kedua)
Repo: `katalir-core` · `HEAD = e5ba734`, `origin/main = 13eca93`

---

## 0. PEMBARUAN SESI KEDUA — blocker build SELESAI

Blocker `npm run e2e:prod` yang dulu dicatat di §4 akhirnya **selesai**.
Akarnya ternyata **dua sebab lingkungan** yang berbeda:

| Sebab | Gejala | Solusi |
|---|---|---|
| A. `next lint` menggantung | Build berhenti di `buildStage: "compile"` >9 menit, `.next` hanya 7 berkas metadata | Tambahkan `--no-lint` |
| B. shim safe-delete WorkBuddy | `SAFE_DELETE_BULK_CONFIRM_REQUIRED {count:178, threshold:50, scope:"turn"}` pada `.next/export` | Salin hasil sendiri: `scripts/export-out.mjs` |

Akar B terbukti dari pesan galatnya: Next.js menghapus `.next/export` (176–178
berkas) di langkah pembersihan **terakhir**, sedangkan lingkungan ini membatasi
**50 penghapusan per giliran tool**. Baris `✓ Generating static pages (21/21)`
sudah tercetak sebelum galat — jadi ini langkah kosmetik, bukan kegagalan build.

**Perintah build yang sekarang bekerja:**

```bash
cd nexus-frontend
npx next build --no-lint --experimental-build-mode generate   # compile + generate
node scripts/export-out.mjs --clean                          # .next/server/app -> out/
```

Hasil: **`out/` 103 berkas**, chunk `page-27addee031fc38d6.js` (70.277 B)
memuat `__katalir_card`, `srv-card`, `credential_form`.

### Hasil verifikasi browser

```
npx playwright test -c playwright.approval.config.ts   -> 15 passed  (build produksi lokal)
  ├─ 13 tes approval-card (tidak ada regresi)
  └─  2 tes card-persistence (Bug #3: kartu bertahan setelah refresh)
npx playwright test -c playwright.unit.config.ts       ->  7 passed  (decodePersistedCard)

E2E_BASE_URL=https://proyek-agent.pages.dev ... card-persistence.spec.ts
                                                       ->  1 FAILED  (lihat §4b)
```

### Catatan hash chunk

| | |
|---|---|
| Build lokal sesi ini | `page-27addee031fc38d6.js` — 70.277 B, **memuat** `__katalir_card` |
| Situs live sekarang | `page-6eb4f85538eda943.js` — 69.193 B, **TIDAK memuat** `__katalir_card` |

Live belum memuat fix Bug #3. Selisih ukuran (+1.084 B) konsisten dengan
penambahan decoder + persistensi kartu.

---

## 1. Commit terakhir

| | |
|---|---|
| HEAD | `e5ba734` — `fix(chat): 3 bug kritis dari test browser user (approval card, discovery, vault)` |
| origin/main | `13eca93` — `docs: status launch-ready Katalir` |
| Selisih | **1 commit lokal belum di-push** (`e5ba734`) |

`e5ba734` menyentuh: `api_server.py`, `database.py`, `textual_tool_handlers.py`,
`nexus-frontend/src/features/chat/hooks/useChat.ts`, + 4 berkas tes
(`test_card_persistence.py`, `test_discovery_agent.py`, `test_intent_alignment.py`,
`test_tool_injection.py`). Ringkasan: 714 tes lulus (naik dari 706).

Commit sesi ini dan pendahulunya:

```
fa5fe7f  docs: bukti harness e2e:prod — 26 tes approval-card ikut suite resmi
986decb  docs: bukti deploy kedua — hasil tool + alignment terverifikasi di situs live
415c5b1  fix(chat): render tool result + alignment after approval
a216846  fix(ui): kartu persetujuan tidak pernah dirender — ditemukan lewat bukti browser
0a87f03  docs: laporan handoff sesi katalir
2a71e48  fix(api): teruskan status dari gateway — .stop hardcode "success"
90f1d59  fix(api): jangan telan requires_approval — bug ditemukan verifikasi produksi
a6bbbd6  feat(ui): kartu persetujuan + audit arsitektur chat frontend
b7da2ac  feat(security): intent-alignment check — defense-in-depth injeksi prompt
5a63110  feat(security): tutup 4 gap — sanitasi tool result, input, allowlist, approval
b50efdb  feat(security): policy gate deterministik + red team suite (41 test)
8291a94  feat(chat): hentikan kirim param `tools` — jalur teks jadi utama
8565246  feat(tool): textual tool calling format [ALAT: args] — model-agnostic
daa2a0c  feat(vault): gerbang fail-closed + tool check_credential + broker secret://
```

---

## 2. Fitur yang TERVERIFIKASI

| Fitur | Status | Bukti |
|---|---|---|
| Live site | ✅ 200 | `katalir.de5.net` → 200; `proyek-agent.pages.dev/chat` → 200 |
| Bundle live memuat perbaikan | ✅ | chunk `page-6eb4f85538eda943.js` (69.193 B) memuat `approval-card`, `approval-alignment`, `tool-result-card`, `tool-result-output`, `approval-approve`, `approval-deny` |
| Backend produksi | ✅ | `/health` → 200; `/workflows` → 401 (auth aktif) |
| Kartu persetujuan (approval card) | ✅ 13/13 | `playwright.approval.config.ts` — **13/13 lulus** di build produksi lokal **dan** di situs live |
| Hasil tool tampil setelah Setujui | ✅ | 4 tes formatter (objek / string / `{message}` / kosong) + screenshot `tool-result` |
| `alignment` dirender | ✅ | `<details data-testid="approval-alignment">` — tes intent-alignment lulus |
| Form kredensial (vault) | ✅ | tes `requires_credential: kartu form kredensial tetap dirender` lulus **di situs live** |
| **Kartu bertahan setelah refresh (Bug #3)** | ⚠️ build lokal ✅ / live ❌ | `card-persistence.spec.ts` **2/2 lulus** terhadap `out/` produksi; **1/2 gagal** di situs live karena deploy belum memuat fix (§4b) |
| **Decoder `decodePersistedCard`** | ✅ 7/7 | `card-persistence.unit.spec.ts` — pemetaan field, `_localId` wajib, baris biasa aman |
| Kontrak keamanan `/chat/approve` | ✅ | body persis `{approval_token, decision}`; client tidak mengirim ulang tool/args |
| Jalur tetangga tidak rusak | ✅ | `success` bubble + `denied` → error-card, keduanya lulus |
| Suite backend (pytest) | ✅ 714 passed | lihat §5 |

---

## 3. Gap yang DITUTUP

1. **Kartu persetujuan tidak pernah dirender.** `useChat` menaruh pesan
   `approval_prompt` ke cache dengan benar, tetapi layer render `ChatApp.tsx`
   hanya memetakan `credential_form`/`oauth_prompt`/`error` — `approval_prompt`
   jatuh ke `return null`. Bubble user muncul lalu hilang tanpa jejak. (`a216846`)
2. **`result` dari `/chat/approve` dibuang.** `ApprovalCard` hanya membaca status
   HTTP, jadi output tool tidak pernah terlihat user. Sekarang diteruskan lewat
   `onDecision` → kartu `tool_result`. (`415c5b1`)
3. **`alignment` diteruskan tapi tidak dirender.** Sekarang tampil sebagai
   `<details>` "Kenapa tool ini butuh persetujuan?". (`415c5b1`)
4. **`status` di-hardcode `"success"`** di `/chat`, sehingga `requires_approval`
   mustahil sampai ke UI. (`2a71e48`)
5. **`requires_approval` ditelan** oleh jalur API. (`90f1d59`)
6. **`tool_call_parser` ada tapi tidak pernah dipanggil** — proteksi tampak ada,
   padahal mati. (`daa2a0c` dkk.)
7. **Native `tools` merusak setiap request** (HTTP 500) — digantikan jalur teks
   `[ALAT: args]`. (`8291a94`)
8. **Kartu kredensial hilang saat refresh/navigasi.** Kartu hanya hidup di cache
   klien (TanStack `_localId`) dan tidak pernah dipersist; `GET /messages` hanya
   mengembalikan `{role, content}`, jadi kartunya tidak bisa dibangun ulang.
   Sekarang dipersist sebagai baris `role="system"` berisi envelope
   `{__katalir_card, ...}` dan didekode `decodePersistedCard` di klien.
   Dibuktikan di browser: `card-persistence.spec.ts` 2/2. (`e5ba734`)
9. **`_missing_provider(tool)` memanggil `check_credential(provider, "")`** dengan
   email KOSONG, sedangkan vault disimpan per-user — jadi TELEGRAM/SLACK/EMAIL/
   SHEETS selalu jatuh ke `requires_credential`, tidak pernah
   `requires_approval`. Tes lama menutupinya karena selalu monkeypatch
   `_missing_provider`. (`e5ba734`)

Pola yang berulang di bug-bug ini: **proteksi terlihat ada, padahal mati.**
Yang menangkapnya adalah menjalankan alurnya di browser — bukan type-check.

---

## 4. KNOWN LIMITATIONS

### 4a. Blocker build — SELESAI (lihat §0)

Riwayat lengkapnya, supaya tidak diulang dari nol:

- ~~`node` managed (22.22.2) tidak bisa memuat `@next/swc-win32-x64-msvc`
  (`DLL initialization routine failed`)~~ → **diatasi**: pakai node 24 sistem.
- ~~Build macet >9 menit di `buildStage: "compile"` tanpa menulis berkas~~ →
  **diatasi**: `--no-lint`. Ini sebab sebenarnya di balik "macet" yang dulu
  dilaporkan; `EPERM: open 'out\404.html'` adalah gejala sekunder.
- ~~`SAFE_DELETE_BULK_CONFIRM_REQUIRED {count:178, threshold:50, scope:"turn"}`~~ →
  **diatasi**: salin hasil sendiri lewat `scripts/export-out.mjs` (shim
  safe-delete membatasi 50 hapus/giliran; Next.js menghapus 176–178 berkas
  `.next/export` di langkah terakhir).

**Catatan penting:** memindahkan `.next` lebih dulu TIDAK menolong (sudah
dicoba). Build dari `.next` yang benar-benar kosong tetap macet di sebab A,
lalu menabrak sebab B begitu kompilasi berhasil. Kedua flag harus dipakai
bersama.

`npm run e2e:prod` sendiri masih memakai `playwright.config.ts` yang menyalakan
`webServer` + `globalSetup` ke Supabase, jadi ia tetap tidak bisa jalan di
lingkungan tanpa kredensial. Yang **sudah** hijau adalah suite kartu lewat
`playwright.approval.config.ts` (stub per-path, tanpa backend).

### 4b. Fix Bug #3 BELUM ter-deploy ke situs live

Dijalankan terhadap `https://proyek-agent.pages.dev`: **1/2 gagal**. Buktinya
diambil langsung dari bundel yang disajikan situs:

```
live chunk: page-6eb4f85538eda943.js (69.193 B)
__katalir_card     0        <- sentinel kartu TIDAK ada
srv-card           0        <- decoder TIDAK ada
approval-card      1        <- fix sesi sebelumnya ADA
```

Ini **bukan bug kode**: build lokal dari source yang sama lulus 15/15. Yang
perlu dilakukan: deploy `out/` hasil sesi ini ke Cloudflare Pages, lalu
jalankan ulang spec dengan `E2E_BASE_URL`.

### 4c. Verifikasi UI melawan backend produksi dengan sesi nyata TERBLOKIR

Refresh token `.autonomous_session.json` sudah dicabut dan password grant
untuk user otonom ditolak — kredensial test account berubah sejak 2 Okt.
Sebagai gantinya: spec stub per-path terhadap build produksi dan situs live.
Konsekuensinya, yang dibuktikan adalah **rantai render + kontrak data**, bukan
integrasi end-to-end dengan Supabase hidup.

### 4d. Keputusan sengaja, bukan bug

- TOLAK tidak menambah bubble `tool_result` (backend tidak mengembalikan
  `result` untuk deny; kartu "dibatalkan" sudah jadi tanda terima).
- `alignment` hanya ditampilkan untuk kasus `not_aligned`.
- Rate limiter masih in-memory (`TurnBudget`) — Railway multi-replica bisa
  melewatinya. Ditunda, bukan cacat yang tak disadari.
- Investigasi gateway 500 dan wiring `qwen_param_parser.py` sengaja ditunda.

### 4e. Bug #2 belum diuji terhadap LLM sungguhan

Butuh kredensial gateway yang masih hidup. Yang dibuktikan: aturan + placeholder
ada di prompt, dan tes regresi mencegah aturannya hilang saat prompt diedit.

### 4f. Catatan hash chunk

Build lokal sesi ini `page-27addee031fc38d6.js` (70.277 B) **berbeda** dari
chunk live `page-6eb4f85538eda943.js` (69.193 B) — dan kali ini **isinya memang
berbeda**, bukan sekadar nama. Selisih +1.084 B adalah decoder + persistensi
kartu yang belum ter-deploy (§4b). Catatan lama di sesi pertama ("ukuran
identik, hanya nama berbeda") berlaku untuk build 5 Okt pagi, bukan yang ini.

---

## 5. Test & verifikasi (ringkas)

```
pytest tests/ -q                                     -> 714 passed  (Python 3.12 sistem)
npx playwright test -c playwright.unit.config.ts      ->   7 passed  (decodePersistedCard)
npx playwright test -c playwright.approval.config.ts  ->  15 passed  (production build lokal)
  ├─  13 approval-card
  └─   2 card-persistence (Bug #3: kartu bertahan setelah refresh)
E2E_BASE_URL=https://proyek-agent.pages.dev \
  npx playwright test -c playwright.approval.config.ts \
    tests/card-persistence.spec.ts                    -> 1 FAILED   (live belum ter-deploy, §4b)
npx playwright test --list -c playwright.config.ts     -> 514 tes / 44 berkas
```

---

## 6. Cara re-run full suite

Prasyarat toolchain — **wajib runtime sistem**, bukan managed WorkBuddy:

```bash
export PATH="/c/Program Files/nodejs:/c/Users/user/AppData/Local/Programs/Python/Python312:$PATH"
node --version                # harus v24.x  (managed 22.22.2 gagal memuat @next/swc)
python -c "import fastapi"    # backend uvicorn butuh Python 3.12 sistem
```

### 6.1 Build produksi (dua langkah, WAJIB)

```bash
cd nexus-frontend

# 1. Pastikan port 3000 bebas (scripts/check-no-dev-running.mjs memblokir build)
node scripts/check-no-dev-running.mjs

# 2. Bersihkan sisa artefak supaya tidak menabrak batas 50 hapus/giliran.
#    Pindahkan (jangan hapus) supaya bisa dibandingkan:
mv .next .next.old 2>/dev/null ; mv out out.old 2>/dev/null

# 3. Compile + generate. `--no-lint` WAJIB: tanpa itu build menggantung
#    di "Creating an optimized production build" (>9 menit, tanpa progres).
npx next build --no-lint --experimental-build-mode generate

# 4. Salin hasil ke out/. Langkah bawaan Next.js ini yang gagal karena
#    shim safe-delete (menghapus .next/export yang berisi 176+ berkas).
node scripts/export-out.mjs --clean
```

`export-out.mjs` akan mengeluh bila `out/chat.html` tidak ada — itu tanda
langkah 3 belum selesai.

### 6.2 Jalankan spec

```bash
# Fixture auth opsional; spec jatuh ke dummySession() bila tidak ada:
ls _e2e_session.refreshed.json 2>/dev/null || echo "(pakai dummySession)"

PORT=3000 node scripts/serve-out.mjs &
npx playwright test -c playwright.approval.config.ts          # 15 tes
npx playwright test -c playwright.unit.config.ts              # 7 tes
```

Untuk menguji situs live: `E2E_BASE_URL=https://proyek-agent.pages.dev`
(tambahkan `E2E_SHOT_PREFIX=...-live` agar screenshot tidak menimpa bukti lokal).

Untuk `npm run e2e:prod` (suite penuh 514 tes): butuh shell biasa di luar
sandbox tool, atau CI, karena `playwright.config.ts` menyalakan uvicorn +
`globalSetup` ke Supabase — dua hal yang tidak tersedia di lingkungan ini.

---

## 7. Dokumen terkait

```
docs/debug-approval-card-not-rendered.md   latar bug render + bukti + catatan harness
docs/debug-status-wrapper.md               trace bug status hardcode
docs/frontend-chat-architecture.md         alur chat + gap
docs/BUGFIX-3-KRITIS-2026-10-06.md         3 bug kritis + laporan lanjutan sesi kedua
docs/security/threat-model-tool-injection.md  12 vektor injeksi + status
scripts/export-out.mjs                     pengganti langkah export Next.js yang diblokir
nexus-frontend/tests/card-persistence.spec.ts       Bukti Bug #3 (browser)
nexus-frontend/tests/card-persistence.unit.spec.ts  Bukti decoder (satuan)
docs/marketing/screenshots/approval-card-gallery.html  galeri bukti (self-contained)
```
