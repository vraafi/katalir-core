# FASE 1 — Riset & Keputusan: Migrasi Gateway LLM → Gemini Provider

**Tanggal:** 2026-10-12 · **Standar:** Oktober 2026 · **Mode:** AUTONOMOUS + GEMINI-FIRST

---

## 1. Mengapa gateway lama ditinggalkan (bukti, bukan opini)

| Gejala | Bukti |
|---|---|
| Burst → HTTP 500 massal | `POST /v1/chat/completions` dengan `tools` → 500 pada 1/3/5/12 tools (semua gagal saat diuji) |
| Seri berkepanjangan → menggantung | > ~15 panggilan serial → tidak ada respons sampai timeout |
| Hanya 1 model yang mendiskriminasi | `qwen/qwen3.8-27b` menilai BENAR=1.0 / SALAH=0.0; `allam-2-7b` memberi **1.0 untuk keduanya** = cap karet (rubber stamp) |
| Akibat | TASK 4 `final_score=0`, TASK 5 gagal 20/21 fitur, penilaian 420 tidak bisa diselesaikan penuh |

Kesimpulan: gateway `nexus-gateway-vps.tail7f0d5a.ts.net` **tidak layak** sebagai penilai/penyedia LLM produksi.

---

## 2. Batas laju Gemini API (sumber resmi)

Sumber: <https://ai.google.dev/gemini-api/docs/rate-limits>

| Aturan | Nilai (Okt 2026) |
|---|---|
| Dimensi batas | **RPM** (request/menit), **TPM** (token input/menit), **RPD** (request/hari) |
| Cakupan | **PER PROJECT, bukan per API key** — kutipan: *"Rate limits are applied per project, not per API key."* |
| Reset RPD | tengah malam **Pacific Time** |
| Pelanggaran | melebihi **salah satu** dimensi → error rate-limit (429) |
| Batas berbasis belanja | jendela bergulir **10 menit**; Free = N/A; Tier 1 $10 / Tier 2 $50 / Tier 3 $200 |
| Saat kena | `429 RESOURCE_EXHAUSTED` → tunggu lalu ulangi; perkecil konteks/output |
| Tier | Free → Tier 1 (pasang billing) → Tier 2 (bayar $100 + 3 hari) → Tier 3 ($1000 + 30 hari) |

**Konsekuensi desain (penting):** karena kuota bercakupan **per (project, model)**, rotasi banyak kunci hanya menambah kapasitas bila kunci-kunci itu berada di **project berbeda**. Ini **dibuktikan empiris** pada proyek ini: `GEMINI_KEY_1` kena 429 pada `gemini-3.8-flash` sementara `GEMINI_KEY_2` **sukses pada model yang sama** beberapa detik kemudian → kunci berada di project berbeda → rotasi benar-benar menggilir kuota. (Payload 429 asli proyek: `quotaId=GenerateRequestsPerMinutePerProjectPerModel-FreeTier`, `quotaValue=5`, `retryDelay=5s`.)

---

## 3. Tiga opsi migrasi

### Opsi A — `gemini-api-rotator` (rotasi kunci di dalam aplikasi) ✅ **DIPILIH**
- PyPI: <https://pypi.org/project/gemini-api-rotator/> (v2.0.0, rilis 28 Agu 2026, MIT, Python ≥3.10)
- GitHub: <https://github.com/XenonTheInertG/gemini-api-rotator>
- Fitur: cooldown per kunci, **backoff eksponensial**, pelacakan RPM per kunci, statistik latensi (SQLite opsional), **pemulihan kunci tersuspend otomatis**, *alert hooks*, CLI (`gemini-rotator test/status/stats`), inti **tanpa dependensi** (ekstra `[genai]` untuk panggilan nyata).
- `RotatorConfig` paket: `rpm_per_key=15, cooldown_base_seconds=60, cooldown_max_seconds=1800, max_concurrent_per_key=5, max_retries=3, retry_delay_seconds=0.5` — brief meminta nilai **lebih konservatif** (10 / 60 / 1800 / 3 / 4 / 1.0), dan itu yang dipakai.
- Klasifikasi error paket: `429/RESOURCE_EXHAUSTED/QUOTA → rate_limited`; `CONSUMER_SUSPENDED/PERMISSION_DENIED/API_KEY_INVALID → suspended`; `500/503/INTERNAL/UNAVAILABLE → transient`.

**Mengapa dipilih:** paling cocok untuk FastAPI in-process, tanpa layanan tambahan, dan — yang menentukan — **repositori ini sudah punya padanannya yang teruji**: `gemini_key_pool.KeyPool` (rotasi round-robin, cooldown per kunci, blokir per (kunci, model), klasifikasi 429 dari payload asli, `HttpRetryOptions(attempts=1)`). Jadi Opsi A bukan "membangun rotator dari nol" melainkan **menyelesaikan integrasi yang sudah 90% ada**.

### Opsi B — LiteLLM Proxy (gateway Gemini)
- Docs: <https://docs.litellm.ai/docs/providers/gemini> · Fallback: <https://docs.litellm.com.cn/docs/proxy/reliability>
- Kelebihan: satu endpoint OpenAI-compatible, `fallbacks=[...]`, virtual key, pelacakan biaya, rotasi beberapa kunci via daftar `api_key`.
- **Ditolak karena:** menambah **proses/layanan baru** (proxy terpisah + config.yaml) untuk masalah yang bisa diselesaikan in-process. Ini justru mengulang pola gateway yang sedang bermasalah (satu titik gagal jaringan).

### Opsi C — agentgateway (Gemini native)
- Docs: <https://agentgateway.dev/docs/standalone/main/documentation/llm/api-types/gemini/>
- Kelebihan: dukungan native format Gemini, streaming, token counting; sisi enterprise (Solo.io) ada.
- **Ditolak karena:** produk gateway berbasis Envoy/Kubernetes — beban infrastruktur jauh melebihi kebutuhan; tidak menyelesaikan rotasi kunci aplikasi.

---

## 4. Keputusan

> **Opsi A.** Implementasi: paket `gemini-api-rotator==2.0.0` **dipasang** (terverifikasi impor + `RotatorConfig`), dan mesin rotasi runtime memakai `gemini_key_pool.KeyPool` yang sudah teruji terhadap payload 429 **asli** proyek ini. Modul baru `gemini_llm.py` mengekspor `MODEL_CHAIN`, `chat_with_fallback()`, pemetaan tingkat berpikir, dan `health_check()`.

Alasan memakai `KeyPool` sebagai mesin (bukan `GeminiAPIRotator` langsung): `KeyPool` sudah terpasang di `api_server.py`, sudah menangani kenyataan proyek ini (404 entitlement per pasangan kunci-model, 401 kunci dicabut, `attempts=1` agar SDK tidak mengulang sendiri dan menembus anggaran `/chat`).

---

## 5. Rantai model — **dikoreksi oleh bukti**

Brief meminta `MODEL_CHAIN = [gemini-3.8-flash, gemini-3.5-flash-lite, gemini-2.5-flash-lite, gemini-2.5-flash, gemma-4-31b-it]`. Semua nama itu **ada** di `list_models` live, **tetapi** matriks empiris (`tests/_gem_matrix.json`) menemukan tiga kenyataan yang harus ditangani:

1. **`gemini-2.5-flash` & `gemini-2.5-flash-lite` → 404 "no longer available to new users"** untuk sebagian project (kunci 10/11). Masih boleh untuk project lama, tetapi tidak boleh diandalkan.
2. **`thinking_budget=0` ditolak (400) oleh `gemini-3.5-flash-lite` dan semua `gemma-*`** → konfigurasi berpikir **wajib sadar-model**.
3. **Tanpa blok berpikir, model thinking membakar anggaran token untuk berpikir → konten KOSONG** (terukur pada 3.6-flash & 3.5-flash dengan `max_output_tokens=24`).

Karena itu rantai dipertahankan **persis sesuai brief** sebagai `MODEL_CHAIN`, ditambah `MODEL_CHAIN_RESERVE` berisi model **terverifikasi-hidup**: `gemini-3.7-flash`, `gemini-3.6-flash`, `gemini-3.5-flash`, `gemini-3.1-flash-lite`, `gemma-4-26b-a4b-it`. Ditambah jaring pengaman: **400 karena blok berpikir → ulangi tanpa blok berpikir**.

### Matriks terukur (kunci #3, `tests/_gem_matrix.json`)

| model | plain | `thinking_budget=0` | `thinking_level=low` |
|---|---|---|---|
| gemini-3.8-flash | 503 | **OK 2.6s** | 503 |
| gemini-3.7-flash | 503 | **OK 6.5s** | **OK 10.7s** |
| gemini-3.6-flash | EMPTY | **OK 1.5s** | EMPTY |
| gemini-3.5-flash | EMPTY | **OK 2.1s** | EMPTY |
| gemini-3.5-flash-lite | **OK 1.5s** | 400-invalid | **OK 1.0s** |
| gemini-3.1-flash-lite | OK 14.2s | OK 10.9s | EMPTY |
| gemini-2.5-flash | EMPTY | **OK 1.1s** | 400-invalid |
| gemini-2.5-flash-lite | OK 3.5s | **OK 1.6s** | 400-invalid |
| gemma-4-31b-it | EMPTY 25.4s | 400-invalid | 400-invalid |
| gemma-4-26b-a4b-it | EMPTY | 400-invalid | 400-invalid |

**Catatan operasional:** `GEMINI_CALL_TIMEOUT_S` default 20 s di `gemini_key_pool`. `gemini-3.8-flash` kadang butuh 5–25 s, jadi ia bisa habis waktu dan rantai lanjut ke model berikutnya — perilaku yang benar (bukan bug).

---

## 6. Tautan

- Batas laju Gemini: <https://ai.google.dev/gemini-api/docs/rate-limits>
- Lihat batas aktif: <https://aistudio.google.com/rate-limit>
- `gemini-api-rotator`: <https://pypi.org/project/gemini-api-rotator/> · <https://github.com/XenonTheInertG/gemini-api-rotator>
- LiteLLM Gemini: <https://docs.litellm.ai/docs/providers/gemini>
- agentgateway Gemini: <https://agentgateway.dev/docs/standalone/main/documentation/llm/api-types/gemini/>
