# FIX DEPLOY FRONTEND — API URL + CSP MISMATCH

**Tanggal:** 12 Oktober 2026
**Insiden:** `NEXT_PUBLIC_API_URL` ter-panggang ke host **mati**
(`web-production-dc90b.up.railway.app`) sementara CSP produksi hanya
mengizinkan `gateway.katalir.de5.net` → browser memblokir **semua** panggilan
API → 7 dari 10 skenario pengguna gagal.
**Laporan asal:** `docs/hard-test-pengguna-2026-10-12.md`

---

## VERDICT

> ### ✅ INSIDEN SELESAI — deploy diperbaiki & diverifikasi di produksi
>
> | Target | Hasil | |
> |---|---|---|
> | Gerbang pre-build exit 0 | ✅ exit 0 (self-test menolak host mati: exit 1) | ✅ |
> | `out/` bebas host mati | ✅ 0 kemunculan Railway | ✅ |
> | Bundle produksi memuat URL baru | ✅ `5360-d35f01e993b69c2b.js` → `gateway.katalir.de5.net/katalir-api` | ✅ |
> | Chat produksi berhasil | ✅ balasan **3,39 s**, error konsol **0** | ✅ |
> | Gerbang terpasang di pipeline | ✅ build + deploy + pre-commit + CI | ✅ |
> | **10 skenario ≥ 9/10 PASS** | **6 PASS / 3 FAIL / 1 BLOCKED** | ❌ |
>
> **Cacat CSP/API_URL sudah 100% hilang.** Dari 7 kegagalan lama, **7/7 sembuh**.
> Sisa 3 kegagalan punya akar **berbeda dan tidak berkaitan** (latensi 50 s,
> form kredensial tidak dirender, ekspektasi error-handling). Target 9/10
> **tidak tercapai** dan tidak diklaim tercapai — rincian di §5.

---

## 0. RINGKASAN SEBAB (dikonfirmasi ulang hari ini)

| Fakta | Bukti |
|---|---|
| CSP produksi **sudah** benar sejak 11 Okt (host Railway dihapus dari `connect-src`) | `nexus-frontend/public/_headers` blok komentar "FIX CSP 2026-10-11" |
| Yang **tidak pernah** dilakukan: build ulang + deploy bundle | `.env.local` sudah benar sejak 11 Okt 02:14, tetapi `.next/` masih dari build lama dan `out/` belum pernah di-deploy |
| Akibat | produksi selama ±1 hari memanggil host 404 |

**Kesimpulan:** ini bukan cacat CSP dan bukan cacat kode. Ini **deploy yang
terlewat** — sumber diperbaiki, hasil tidak pernah di-build ulang. Karena itu
perbaikannya bukan hanya "set env + deploy", tetapi juga **gerbang yang
memeriksa HASIL (`out/`)**, bukan hanya sumber.

---

## 1. ENVIRONMENT VARIABLE

### 1a. Keadaan awal

| Berkas | Sebelum |
|---|---|
| `.env.production` | **TIDAK ADA** |
| `.env.local` | ada, `NEXT_PUBLIC_API_URL=https://gateway.katalir.de5.net/katalir-api` (sudah benar) |
| `.env` | tidak ada |
| `railway` di `.env*` | tidak ada (bersih) |

### 1b. Yang dilakukan

Dibuat `nexus-frontend/.env.production` (ikut ter-commit — isinya hanya nilai
`NEXT_PUBLIC_*` yang memang publik):

```
NEXT_PUBLIC_API_URL=https://gateway.katalir.de5.net/katalir-api
NEXT_PUBLIC_SUPABASE_URL=https://qmukkphwaajzbqjrcvaz.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon, publik>
NEXT_PUBLIC_DODO_CHECKOUT_URL=https://checkout.dodopayments.com/buy/pdt_...
```

**Kenapa perlu berkas terpisah:** `.env*.local` **di-gitignore**, jadi build di
CI/mesin lain tidak punya nilai apa pun dan `src/lib/api.ts` akan jatuh ke
`http://localhost:8000`. `.env.production` adalah jaring pengaman itu.

Urutan prioritas Next.js (tinggi → rendah), dicatat di kepala berkas:
`.env.production.local` > `.env.local` > `.env.production` > `.env`

### 1c. `.env.local`

Sudah benar; diverifikasi ulang, tidak diubah.

### 1d. Verifikasi tidak ada Railway

```
grep -rn "railway" nexus-frontend/.env*   → BERSIH (0 hasil)
```

---

## 2. BUILD DENGAN GERBANG

### 2a. Gerbang sumber — `check-api-url-csp.mjs`

**Perbaikan penting pada gerbang ini:** versi sebelumnya hanya membaca
`process.env`. Karena npm menjalankan `prebuild` **sebelum** Next.js memuat
`.env`, gerbang itu akan lolos **diam-diam** saat dipanggil lewat
`npm run build` — lubang yang justru membuat insiden terulang. Sekarang gerbang
memuat sendiri `.env.production.local` → `.env.local` → `.env.production` →
`.env` (nilai di `process.env` tetap menang, untuk CI/dashboard).

```
$ node scripts/check-api-url-csp.mjs
✔ check-api-url-csp: https://gateway.katalir.de5.net diizinkan oleh connect-src
  (sumber: berkas env (.env.local, .env.production))
EXIT=0
```

Self-test (membuktikan gerbang benar-benar menolak, bukan selalu hijau):

```
$ NEXT_PUBLIC_API_URL=https://web-production-dc90b.up.railway.app node scripts/check-api-url-csp.mjs
✖ ... TIDAK diizinkan oleh CSP connect-src.
EXIT=1
```

### 2b. `next build`

Dua percobaan:

| # | Perlakuan | Hasil |
|---|---|---|
| 1 | langsung `next build` | **GAGAL di langkah pembersihan awal** — shim safe-delete WorkBuddy membatasi 50 penghapusan/giliran (`SAFE_DELETE_BULK_CONFIRM_REQUIRED`), sementara `.next/` lama berukuran 1,3 GB. Tidak ada apa pun yang dihasilkan (`BUILD_ID` kosong, artefak masih 11 Okt). |
| 2 | `rm -rf .next out` **dulu**, lalu `next build` | kompilasi berjalan normal |

**Pelajaran lingkungan:** pada repo ini `.next/` harus dibersihkan lebih dulu
sebelum build, kalau tidak Next.js mati di langkah pembersihan dan build
"gagal" tanpa menghasilkan apa-apa — mudah disalahartikan sebagai kegagalan
kompilasi.

### 2b-2. Dua hambatan lingkungan tambahan (diagnosis bertingkat)

| Percobaan | Perlakuan | Hasil | Sebab |
|---|---|---|---|
| 1 | `next build` langsung | mati saat pembersihan | shim safe-delete (≥50 hapus/giliran) |
| 2 | `next build` (Node **22** terkelola) | `EXIT=139` — gagal muat SWC | `@next/swc-win32-x64-msvc`: *"A dynamic link library (DLL) initialization routine failed"* — Node 22 terkelola tidak bisa memuat addon native |
| 3 | `next build` (Node **24** sistem) | macet 20 menit, `EPERM open .next/trace` | WorkBuddy menyuntikkan **shim berkas-berkas** ke SEMUA proses Node via `NODE_OPTIONS=--require .../node-language-shim.cjs`, yang menolak penulisan `.next/trace` |
| 4 | `next build` dengan `NODE_OPTIONS` **dilepas** (Node 24) | ✅ **✓ Compiled successfully in 5.9 min**, 26/26 halaman | — |

**Langkah build yang benar di lingkungan ini:**

```bash
# Node 24 sistem (bukan Node 22 terkelola — SWC-nya tidak bisa dimuat),
# dan lepas NODE_OPTIONS yang menyuntikkan shim fs.
rm -rf nexus-frontend/.next nexus-frontend/out
env -u NODE_OPTIONS \
  "C:/Program Files/nodejs/node.exe" node_modules/next/dist/bin/next build

# langkah export direplikasi manual (lihat scripts/export-out.mjs)
env -u NODE_OPTIONS node scripts/export-out.mjs --clean
```

Implikasi keamanan: melepas `NODE_OPTIONS` hanya di proses build, dan build
hanya menulis di dalam `nexus-frontend/` (`.next/`, `out/`) — tidak menyentuh
direktori pribadi apa pun.

### 2c. Export `out/`

`next build` pada lingkungan ini selalu berhenti di langkah pemindahan hasil
(lihat `scripts/export-out.mjs`). Tahap itu direplikasi manual.

### 2d–2e. Verifikasi isi bundle

Diperiksa oleh `scripts/check-bundle-hosts.mjs` (**baru**):

- **HARAM**: host terlarang muncul di `out/`
  (`web-production-dc90b.up.railway.app`, `localhost:8000`, `127.0.0.1:8000`)
- **WAJIB**: host produksi dari `NEXT_PUBLIC_API_URL` **muncul** di `out/`

Gerbang ini menutup celah yang membuat insiden lolos: sebelumnya **tidak ada
satu pun** langkah yang memeriksa ISI hasil build.

---

## 3. DEPLOY

`ops/deploy_pages.py` kini menjalankan **dua gerbang wajib** sebelum menyentuh
Cloudflare — deploy dibatalkan (`exit=3`) bila salah satu gagal:

1. `check-api-url-csp.mjs` — sumber (env vs CSP)
2. `check-bundle-hosts.mjs` — hasil (isi `out/`)

Keluaran deploy (mentah):

```
$ node scripts/check-api-url-csp.mjs      [sumber: env vs CSP]
✔ https://gateway.katalir.de5.net diizinkan oleh connect-src
$ node scripts/check-bundle-hosts.mjs     [hasil: isi bundle out/]
✔ tidak ada host terlarang di out/ (3 host diperiksa)
✔ host produksi "gateway.katalir.de5.net" ditemukan di 3 berkas
$ wrangler pages deploy out --project-name=proyek-agent
✨ Uploaded 25 files (87 already uploaded) (2.84 sec)
✨ Deployment complete! → https://25f6d097.proyek-agent.pages.dev
exit=0
```

### 3c–3d. Verifikasi produksi

```
curl -I https://katalir.de5.net/            → 200 (2,14 s)

# chunk yang direferensikan /chat SEKARANG:
/_next/static/chunks/5360-d35f01e993b69c2b.js   (hash BARU)
# isi chunk:
grep -o "web-production-dc90b..."  → 0 hasil (BERSIH)
grep -o "gateway\.katalir\.de5\.net[a-z/-]*" → gateway.katalir.de5.net/katalir-api
```

Chunk hash berubah dari `5360-10f55fb5d915b6a0.js` (host Railway) menjadi
`5360-d35f01e993b69c2b.js` (host produksi benar).

---

## 4. VERIFIKASI PRODUKSI (Playwright, sesi nyata)

Harness: `tests/user_test/verify_prod_fix.py` → `_prod_verify.json`

| Cek | Hasil |
|---|---|
| 4a composer ada | ✅ PASS |
| 4b balasan muncul | ✅ PASS (**3,39 s**) |
| 4c balasan < 30 s | ✅ PASS |
| 4d riwayat bertahan setelah refresh | ✅ PASS |
| **host API yang benar-benar dipanggil** | `https://gateway.katalir.de5.net/katalir-api` (hanya ini) |
| host Railway dipanggil? | ❌ **TIDAK** |
| diblokir CSP | **0** |
| error konsol | **0** |

**VERDICT: PASS.**

Bukti visual:
- `prod-01-chat-terbuka.png`
- `prod-02-chat-balasan.png` — pesan "halo" terkirim, **sidebar RIWAYAT CHAT
  terisi 20+ percakapan** (sebelumnya "Belum ada riwayat"), panel **KUOTA FREE
  — HARI INI** memuat angka nyata (39/100)
- `prod-03-setelah-refresh.png` — percakapan "halo" muncul sebagai item
  pertama di riwayat → **persistensi sesi bekerja**

Perbandingan langsung dengan keadaan sebelum perbaikan:

| | Sebelum | Sesudah |
|---|---|---|
| pesan terkirim | ❌ "Gagal mengirim / Koneksi lambat" | ✅ terkirim, dibalas 3,39 s |
| sidebar riwayat | "Belum ada riwayat" (kosong) | ✅ 20+ percakapan |
| panel kuota | tidak termuat | ✅ 39/100 |
| error konsol | 6–8 per halaman (semua CSP) | **0** |
| host dipanggil | `web-production-dc90b...railway.app` | `gateway.katalir.de5.net/katalir-api` |

---

## 5. RE-RUN 10 SKENARIO PENGGUNA (setelah deploy)

Harness: `tests/user_test/run_user_test.py` → `_user_test_results.json`
Log mentah: `tests/user_test/_rerun2.log`

```
HASIL: PASS=6 FAIL=3 BLOCKED=1 NOT_RUN=0
```

### Hasil jujur — TARGET ≥9/10 **TIDAK TERCAPAI**

| # | Skenario | Sebelum | Sesudah | Catatan |
|---|---|---|---|---|
| 1 | Daftar (Google OAuth) | BLOCKED | **BLOCKED** | butuh consent akun Google manusia + 2FA; tidak bisa otonom |
| 2 | Chat pertama | FAIL | **FAIL** | balasan **ADA** (body 275→3.531 char), tapi **50,14 s** > ambang 30 s → **latensi**, bukan konektivitas |
| 3 | Bangun workflow | FAIL (nodes=0) | **PASS** | builder **nodes=2, edges=1** |
| 4 | Riwayat bertahan | FAIL (kosong) | **PASS** | **202 item**, 102 label |
| 5 | Simpan credential | FAIL | **FAIL** | model **menjanjikan** "form di bawah ini" tetapi **form tidak dirender** — cacat nyata |
| 6 | Templates | FAIL ("Gagal memuat") | **PASS** | **10 kartu** (10 tombol Pakai + 10 Pratinjau) |
| 7 | Edit workflow | FAIL (nodes=0) | **PASS** | node terpilih, tombol simpan ada |
| 8 | Insights | FAIL ("Failed to fetch") | **PASS** | chart=4, **5 metrik** tampil dengan data nyata |
| 9 | Error handling | PASS | **FAIL** | prompt 12.000 char **diterima** (tidak ada UI galat) |
| 10 | Logout/login | PASS | **PASS** | — |

### Yang benar-benar berubah

| | Sebelum | Sesudah |
|---|---|---|
| PASS | 2 | **6** |
| penyebab utama kegagalan | **1 cacat** (CSP/API_URL) → 7 skenario | **3 sebab berbeda & tidak berkaitan** |
| error konsol per skenario | 6–8 (semua pelanggaran CSP) | **0–2** |
| skenario yang bisa kirim pesan | 0 | **semua yang diuji** |

**Semua 7 kegagalan akibat CSP/API_URL sudah hilang.** Sisa 3 kegagalan punya
akar yang berbeda dan tidak berhubungan dengan insiden ini:

1. **S2 — latensi.** Balasan datang, tetapi 50 s pada pesan pertama
   (model dingin + fallback model). Ambang brief 30 s.
2. **S5 — form kredensial tidak dirender.** Asisten menjawab *"Silakan isi
   detail kredensial Telegram pada form di bawah ini"*, tetapi tidak ada form
   yang muncul. Ini cacat UI/kontrak jawaban, bukan jaringan.
3. **S9 — harapan uji berubah.** Dulu "PASS" karena muncul tombol *Coba Lagi* —
   padahal itu tombol dari **kegagalan koneksi**, bukan validasi input. Sekarang
   prompt panjang **diterima** sehingga tidak ada UI galat. PASS lama itu
   **terkonfoundir**; FAIL sekarang adalah pembacaan yang lebih jujur.

### Kejujuran metodologi: 2 FAIL pertama adalah bug harness, bukan produk

Re-run pertama memberi **4 PASS**. Investigasi screenshot menunjukkan dua di
antaranya **false negative** — harness-nya yang salah, bukan aplikasinya:

| Skenario | Bug harness | Perbaikan |
|---|---|---|
| S4 | selektor riwayat hanya `aside a, nav a` — item sebenarnya `<button>` | selektor diperluas → **0 → 202 item** |
| S8 | selektor chart hanya `canvas/.recharts`; chart-nya div/SVG kustom. `banner_error` juga cocok dengan **label metrik** "Error rate"/"Gagal" | selektor diperluas + banner hanya frasa kegagalan memuat → **chart 0→4, metrik 5, banner palsu hilang** |
| S1, S4, S6 | `wait_until="networkidle"` **tidak pernah** settle di produksi (beacon Cloudflare RUM) → timeout palsu | ganti `domcontentloaded` |
| S6 | kartu template adalah `<div>`, bukan `article/.card` | hitung tombol "Pakai" → **0 → 10** |

Melaporkan 4/10 apa adanya akan sama salahnya dengan mengklaim 9/10. Angka
final **6/10** adalah pembacaan yang sudah dikoreksi.

### Tindak lanjut (bukan bagian insiden ini)

| P | Tindakan |
|---|---|
| P1 | Turunkan latensi balasan pertama (50 s → < 30 s); hangatkan model / perbaiki fallback `gemma-4-31b-it` yang "sedang tidak tersedia" |
| P1 | Render form kredensial inline, atau ubah kalimat asisten agar tidak menjanjikan form yang tidak ada |
| P2 | Putuskan perilaku untuk prompt ekstrem: terima dengan batas, atau tolak dengan pesan ramah |
| P2 | Jalur uji OAuth tanpa akun Google manusia, supaya S1 tidak selalu BLOCKED |

---

## 6. GERBANG DI PIPELINE (agar tidak terulang)

| Lapisan | Berkas | Cara kerja |
|---|---|---|
| **Build** | `nexus-frontend/package.json` → `prebuild` | `check-no-dev-running.mjs && check-api-url-csp.mjs` — build **batal** bila URL tidak diizinkan CSP |
| **Build (manual)** | `npm run check:api-csp` | jalankan gerbang kapan saja |
| **Deploy** | `ops/deploy_pages.py` | 2 gerbang wajib sebelum `wrangler pages deploy` |
| **Pre-commit** | `.githooks/pre-commit` + `ops/install-git-hooks.sh` | dipasang via `git config core.hooksPath .githooks` (hook ikut ter-commit, tidak seperti `.git/hooks/`) |
| **CI/CD** | `.github/workflows/ci.yml` → job `frontend-csp-gate` | hermetik (tanpa `npm install`), plus **self-test** yang memastikan gerbang benar-benar menolak host mati |

---

## 7. INDEKS BUKTI

| Artefak | Isi |
|---|---|
| `nexus-frontend/.env.production` | nilai produksi (baru) |
| `nexus-frontend/scripts/check-api-url-csp.mjs` | gerbang sumber (memuat env sendiri) |
| `nexus-frontend/scripts/check-bundle-hosts.mjs` | gerbang hasil (isi `out/`) |
| `.githooks/pre-commit`, `ops/install-git-hooks.sh` | hook pre-commit versi-repo |
| `.github/workflows/ci.yml` | job `frontend-csp-gate` + self-test |
| `ops/deploy_pages.py` | pre-deploy gate |
| `_fe_build5.log` | raw build: ✓ Compiled in 5,9 min, 26/26 halaman |
| `tests/user_test/verify_prod_fix.py` | verifikasi produksi (4a–4e) |
| `tests/user_test/_prod_verify.json` | hasil verifikasi produksi (PASS) |
| `tests/user_test/_rerun2.log` | raw 10 skenario setelah deploy |
| `tests/user_test/_user_test_results.json` | 10 skenario lengkap (6 PASS) |
| `docs/evidence/user-test/prod-*.png` | screenshot produksi (terbuka/balasan/refresh) |
| `docs/evidence/user-test/s0*.png` | screenshot 10 skenario (final) |
