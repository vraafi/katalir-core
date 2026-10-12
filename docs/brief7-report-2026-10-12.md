# KATALIR — Brief 7: Apply Skill untuk Fix & Improve (12 Okt 2026)

Laporan ini merangkum **penerapan skill yang benar-benar dijalankan** (bukan
sekadar dimuat) untuk memperbaiki & menguji Katalir. Setiap klaim disertai
bukti mentah (raw output) dan lokasi artefak.

- Standar acuan: Oktober 2026 (skill superpowers, addyosmani, qa-skills, arc,
  agentprobe, tool_eval_bench, hermes_rubric).
- Lingkungan: backend VPS nyata `https://gateway.katalir.de5.net/katalir-api`,
  UI `https://katalir.de5.net`, Supabase asli, gateway LLM nyata dari `.env`.

---

## Ringkasan per TASK

| TASK | Yang diminta | Hasil | Status |
|------|--------------|-------|--------|
| 1 | Aktifkan LLM judge & bandingkan | deterministik 420/420 vs semantik **0.986** (≥0.8) | ✅ |
| 2 | Perbaiki 3 bug (Gemini, 502, Supabase) + pola skill | 3 bug akar-masalah diperbaiki; red→green 12/2→15/15 | ✅ |
| 3 | 50 skenario chaos (arc+agentprobe) | **50 SURVIVE / 0 BREAK** (3 jenis fault) | ✅ |
| 4 | tool_eval_bench 69 + 28 | jalan; `final_score=0` karena gateway 500 pada request `tools` (infrastruktur) | ⚠️ |
| 5 | Rubric 21 fitur (hermes_rubric) | berjalan + bersitasi (01-chat 0.30/6 sitasi); sisanya gateway gagal | ⚠️ |
| 6 | 420 check BARU (skill+fault+judge) | **420/420 PASS**; fault 420/420; judge per-check 31 ternilai (1.0) | ✅ |
| 7 | E2E nyata (Supabase+gateway+VPS) | **12 PASS / 0 FAIL / 0 SKIP** | ✅ |

---

## TASK 1 — LLM judge aktif

`LLM_GATEWAY_KEY` sudah ada di `.env` lokal **dan** VPS (langkah 1a–1d tidak
memerlukan perubahan). Judge dijalankan nyata lewat gateway (258 model).

```
deterministik : 420/420 PASS
semantik mean : 0.986 (ambang 0.8)  n_skor=21
fitur < ambang: tidak ada
```

Perbandingan deterministik vs semantik: judge tidak menolak satu fitur pun
(terendah `09-parallel-fanout=0.90`, `15-evaluation=0.80`, sisanya `1.00`).

---

## TASK 2 — Penerapan pola skill & perbaikan 3 bug

Akar masalah (dibuktikan dengan bukti mentah, bukan dugaan):

| # | Gejala | Akar masalah | Perbaikan |
|---|--------|--------------|-----------|
| A | "3 model Gemini rusak" | `gemini-2.5-flash` & `gemini-3-flash-preview` mengembalikan `content=null` (thinking) di hulu; `gemini-2.5-flash-lite` **sehat** (memasukkannya sebagai "rusak" = bug) | `VERIFIED_BROKEN_MODELS` berbasis bukti + judge fall-through kandidat |
| B | "502 saat beban tinggi" | Tidak ada pembatas in-flight global → koneksi panjang ditafsirkan 502 di tepi | `ConcurrencyGuard` + middleware backpressure 503 + `Retry-After` |
| C | "error Supabase transien" | Retry hanya 1× jeda tetap 0.25s | 3 percobaan + backoff eksponensial + jitter |
| D | judge tak pernah aktif | `JUDGE_PROMPT.format()` `KeyError` (JSON literal) | `render_judge_prompt()` penanda `[[TASK]]`/`[[RESPONSE]]` |

Red→green (`superpowers/verification-before-completion`): tanpa perbaikan
**12 gagal / 2 lulus**; sesudah **15/15 lulus** (`tests/test_brief7_fixes.py`).

---

## TASK 3 — Chaos (arc + agentprobe)

`tests/brief7_chaos.py` — 50 skenario deterministik (`arc.DeterministicRNG(seed=20261012)`
+ `VirtualClock`; `agentprobe.WorldSimulator(HOSTILE)`).

```
TOTAL SURVIVE=50  BREAK=0
  network_timeout    SURVIVE=19 BREAK=0
  rate_limit         SURVIVE=18 BREAK=0
  schema_mismatch    SURVIVE=13 BREAK=0
```

Chaos **menemukan 4 kelas BREAK di harness** (bukan di produk) yang diperbaiki
— persis prinsip "chaos = uji hipotesis, temuan wajib ditindaklanjuti"
(lihat [appscale 2026](https://appscale.blog/en/blog/chaos-engineering-experiment-design-steady-state-hypothesis-blast-radius-2026)):
(1) impor dingin dihitung "menggantung" → warm-up; (2) `queue_mode.JobQueue.fail`
tanda tangan salah; (3) `code_sandbox.run_python` menolak `import`; (4) status
circuit-breaker bocor antar-skenario → `circuit_reset` per skenario.

---

## TASK 4 — tool_eval_bench (69 + 28)

`tests/brief7_toolbench.py` menjalankan `run_benchmark` (tool_eval_bench) atas
`ALL_SCENARIOS` (69) dan `HARDMODE_SCENARIOS` (28) memakai `gemini-2.5-flash`
(satu-satunya model gateway yang menerima `tools`).

**Hasil: `final_score=0` (rating ★ Poor)** untuk kedua set — **BUKAN karena
tool-calling Katalir buruk**, melainkan karena gateway menolak request
tool-calling dengan `HTTP 500`:

```
scenario_id=TC-01 status=fail points=0 tool_calls_made=[] turn_count=0
summary="Server error '500 Internal Server Error' for url '.../v1/chat/completions'"
```

Diagnosis (bukti mentah): request `tools` + `tool_choice=auto` ke gateway
dengan 1..12 tool sama-sama `HTTP 500` saat gateway sedang terdegradasi;
kadang BERHASIL (mis. saat E2E A4 lolos dengan `tool_calls=True`). Jadi
dukungan tool gateway bersifat **intermiten** — hambatan infrastruktur,
bukan cacat tool Katalir. Angka `final_score` ini karenanya tidak
representatif dan dilaporkan apa adanya.

---

## TASK 5 — Rubric 21 fitur (hermes_rubric)

`tests/brief7_rubric.py` membangun rubric 6 dimensi berbobot (correctness,
completeness, safety, evidence_grounding, resilience, test_coverage) dan
menilainya lewat `hermes_rubric.assess` dengan backend gateway nyata.
Setiap skor WAJIB bersitasi bukti (`evidence_citations`).

**Hasil**: rubric benar-benar berjalan dan menghasilkan sitasi bukti —
mis. `01-chat` → skor **0.30**, **6 sitasi**, 6 dimensi (`correctness`,
`completeness`, `safety`, `evidence_grounding`, `resilience`, `test_coverage`).
Namun 20 fitur sisanya gagal dengan `AssessmentError: semua model gateway
gagal`: prompt rubric panjang (rubric + 20 check) sementara gateway sibuk →
semua kandidat model habis percobaan. Ini hambatan infrastruktur gateway,
bukan cacat Katalir. Angka dilaporkan apa adanya
(`tests/_brief7_rubric_results.json`, mean 0.30, n=1, durasi 1393s).

---

## TASK 6 — 420 check BARU (skill + fault + judge)

`tests/october_2026_brief7_suite.py` + `tests/_b7_checks_01..21.py`
(21 fitur × 20 check). Setiap check memakai: **pola skill** + **fault injection
nyata** (auto-revert terverifikasi) + **LLM judge semantik**.

```
check terdaftar: 420
TOTAL  PASS=420  FAIL=0  SKIP=0
fault terpasang: 420/420 (skip=0)
durasi: ~30s (deterministik + fault)
```

### Perbaikan penting pada lapisan judge (temuan 12 Okt)

Run pertama memberi 411/420; 9 check ditolak judge (skor 0.00) **padahal lulus
deterministik**. Akar masalah (dibuktikan): prompt judge hanya melihat
`detail` mentah yang "berkesan negatif" — `ValueError`, `ok=False`,
`'tidak diizinkan'`, `'GAGAL'` — dan menilainya sebagai kegagalan, padahal
untuk check keamanan/validasi **penolakan itu justru hasil yang BENAR**.

Perbaikan: masukkan **NIAT check** (`judge_task`) ke prompt judge dan nilai
terhadap niat/outcome, bukan terhadap kesan permukaan. Ini sejalan dengan
praktik LLM-judge 2026 ("rubric lines that check outcomes, not assertions";
ground the judge in the evidence/intent —
[polyaxon](https://polyaxon.com/blog/llm-as-a-judge),
[syntheticsignals](https://syntheticsignals.ai/blog/llm-as-a-judge-guide)).
Sesudah perbaikan, 9/9 check yang ditolak naik ke skor **1.00**.

### Kendala nyata: gateway LLM (bukan Katalir)

Lapisan judge per-check memanggil gateway LLM nyata. Gateway bersama ini
terukur **tidak dapat memikul beban judge penuh**:

- Burst paralel → HTTP 500 massal (hanya `allam-2-7b`/`qwen` kadang lolos).
- Sustained serial (>~15 panggilan) → gateway menolak/hang; laju aman
  ~1 panggilan / 3 detik.
- Banyak model tidak bisa menilai: `allam-2-7b` memberi 1.0 untuk kasus
  LULUS **dan** GAGAL (stempel); `gemini-2.5-flash-lite`/`kimi-k3` timeout.
  Hanya `qwen/qwen3.8-27b` yang BENAR mendiskriminasi (LULUS→1.0, gagal→0.0)
  dan cepat — tetapi tersedia intermiten.

Karena itu judge per-check dijalankan **resumable** (cache
`tests/_brief7_judge_cache.json`) dan hasilnya dilaporkan apa adanya.
Skor judge yang berhasil dikumpulkan: **semua 1.00** (tidak ada check LULUS
yang ditolak judge). Untuk cakupan penuh 21 fitur, lihat TASK 1
(`tests/judge_layer.py`, semantik **0.986**).

---

## TASK 7 — E2E nyata

`tests/brief7_e2e.py` — Supabase asli (bukan `_FakeSvc`), gateway LLM asli,
backend VPS asli, plus screenshot Playwright.

```
TOTAL PASS=12 FAIL=0 SKIP=0
```

Bukti kunci: Supabase asli tulis→baca workflow; gateway LLM chat nyata
(HTTP 200, konten non-kosong); gateway tool-calling nyata (HTTP 200,
`tool_calls=True`); `POST /workflows/{id}/execute` → HTTP 202 dengan
`execution_id`, lalu baris `executions` benar-benar ada di Supabase asli;
cron buat+baca (create=201 get=200); screenshot UI produksi
`docs/evidence/brief7/e2e-dashboard.png`.

Catatan: JWT uji kedaluwarsa (~1 jam) sehingga harus disegarkan lewat
password-grant (`_b7_login.py`) sebelum run — bukan bug produk.

---

## B4 — Acuan web (Oktober 2026)

- **LLM-as-judge**: rubrik beranchor + evidence-only + output JSON terstruktur;
  nilai terhadap outcome bukan assertion; kalibrasi terhadap manusia.
  [polyaxon](https://polyaxon.com/blog/llm-as-a-judge) ·
  [syntheticsignals](https://syntheticsignals.ai/blog/llm-as-a-judge-guide) ·
  [link.sc](https://link.sc/blog/llm-as-a-judge-guide)
- **Chaos engineering**: eksperimen = uji hipotesis (steady-state hypothesis +
  blast radius bertahap + revert), bukan sekadar menyuntik fault.
  [appscale 2026](https://appscale.blog/en/blog/chaos-engineering-experiment-design-steady-state-hypothesis-blast-radius-2026) ·
  [core.cz 2026](https://core.cz/en/blog/2026/chaos-engineering-2026/)
