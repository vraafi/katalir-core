# Model Gemini Gratis — Temuan Empiris 14/15 Okt 2026

Pertanyaan yang dijawab: *"Repo terbaik Okt 2026 untuk API key Google AI Studio supaya
memunculkan model yang bisa dipakai gratis? Katalir cuma punya 1 model Gemini, padahal
saya punya 10+ API key."*

Jawaban singkat: **premisnya perlu dikoreksi dua kali**, dan akar masalahnya bukan
"repo yang kurang" — melainkan **sumber daftar picker** di Katalir.

---

## 1. Koreksi premis #1 — bukan 1 model, tapi 5

`GET /models` produksi (probe 2026-10-14, `models_after.json`) menyajikan **12 model**,
5 di antaranya Gemini:

| # | id | provider |
|---|---|---|
| 1 | `gemini-2.5-flash` | Gateway · google_gemini |
| 2 | `gemini-2.5-flash-lite` | Gateway · google_gemini |
| 3 | `gemini-3-flash-preview` | Gateway · google_gemini |
| 4 | `gemini-3.5-flash-lite` | Gateway · google_gemini |
| 5 | `gemini-3.8-flash` | Gateway · google_gemini |

Tapi jumlah **sebenarnya yang bisa dilayani** jauh lebih banyak — lihat §3.

## 2. Koreksi premis #2 — "free tier = Flash-Lite saja" itu MITOS untuk API

Beberapa media (3–9 Okt 2026) melaporkan Google membatasi free tier ke Flash-Lite
sejak 9 Okt 2026. **Untuk API (AI Studio) laporan itu tidak berlaku** — minimal untuk
kunci kita. Bukti: `gemini-3.8-flash`, `3.7-flash`, `3.6-flash`, `3.5-flash`,
`2.5-flash` semua menjawab **200 OK** di free tier.

Kebijakan 9 Okt itu menyasar **aplikasi konsumen Gemini (Web/App)**, bukan endpoint
`generativelanguage.googleapis.com`. Media mencampur keduanya.

> Konsekuensi: keputusan lama "gemma tidak bisa dilayani, hapus dari picker" juga perlu
> diperiksa ulang — lihat §5.

## 3. Hasil probe — 14 model benar-benar gratis

Metode (`probe_gemini_free_models_v2.py`):
1. `client.models.list()` → katalog **otoritatif** dari Google (63 model untuk kunci ini).
2. Saring ke model teks-chat → 19 kandidat.
3. `generate_content` 1 kata per model.
4. Yang GAGAL diuji ulang pada 2 kunci lain → membedakan *entitlement kunci* dari
   *model memang tidak tersedia*.

### ✅ BISA DIPAKAI GRATIS (14)

| model | catatan |
|---|---|
| `gemini-3.8-flash` | **terbaru & terkuat yang gratis** (OK via `GEMINI_KEY_3`) |
| `gemini-3.7-flash` | OK |
| `gemini-3.6-flash` | OK |
| `gemini-3.5-flash` | OK |
| `gemini-3.5-flash-lite` | default Katalir sekarang |
| `gemini-3.1-flash-lite` | OK |
| `gemini-3.1-flash-lite-preview` | OK |
| `gemini-3-flash-preview` | OK |
| `gemini-2.5-flash` | OK (kadang lambat: 22 s pada probe pertama) |
| `gemini-2.5-flash-lite` | OK |
| `gemini-flash-latest` | alias |
| `gemini-flash-lite-latest` | alias |
| `gemma-4-31b-it` | OK via `GEMINI_KEY_2` (kunci 1 gagal — entitlement per-kunci) |
| `gemma-4-26b-a4b-it` | OK |

### ❌ TIDAK BISA (5) — semuanya kelas Pro/Argon berbayar

`gemini-2.5-pro` · `gemini-3.1-pro-preview` · `gemini-3.1-pro-preview-customtools` ·
`gemini-4-argon` · `gemini-pro-latest`

`gemini-4-argon` **ada di katalog** (rilis 30 Sep / stabil 13 Okt 2026, konteks output
1 juta token) tapi free tier menolak dengan **429 RESOURCE_EXHAUSTED** → memang berbayar,
bukan bug. Harga intro dilaporkan diskon 50%.

## 4. Akar masalah sebenarnya — sumber daftar picker

Ini temuan intinya, dan **bukan** soal kurang repo:

```
   PICKER (/models)                        YANG BENAR-BENAR MELAYANI
   ─────────────────                       ─────────────────────────
   model_discovery.get_available_models()  api_server → gemini_key_pool
        │                                        │
        └─ gateway_roster.roster_catalog()       └─ 13 kunci → API Gemini langsung
           (nexus-gateway-vps)                      client.models.list() = 63 model
           → 5 model Gemini                          → 14 model gratis terbukti

   GEMINI_FALLBACK (3 id keras) hanya dipakai bila gateway MATI
```

* `_resolve_model()` (api_server.py:740) memvalidasi permintaan terhadap
  `md.get_available_models()` — **daftar gateway**, bukan katalog kunci.
  Model yang tak ada di sana diganti default dengan `fallback=True` → spanduk
  *"Model yang Anda pilih tidak tersedia"*. Ini persis mekanisme bug gemma.
* Jalur eksekusi utama justru **langsung** ke pool 13 kunci (`LLM_PROVIDER=gemini`),
  yang mampu 14 model.

**Jadi: kunci Anda tidak "disia-siakan" — tapi picker-nya memang buta terhadap
kemampuan kunci Anda sendiri.** Daftar ditentukan oleh gateway pihak ketiga,
sementara eksekusi dilakukan oleh kunci Anda.

## 5. Koreksi temuan lama: gemma

Brief "FINAL PUSH" (14 Okt) menyimpulkan `google/gemma-4-31b-it` "kuota habis, tidak
bisa dilayani" lalu menghapusnya dari picker. Probe hari ini menunjukkan nuansa penting:

* via **gateway** (`nvidia/google/gemma-4-31b-it`) → benar rusak (hint 52985 ms).
* via **kunci langsung** → **200 OK** pada `GEMINI_KEY_2`; gagal pada `GEMINI_KEY_1`.

Artinya masalahnya **entitlement per (kunci, model)** — persis kelas yang sudah
ditangani `gemini_key_pool.mark(kind="entitlement")`. Menghapusnya dari picker masih
dapat dipertahankan (gateway rusak), tapi alasan "kuota habis" **tidak akurat**.

## 6. Repo terbaik Okt 2026 (untuk konteks)

Catatan: Katalir **sudah** punya rotasi kunci sendiri (`gemini_key_pool`, 13 kunci,
cooldown per-(kunci, model)). Jadi repo berikut berguna sebagai referensi/pembanding,
bukan kebutuhan mendesak.

| repo | kegunaan | catatan |
|---|---|---|
| `snailyp/gemini-balance` (+ banyak fork) | proxy Gemini multi-kunci, FastAPI, rotasi + filter model + monitoring | kanonik; arsitektur paling dekat dengan `gemini_key_pool` |
| `tashfeenahmed/freellmapi` | agregat 34 provider gratis / 635 endpoint → satu `/v1` | klaim "88 model tak jelas asalnya" (paper CISPA arXiv 2603.01919) — **jangan** untuk data sensitif |
| `bl-ue/AIClient-2-API` | konversi klien Gemini CLI/Antigravity (OAuth) → OpenAI-compatible | jalur kuota berbeda (CLI, bukan API key) |
| `Aobing-code/fishrouter` | router multi-provider + rotasi kunci + failover | alternatif ringan |
| `LiteLLM` | gateway multi-provider matang | untuk skala produksi |

**Tidak ada repo yang bisa "memunculkan" model gratis yang tidak ada.** Yang menentukan
adalah kebijakan Google + entitlement per kunci — dan itu sudah kita ukur di §3.

## 7. Rekomendasi

1. **Jangan** ganti infrastruktur ke `gemini-balance`/`FreeLLMAPI` — Katalir sudah
   lebih baik: pool sendiri + cooldown per-(kunci, model) + fallback berantai.
2. **Yang layak dikerjakan**: buat picker membaca katalog kunci sendiri
   (`client.models.list()` lewat pool) sebagai sumber tambahan, lalu irisan dengan
   allowlist + probe liveness. Itu menaikkan pilihan Gemini dari **5 → ~14** dan
   membuat kunci terpakai penuh.
3. Pertahankan `_resolve_model` tetap memvalidasi — jangan longgarkan gerbangnya;
   cukup perkaya **sumber** daftarnya.
4. `gemini-4-argon` tetap tidak gratis; jangan dijanjikan di copy pemasaran.

## 8. Reproduksi

```bash
python docs/evidence/scripts-2026-10-14/probe_gemini_free_models_v2.py
```

Keluaran mentah: `docs/evidence/gemini-free-models-2026-10-14/probe_run_v2.txt`
(+ `.json`, termasuk katalog 63 model lengkap).
