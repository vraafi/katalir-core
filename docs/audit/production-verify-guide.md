# Panduan Verifikasi Production Manual

Panduan ini untukMemeriksa produksi **secara visual di browser**. Verifikasi
otomatis (Playwright) menutup kasus happy path saja; langkah di bawah
menangkap hal yang tidak bisa dilihat script: sesi login sungguhan,
state setelah klik, dan kondisi yang hanya muncul di browser nyata.

Audit terakhir: 2026-09-28, deploy `352f633`.

---

## 0. Aturan emas

Status **200 tidak berarti fungsional**. Regresi yang yang pernah rusak
penuh: semua route membalas 200 sementara setiap panggilan API gagal,
karena `NEXT_PUBLIC_API_URL` ter-inline `localhost:8000` ke bundle.
Selalu cek *konten yang benar-benar tampil*, bukan kode status.

---

## 1. Login

1. Buka jendela incognito (abaikan sesi lama).
2. Buka `https://katalir.de5.net`.
3. Klik "Start now" → login Google.
4. Pastikan `/chat` terbuka dan composer terisi.

**Gagal kalau:** masih terlihat "Silakan masuk dulu" setelah login.

---

## 2. Halaman Integrasi (paling rawan)

1. Buka `/integrations` dalam keadaan sudah login.
2. **Verifikasi daftar katalog muncul** — bukan macet di "Loading...".
   Tunggu 5-10 detik; itu normal.
3. **Verifikasi search bar berfungsi** — ketik `cloudflare`, daftar
   menyaring tanpa reload halaman.
4. Klik satu kartu (mis. **Cloudflare**).
5. **Verifikasi halaman detail tampil:**
   - judul **Cloudflare**
   - baris **Tools (20)**
   - transport metadata **composio-remote**
6. **Harus TIDAK** menampilkan "Integrasi tidak ditemukan".

**Gagal kalau:** macet di "Loading..." → Hampir pasti `NEXT_PUBLIC_API_URL`
salah. Periksa Network tab: request ke `localhost:8000` = regresi.
Request ke `*.up.railway.app` = benar.

---

## 3. Halaman Detail via URL langsung

Alur di atas mengambil slug dari klik. Uji juga jalur query param:

`https://katalir.de5.net/integrations/catalog?slug=cloudflare`

Harus menampilkan **Cloudflare** + **Tools (20)**.

JANGAN memakai `/integrations/cloudflare`. Static export hanya
menghasilkan satu slug (`generateStaticParams` → `[{ slug: "catalog" }]`),
sehingga bentuk itu **404**. Ini perilaku yang diharapkan, bukan bug.

---

## 4. Screenshot untuk materi marketing

Screenshot yang sudah terverifikasi ada di `docs/marketing/screenshots/`:

- `self-healing-retry.png` — kartu retry (RETRY 1/5, 2/5) + saran forum
- `self-healing-escalate.png` — 5 retry lalu escalate + saran
- `self-healing-credential.png` — gagal-cepat, tanpa retry
- `integration-detail-desktop.png` — halaman detail integrasi

> Catatan: tiga screenshot `self-healing-*` diambil dengan sesi dummy
> lokal karena tidak ada token E2E yang tersedia. Semua endpoint di-stub,
> jadi token tidak pernah menyentuh server — tetapi account yang tampil
> di pojok kiri bawah adalah email dummy, bukan akun asli. Jangan memakai
> ketiga screenshot ini untuk materi publik tanpa noting hal ini.

---

## 5. Cara melaporkan

Kalau ada langkah gagal, laporkan:

```
STEP=<nomor> GAGAL
YANG_DIHARAPKAN=<...>
YANG_MUNCUL=<...>
SCREENSHOT=<path>
```
