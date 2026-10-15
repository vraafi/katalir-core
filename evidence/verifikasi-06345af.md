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
- **Verdict ringkas:** semua klaim TERBUKTI; satu koreksi non-substantif (K6,
  angka fluktuatif). Satu koreksi PROSES-EVIDENCE terhadap EVL-1 (kategori 1) —
  bukan klaim `06345af`, tidak memengaruhi gerbang.

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

`served` (14, semua kelas flash/flash-lite/gemma — non-pro):
gemini-2.5-flash · 2.5-flash-lite · 3-flash-preview · 3.1-flash-lite ·
3.1-flash-lite-preview · 3.5-flash · 3.5-flash-lite · 3.6-flash ·
3.7-flash · 3.8-flash · flash-latest · flash-lite-latest ·
gemma-4-26b-a4b-it · gemma-4-31b-it

`failed` (5, SEMUA kelas pro/argon) dengan error mentah per baris:
- gemini-2.5-pro → 404 "no longer available to new users" (entitlement)
- gemini-3.1-pro-preview → 429 RESOURCE_EXHAUSTED (juga di KEY_2, KEY_3)
- gemini-3.1-pro-preview-customtools → 429 RESOURCE_EXHAUSTED
- gemini-4-argon → 429 RESOURCE_EXHAUSTED (juga di KEY_2, KEY_3)
- gemini-pro-latest → 429 RESOURCE_EXHAUSTED

Entitlement per (kunci, model) — baris mentah:
- gemma-4-31b-it → `"OK (via GEMINI_KEY_2#a634dfdd)"` (gagal di KEY_1)
- gemini-3.8-flash → `"OK (via GEMINI_KEY_3#fd9f7450)"` (KEY_2 kena 503 overloaded)

## KATEGORI 3 — Verdict per klaim `06345af`

| # | Klaim | Bukti segar (sesi ini) | Verdict |
|---|---|---|---|
| K1 | Pool 13 kunci terpasang & jalan di produksi | SSH VPS: `grep -c '^GEMINI_KEY_' .env` = **13**, `systemctl is-active` = active; `/root/api_server.log` (40 MB): **1.476 baris "Gemini GEMINI_KEY_*", 13/13 kunci terpakai** (131/123/118/115/114/114/113/113/111/110/109/105/100) | **TERBUKTI** |
| K2 | Katalog kunci = 63 model | Parse segar: `len(catalog_all) = 63` | **TERBUKTI** |
| K3 | Disaring ke 19 kandidat text-chat | Parse segar: `len(candidates_text_chat) = 19` | **TERBUKTI** |
| K4 | 14 model gratis; 5 tidak bisa, semuanya Pro/Argon | Dump baris segar (kategori 2): 14 OK semua flash/gemma; 5 failed semua pro/argon (2 entitlement-404/alias, 3 kuota-429) | **TERBUKTI** |
| K5 | "free tier = Flash-Lite saja" = mitos utk API; laporan media menyasar Gemini Apps | Fetch segar 15 Okt 18:15 halaman resmi Google support.google.com/gemini/answer/17004136: *"changes to model availability for **Gemini Apps** when you use a **personal account**… take effect for users without an AI subscription on **October 9th**… use **Flash-Lite** for all responses"* — seluruhnya konteks aplikasi konsumen. Media (contoh segar: zhuanlan.zhihu.com/p/2092564867198853982, ~10 Okt) menggemakan versi digeneralisasi "Free tier hanya Flash-Lite". Probe: 3.5/3.6/3.7/3.8-flash = 200 OK via endpoint API | **TERBUKTI** |
| K6 | Akar masalah: picker ← gateway_roster (5 Gemini) vs eksekusi ← pool kunci (63) | `api_server.py:740` (`_resolve_model`): `available = {m["id"] for m in md.get_available_models()}` ← gateway_roster. `/models` produksi snapshot 15:48 (raw `docs/evidence/verifikasi-06345af/prod_models_raw.json`): **11 model / 4 Gemini, degraded=True, roster_source=cache**; 14 Okt: 12/5. Live 18:15: HTTP 401 tanpa token (endpoint hidup) | **TERBUKTI (substansi)** — angka "5" fluktuatif 4–5 (roster upstream degradasi), koreksi non-substantif |
| K7 | Pool 13 kunci benar-benar dipakai (30 hari) | SSH segar (kategori 1): 13/13 kunci terpakai merata, 1.476 request | **TERBUKTI** |
| K8 | gemma-4-31b-it "kuota habis" tidak akurat — entitlement per kunci | Baris mentah: `"OK (via GEMINI_KEY_2#a634dfdd)"`, gagal di KEY_1 | **TERBUKTI** |

## KATEGORI 4 — Picker before/after

**BEFORE (segar, sesi ini):**
- Produksi 15 Okt 15:48: **total 11 model, Gemini 4** (2.5-flash, 2.5-flash-lite,
  3.5-flash-lite, 3.8-flash; sisanya groq/nvidia via gateway), `degraded=true`,
  `roster_source=cache`, `not_offered_filtered=["google/gemma-4-31b-it"]`.
- 14 Okt (snapshot cleanup): total 12, Gemini 5 (`gemini-3-flash-preview` kini hilang).
- Live probe 18:15 via SSH→localhost:8100: HTTP 401 (butuh token; endpoint hidup).

**AFTER:** diisi Fase 2 — target Gemini ≥10 (`evidence/probe-before-after.md`).

## KATEGORI 5 — Unit test (baseline pytest)

- **Committed HEAD** (`api_server.py` WIP di-stash sementara, backup aman):
  `pytest tests/test_model_picker_gate.py -q` → **15 passed in 5.43s** (EXIT=0).
- Working tree + WIP Fase 2 (untracked, buatan sesi sebelumnya):
  **4 FAILED** — `NameError: name 'key_catalog' is not defined` di
  `api_server.py:3119` (WIP memanggil `key_catalog.picker_additions()` tetapi
  import modulnya TIDAK pernah ditambahkan).
  `pytest tests/test_key_catalog.py -q` → **15 errors** —
  `AttributeError: module 'key_catalog' has no attribute 'KEY_CATALOG_TTL_SECONDS'`
  (modul WIP lebih tua dari kontrak test-nya).
  → WIP dinyatakan RUSAK/LENGKAP-SEPAROH; diperbaiki di Fase 2, bukan regression
  kode ter-commit.
- Hasil pytest akhir Fase 2: akan diisi setelah implementasi.

## KATEGORI 6 — Skill & riset repo (Fase 2)

Diisi di Fase 2: hasil pencarian web (min 5 sumber + tanggal akses), repo skill
yang di-clone + SKILL.md yang dibaca, license. Sumber segar sesi Fase 1 yang
sudah dipakai: Google Support #17004136 (akses 15 Okt 2026, fetch penuh) dan
Zhihu (hasil pencarian 15 Okt 2026).

---

## PUTUSAN GERBANG KONTRADIKSI

- 8 klaim `06345af`: **8 TERBUKTI** (K6 dengan satu koreksi non-substantif:
  angka "5 Gemini" fluktuatif 4–5 karena roster upstream degradasi ≥33 jam —
  mekanisme akar masalah tetap terbukti dari kode + snapshot).
- Tidak ada klaim TERKOREKSI substantif atau TIDAK TERBUKTI.
- Temuan tambahan (di luar klaim 06345af): koreksi proses-evidence EVL-1
  (origin/main), WIP Fase 2 rusak. Keduanya dicatat, bukan blocker.

**GERBANG LOLOS → auto-lanjut Fase 2** (implementasi additive katalog kunci,
memperbaiki WIP rusak menjadi implementasi utuh + import + test lulus).
