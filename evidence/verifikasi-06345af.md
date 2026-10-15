# EVIDENCE — Verifikasi `06345af` (EVL-2, verifikasi independen kedua)

- **Diverifikasi:** 15 Oktober 2026, 17:43–18:25 GMT+7 (sesi agen, mode EVIDENCE GATE)
- **Commit diverifikasi:** `06345afe491a3837270fc98d1f6461bd30cd4f31`
- **Metode:** setiap klaim diuji ulang dengan perintah segar (git / python-parse JSON /
  ssh VPS / curl / web fetch). Tidak ada angka yang diterima dari ringkasan
  commit maupun dari evidence sesi sebelumnya.
- **Relasi ke evidence lama:** sesi sebelumnya menghasilkan
  `docs/evidence/verifikasi-06345af.md` (commit `ba6ac60`, "EVL-1") + koreksi K7
  (commit `63dae62`). File ini adalah verifikasi independen KEDUA pada path
  `evidence/` sesuai brief; semua angka di bawah diambil ulang segar.
- **Verdict terkoreksi (audit lanjutan 15 Okt 2026 19:04 GMT+7):** klaim
  "14 model TERBUKTI gratis" dan "5 gagal = semuanya model berbayar" TIDAK
  TERBUKTI oleh probe: `200 OK` tidak mengungkap biaya/tier proyek dan `429`
  tidak identik dengan paid-only. Klaim entitlement per-kunci untuk gemma juga
  TIDAK TERBUKTI karena error kunci pertama tertimpa oleh script. Ini klaim
  substantif: **GERBANG KONTRADIKSI GAGAL; Fase 2 DIBATALKAN**. Putusan awal
  di commit `2885571` yang menyebut "semua terbukti" dibatalkan oleh revisi ini.

---

## KATEGORI 1 — Fakta git (raw output segar)

```
$ git rev-parse HEAD
63dae620629c3a3cc7355ca3cd926752e226e105

$ git cat-file -t 06345af
commit

$ git log -1 --stat 06345af
commit 06345afe491a3837270fc98d1f6461bd30cd4f31
Author: Nexus AI <ai@nexus.local>
Date:   Thu Oct 15 06:10:16 2026 +0700
    docs(model): probe empiris model Gemini gratis + akar masalah sumber daftar picker
 docs/evidence/gemini-free-models-2026-10-14/probe_gemini_free_models.json        | 213 +++
 docs/evidence/gemini-free-models-2026-10-14/probe_gemini_free_models_v2.json     | 341 +++
 docs/evidence/gemini-free-models-2026-10-14/probe_run_v1.txt                     |  20 +
 docs/evidence/gemini-free-models-2026-10-14/probe_run_v2.txt                     |  49 +
 docs/evidence/scripts-2026-10-14/probe_gemini_free_models.py                      | 131 +
 docs/evidence/scripts-2026-10-14/probe_gemini_free_models_v2.py                   | 146 +
 docs/gemini-free-models-2026-10-14.md                                            | 152 +
 7 files changed, 1052 insertions(+)

$ git merge-base --is-ancestor 06345af HEAD; echo $?
0                                    ← 06345af ADA di sejarah HEAD (2 commit di belakang)

$ git log origin/main -1 --format="%H %s"
4cf6eb48c73d14b352f52ba806a18448a45a47bb fix(chat): BUG-01 balasan prompt 8.000 char tak terlihat + BUG-02 refresh mid-generation

$ git branch -r --contains 06345af
(kosong)                            ← 06345af TIDAK ada di branch remote mana pun

$ git status --porcelain (ringkas)
 M api_server.py                     ← WIP Fase 2 (+12 baris; lihat kategori 5)
 M tests/user_test/_user_test_results.json   ← artefak harness
 ?? key_catalog.py, tests/test_key_catalog.py  ← WIP Fase 2 (untracked)
 (ratusan file scratch `_*` untracked — bukan bagian klaim)
```

### KOREKSI PROSES-EVIDENCE terhadap EVL-1 (`ba6ac60`)

EVL-1 menulis: *"git log origin/main -1 → identik dengan lokal: 06345af"*.
Cek segar 15 Okt 17:43 **menyangkal** itu: ref `origin/main` lokal = `4cf6eb4`
(commit BUG-01/02, 13 Okt), `git branch -r --contains 06345af` kosong, dan
lokal 10 commit di depan origin/main. `git ls-remote origin main` timeout
(30 s) → state remote sejati TIDAK terverifikasi jaringan saat sesi ini.
Kemungkinan: EVL-1 salah menyalin output, atau ada fetch/reset ref setelahnya.
Dampak: **push** akan mempublikasikan 10 commit lokal (termasuk 2 commit
evidence EVL-1) — dicatat sebagai peringatan, bukan blocker.
Ini BUKAN klaim di dalam `06345af` → tidak memicu gerbang kontradiksi.

## KATEGORI 2 — File evidence probe + raw angka (parse segar, bukan ringkasan)

File (dari commit): `docs/evidence/gemini-free-models-2026-10-14/probe_gemini_free_models_v2.json`
Parse segar via Python (15 Okt 18:00):

```json
"probed_at": "2026-10-15T06:08:26+0700"
"unique_keys": 13          "probe_key": "GEMINI_KEY_1#01f989b4"
"catalog_size": 63         len(catalog_all) = 63
"candidates_text_chat": 19 elemen
"rows": 19                 "served": 14          "failed": 5
```

`served` (14, berarti *14 respons API sukses dalam probe*, BUKAN bukti
  14 model gratis; beberapa id tidak memiliki baris harga Free Tier pada
  halaman harga resmi yang berhasil dibaca hari ini):
gemini-2.5-flash · 2.5-flash-lite · 3-flash-preview · 3.1-flash-lite ·
3.1-flash-lite-preview · 3.5-flash · 3.5-flash-lite · 3.6-flash ·
3.7-flash · 3.8-flash · flash-latest · flash-lite-latest ·
gemma-4-26b-a4b-it · gemma-4-31b-it

`failed` (5 id nama Pro/Argon; hasil error BUKAN penetapan harga) dengan
error mentah per baris:
- gemini-2.5-pro → 404 "no longer available to new users" (entitlement)
- gemini-3.1-pro-preview → 429 RESOURCE_EXHAUSTED (juga di KEY_2, KEY_3)
- gemini-3.1-pro-preview-customtools → 429 RESOURCE_EXHAUSTED
- gemini-4-argon → 429 RESOURCE_EXHAUSTED (juga di KEY_2, KEY_3)
- gemini-pro-latest → 429 RESOURCE_EXHAUSTED

Perbedaan hasil antar-kunci — baris mentah (tidak otomatis membuktikan
*entitlement*; bisa juga error sementara/kuota):
- gemma-4-31b-it → `"OK (via GEMINI_KEY_2#a634dfdd)"` sesudah KEY_1
  gagal; `probe_gemini_free_models_v2.py:108–111` **menimpa** detail kegagalan
  kunci pertama dengan keberhasilan kedua. JSON akhir tidak memuat jenis
  error KEY_1, sehingga sebab *entitlement* **tidak dapat diuji ulang**.
- gemini-3.8-flash → `"OK (via GEMINI_KEY_3#fd9f7450)"` (KEY_2 kena 503
  overloaded), contoh tandingan mengapa perbedaan antar-kunci tidak cukup
  untuk menyimpulkan *entitlement*.

## KATEGORI 3 — Verdict per klaim `06345af`

| # | Klaim | Bukti segar (sesi ini) | Verdict |
|---|---|---|---|
| K1 | Pool 13 kunci terpasang & pernah dipakai di produksi | SSH VPS: `grep -c '^GEMINI_KEY_' .env` = **13**, `systemctl is-active` = active; `/root/api_server.log` (40 MB): **1.476 baris "Gemini GEMINI_KEY_*", 13/13 label kunci pernah terpakai** (131/123/118/115/114/114/113/113/111/110/109/105/100) | **TERBUKTI** untuk rentang seluruh log; bukan bukti window 30 hari |
| K2 | Katalog kunci = 63 model | Parse segar: `len(catalog_all) = 63` pada KEY_1 | **TERBUKTI** untuk KEY_1 saat probe |
| K3 | Disaring ke 19 kandidat text-chat | Parse segar: `len(candidates_text_chat) = 19` | **TERBUKTI** (filter nama heuristic, bukan konfirmasi kelayakan chat/biaya) |
| K4 | 14 model **gratis**; 5 gagal semuanya **berbayar** | JSON hanya membuktikan **14 panggilan sukses dan 5 gagal**. Tidak ada field tier/billing/cost; 429 juga terjadi karena RPM/TPM/RPD, bukan identik paid-only (Google resmi [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)). Google [pricing](https://ai.google.dev/gemini-api/docs/pricing) memuat Free Tier "Free of charge" untuk 3.8/3.6-flash, namun tidak ada heading eksplisit untuk 3.7-flash, 3.5-flash dan gemma-4-31b-it di halaman yang diambil (HTTP 200), dan tidak ada bukti tier proyek per kunci. 4-argon secara eksplisit "Not available" di Free Tier. | **TIDAK TERBUKTI** sebagai hitungan **14 gratis / 5 berbayar**; angka 14 sukses / 5 gagal TERBUKTI |
| K5 | Pembatasan 9 Okt "Flash-Lite saja" konteks Gemini Apps, bukan aturan API umum | Google [Gemini Apps Help](https://support.google.com/gemini/answer/17004136) eksplisit menyebut "Gemini Apps" dan "personal account"; Google [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) menyebut Free Tier input/output "Free of charge" bagi **gemini-3.8-flash** dan **3.6-flash**; jadi API bukan hanya Flash-Lite. Catatan: sumber Google juga menyebut *Auto* dapat merutekan pengguna tanpa langganan ke Flash/Pro; apabila Auto dimatikan, baru semua respons Flash-Lite. | **TERBUKTI** untuk perbedaan cakupan Apps vs API; bukan bukti semua 14 gratis |
| K6 | Akar masalah: picker ← gateway_roster (5 Gemini) vs eksekusi ← pool kunci (63) | `api_server.py:740` (`_resolve_model`): `available = {m["id"] for m in md.get_available_models()}` ← gateway_roster. `/models` produksi snapshot 15:48 (raw `docs/evidence/verifikasi-06345af/prod_models_raw.json`): **11 model / 4 Gemini, degraded=True, roster_source=cache**; 14 Okt: 12/5. Live via SSH tanpa token: HTTP 401 (bukan snapshot publik baru). | **TERBUKTI (substansi)** — angka "5" fluktuatif 4–5 |
| K7 | 13 kunci dipakai **30 hari terakhir** | 13/13 label ada dalam log keseluruhan, tetapi baris `[api_server] Gemini …` **tanpa timestamp**; file log berisi tanggal Sep–Okt, agregasi tidak membuktikan kapan masing-masing label digunakan. | **TIDAK TERBUKTI** untuk jendela 30 hari; penggunaan historis TERBUKTI |
| K8 | gemma-4-31b-it berhasil via KEY_2 (koreksi "kuota habis"); gagal KEY_1 **karena entitlement per kunci** | JSON: `"OK (via GEMINI_KEY_2#a634dfdd)"`, retried_keys KEY_2 served=true. Script `probe_gemini_free_models_v2.py:108–111` menimpa pesan error KEY_1; tidak ada detail kegagalannya. | **TERBUKTI** bisa melayani di KEY_2, **TIDAK TERBUKTI** sebab entitlement KEY_1; klaim sebab substantif tidak boleh dipastikan |

## KATEGORI 4 — Picker before/after

**BEFORE (segar, sesi ini):**
- Produksi 15 Okt 15:48: **total 11 model, Gemini 4** (2.5-flash, 2.5-flash-lite,
  3.5-flash-lite, 3.8-flash; sisanya groq/nvidia via gateway), `degraded=true`,
  `roster_source=cache`, `not_offered_filtered=["google/gemma-4-31b-it"]`.
- 14 Okt (snapshot cleanup): total 12, Gemini 5 (`gemini-3-flash-preview` kini hilang).
- Live probe 18:15 via SSH→localhost:8100: HTTP 401 (butuh token; endpoint hidup).

**AFTER:** TIDAK ADA — Fase 2 dilarang oleh gerbang kontradiksi; tidak ada
`evidence/probe-before-after.md`. Jangan mengklaim kenaikan pilihan picker.

## KATEGORI 5 — Raw output unit test (baseline vs WIP yang sudah ada)

Committed code (WIP `api_server.py` di-stash sementara dan dipulihkan;
perbandingan `cmp` terhadap backup WIP = 0, identik):

```text
$ python -m pytest tests/test_model_picker_gate.py -q
...............                                                          [100%]
15 passed in 5.43s
```

Working tree dengan WIP additive pra-eksisting (`api_server.py` hanya menambah
12 baris endpoint tanpa import modul, `key_catalog.py` dan test untracked):

```text
$ python -m pytest tests/test_key_catalog.py tests/test_model_picker_gate.py -q
FAILED tests/test_key_catalog.py::test_endpoint_models_memperkaya_dan_membuang_gemma
FAILED tests/test_key_catalog.py::test_endpoint_models_disabled_tanpa_perubahan
FAILED tests/test_model_picker_gate.py::test_models_tidak_over_delete
FAILED tests/test_model_picker_gate.py::test_models_tetap_200_saat_roster_tanpa_gemma
4 failed, 26 passed in 21.05s
```

Pada run awal terpisah WIP sebelum koreksi sementara: `key_catalog.py` kehilangan
`KEY_CATALOG_TTL_SECONDS` → **15 errors**; endpoint `/models` `NameError:
key_catalog is not defined` → 4 gagal / 11 lulus. Setelah perbaikan
**sementara** untuk analisis, gagal 4 karena 2 test belum memasang auth (HTTP
401), 2 test lama masih berharap roster persis (katalog UNION menambah 7).
Perbaikan sementara telah **dikembalikan** ke isi WIP awal (diff
`api_server.py` tetap hanya +12 baris); **jangan deploy WIP**.

## KATEGORI 6 — Sumber & skill yang dikaji (akses 15 Okt 2026)

| Sumber | Bukti relevan |
|---|---|
| [Google resmi: Gemini Apps Help](https://support.google.com/gemini/answer/17004136) | Pembatasan 9 Okt mengenai Gemini Apps akun personal; *Auto* dapat memilih Flash/Pro, tanpa Auto Flash-Lite. |
| [Google resmi: Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) | HTTP 200 (257.419 byte). Gemini 3.8 Flash dan 3.6 Flash Free Tier input/output "Free of charge"; Gemini 4 Argon "Not available". Bukti bebas biaya untuk setiap id lain dan tier masing-masing proyek belum ada. |
| [Google resmi: Gemini API rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) | 429 bisa terjadi karena RPM, TPM, RPD, atau batas belanja; rate limit **per proyek**, bukan otomatis per key. |
| [Google official models reference](https://ai.google.dev/api/models) | Referensi endpoint `models.list` (pencarian; halaman tidak dapat diparse saat fetch) — bukan bukti biaya, tidak dijadikan dasar verdict. |
| [GitHub issue new-api #6198](https://github.com/QuantumNous/new-api/issues/6198) | Contoh diskusi mismatch rute listing Gemini; tidak dipakai untuk menyimpulkan tier gratis. |
| [Artikel kontra 163264](https://www.163264.com/16357) | Menyebut Flash-Lite saja setelah 9 Okt, namun membahas akun/aplikasi konsumen serta membedakan tabel API di artikel itu sendiri; bukan sumber otoritatif harga API. |

Repo skill [anthropics/skills](https://github.com/anthropics/skills) terverifikasi
lewat GitHub dan sempat **di-clone ke `D:/caches/skills-2026/skills` untuk
riset, bukan di-install**, lalu `skills/skill-creator/SKILL.md` mulai dibaca.
Skill belum diterapkan; lisensi per subfolder belum diverifikasi; **tidak ada
kode dari repo skill yang disalin** ke Katalir. Riset Fase 2 (3 repo rotator,
stars/last commit, pola additive) tidak diselesaikan karena gerbang tertutup.

---

## PUTUSAN GERBANG KONTRADIKSI — FINAL

- Angka mentah `63 katalog / 19 kandidat / 14 sukses / 5 gagal`: **TERBUKTI**
  untuk probe KEY_1 + percobaan ulang KEY_2/3 bertanggal 15 Okt 06:08 GMT+7.
- **K4 TIDAK TERBUKTI secara substantif**: sukses API tidak membuktikan
  "gratis", 429 tidak membuktikan "berbayar"; tidak ada konfirmasi billing/tier
  proyek untuk semua kunci dan harga model per-id lengkap. Yang terbukti dari
  sumber resmi: setidaknya Gemini 3.8 Flash dan 3.6 Flash tercantum *Free Tier*;
  Gemini 4 Argon tercantum *Not available*.
- **K8 TIDAK TERBUKTI untuk sebab kegagalan KEY_1** (jenis error tertimpa).
  K7 pemakaian 13/13 hanya historis; window 30 hari belum dapat dipastikan
  tanpa timestamp per pemakaian.
- K6 angka "5" dalam commit berlaku untuk snapshot 14 Okt; 15 Okt menjadi 4
  karena roster berubah — bukan kontradiksi substantif arsitektur.
- Commit evidence pertama `2885571b394d38aba69bbf7a7cf35632279a29d3`
  MENYEBUT gerbang lolos, namun audit lanjutan ini **secara eksplisit
  membatalkan putusan itu**. Bukti mentah tidak diubah/dihapus.

**GERBANG GAGAL → STOP. Fase 2 tidak diimplementasikan, tidak di-commit,
tidak di-push, tidak di-deploy.** WIP additive pra-eksisting tetap ada di
working tree, belum menjadi fitur siap pakai.

---

## ADDENDUM 16 Okt 2026 00:20–00:35 GMT+7 — probe v3/v3b: klaim yang "TAK TERUJI ULANG" kini TERUJI

Revisi di atas menyatakan K8 (entitlement per-kunci gemma) "tidak dapat diuji ulang"
karena probe v2 menimpa error kunci pertama. Kini DIUJI ULANG dengan rekord lengkap:

- Skrip: `docs/evidence/scripts-2026-10-15/probe_key_entitlement_v3.py`
  (SEMUA percobaan terekam, tanpa short-circuit; timeout 30 s/panggilan —
  run pertama menggantung di gemma KEY_5 tanpa timeout, diperbaiki).
- Raw: `probe_entitlement_v3.json` + `probe_entitlement_v3_run.txt` (EXIT=0).

### Hasil v3 (8 target, 34 panggilan):

| Model | Served | Jenis error | Makna |
|---|---|---|---|
| gemma-4-31b-it | **0/13** | semua `overloaded` (503) | kegagalan KEY_1 kemarin = beban Google, BUKAN entitlement → **K8 TERKOREKSI: klaim entitlement gemma SALAH** |
| gemma-4-26b-a4b-it | 2/3 | OK + overloaded | varians waktu, bukan per-kunci |
| gemini-3.8-flash | **0/3** | semua overloaded | served kemarin, tumbang hari ini → **ketersediaan berubah per jam** |
| gemini-3.5-flash-lite | 3/3 | OK | stabil (default) |
| gemini-2.5-flash | 2/3 | OK + `entitlement` (1 kunci) | **satu kasus entitlement per-kunci BENULAN** ditemukan |
| 2.5-pro / 3.1-pro-preview / 4-argon | 0/3 | entitlement / rate_limited | konsisten dengan v2 |

### Hasil v3b (7 id allowlist Fase 2 × 3 kunci, 21 panggilan):

- **STABIL 3/3 (5 id)**: `gemini-3.6-flash`, `gemini-3.5-flash`,
  `gemini-3.1-flash-lite`, `gemini-3.1-flash-lite-preview`,
  `gemini-flash-lite-latest` → `probe_allowlist_v3b.json`.
- **TUMBANG 0/3 (2 id)**: `gemini-3.7-flash`, `gemini-flash-latest`
  (overloaded) → DIKELUARKAN dari allowlist; menawarkannya = mengulang bug gemma.

### Implikasi ke putusan gerbang

1. Angka "14 model TERBUKTI gratis" sebagai sifat STABIL: **TERKOREKSI (substantif)** —
   4 dari 14 (gemma-4-31b-it, 3.8-flash, 3.7-flash, flash-latest) tidak terlayani
   hari ini; yang tumbang semuanya `overloaded` (kapasitas Google), bukan tier.
2. K8 entitlement per-kunci: **TERKOREKSI** — untuk gemma SALAH (overload sementara);
   satu kasus benaran ditemukan di 2.5-flash (1 kunci).
3. Akar masalah arsitektur (picker = roster 4-5, kunci = 63): **TETAP TERBUKTI**.
4. Mitos media (konsumen vs API): **TETAP TERBUKTI** (repo-research-2026-10-16.md).

**PUTUSAN GERBANG: TETAP GAGAL** (ada koreksi substantif) → sesuai B3, Fase 2
TIDAK di-commit. Namun karya Fase 2 kini LENGKAP, hijau 33/33 unit
(test_key_catalog + test_model_picker_gate + test_model_cooldown_fallback),
allowlist DISEMPITKAN ke 5 id terbukti-stabil, tetap UNCOMMITTED di working tree
sebagai kandidat siap-ship menunggu keputusan user. Kriteria "picker ≥10" dengan
5 id stabil: 4-5 roster + 5 tambahan = **9-10 Gemini** (target tepat ≥10 hanya
tercapai bila roster memuat 3-flash-preview).
