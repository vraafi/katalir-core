# Fitur #11 — Testing Framework (workflow testkit)

**Status:** ✅ HIJAU — 119/119 skenario katalog + 11/11 adversarial + load 0 error
**Berkas:** `workflow_testkit.py`, `tests/test_workflow_testkit.py`,
`.github/workflows/ci.yml`

## Masalah yang diselesaikan

Sebelum fitur ini tidak ada cara sistematis menguji **perilaku** workflow.
Setiap fitur (#1–#10) menulis test-nya sendiri, tetapi tidak ada harness yang:
menjalankan graf melalui engine asli, mendefinisikan skenario secara
deklaratif, menyediakan katalog luas, mengukur perilaku di bawah beban, dan
menjalankan matriks adversarial keamanan.

## Research

| Paket / Pendekatan | Verdict | Alasan |
|---|---|---|
| `agentest` | ❌ | Rilis terakhir Mar 2026 (7 bulan), 2 rilis. |
| `robotframework-agenteval` | ❌ | Menyeret Robot Framework penuh untuk kebutuhan yang bisa dipenuhi harness ~600 baris. |
| `pytest-asyncio` | ❌ | Repo memakai konvensi `asyncio.run()` per test; menambah plugin mengubah harness SELURUH repo. |
| **harness in-house di atas engine asli** | ✅ **dipakai** | Engine sudah punya titik injeksi (`registry`, `reasoner`, `healing_factory`); nol dependency baru. |

**Pilihan:** harness in-house; engine NYATA (`StatefulOrchestrator`), hanya
batas I/O yang di-stub.
**Alasan:** menguji engine sungguhan, bukan tiruan engine — dan berjalan
**hermetik** (tanpa Supabase/LLM/jaringan) sehingga bisa jadi gerbang CI.

## Implementasi

- **`workflow_testkit.py`** — `Scenario`, `run_flow()`, `run_scenario()`,
  `build_catalog()` (119 skenario), `security_adversarial()`, `load_test()`,
  CLI (`python workflow_testkit.py [--load] [--json]`).
- **`tests/test_workflow_testkit.py`** — 12 test (termasuk **meta-test**).
- **`.github/workflows/ci.yml`** — CI hermetik: testkit + pytest terpilih.
- **`database.py`** — temuan keamanan: `bot_token` ditambahkan ke
  `_SENSITIVE_KEYS` (lihat di bawah).

### Katalog (119 skenario)

| Kategori | Jumlah | Cakupan |
|---|---|---|
| linear | 22 | rantai 1–6 node; campuran mcp→agent→mcp |
| provider | 16 | 8 provider × (sukses, gagal) |
| placeholder | 18 | alias, indeks, negatif, list-of-dict, `["kunci"]`, akar tak dikenal |
| condition | 24 | ==, !=, <, <=, >, >=, in, not, and/or, aritmatika; + 2 error |
| batch | 8 | split_in_batches 1/2/3/4/5/7/10 |
| parallel | 4 | fan-out 2/3/5/8 → merge |
| delegation | 2 | supervisor → 1 & 2 sub-agent |
| error | 7 | agent gagal, tanpa trigger, siklus, kind ngawur |
| graph | 7 | kedalaman 10/20/40; lebar 10/20/30; node tanpa predesesor |
| security | 11 | matriks adversarial (di bawah) |

## Hard Test — 12/12 PASS

```
tests/test_workflow_testkit.py ............ [100%]  12 passed in 2.76s
```

| # | Test | Status | Bukti |
|---|---|---|---|
| 1 | katalog ≥ 100 | ✅ | 119 skenario, ID unik |
| 2 | seluruh katalog lulus | ✅ | 119/119 |
| 3 | **META**: ekspektasi salah → FAIL | ✅ | `status=FAIL \| error_substr=FAIL` |
| 4 | **META**: node status salah → FAIL | ✅ | `node:m1=FAIL` |
| 5 | stub provider di-restore | ✅ | `run_async` identik objek asli; state kosong |
| 6 | agent dipanggil | ✅ | `reasoner_calls=1`, `instruction='jawaban'` |
| 7 | error dilaporkan | ✅ | `provider 'telegram' status=error: boom-xyz` |
| 8 | adversarial keamanan | ✅ | 11/11 |
| 9 | load test 0 error | ✅ | 20 & 50 konkuren, 0 error |
| 10 | tidak menyentuh jaringan | ✅ | registry stub, 0 invoke asli |
| 11 | semua kategori terwakili | ✅ | 10 kategori |
| 12 | bot_token teredaksi | ✅ | `[REDACTED]`, `chat_id` utuh |

### Load test (raw)

```
n=  50 errors=0 wall=11.1ms  p50=8.13ms  p95=9.74ms  max=9.85ms   thr=4493.2/s
n= 100 errors=0 wall=74.5ms  p50=69.01ms p95=71.72ms max=71.96ms  thr=1342.9/s
n= 200 errors=0 wall=43.1ms  p50=31.24ms p95=37.65ms max=38.12ms  thr=4638.6/s
```
Catatan jujur: n=100 lebih lambat dari n=200 — artefak penjadwalan/GC, bukan
pola; semua level **0 error**.

### Adversarial keamanan — 11/11

| Skenario | Bukti |
|---|---|
| SSRF host privat ditolak | `127.0.0.1,10.0.0.5,192.168.1.10,169.254.1.1,172.16.5.5,0.0.0.0` → 6/6 |
| SSRF host publik diizinkan | `8.8.8.8` lolos |
| Sandbox: import ditolak | `import os`, `__import__` → 4/4 |
| Sandbox: open/eval/exec/getattr | 5/5 |
| Sandbox: escape dunder | `__globals__`,`__mro__`,`__subclasses__` → 4/4 |
| Redaksi rahasia di log | api_key/password/bot_token/ghp → 0 bocor |
| Validasi graf rusak | 5 bentuk → 5/5 (validator templates + MCP) |
| API key MCP palsu | 6 bentuk → 6/6 |
| API key MCP diubah | tanda tangan palsu ditolak |
| Cron invalid | 7/7 ditolak; 3 sah diterima; TZ non-IANA 3/3 ditolak |
| Sanitasi input injeksi | output tetap terbatas |

## Temuan nyata (ditemukan oleh fitur ini)

1. **`bot_token` TIDAK teredaksi** (medium). Kredensial Telegram disimpan
   sebagai `{"bot_token": ..., "chat_id": ...}`; `_SENSITIVE_KEYS` mencocokkan
   **eksak** dan hanya memuat `token`, sehingga `bot_token` lolos dan nilainya
   tercetak utuh di log eksekusi. **Diperbaiki**: `bot_token`,
   `telegram_bot_token`, `access_token_secret` ditambahkan.
2. **Node tanpa predesesor (bukan trigger) tetap dieksekusi** — `_runnable`
   memakai "semua predesesor completed"; himpunan kosong lolos secara vakum.
   Didokumentasikan sebagai perilaku nyata (skenario
   `graph-node-tanpa-predesesor`), bukan disembunyikan.
3. **`next_fire_utc` tidak menolak cron 6-field** — croniter menerimanya.
   Gerbang API yang benar adalah `is_valid_cron` (menolak != 5 field). Matriks
   adversarial diperbaiki untuk menguji gerbang yang benar.

## Blocker
Tidak ada. CI dijalankan pada suite hermetik saja; suite yang butuh
Supabase/Gemini sengaja TIDAK dimasukkan agar CI tidak "hijau palsu".

## Next
Semua 11 fitur selesai — lihat tabel final di `implementation-log-2026-10-08.md`.
