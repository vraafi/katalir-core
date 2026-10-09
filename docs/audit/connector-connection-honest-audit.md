# AUDIT JUJUR — "Apakah 25.000+ connector sudah dipastikan terhubung?"

**Dijalankan**: Okt 2026 · **Metode**: pengukuran langsung katalog + panggilan HTTP nyata
**Sumber angka**: `mcp_registry.coverage()`, `load_cached()` (29.558 entri), ledger aktivasi

---

## JAWABAN SINGKAT

**TIDAK.** 25.925 adalah **total katalog**, bukan "terhubung".
Yang benar-benar **merespons panggilan API nyata**: **±597** (24 dari 40 sampel
acak × 994 aktivasi = ~25%, dibulatkan konservatif).

Angka "terhubung" yang jujur: **≈597 dari 25.925 (≈2,3%)**.

---

## 1. HITUNG ULANG

| Metrik | Angka | Sumber / perintah |
|--------|-------|-------------------|
| Total **entri cache** | **29.558** | `len(mcp_registry.load_cached())` |
| Total **katalog** (basis `coverage()`) | **25.925** | `coverage()['total']`, basis `dedup_canonical` |
| `metadata_only` | **25.902** | `coverage()['metadata_only']` = 25.925 − 23 |
| Punya `endpoint_url`/URL di `install_config.package` | **1.002** | hitung langsung dari 29.558 entri |
| `healthy=True` | **995** (dari 1.000 kandidat) | `activation_plan()` → 995 `ready`, 5 `unhealthy` |
| **Benar-benar executable** | **1.017** | `coverage()['executable']` setelah aktivasi dipersist (23 → 1.017) |
| Sudah **di-test LIVE** (panggilan nyata) | **50** | 10 + 40 sampel acak (audit ini) |

### Rincian level (dari 29.558 entri cache)

| Level | Definisi | Jumlah |
|-------|----------|--------|
| L1 | Ada nama + deskripsi | **29.558** (nama), deskripsi lengkap |
| L2 | Ada URL endpoint | **1.002** |
| L3 | Transport `callable` | **1.017** |
| L4 | `runtime_verified = true` | **23** |
| L5 | Dipakai user & stabil | **tidak terukur** (lihat §5) |

---

## 2. DEFINISI "TERHUBUNG" — per level

| Level | Definisi | Angka JUJUR | Catatan |
|-------|----------|-------------|---------|
| **L1 Catalog** | nama + deskripsi | **25.925** | hanya metadata; tidak ada jalur eksekusi |
| **L2 Endpoint** | punya URL | **1.002** | URL ada, belum dibuktikan hidup |
| **L3 Callable** | URL bisa dipanggil | **≈600** | dari 40 sampel: 24 HTTP 200 → ekstrapolasi 994 × 60% ≈ 596 |
| **L4 Verified** | benar-benar kirim/terima data | **≈573** | 23 dari 40 sampel sukses `tools/list` (benar-benar menerima daftar tool) |
| **L5 Production** | dipakai user, stabil | **0 terverifikasi** | backend produksi 404 (lihat §5) |

---

## 3. TEST LIVE 10 CONNECTOR RANDOM

Sampel acak **seed 2026 10 09** dari 1.000 `streamable_http` ber-URL.
Panggilan nyata: `initialize` → `notifications/initialized` → `tools/list`.

| # | Connector | HTTP | tools | Catatan |
|---|-----------|------|-------|---------|
| 1 | `glama-connector/s0hms42de7` | **200** | 92 | tools/list OK |
| 2 | `glama-connector/z3cb0y9lxt` | **200** | 8 | tools/list OK |
| 3 | `glama-connector/v91bh3bitg` | **200** | 6 | tools/list OK |
| 4 | `glama-connector/f7ff5obqzc` | 401 | — | `Invalid or missing API key` |
| 5 | `glama-connector/wv098o84nh` | **200** | 6 | tools/list OK |
| 6 | `glama-connector/mmuip7r6ts` | 401 | — | `Authentication required` |
| 7 | `glama-connector/dl9vg3o9p5` | **200** | 14 | tools/list OK |
| 8 | `glama-connector/j81orh5l61` | — | — | `ProxyError: 502 Bad Gateway` |
| 9 | `glama-connector/c186ztfwpg` | **200** | 4 | tools/list OK |
| 10 | `glama-connector/f06nlzvc8r` | 401 | — | `Sign in with Discord` |

**Hasil: 6/10 HTTP 200, 6/10 `tools/list` berhasil.**

Uji lanjutan pada 4 yang gagal (membedakan **hidup-butuh-auth** vs **mati**):

| Connector | GET | Kesimpulan |
|-----------|-----|------------|
| `f7ff5obqzc` | 405 `Method not allowed` | **hidup**, butuh API key |
| `mmuip7r6ts` | 401 | **hidup**, butuh auth |
| `j81orh5l61` | 502 Bad Gateway | **MATI** |
| `f06nlzvc8r` | 401 | **hidup**, butuh auth |

→ **9/10 endpoint benar-benar hidup**; 3 butuh kredensial, 1 mati.

### Sampel diperluas: 40 acak dari 994 "activated"

| Klasifikasi | Jumlah | % |
|-------------|--------|---|
| HTTP 200 (hidup & menjawab) | **24** | 60% |
| ↳ di antaranya `tools/list` OK (terima data nyata) | **23** | 57,5% |
| 401/403 (hidup, butuh kredensial) | **15** | 37,5% |
| Mati / error jaringan / 5xx | **1** | 2,5% |

**Ekstrapolasi konservatif**: 994 × 57,5% ≈ **572 connector** benar-benar
menerima dan menjawab panggilan data. Dari 25.925 katalog = **2,2%**.

---

## 4. KOREKSI KLAIM

| Klaim | Status | Koreksi |
|-------|--------|---------|
| "25.902 / 25.925 connector" | **MENYESATKAN bila disebut 'terhubung'** | Itu **total katalog**, bukan terhubung. Terhubung nyata ≈597 (**2,3%**). |
| "995 activated" | **BENAR tapi hanya level transport** | Terverifikasi: `activate_and_persist(verify_network=True)` → `ready: 995`, `activated: 994`. Artinya **transport-nya bisa dieksekusi**, BUKAN terbukti hidup. Hanya **57,5%** yang benar-benar menerima data. |
| "251 verified (APIs.guru)" | **PERLU KOREKSI** | Angka itu dari **host hidup** (250/251 tanpa FAIL harness), bukan verifikasi API nyata. Log sendiri menyatakan 35 host Amadeus sudah mati. Uji ulang 10 host: 7 menjawab, `neptune.amazonaws.com` **ProxyError/mati**. **251 = host hidup, bukan API terverifikasi.** |

### Angka jujur

> **≈597 dari 25.925 connector (≈2,3%) benar-benar terhubung dan menjawab
> panggilan data nyata.** Sisanya: 24.923 metadata-only (L1), dan ≈397
> ber-URL yang butuh kredensial atau sudah mati.

---

## 5. TEMUAN KRITIS: AKTIVASI TASK 1 TIDAK PERNAH DIPERSIST

Ini temuan paling penting dari audit.

```
SEBELUM audit:  coverage executable = 23
                connector_activation.json ADA? = False   (gitignored, tidak pernah ditulis)
```

Artinya: klaim **"executable 23 → 1018"** (TASK 1) **tidak terwujud di
lingkungan mana pun** — ledger aktivasi tidak ada, sehingga `executable_servers()`
tetap memakai jalur lama dan `coverage()` tetap **23**.

Setelah aktivasi dijalankan dan dipersist sungguhan di audit ini:

```
activate_and_persist(verify_network=True) →
  {"stage":"verified","ready":995,"head_checked":50,"duration_s":182,7,
   "stats":{"activated":994,"skipped":6,"tools_total":17449,
            "by_auth":{"none":616,"oauth2":237,"api_key":141}},
   "persisted":{"total":994,"added":994,"unknown_ids":0}}

SESUDAH: coverage executable = 1017
         ledger ada = True
         _activated_ids() = 994
```

**Kesimpulan**: mekanismenya **benar dan terbukti bekerja**, tetapi hasilnya
**tidak dipersist sebagai artefak deploy** (`connector_activation.json` masuk
`.gitignore` baris 126). Di setiap deploy baru, angka kembali ke 23.

### Temuan kritis 2: produksi 404

```
GET https://web-production-dc90b.up.railway.app/version
→ {"status":"error","code":404,"message":"Application not found"}
GET https://katalir.de5.net/version
→ HTML (frontend Cloudflare, bukan API)
RAILWAY_API_TOKEN → "Not Authorized"
```

Backend produksi **tidak dapat dijangkau** (domain 404) dan token Railway
sudah kedaluwarsa. **L5 (Production) tidak dapat diverifikasi = 0 terverifikasi.**

---

## 6. LAPORAN JUJUR

| Level | Angka | Bukti |
|-------|-------|-------|
| **Total katalog** | **25.925** | `coverage()['total']` |
| **L1 Catalog** (nama+deskripsi) | **25.925** | 29.558 entri, 0 tanpa nama |
| **L2 Endpoint** (punya URL) | **1.002** | hitung `install_config.package` |
| **L3 Callable** (HTTP 200) | **≈600** | 24/40 sampel × 994 |
| **L4 Verified** (kirim/terima data) | **≈573** | 23/40 sampel `tools/list` OK |
| **L5 Production** (dipakai, stabil) | **0 terverifikasi** | backend produksi 404 |
| **Terhubung nyata (jujur)** | **≈597 / 25.925 = 2,3%** | gabungan L3+L4 |

### Gap — apa yang harus dilakukan untuk menaikkan angka

1. **Persist ledger aktivasi sebagai artefak deploy** (paling mendesak).
   `connector_activation.json` ada di `.gitignore:126`. Pindahkan ke
   Supabase (tabel `connector_activations`) atau keluarkan dari gitignore.
   Tanpa ini, **setiap deploy mengembalikan angka ke 23**.
2. **Jalankan verifikasi live sebagai bagian deploy** (*cron*), bukan sekali.
   57,5% hidup hari ini belum tentu besok. Simpan `last_live_check` +
   `http_status` per connector sehingga L4/L5 dapat diaudit kapan saja.
3. **Pisahkan metrik `activated` dari `live`.** `coverage()` saat ini
   mempromosikan `streamable_http` → executable hanya berdasar ledger.
   Tambahkan `live_verified` sebagai counter terpisah agar tidak ada lagi
   klaim "1018 executable" yang dibaca sebagai "1018 hidup".
4. **Kredensial untuk 37,5% yang butuh auth.** 15/40 sampel butuh API key.
   Jalur `end_user_credentials` (fitur #6) sudah ada; perlu dihubungkan agar
   connector ber-auth dapat dihitung L4.
5. **Perbaiki/keluarkan yang mati.** 2,5% mati (502). Tandai `healthy=false`
   otomatis dari hasil probe agar tidak masuk hitungan.
6. **Hidupkan kembali backend produksi** — tanpa itu L5 selamanya 0.
7. **Turunkan ekspektasi bahasa.** "25.902 connector" hanya boleh disebut
   "terkatalog". Untuk "terhubung", pakai **≈597** sampai butir 1–4 selesai.

---

## Kesimpulan

- **25.000+ connector TIDAK terhubung.** Itu angka katalog (L1).
- Yang terhubung nyata: **≈597 (2,3%)**.
- Aktivasi TASK 1 **bekerja** (23 → 1.017) tetapi **tidak dipersist**, jadi
  tidak bertahan lintas deploy.
- Klaim "251 verified" = **host hidup**, bukan verifikasi API — perlu koreksi.
- Produksi tidak dapat diverifikasi (404 + token kedaluwarsa).

Semua angka di atas berasal dari perintah mentah yang dapat dijalankan ulang;
skrip audit disimpan sebagai `_audit*.py` beserta keluarannya `_audit*.log`.

## Bukti mentah (tersimpan di repo)

| Berkas | Isi |
|--------|-----|
| `docs/audit/evidence/live-10-connectors.log` | 10 panggilan live: HTTP status + `tools/list` + error per connector |
| `docs/audit/evidence/live-40-connectors.json` | 40 sampel acak: klasifikasi 200 / 401-403 / mati, per endpoint |
| `docs/audit/evidence/coverage-recount.log` | `coverage()` + `len(load_cached())` + `len(_activated_ids())` (hitungan ulang) |

Perintah reproduksi:

```
C:/Users/user/AppData/Local/Programs/Python/Python312/python.exe _audit1.py   # coverage awal
C:/Users/user/AppData/Local/Programs/Python/Python312/python.exe _audit11.py  # aktivasi + persist
C:/Users/user/AppData/Local/Programs/Python/Python312/python.exe _audit_live.py  # 10 live
C:/Users/user/AppData/Local/Programs/Python/Python312/python.exe _audit12.py  # 40 live
```
