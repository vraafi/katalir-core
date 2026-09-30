# Investigasi API 2026 — Supabase & Railway

- **Tanggal akses dokumentasi:** 2026-09-30
- **Commit saat investigasi:** `ffab250`
- **Status:** READONLY. Tidak ada credential yang dirotasi, dimigrasikan, atau
  direstart. Tidak ada file produk yang diubah.

> **Tujuan:** menguji ulang hipotesis "rotasi gagal karena credential
> bermasalah" terhadap kemungkinan lain — bahwa **metode/API yang saya pakai
> sudah usang di 2026**. Hasil: hipotesis itu **sebagian BENAR, sebagian
> SALAH.**

---

## ⚠️ KOREKSI TERHADAP KESIMPULAN SEBELUMNYA

Saya sebelumnya menyimpulkan: *"Fingerprint identik + kunci lama masih
`HTTP 200` → rotasi gagal, tidak ter-save di Supabase."*

**Kesimpulan itu terlalu cepat, dan untuk Railway saya ternyata salah total.**

| Klaim lama | Status setelah riset 2026 |
|---|---|
| "Railway 403 = token expired" | ❌ **SALAH.** 403 = **Cloudflare `error code: 1010`** (blokir signature `Python-urllib`). Dengan User-Agent normal → `HTTP 200`. Token-nya sendiri memang tidak sah, tapi itu masalah **terpisah**. |
| "Rotasi Supabase gagal tersimpan" | ⚠️ **BELUM TERVERIFIKASI.** Dokumentasi resmi **tidak** menyatakan rotasi legacy key dihentikan. Yang terbukti: project **belum selesai migrasi** ke key baru. |
| "Metode rotasi lama tidak didukung" | ❌ **TIDAK DITEMUKAN** di dokumentasi. Halaman `rotating-anon-service-and-jwt-secrets` memang **404** (dipindahkan), tapi halaman API Keys resmi masih menjelaskan rotasi lewat Dashboard. |

Sesuai [10], saya **berhenti mengklaim "rotasi gagal"** sampai metode
verifikasi yang benar di 2026 dipakai.

---

## SECTION 1 — Supabase API 2026

### 1.1 Sumber resmi

**Sumber 1 — [supabase.com/docs/guides/api/api-keys](https://supabase.com/docs/guides/api/api-keys)** (akses 2026-09-30)

> "Supabase is deprecating the anon and service_role keys **by the end of
> 2026**. Use the publishable (`sb_publishable_xxx`) and secret
> (`sb_secret_xxx`) keys instead."

| Type | Format | Privilege | Status |
|---|---|---|---|
| Publishable key | `sb_publishable_...` | Low (RLS-limited) | **Baru** |
| Secret key | `sb_secret_...` | Elevated (bypass RLS) | **Baru** |
| anon JWT | `eyJ...` | Low | **Legacy** |
| service_role JWT | `eyJ...` | Elevated | **Legacy** |

Catatan kompatibilitas yang **kritis untuk Katalir**:

> "Send publishable and secret keys on the `apikey` header, **not** on
> `Authorization: Bearer`. Because the keys aren't JWTs, anything that tries
> to verify one as a JWT fails."

`security.py:351` Katalir memverifikasi JWT secara lokal (`_decode_local`).
Kunci `sb_secret_` **tidak akan lolos** verifikasi itu — dan itu memang benar
secara desain, karena `sb_secret_` sudah diotorisasi di API Gateway.

**Sumber 2 — [supabase.com/docs/guides/auth/signing-keys](https://supabase.com/docs/guides/auth/signing-keys)** (akses 2026-09-30)

| Aspek | Legacy JWT secret | JWT signing keys |
|---|---|---|
| Zero-downtime rotation | "Downtime, sometimes being significant" | "No downtime, as each rotation step is independent" |
| Users signed out saat rotation | **"Currently active users get immediately signed out"** | "No users get signed out" |
| Rotasi API key | "anon and service_role **must be rotated simultaneously**" | "can be **independently managed**" |

> **"Can you still use an old anon and service-role API keys after enabling
> the publishable and secret keys?" → "**Yes.** ... transition between the
> API keys with **zero downtime** by gradually swapping your clients while
> both sets of keys are active."**

**Ini membatalkan kekhawatiran "rotasi legacy tidak didukung".** Kedua sistem
boleh hidup berdampingan.

**Sumber 3 — halaman rotasi legacy (404)**

`https://supabase.com/guides/troubleshooting/rotating-anon-service-and-jwt-secrets`
→ **HTTP 404 Not Found** (akses 2026-09-30). Halaman ini tidak lagi
dipublikasikan di lokasi lama. Ini kemungkinan besar **sumber utama**
persepsi "rotasi tidak bisa dilakukan" — halaman hilang, bukan fiturnya
dihapus.

### 1.2 Bukti lokal — format key Katalir

Dari `.env.bak-*` (nilai tidak dicetak, hanya klasifikasi):

```
SUPABASE_SERVICE_ROLE_KEY     JWT (eyJ...)          len=219   LEGACY
SUPABASE_SERVICE_KEY          JWT (eyJ...)          len=219   LEGACY
SUPABASE_KEY                  JWT (eyJ...)          len=208   LEGACY (anon)
SUPABASE_PUBLISHABLE_KEY      sb_publishable_...    len=46    BARU
```

Decode claims (tanpa verifikasi signature — hanya baca payload):

```
SUPABASE_SERVICE_ROLE_KEY
  header : {"alg":"HS256","typ":"JWT"}
  role   : service_role
  ref    : qmukkphwaajzbqjrcvaz
  exp    : 2104080147  -> 2036 (JWT 10 tahun, sesuai docs)
SUPABASE_KEY
  role   : anon
  ref    : qmukkphwaajzbqjrcvaz
```

`alg=HS256` = **symmetric** — persis sistem legacy yang "[n]o longer
recommended".

### 1.3 Bukti langsung — key baru sudah AKTIF di project

```
GET https://<ref>.supabase.co/rest/v1/workflows?select=id&limit=1

  dengan sb_publishable_ ...       -> HTTP 200  rows=0
  dengan legacy service_role JWT   -> HTTP 200  rows=1
```

Dua-duanya `200`. Yang membedakan: `sb_publishable_` **mematuhi RLS**
(`rows=0`, karena anon tidak punya policy sejak fix R-1), sedangkan

### 1.4 Mengapa ini menjelaskan "rotasi tidak terlihat"

Ada penjelasan yang lebih mungkin daripada "reset gagal":

Dokumentasi menyatakan rotasi JWT legacy akan **memotong semua sesi aktif**:

> "Users signed out during rotation — Legacy: **Currently active users get
> immediately signed out**."

Artinya rotasi `service_role` legacy **bukan sekadar "klik reset"**. Ia adalah
breaking change untuk seluruh user yang sedang login, plus `SUPABASE_JWKS`
(240 char, cache JWKS di `.env`) harus ikut berubah supaya verifikasi lokal
di `security.py` tidak gagal.

Kemungkinan besar itulah yang menahan rotasi — dan itu **keputusan yang
wajar**, bukan kegagalan.

### 1.5 Hipotesis pooler-cache: TIDAK terkonfirmasi

Saya tidak bisa mengonfirmasi klaim "pooler cache menahan password baru".
Yang saya bisa buktikan:

```
koneksi pooler dengan password dari .env.bak-*  -> PASS
fingerprint password .env vs 5 backup           -> IDENTIK
```

Keduanya konsisten dengan **dua** hipotesis yang belum bisa dipisahkan tanpa
akses Dashboard:

| Hipotesis | Cara membedakannya (perlu Anda) |
|---|---|
| (a) Reset tidak pernah tersimpan | Settings → Database → lihat "Last password reset" |
| (b) Reset tersimpan tapi pooler/lokal masih pakai nilai lama | Setel ulang, lalu `Restart` project, tunggu, tes lagi |

**Saya tidak mengklaim mana yang benar.** Test koneksi pooler saja **tidak
cukup** sebagai bukti, sesuai [10].

---

## SECTION 2 — Railway API 2026

### 2.1 Endpoint: MASIH VALID

**Sumber — [railway.com/api-reliability.md](https://railway.com/api-reliability.md)** (akses 2026-09-30)

> "The public API is GraphQL at a single endpoint,
> `https://backboard.railway.com/graphql/v2`."

`RAILWAY_GRAPHQL_VALID_2026 = yes`. Endpoint yang saya pakai **tidak** usang.

### 2.2 Format error resmi — dan ini yang membatalkan diagnos saya

Dari sumber yang sama:

> "Railway follows the GraphQL error convention, not HTTP status alone.
> Always inspect the `errors` array, not just the status code."
>
> "**HTTP 200 with an `errors` array** — execution and authorization
> failures. A query that runs but is denied returns 200; the failure is in
> `errors`."
>
> "`INTERNAL_SERVER_ERROR` — An unexpected error, or an **authorization
> denial** (message `Not Authorized`) | **200**"

Artinya: **penolakan otorisasi Railway resmi mengembalikan HTTP 200, bukan
403.** Kalau saya melihat 403, itu **bukan** respons normal dari Railway.

### 2.3 Bukti A/B — 403 itu Cloudflare, bukan Railway

Uji identik, hanya `User-Agent` yang berbeda:

```
$ python (UA default urllib)  -> HTTP 403  body='error code: 1010'
$ User-Agent: curl/8.4.0     -> HTTP 200  errors: "Not Authorized"
$ User-Agent: Mozilla/5.0    -> HTTP 200  errors: "Not Authorized"
```

Response header saat berhasil membuktikan Cloudflare ada di depan tapi
**tidak memblokir**:

```
Server: cloudflare
CF-RAY: a4337ce7ccfcb5a2-CGK
x-ratelimit-limit: 1000
x-ratelimit-remaining: 999
```

`error code: 1010` adalah kode khas Cloudflare: *browser signature diblokir*.
`urllib` bawaan Python menandai dirinya sebagai bot, dan Cloudflare
menolaknya **sebelum** request sampai ke Railway.

> **Kesimpulan 2.3: `RAILWAY_403_ROOT_CAUSE = cloudflare`.** Hipotesis Anda
> benar. 403 itu blokir edge, **bukan** bukti token kadaluarsa.

### 2.4 Tapi ada masalah kedua yang nyata

Setelah Cloudflare dilewati, Railway membalas:

```json
{"errors":[{"message":"Not Authorized",
            "extensions":{"code":"INTERNAL_SERVER_ERROR"},
            "traceId":"1923276929262788132"}],
 "data":null}
```

Jadi **ada dua masalah terpisah**:

1. **403 Cloudflare** — bug di skrip saya (UA bot). Sudah terisolasi.
2. **"Not Authorized"** — token memang tidak sah untuk query account-level.

Token di `.env.bak-20260926-150120` berbentuk UUID 36 char. Dokumentasi
Railway menyebut tiga tipe token: **account**, **workspace**, dan
**project**. Token bertipe project **tidak bisa** menjalankan query
level-account seperti `me { id account { … } }`.

`RAILWAY_403_ROOT_CAUSE` saya perbaiki menjadi dua sebab:
`cloudflare` (untuk 403) + `token/scope` (untuk "Not Authorized").

### 2.5 Perbaikan yang harus diterapkan ke skrip

`scripts/security/railway_deploy_status.py` perlu dua perubahan:

1. Kirim `User-Agent` normal (bukan `Python-urllib/…`).
2. **Periksa `errors` array pada HTTP 200** — jangan hanya status code, karena
   itu persis yang membuat saya salah diagnosa.


`service_role` **bypass RLS** (`rows=1`). Persis seperti dokumentasi.

> **Kesimpulan 1.3: sistem key baru SUDAH AKTIF di project Katalir.** Ini
> **migrasi sebagian selesai** — key baru ada dan berfungsi, tapi semua
> client masih memakai key legacy.


---

## SECTION 3 — Status migrasi project Katalir

```
SUPABASE_PROJECT_KEY_TYPE   = mixed   (legacy JWT + sb_publishable_)
SUPABASE_MIGRATION_STATUS   = migrating
  - sistem key baru  : AKTIF (sb_publishable_ -> HTTP 200, RLS aplicado)
  - secret key baru  : BELUM dipakai di client mana pun
  - client aktif     : 100% masih legacy HS256 JWT
SUPABASE_JWT_SIGNING_KEYS_AVAILABLE = unknown (butuh akses Dashboard)
SUPABASE_NEW_API_KEYS_EXIST = yes (setidaknya sb_publishable_)
```

Yang **terbukti** dari luar (tanpa Dashboard):

| Fakta | Bukti |
|---|---|
| Project punya `sb_publishable_` | ada di `.env.bak-20260917` |
| Key itu **berfungsi** | `GET /rest/v1/workflows` → `HTTP 200` |
| Key itu **mematuhi RLS** | `rows=0` (anon), bukan `rows=1` |
| Client masih legacy | `service_role` = JWT HS256, `exp` 2036 |
| Legacy masih berfungsi | `service_role` → `HTTP 200`, `rows=1` |

Yang **belum** bisa diverifikasi tanpa Dashboard:

- Apakah tab **JWT Signing Keys** sudah ada (indikator migrasi penuh).
- Apakah `sb_secret_` sudah pernah dibuat.
- Kapan `SUPABASE_DB_PASSWORD` terakhir di-reset.

Saya **tidak** mengarang jawaban untuk tiga hal itu.

---

## SECTION 4 — Langkah migrasi (jika Anda setuju)

### Opsi A — Migrasi ke key baru (rekomendasi 2026)

Ini jalur yang didukung dokumentasi dan **tidak** memotong sesi user.

**A1. Buat secret key baru**
Dashboard → Settings → **API Keys** → Publishable and secret API keys →
*Create new API keys*. Akan dapat `sb_secret_...`.

**A2. Ganti backend, satu per satu**
```
database.py:46   SUPABASE_SERVICE_ROLE_KEY  ->  SUPABASE_SECRET_KEY=sb_secret_...
api_server.py    (verifikasi JWT lokal)      ->  biarkan; sb_secret_ tidak lewat itu
```
Kunci baru dikirim di header `apikey`, **bukan** `Authorization: Bearer`.
Artinya `security.py` **tidak** memverifikasinya — itu benar, karena
API Gateway sudah mengotorisasikannya.

**A3. Ganti frontend**
`NEXT_PUBLIC_SUPABASE_ANON_KEY` (JWT) → publishable key `sb_publishable_...`.

**A4. Update Railway variables**, redeploy, verifikasi.

**A5. Nonaktifkan legacy key** — Dashboard → API Keys, cek **"last used"**
indicator sampai 0, baru deactivate. Bisa diaktifkan kembali.

> Rotasi ini **tidak** meng-logout user, dan tidak butuh downtime.

### Opsi B - Rotasi legacy key (tidak direkomendasikan)

。 Anda hanya ingin credential lama mati sekarang, tanpa migrasi:

- Rotasi legacy JWT secret **akan** logout semua sesi aktif.
- `SUPABASE_JWKS` harus ikut di-update.
- Harus rotasi `anon` + `service_role` **bersamaan**.
- Tidak akan menaikkan masa depan — deprecation tetap akhir 2026.

**Rekomendasi: Opsi A.** Opsi B hanya relevan kalau ada insiden yang
memaksacredential lama dimatikan hari ini.

---

## SECTION 5 — Metode verifikasi yang BENAR di 2026

| Yang ingin dibuktikan | Cara benar (2026) | Cara yang SALAH |
|---|---|---|
| `sb_secret_` baru bekerja | `curl -H "apikey: sb_secret_..." /rest/v1/...` | decode sebagai JWT |
| RLS untuk anon | publishable key → `rows=0` |_and_ mengira 0 = error |
| Legacy tidak lagi dipakai | Dashboard → API Keys → **last used** = 0 | mengira 200 = "aman" |
| DB password baru berlaku | Dashboard → Database → **Last password reset** | hanya tes pooler |
| Railway deploy status | UA normal + **periksa `errors` di HTTP 200** | andalkan status code |

**Dua aturan yang saya langgar dan perbaiki di sini:**

1. **Status code saja tidak cukup untuk Railway.** Auth denial resmi
   membalas `200` + `errors`. Skrip `railway_deploy_status.py` harus
   mengirim User-Agent normal **dan** membaca `errors`.
2. **Tes pooler bukan bukti rotasi DB.** Bisa jadi reset-nya tidak tersimpan,
   bisa jadi cache. Butuh konfirmasi dari Dashboard.

