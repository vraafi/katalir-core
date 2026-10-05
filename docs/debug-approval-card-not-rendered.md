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

Dua celah lain yang sengaja TIDAK dikerjakan sesi ini:

1. **Hasil tool tidak pernah tampil.** `POST /chat/approve` mengembalikan
   `{status: "executed", tool, result}`, tetapi `ApprovalCard` hanya membaca
   status HTTP dan menampilkan "TELEGRAM disetujui dan dijalankan." — `result`
   dibuang. User menyetujui, tool jalan, dan output-nya tidak pernah ia lihat.
2. **`alignment` diteruskan tapi tidak dirender.** Prop `alignment` ada di
   `ApprovalCard` tetapi tidak dipakai di JSX, jadi user tidak bisa membedakan
   "policy gate minta izin" dari "pola ini tidak kamu minta" — padahal
   `reason` dari backend sudah membawa konteksnya.

## Catatan harness

`playwright.config.ts` (harness resmi) TIDAK punya `testMatch`, jadi
`tests/approval-card.spec.ts` otomatis ikut `npm run e2e:prod` dan ikut menjaga
regresi ini. Sesi ini **belum** menjalankan `npm run e2e:prod` (ia membangun
ulang produksi + butuh `globalSetup` jaringan); hasil `playwright.approval.config.ts`
di atas TIDAK boleh diklaim setara dengan suite penuh itu.

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
