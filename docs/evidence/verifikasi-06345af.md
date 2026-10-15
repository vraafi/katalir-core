# EVIDENCE — Verifikasi klaim commit `06345af`

- **Diverifikasi:** 15 Oktober 2026, 15:50–16:00 GMT+7
- **Commit diverifikasi:** `06345afe491a3837270fc98d1f6461bd30cd4f31`
- **Verifikator:** sesi Agen (mode EVIDENCE GATE, autonom penuh)
- **Metode:** setiap klaim diuji ulang dengan perintah yang bisa diulang user
  (git / curl / ssh / python). Tidak ada klaim yang diterima dari ringkasan.
- **Catatan path:** brief menyebut `evidence/verifikasi-06345af.md`; repo
  Katalir menaruh seluruh evidence di `docs/evidence/` — file ini memakai
  konvensi repo.

---

## KATEGORI 1 — Fakta git (raw output)

```
$ git rev-parse 06345af
06345afe491a3837270fc98d1f6461bd30cd4f31

$ git log -1 --stat 06345af   (sumber: sesi ini)
 commit 06345afe491a3837270fc98d1f6461bd30cd4f31
 Date:   Thu Oct 15 06:10:16 2026 +0700
 docs(model): probe empiris model Gemini gratis + akar masalah sumber daftar picker

$ git show --stat --format="" 06345af | tail -1
 7 files changed, 1052 insertions(+)
   - docs/gemini-free-models-2026-10-14.md
   - docs/evidence/gemini-free-models-2026-10-14/probe_gemini_free_models.json
   - docs/evidence/gemini-free-models-2026-10-14/probe_gemini_free_models_v2.json
   - docs/evidence/gemini-free-models-2026-10-14/probe_run_v1.txt
   - docs/evidence/gemini-free-models-2026-10-14/probe_run_v2.txt
   - docs/evidence/scripts-2026-10-14/probe_gemini_free_models.py
   - docs/evidence/scripts-2026-10-14/probe_gemini_free_models_v2.py

$ git log origin/main -1 --format="%H %s"   → identik dengan lokal:
06345afe491a3837270fc98d1f6461bd30cd4f31 docs(model): probe empiris model Gemini gratis ...

$ git status --short
 M tests/user_test/_user_test_results.json      ← artefak harness, BUKAN perubahan kita
 (lainnya: direktori scratch `_*`/`.claude` dll, tidak di-stage)
```

## KATEGORI 2 — File evidence + raw output (dari `probe_gemini_free_models_v2.json`)

File: `docs/evidence/gemini-free-models-2026-10-14/probe_gemini_free_models_v2.json`
(dibuat 15 Okt 2026 06:08 GMT+7, script `probe_gemini_free_models_v2.py`)

```json
"probed_at": "2026-10-15T06:08:26+0700",
"unique_keys": 13,
"probe_key": "GEMINI_KEY_1#01f989b4",
"catalog_size": 63,
"catalog_all": [ 63 id ],
"candidates_text_chat": [ 19 id ],
"rows": [ 19 baris ],
"served": [ 14 id ],
"failed": [ 5 id ]
```

`served` (14): gemini-2.5-flash, 2.5-flash-lite, 3-flash-preview,
3.1-flash-lite, 3.1-flash-lite-preview, 3.5-flash, 3.5-flash-lite, 3.6-flash,
3.7-flash, 3.8-flash, flash-latest, flash-lite-latest, gemma-4-26b-a4b-it,
gemma-4-31b-it.

`failed` (5): gemini-2.5-pro, gemini-3.1-pro-preview,
gemini-3.1-pro-preview-customtools, gemini-4-argon, gemini-pro-latest.

Bukti mentah lengkap (raw output probe run) tersimpan di:
`docs/evidence/gemini-free-models-2026-10-14/probe_run_v1.txt`, `probe_run_v2.txt`.

## KATEGORI 3 — Verdict per klaim

| # | Klaim di `06345af` | Bukti (raw) | Verdict |
|---|---|---|---|
| K1 | Pool 13 kunci terpasang di produksi | VPS `grep -c '^GEMINI_KEY_' .env` = **13**; `discover_keys()` → 13 entri / 13 fingerprint unik; probe JSON `unique_keys: 13` | **TERBUKTI** |
| K2 | Katalog kunci = 63 model | `catalog_size: 63`, `catalog_all` = 63 id | **TERBUKTI** |
| K3 | Disaring ke 19 kandidat text-chat | `candidates_text_chat` = 19 id | **TERBUKTI** |
| K4 | 14 model TERBUKTI gratis; 5 tidak bisa, semuanya kelas Pro/Argon | `served` = 14 (semua 200 OK); `failed` = 5: `3.1-pro-preview(-customtools)` + `gemini-4-argon` = 429 RESOURCE_EXHAUSTED (kelas berbayar), `gemini-2.5-pro` = 404 "no longer available to new users" (entitlement), `gemini-pro-latest` = alias pro. Semua id pro/argon. | **TERBUKTI** (nuansa: 2 dari 5 gagal karena entitlement/new-user, bukan semata kuota — kelas model tetap sama) |
| K5 | "free tier = Flash-Lite saja" adalah mitos untuk API; laporan media menyasar Gemini Apps | Sumber resmi: support.google.com/gemini/answer/17004136 "…changes to model availability for **Gemini Apps** when you use a **personal account**… take effect for users without an AI subscription on **October 9th**" (tanpa plan → Flash-Lite). Media Okt 5–9 melaporkan hal yang sama tapi selalu konteks aplikasi/akun personal. Prope kami: 3.8/3.7/3.6/3.5-flash semua 200 OK via endpoint API | **TERBUKTI** |
| K6 | Akar masalah: picker ← gateway_roster (5 Gemini) vs eksekusi ← pool kunci (63 model) | `model_discovery.get_available_models()` ← `gateway_roster`; `/models` produksi 14 Okt: 12 model / 5 Gemini; **kini 15 Okt: 11 model / 4 Gemini** (`gemini-3-flash-preview` menghilang). Kedua snapshot `roster_source=cache degraded=True` | **TERBUKTI (substansi)** — mekanismenya benar; **angka 5 bukan konstan** (4–5; roster upstream degradasi, cache) |
| K7 | Pool 13 kunci "jalan" di produksi (benar-benar dipakai) | Jurnal pertama (journald) menyesatkan: `StandardOutput=append:/root/api_server.log` — **bukan** journald (144 baris systemd, 0 baris aplikasi). Dari log aplikasi (14 Sep–15 Okt 2026, 40 MB): **1.476 request Gemini, 13/13 kunci benar-benar dipakai** (hit: 131, 123, 118, 115, 114, 114, 113, 113, 111, 110, 109, 105, 100). Model teratas: gemini-3.5-flash-lite (1.723), 2.5-flash (87), gemma (56, sebelum dikeluarkan 14 Okt), 2.5-flash-lite (31) | **TERBUKTI** (setelah koreksi metode: telemetry ada, tapi di `/root/api_server.log`, bukan journald — bukti: `docs/evidence/verifikasi-06345af/vps_applog_keys_used.txt`) |
| K8 | "gemma-4-31b-it kuota habis" tidak akurat: via kunci langsung 200 OK di `GEMINI_KEY_2`, gagal di `GEMINI_KEY_1` | baris probe: `gemma-4-31b-it → detail: "OK (via GEMINI_KEY_2#a634dfdd)", retried_keys[0] = GEMINI_KEY_2 served=true` | **TERBUKTI** |

### Dampak koreksi terhadap Fase 2
- Baseline picker bukan "5" tetap: **4–5 Gemini** (bergantung cache roster).
- Justifikasi UNION makin kuat: roster gateway sudah degradasi ≥33 jam;
  sumber additive (TTL 24h, kunci langsung) membuat picker stabil.
- Target diubah sesuai: Gemini picker **dari ±4–5 → ≥10** (bukan "dari 5").

## KATEGORI 4 — Sumber eksternal (link + tanggal akses)

| Sumber | Link | Akses | Isi relevan |
|---|---|---|---|
| Google resmi (Gemini Apps Help) | https://support.google.com/gemini/answer/17004136 | 15 Okt 2026 | Perubahan berlaku utk Gemini Apps + akun personal, efektif 9 Okt 2026; tanpa plan → Flash-Lite |
| Media ZH (rekap tabel resmi) | https://baijiahao.baidu.com/s?id=1878204769524823352 | 15 Okt 2026 | "无订阅只剩Flash-Lite" — merujuk artikel Google 17004136 (konteks aplikasi) |
| Aibase TW | https://news.aibase.com/tw/news/31471 | 15 Okt 2026 | 10月9日起免费版仅留Flash-Lite — akun personal, aplikasi |
| 163264.com | https://www.163264.com/16357 | 15 Okt 2026 | "10月9日起仅限 Flash-Lite 模型" — consumer |
| 51CTO (Argon berbayar) | https://www.51cto.com/aigc/12099.html | 15 Okt 2026 | Gemini 4 Argon API stabil (berbayar) — mendukung "kelas Pro/Argon = paid" |
| GitHub course commit | https://github.com/killkli/boyo-ai-agent-course/commit/dc49cc8e1f9ad9b3cf221497ff8d7f5bbdc9bc04 | 15 Okt 2026 | "gemini 3.1 pro preview 已不開放免費方案使用" |

Kesimpulan kategori: **tidak ada satu pun sumber kredibel** yang mengatakan
free-tier API (`generativelanguage.googleapis.com`) dibatasi ke Flash-Lite.
Seluruh laporan Okt membahas aplikasi Gemini (web/mobile, langganan AI
Plus/Pro/Ultra). Klaim K5 terbukti dari sumber resmi Google sendiri.

## KATEGORI 5 — Bukti kode arsitektur (raw grep)

```
$ grep -n "_resolve_model" api_server.py
591:#   `md.get_available_models()` juga dipakai `_resolve_model` (baris ~707) dan
721:def _resolve_model(requested: str | None, user_tier: str) -> tuple[str, bool, str | None]:
2044:    model_id, tier_fallback, resolve_reason = _resolve_model(model, user_tier)

api_server.py:721-733:
def _resolve_model(requested: str | None, user_tier: str) -> tuple[str, bool, str | None]:
    """Validasi model + tier-gate terhadap hasil discovery (cache 1 jam).
    ...
          - id tak ada di daftar discovery    -> `model_unavailable`
    """
    default_id = _default_model_id()
    tier = db.effective_tier(user_tier)
```

Jalur: picker → `GET /models` → `model_discovery.get_available_models()` →
`gateway_roster` (sedikit Gemini). Eksekusi: `api_server` → `gemini_key_pool`
(13 kunci) → katalog 63 model. `_resolve_model` memvalidasi terhadap daftar
**gateway**, sehingga id yang kunci mampu layani tapi gateway tidak mencantumkan
akan diganti default + `fallback=True`. → Substansi akar masalah TERBUKTI.

## KATEGORI 6 — Endpoint produksi + analitik journal (raw)

Endpoint: `curl -s -H "Authorization: Bearer <token>" -H "User-Agent: Mozilla/5.0…"`
`https://gateway.katalir.de5.net/katalir-api/models` (akun uji sekali-pakai,
dihapus setelah probe; token disamarkan di evidence).

**15 Okt 2026 15:48 (sekarang):** HTTP 200 ·
`roster_source=cache degraded=True` · default=`gemini-3.5-flash-lite` ·
**total=11 model, Gemini=4** (2.5-flash, 2.5-flash-lite, 3.5-flash-lite, 3.8-flash).
Respons mentah: `docs/evidence/verifikasi-06345af/prod_models_raw.json`
+ `prod_models_curl.txt`.

**14 Okt 2026 (snapshot commit cleanup):** total=12, Gemini=5 — diperiksa dari
`docs/evidence/models-picker-2026-10-14/models_after.json` (juga `degraded=True`).
Selisih: hanya `gemini-3-flash-preview` hilang dari cache roster.

**Journal 30 hari** (`docs/evidence/verifikasi-06345af/vps_journal_30d_summary.txt`):
144 baris, semuanya lifecycle systemd; 0 request log; 0 label kunci.

**Koreksi metode (temuan kedua):** unit `katalir-backend` memakai
`StandardOutput=append:/root/api_server.log` → stdout aplikasi **TIDAK masuk
journald**. Grep journald dulu menghasilkan "0 baris aplikasi" yang SALAH
sebagai bukti "tidak ada telemetry". Bukti pemakaian nyata diambil dari
`/root/api_server.log` (`vps_applog_keys_used.txt`): **13/13 kunci terpakai
1.476x** pada 14 Sep–15 Okt 2026. Catatan instrumen: baris `[api_server]
Gemini <label> model=<id>` tidak membawa timestamp → agregasi per-hari tidak
mungkin; total + rentang log masih valid.

---

## PUTUSAN GERBANG KONTRADIKSI (revisi setelah klarifikasi K7)

Setelah klarifikasi lokasi log aplikasi (`StandardOutput=append` →
`/root/api_server.log`, bukan journald), **K7 menjadi TERBUKTI penuh**:
1.476 request Gemini, 13/13 kunci terpakai, 14 Sep–15 Okt 2026.

Tersisa satu koreksi non-substantif: **K6 angka** ("5 Gemini") — snapshot
14 Okt = 12 model/5 Gemini; sekarang = 11 model/4 Gemini
(`roster_source=cache degraded=True`; `gemini-3-flash-preview` hilang dari
cache). Mekanisme akar masalah tetap TERBUKTI.

**GERBANG LOLOS.** Implikasi Fase 2: baseline picker Gemini 4–5 (fluktuatif),
justifikasi UNION makin kuat karena sumber gateway sedang tidak stabil.
