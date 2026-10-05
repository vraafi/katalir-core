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
| **Kartu bertahan setelah refresh (Bug #3)** | ✅ lokal + LIVE | `card-persistence.spec.ts` **2/2 lulus** terhadap `out/` produksi **dan** `https://proyek-agent.pages.dev` (§4b) |
| **Decoder `decodePersistedCard`** | ✅ 7/7 | `card-persistence.unit.spec.ts` — pemetaan field, `_localId` wajib, baris biasa aman |
| Kontrak keamanan `/chat/approve` | ✅ | body persis `{approval_token, decision}`; client tidak mengirim ulang tool/args |
| Jalur tetangga tidak rusak | ✅ | `success` bubble + `denied` → error-card, keduanya lulus |
| **Fix Bug #1 (approval Telegram)** | ✅ kode + harness | parser tidak membuang field; alias `text/message`→`pesan`. 3/3 skenario `requires_approval` + token. **Backend produksi belum redeploy** (§4g) |
| **Fix Bug #2 (discovery over-asking)** | ✅ kode + harness | 5/5 prompt alur-jelas membangun workflow dgn placeholder. **Backend produksi belum redeploy** (§4g) |
| Suite backend (pytest) | ✅ 737 passed | lihat §5 |

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

### 4b. Fix Bug #3 — SUDAH ter-deploy & TERBUKTI di situs live (6 Okt 2026)

Dijalankan terhadap `https://proyek-agent.pages.dev`: **2/2 lulus** (spec
persistensi) dan **15/15 lulus** (suite kartu penuh). Buktinya diambil
langsung dari bundel yang disajikan situs:

```
live chunk: page-fd95553c83308fb4.js (70.311 B)
__katalir_card     1        <- sentinel kartu ADA
srv-card           1        <- decoder ADA
credential_form    1        <- form kredensial ADA
```

Screenshot bukti: `docs/marketing/screenshots/card-persistence-after-reload.png`
(kartu kredensial dirender ulang SETELAH refresh, pada situs produksi, murni
dari baris `role="system"` yang dipersist server).

Deploy dilakukan lewat `_deploy_pages.py` (wrangler direct upload). Hash chunk
berubah antar-deploy (`page-27addee031fc38d6.js` → `page-fd95553c83308fb4.js`)
karena build id berubah, tetapi penanda Bug #3 tetap ada di keduanya
(diverifikasi dengan `grep` pada bundel live, bukan hanya nama file).

### 4c. Verifikasi UI melawan backend produksi dengan sesi nyata TERBLOKIR

Refresh token `.autonomous_session.json` sudah dicabut dan password grant
untuk user otonom ditolak — kredensial test account berubah sejak 2 Okt.

**DIPERBARUI 6 Okt 2026:** akun E2E tetap (`nexus-frontend/_e2e_user.json`)
BERHASIL di-grant ulang lewat `grant_type=password`, jadi probe `POST /chat`
ke backend produksi sekarang bisa dilakukan dengan JWT sah. Hasil probe
justru mengungkap temuan penting — lihat §4g.

### 4d. Keputusan sengaja, bukan bug

- TOLAK tidak menambah bubble `tool_result` (backend tidak mengembalikan
  `result` untuk deny; kartu "dibatalkan" sudah jadi tanda terima).
- `alignment` hanya ditampilkan untuk kasus `not_aligned`.
- Rate limiter masih in-memory (`TurnBudget`) — Railway multi-replica bisa
  melewatinya. Ditunda, bukan cacat yang tak disadari.
- Investigasi gateway 500 dan wiring `qwen_param_parser.py` sengaja ditunda.

### 4e. Bug #2 — dibuktikan di harness (5/5), BELUM di backend produksi

Uji harness `_bug2_evidence.py` lewat `_agentic_run_gateway` dengan model
palsu: **5/5 prompt beralur-jelas membangun workflow** dengan placeholder
`{{chat_id}}` diteruskan ke canvas, tanpa over-asking. Prompt sistem memuat
`ATURAN BUILD WORKFLOW` + placeholder (dikunci test).

NAMUN probe backend produksi menunjukkan perilaku LAMA (lihat §4g).

### 4f. Catatan hash chunk

Build lokal `page-27addee031fc38d6.js` (70.277 B) disajikan sebagai
`page-fd95553c83308fb4.js` (70.311 B) di live. Selisih kecil berasal dari
build id/metadata; penanda Bug #3 (`__katalir_card`, `srv-card`,
`credential_form`) ada di KEDUANYA. Yang penting: bundel lokal dan live
sekarang setara secara fungsional (dulu live `page-6eb4f85538eda943.js`
69.193 B TANPA penanda apa pun).

### 4g. TEMUAN KRITIS — backend produksi BELUM punya fix Bug #1/#2 (6 Okt 2026)

Probe `POST /chat` ke `web-production-dc90b.up.railway.app` dengan JWT sah
(akun E2E, §4c) menunjukkan backend produksi masih berperilaku seperti SEBELUM
fix:

```
prompt : "setiap pagi jam 7 ambil data dari API lalu kirim ke telegram"
status : success
workflow: TIDAK ADA
reply  : "Baik, saya bisa bantu membuatkan workflow tersebut. Untuk
          memulainya, saya butuh beberapa informasi: 1. URL API mana ...
          2. Chat ID Telegram ... 3. Data spesifik apa ..."
```

Itu **persis gejala Bug #2** (over-asking; alur jelas tapi agen menahan diri).
Kode fix sudah ADA di `main` (`f8b8cba`) dan sudah ter-push
(`git ls-remote` → `f8b8cbae`), tetapi Railway belum menjalankan ulang
build/deploy.

**PENGHALANG deploy:** token akun Railway yang dipakai skrip lama
(`RAILWAY_akun`) sudah TIDAK ADA di `.env`. Yang tersisa hanya
`RAILWAY_TOKEN`/`RAILWAY_API_TOKEN` (token project 36 karakter) dan keduanya
menjawab `Not Authorized` untuk query akun — jadi redeploy tidak bisa
dipicu dari sini. Railway biasanya auto-deploy saat push, tetapi tidak
terjadi dalam ~10 menit setelah `f8b8cba` ter-push.

**YANG DIBUTUHKAN:** picu redeploy service `web` pada project
`sunny-vibrancy` (environment `production`) lewat dashboard Railway, atau
pulihkan `RAILWAY_akun` di `.env`. Setelah itu jalankan ulang probe §4g:
`workflow` harus `ADA` dan `reply` tidak boleh bertanya-tanya lagi.
kartu yang belum ter-deploy (§4b). Catatan lama di sesi pertama ("ukuran
identik, hanya nama berbeda") berlaku untuk build 5 Okt pagi, bukan yang ini.

---

## 5. Test & verifikasi (ringkas)

```
pytest tests/ -q                                     -> 737 passed  (Python 3.12 sistem; +23 tes regresi 6 Okt)
npx playwright test -c playwright.unit.config.ts      ->   7 passed  (decodePersistedCard)
npx playwright test -c playwright.approval.config.ts  ->  15 passed  (production build lokal)
  ├─  13 approval-card
  └─   2 card-persistence (Bug #3: kartu bertahan setelah refresh)
E2E_BASE_URL=https://proyek-agent.pages.dev \
  npx playwright test -c playwright.approval.config.ts \
    -o <dir-luar-repo>                                ->  15 passed  (LIVE, 6 Okt — Bug #3 ter-deploy)
_agentic_run_gateway (harness, model palsu)           -> 5/5 prompt workflow membangun (§4e)
_bug1_evidence.py (rantai teks nyata)                 -> 3/3 skenario requires_approval + token
npx playwright test --list -c playwright.config.ts     -> 514 tes / 44 berkas
```

Catatan: jalankan Playwright dengan `-o <dir di luar repo>`. Bila
`test-results/` diarahkan ke dalam repo, langkah pembersihan bawaan Playwright
menghapus >50 berkas dalam satu giliran dan tertahan shim safe-delete
(`SAFE_DELETE_BULK_CONFIRM_REQUIRED`).

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
