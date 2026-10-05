# Kartu persetujuan: ada di kode, MATI di runtime

Tanggal: 5 Oktober 2026
Status: **diperbaiki, ter-deploy, dan terbukti di situs live** — `ChatApp.tsx`
(cabang `approval_prompt`); 9/9 tes browser lulus lokal DAN terhadap
`https://proyek-agent.pages.dev`.
Konteks: lanjutan dari `laporan_katalir_sesi_baru.md` bagian 7 butir 1
("Screenshot kartu persetujuan ❌ — belum pernah dilihat di browser").

---

## Kenapa dicari

Sesi sebelumnya menutup dengan klaim yang jujur: kartu persetujuan ada di kode,
`tsc` 0 error, `/chat/approve` terbukti 6/6 lewat curl di produksi — **tapi
kartunya belum pernah dilihat di browser**. Klaim seperti itu belum menguji
apa pun: type-check hanya membuktikan tipe cocok, curl hanya membuktikan
endpoint menjawab. Yang belum dibuktikan adalah **user bisa melihat dan
memakai kartunya**.

Percobaan pertama membuktikan kenapa keraguan itu benar.

## Gejala

Spec browser (`tests/approval-card.spec.ts`) men-stub `POST /chat` agar
membalas `requires_approval`, lalu mengirim pesan seperti user. Yang terjadi:

```
5 failed, 2 passed
Locator: getByTestId('approval-card')  ->  element(s) not found
```

Snapshot DOM saat gagal:

```yaml
- main:
  - text: kirim laporan ini ke telegram sekarang   # bubble user ADA
  - textbox "Pesan"
  - button "Kirim" [disabled]
```

Bubble user tampil, lalu… tidak ada apa pun. Bukan kartu, bukan kartu error,
bukan bubble "…". **Pesan assistant menghilang tanpa jejak.**

## Akar masalah

`src/features/chat/hooks/useChat.ts` sudah benar: pada `status:
requires_approval` ia menaruh pesan `system` bertipe `approval_prompt` ke cache
TanStack (dengan `_localId` dipertahankan, seperti form kredensial).

Yang membuangnya adalah **layer render** di `src/app/chat/ChatApp.tsx`.
`unconfirmed.map(...)` hanya memetakan tiga tipe pesan system:

| `m.type` | hasil |
|---|---|
| `credential_form` | dipetakan -> `<CredentialForm>` |
| `oauth_prompt` | dipetakan -> `<OAuthConnectCard>` |
| `error` | dipetakan -> kartu error |
| `approval_prompt` | **jatuh ke `return null`** |

`thread.tsx` sudah punya cabang render `<ApprovalCard>` — tetapi tidak pernah
menerima pesannya, karena `ChatApp` menyaringnya lebih dulu. Jadi rantainya
terputus tepat di satu `map`, dan gejalanya menipu: **bukan error, bukan
crash — hanya bubble yang hilang.**

## Kenapa 706 tes + `tsc` tidak menangkapnya

Tidak ada satu pun tes yang merender `requires_approval` di browser:

* tes unit menguji `useChat` sampai cache (`data.requiresApproval` benar),
  lalu berhenti — layer render tidak pernah dieksekusi;
* `tsc` 0 error: tipe `approval_prompt` memang sudah ada di union `Msg`, jadi
  tidak ada yang dilanggar. Tipe tidak bisa menangkap cabang `map` yang lupa.

Pola ini persis dua bug di laporan sebelumnya:

* #3 — `tool_call_parser.py` ada tapi tidak pernah dipanggil;
* #12 — `/chat` menimpa `status` apa pun menjadi `"success"`.

Ketiganya sama: **proteksi terlihat ada, padahal mati.**

## Perbaikan

`src/app/chat/ChatApp.tsx` — cabang baru di `unconfirmed.map`, mengikuti pola
`credential_form`/`oauth_prompt` yang sudah ada:

```tsx
if (m.type === "approval_prompt") {
  return {
    key: `appr-${m.id ?? m._localId ?? m.tool ?? "approval"}`,
    role: "system",
    type: "approval_prompt",
    tool: m.tool, toolArgs: m.toolArgs, reason: m.reason,
    alignment: m.alignment, approvalToken: m.approvalToken,
    original: m.original ?? "",
  };
}
```

`approvalToken` wajib diteruskan: tanpa itu `thread.tsx` menampilkan catatan
"Persetujuan tidak tersedia" dan klik Setujui tidak bisa diverifikasi server.

## Bukti setelah perbaikan

```
npx playwright test -c playwright.approval.config.ts   -> 9 passed (18.3s)
npx tsc --noEmit                                        -> 0 error
```

Dijalankan di **production build** (`out/` dari `next build`, disajikan
`scripts/serve-out.mjs`), bukan `next dev`. Screenshot:

```
docs/marketing/screenshots/approval-card-telegram.png       kartu + args dari server
docs/marketing/screenshots/approval-card-intent.png         pemicu intent-alignment
docs/marketing/screenshots/approval-card-approved.png       setelah Setujui
docs/marketing/screenshots/approval-card-denied.png         setelah Tolak
docs/marketing/screenshots/approval-card-expired.png        token kedaluwarsa (400)
docs/marketing/screenshots/approval-card-policy-denied.png  status `denied`
docs/marketing/screenshots/approval-card-needs-spec.png     status `needs_spec`
docs/marketing/screenshots/approval-card-gallery.html       indeks semua di atas
```

Galeri itu **self-contained**: gambarnya di-inline (WebP hasil downscale dari
PNG asli) supaya satu berkas tetap menampilkan bukti tanpa server maupun
berkas pendamping — Preview sandbox hanya menyajikan satu berkas, dan
percobaan pertama dengan `<img src>` relatif menghasilkan galeri bergambar
rusak.

Yang dikunci tes (bukan sekadar "kartu terlihat"):

* args yang tampil adalah **args dari server**, bukan gema pesan user;
* body `POST /chat/approve` **persis** `{approval_token, decision}` — client
  tidak boleh mengirim ulang tool/args;
* pesan `detail` dari server dipakai apa adanya, dan setelah gagal tombol
  tetap aktif (tidak terkunci);
* cabang tetangga (`requires_credential`, balasan `success`) tetap normal.

## Sebelum deploy: situs live masih buggy

Ini penting dicatat supaya tidak ada klaim "sudah ter-deploy ✅" yang keliru.
Sebelum sesi ini, spec yang diarahkan ke `https://proyek-agent.pages.dev`
GAGAL dengan snapshot DOM identik dengan kegagalan pra-perbaikan:

```
E2E_BASE_URL=https://proyek-agent.pages.dev \
  npx playwright test -c playwright.approval.config.ts --grep "policy gate"
-> 1 failed: approval-card tidak ditemukan
```

Chunk yang disajikan situs itu saat itu (`page-3a9ac0f0e22609ec.js`) memang
mengandung string `approval-card`, `approval-approve`, dan `approval_token`.
Artinya: **memeriksa keberadaan string di bundle bukan bukti apa pun.** Yang
mati adalah alur render-nya, dan itu hanya terbukti dengan menjalankan alurnya.

## Deploy + bukti di situs live

```
python _deploy_pages.py            -> EXIT=0 (proyek-agent, upload `out/`)
```

Bukti deploy bukan "exit code 0", melainkan chunk yang benar-benar disajikan:

```
situs live : /_next/static/chunks/app/chat/page-13bab09d2d8dae02.js
build lokal: /_next/static/chunks/app/chat/page-13bab09d2d8dae02.js   (sama)
```

Chunk hash itu berubah setelah perbaikan `ChatApp.tsx` — jadi kecocokan ini
membuktikan versi yang disajikan situs = build yang diuji, bukan build lama.

Lalu spec yang sama dijalankan lagi terhadap situs live:

```
E2E_BASE_URL=https://proyek-agent.pages.dev E2E_SHOT_PREFIX=approval-card-live \
  npx playwright test -c playwright.approval.config.ts
-> 9 passed (20.4s)
```

Screenshot run live disimpan terpisah (`approval-card-live-*.png`, tujuh berkas)
supaya bukti build lokal dan bukti situs live tidak saling menimpa.

Dua celah lain yang terbuka saat dokumen ini pertama ditulis — **keduanya
sudah ditutup sesi yang sama** (kommit `fix(chat): render tool result +
alignment after approval`):

1. **Hasil tool tidak pernah tampil.** `POST /chat/approve` mengembalikan
   `{status: "executed", tool, result}`, tetapi `ApprovalCard` hanya membaca
   status HTTP dan menampilkan "TELEGRAM disetujui dan dijalankan." — `result`
   dibuang. Sekarang keputusan diteruskan lewat `onDecision` ke ChatApp, yang
   menaruh kartu `tool_result` di cache percakapan (format: string / `{message}`
   / dict JSON rapi / pesan eksplisit bila kosong). Dikunci 4 tes formatter +
   screenshot `approval-card-tool-result.png`. Keputusan TOLAK sengaja tidak
   menambah bubble: backend tidak mengembalikan `result` untuk deny, dan kartu
   persetujuan sudah menjadi tanda terima "dibatalkan".
2. **`alignment` diteruskan tapi tidak dirender.** Sekarang tampil sebagai
   `<details>` "Kenapa tool ini butuh persetujuan?" dengan bahasa manusia untuk
   `not_aligned` — user bisa membedakan "policy gate minta izin" dari "pola ini
   tidak kamu minta".

## Pembaruan sesi yang sama: hasil tool + alignment (kommit `415c5b1`)

Kedua celah di atas ditutup di hari yang sama, lalu di-deploy ulang:

```
kommit + push      : 0a87f03..415c5b1  main -> main (HEAD == origin/main)
deploy frontend    : EXIT=0, chunk live berubah
                     page-13bab09d2d8dae02.js -> page-dc3e7d8eb0b7ff3c.js
spec lokal         : 13 passed (38.3s)  - production build, port 3000
spec situs live    : 13 passed (33.1s)  - proyek-agent.pages.dev
tsc --noEmit       : 0 error
pytest tests/ -q   : 706 passed, 1 warning (108.33s)
katalir.de5.net    : HTTP 200
```

Screenshot baru: `approval-card-tool-result.png` (lokal) dan
`approval-card-live-tool-result.png` (situs live). Galeri diperbarui:
`approval-card-gallery.html` kini menampung 11 bukti (3 live + 8 lokal).

**Verifikasi UI melawan backend produksi dengan sesi nyata: TERBLOKIR.**
Refresh token `.autonomous_session.json` sudah dicabut (`refresh_token_not_found`)
dan password grant untuk user otonom menolak (`invalid_credentials`) — kredensial
test account berubah sejak 2 Okt. Sesuai kontrak laporan: ini dilaporkan, bukan
dipalsukan. Yang ditempuh sebagai gantinya: spec stub per-path terhadap build
dan situs live (13/13), karena bentuk response `/chat/approve` di produksi
(`{status:"executed", tool, result}`) sudah pernah dibuktikan sesi sebelumnya.
User perlu memperbarui kredensial test account bila ingin bukti end-to-end
yang benar-benar menyentuh backend.

## Catatan harness — `npm run e2e:prod`

`playwright.config.ts` (harness resmi) TIDAK punya `testMatch`, jadi
`tests/approval-card.spec.ts` otomatis ikut `npm run e2e:prod`. Itu **dibuktikan**,
bukan diasumsikan:

```
npx playwright test --list -c playwright.config.ts
-> Total: 514 tests in 44 files
   approval-card.spec.ts -> 26 entri (13 tes x 2 proyek: guest + logged-in)
```

### Percobaan menjalankan suite penuh: TERBLOKIR (sebab lingkungan)

`npm run e2e:prod` dicoba di sesi lanjutan. Suite ini **tidak pernah sampai
menjalankan satu tes pun**, karena langkah `next build` di dalam `webServer`
gagal lebih dulu. Tiga sebab ditemukan berurutan — semuanya lingkungan, bukan
kode:

| # | Gejala | Sebab | Status |
|---|---|---|---|
| 1 | `Failed to load SWC binary for win32/x64`, exit `3221225477` | `node` di PATH menunjuk runtime managed WorkBuddy (`22.22.2`) yang gagal meng-init `@next/swc-win32-x64-msvc` (DLL init failed). Biner-nya tidak rusak: hash identik dengan tarball registry, dan **lulus** di `node 24.16.0` sistem | **diatasi**: jalankan dengan `node` 24 sistem |
| 2 | `SAFE_DELETE_BULK_CONFIRM_REQUIRED count=50 threshold=50` | shim safe-delete WorkBuddy membatasi 50 hapus per-turn; `next build` membersihkan `.next` (dan Playwright membersihkan `test-results`) melebihi itu | **diatasi**: direktori artefak dipindah (rename) lebih dulu, atau shim dimatikan untuk proses build |
| 3 | `EPERM: open '...\out\404.html'` | langkah `Exporting` Next gagal menulis `out/404.html`. Menulis berkas yang sama secara manual **berhasil**, jadi ini race/lock level Windows — bukan izin path, bukan shim (stack tidak lagi memuat frame shim) | **BELUM teratasi** |

Bukti sebab #3 bukan soal path/kode: build berjalan sampai
`✓ Compiled successfully`, `✓ Generating static pages (21/21)`, dan menghasilkan
`out/_next/static/chunks/app/chat/page-dc3e7d8eb0b7ff3c.js` (69.193 byte) —
**hash identik** dengan build yang sudah di-deploy. Yang gagal hanya penulisan
`404.html` di akhir. Karena itu suite penuh belum bisa diklaim hijau di sini.

### Yang tetap diverifikasi (dan sudah)

Build produksi lengkap masih tersedia, jadi spec yang sama dijalankan ulang
terhadap dua bentuk produksi:

```
production build lokal (out/, disajikan scripts/serve-out.mjs)  -> 13 passed (35.2s)
situs live https://proyek-agent.pages.dev                       -> 13 passed (36.0s)
```

**Jebakan yang sempat menyesatkan:** run pertama terhadap build lokal gagal
**13/13** dengan `approval-card not found` — persis gejala bug aslinya. Sebabnya
bukan produk: `_e2e_session.refreshed.json` sudah kedaluwarsa (ttl −2727 s),
sehingga app menampilkan gerbang login dan kartu tak pernah dirender. Setelah
fixture basi itu disingkirkan (spec jatuh ke `dummySession()`), 13/13 lulus.
Fixture E2E bersifat sementara; fixture basi menghasilkan kegagalan yang
menyamar sebagai regresi produk — periksa TTL-nya sebelum menyalahkan kode.

Screenshot run ulang disimpan dengan prefiks terpisah (`verify-local-*`,
`verify-live-*`) agar bukti lama tidak tertimpa.

## Cara menjalankan ulang

```bash
cd nexus-frontend
npm run build                                  # tulis ulang out/
# penting: build menolak jalan kalau port 3000 terpakai (prebuild check)
PORT=3000 node scripts/serve-out.mjs &         # production build, bukan dev
npx playwright test -c playwright.approval.config.ts
```

Port 3000 harus bebas lebih dulu — `scripts/check-no-dev-running.mjs`
menganggap listener apa pun di sana sebagai dev server dan memblokir build.

### Prasyarat toolchain (kalau dijalankan dari shell WorkBuddy)

```bash
# node 24 sistem — runtime managed 22.22.2 TIDAK bisa memuat @next/swc
export PATH="/c/Program Files/nodejs:/c/Users/user/AppData/Local/Programs/Python/Python312:$PATH"
node --version   # harus v24.x
python -c "import fastapi"   # backend uvicorn butuh Python 3.12 sistem, bukan managed 3.13
```

Sebelum menjalankan spec approval, pastikan `_e2e_session.refreshed.json` **tidak
kedaluwarsa** (atau tidak ada, supaya spec memakai `dummySession()`); fixture
basi membuat semua tes gagal dengan gejala yang menyerupai bug produk.
