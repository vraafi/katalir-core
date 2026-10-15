# EVIDENCE — Semua Model Free Google AI Studio (probe v4, 16 Okt 2026 01:10 GMT+7)

Brief: DYNAMIC MODEL DISCOVERY — gerbang Fase 0 mensyaratkan **≥10 model lolos**
probe `generate_content` untuk melanjutkan Fase 1.

## Metode

- Skrip: `docs/evidence/scripts-2026-10-15/probe_semua_model_v4.py` (EXIT=0)
- Katalog: `client.models.list()` via pool (KEY_1) → **63 model** →
  kandidat text-chat (supported_actions ∋ generateContent, bukan
  image/tts/audio/embedding/dll.) → **19 kandidat**
- Probe: `generate_content` "Balas tepat satu kata: OK", timeout **10 s**
  (hard-limit thread 15 s), **maks 3 kunci per model**, semua percobaan terekam
- Raw: `evidence/models-list-raw.json` + `evidence/probe-semua-model-v4.json`

## Tabel hasil (MODEL | STATUS | KUNCI LOLOS | ERROR KIND)

| Model | Status | Kunci lolos | Error kind |
|---|---|---|---|
| gemini-2.5-flash | LOLOS | 2/3 | entitlement (1 kunci) |
| gemini-2.5-flash-lite | LOLOS | 2/3 | entitlement (1 kunci) |
| gemini-3.1-flash-lite | LOLOS | 3/3 | — |
| gemini-3.1-flash-lite-preview | LOLOS | 3/3 | — |
| gemini-3.5-flash | LOLOS | 3/3 | — |
| gemini-3.5-flash-lite | LOLOS | 3/3 | — |
| gemini-3.6-flash | LOLOS | 2/3 | overloaded (1 kunci) |
| gemini-flash-lite-latest | LOLOS | 3/3 | — |
| gemma-4-26b-a4b-it | LOLOS | 2/3 | overloaded (1 kunci) |
| gemini-3-flash-preview | gagal | 0/3 | overloaded |
| gemini-3.7-flash | gagal | 0/3 | overloaded |
| gemini-3.8-flash | gagal | 0/3 | overloaded |
| gemini-flash-latest | gagal | 0/3 | overloaded |
| gemma-4-31b-it | gagal | 0/3 | overloaded |
| gemini-2.5-pro | gagal | 0/3 | entitlement |
| gemini-3.1-pro-preview | gagal | 0/3 | rate_limited |
| gemini-3.1-pro-preview-customtools | gagal | 0/3 | rate_limited |
| gemini-pro-latest | gagal | 0/3 | rate_limited |
| gemini-4-argon | gagal | 0/3 | rate_limited |

## PUTUSAN GERBANG FASE 0

**LOLOS = 9 dari 19 → DI BAWAH AMBANG 10 → GERBANG GAGAL → STOP.**

Fase 1 (dynamic discovery + liveness) TIDAK diimplementasikan, sesuai B3
tanpa rasionalisasi. Catatan objektif (bukan dasar lanjut):

- 9 lolos terdiri dari: 7 Gemini + 1 gemma + (2.5-flash & 2.5-flash-lite adalah
  model roster existing). Tambahan bersih di atas roster ≈ 4-5 id.
- Pola kegagalan konsisten dengan probe 15-16 Okt: `overloaded` (503) bersifat
  time-variant per jam (3.8-flash: served 15 Okt, 0/3 hari ini; gemma-4-26b
  2/3 hari ini vs 2/3 kemarin), sedangkan `rate_limited`/`entitlement` pada
  kelas pro/argon stabil gagal.
- Jendela waktu probe: 01:10 GMT+7 = 18:10 Pacific (RPD reset tengah malam
  Pacific belum terjadi) — kuota harian masih dari kemarin.

## Baseline pendukung

- `evidence/pytest-baseline.txt`: 15/15 PASS (`tests/test_key_catalog.py`)
- Working tree: HEAD `271e560` (evidence gerbang sebelumnya, terpush);
  WIP Fase 2 lama (`key_catalog.py`, allowlist 5 id statis, 33/33 unit)
  tetap uncommitted — bukan bagian dari putusan gerbang ini
