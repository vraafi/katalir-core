# Brief 7 — Laporan Perbaikan & Penerapan Skill (12 Okt 2026)

Dokumen ini mencatat **perbaikan nyata** (bukan sekadar memuat skill) untuk
Brief 7, dengan bukti mentah (raw evidence) dan lokasi kode.

Pola skill yang benar-benar diterapkan:
`superpowers/systematic-debugging` (akar masalah dulu),
`superpowers/verification-before-completion` (verifikasi segar),
`addyosmani/debugging-and-error-recovery` (triage),
`addyosmani/performance-optimization` (ukur→perbaiki→verifikasi),
`qa-skills/chaos-engineering` (fault injection + blast radius + revert),
`qa-skills/ai-system-testing` (judge semantik, property assertions, detector).

---

## Ringkasan temuan & perbaikan

| # | Gejala (brief) | Akar masalah (dibuktikan) | Perbaikan | Bukti |
|---|----------------|---------------------------|-----------|-------|
| A | "3 model Gemini rusak" | `gemini-2.5-flash` & `gemini-3-flash-preview` mengembalikan `content=null` (thinking model) **di hulu**, bahkan pada `max_tokens=512` dan `reasoning_effort=none`. `gemini-2.5-flash-lite` SEHAT — memasukkannya ke daftar "rusak" adalah bug. | `VERIFIED_BROKEN_MODELS` berbasis bukti + judge mencoba kandidat berikutnya (`judge_harness.py`) | `tests/test_brief7_fixes.py` (red→green) |
| B | "502 saat beban tinggi" | Tidak ada pembatas in-flight global; koneksi LLM panjang ditafsirkan 502 di tepi Cloudflare. | `ConcurrencyGuard` + middleware backpressure 503+`Retry-After` (di dalam CORS) — `rate_limit.py`, `api_server.py` | `test_chat_backpressure_returns_503_retry_after` |
| C | "error Supabase transien" | Retry hanya **1×** dengan jeda tetap 0.25s (58× `RemoteProtocolError` di log produksi). | 3 percobaan + backoff eksponensial (0.2/0.4/0.8, cap 2s) + jitter — `database.py` | `test_wrap_write_retries_transient_then_succeeds` |
| D | (ditemukan saat menjalankan TASK 1) judge tidak pernah aktif | `JUDGE_PROMPT.format()` melempar `KeyError: '"correctness"'` karena prompt memuat contoh JSON literal. | `render_judge_prompt()` dengan penanda `[[TASK]]`/`[[RESPONSE]]` + `str.replace` | `test_judge_prompt_render_safe_with_json_braces` |

Red→green (superpowers `verification-before-completion`): tanpa perbaikan
**12 gagal / 2 lulus**; dengan perbaikan **15/15 lulus**.

---

## TASK 1 — Judge LLM aktif

- `LLM_GATEWAY_KEY` sudah ada di `.env` lokal **dan** VPS (tidak perlu ditambah).
- Gateway nyata: 258 model. Kandidat judge: `gemini-2.5-flash-lite`, …
- Hasil `tests/judge_layer.py` (bukti mentah):
  ```
  deterministik : 420/420 PASS
  semantik mean : 0.986 (ambang 0.8)  n_skor=21
  fitur < ambang: tidak ada
  ```
- Perbandingan deterministik vs semantik: **420/420 vs 0.986** — judge tidak
  menolak satu fitur pun; `09-parallel-fanout=0.90`, `15-evaluation=0.80`,
  sisanya `1.00`.

---

## TASK 3 — Chaos (arc + agentprobe)

`tests/brief7_chaos.py` — 50 skenario deterministik (arc `DeterministicRNG` +
`VirtualClock`; agentprobe `WorldSimulator` `HOSTILE`).

```
TOTAL SURVIVE=50  BREAK=0
  network_timeout    SURVIVE=19 BREAK=0
  rate_limit         SURVIVE=18 BREAK=0
  schema_mismatch    SURVIVE=13 BREAK=0
```

Selama pengerjaan, chaos **menemukan 4 kelas BREAK di harness** (bukan di
produk) yang lalu diperbaiki — persis prinsip chaos "temuan wajib
ditindaklanjuti": (1) impor dingin dihitung "menggantung" → warm-up;
(2) `queue_mode.JobQueue.fail(job_id, error)` (harness memakai tanda tangan
salah); (3) `code_sandbox.run_python` menolak `import` → memakai loop murni;
(4) status circuit-breaker bocor antar-skenario → `circuit_reset` per skenario.

Target yang bertahan (fail-fast/terdegradasi rapi): `retry_policy.run_protected`
& `with_retry`, `mcp_compat.expose_tool_errors` (ToolError bertipe),
`code_sandbox.run_python` (killed=True), `guardrails.check_text` (judge gagal →
tetap dict), `chat_stream.stream_or_fallback` (fallback), `stream_with_watchdog`
(heartbeat+error), `queue_mode.JobQueue`, `plugin_system.Sandbox` (CapabilityDenied),
`evaluation.Evaluator`, `source_control.serialize_workflow`.

---

## TASK 6 — 420 check BARU (skill + fault + judge)

`tests/october_2026_brief7_suite.py` + `tests/_b7_checks_01..21.py`.

```
check terdaftar: 420
TOTAL  PASS=420  FAIL=0  SKIP=0
per metode : M1=20, M2=36, M3=50, M4=41, M5=273
per skill  : ai-system-testing=116, chaos-engineering=48, fault-injection=32,
             verification-before-completion=94, test-strategy=89,
             systematic-debugging=27, debugging-and-error-recovery=9,
             performance-optimization=5
fault terpasang: 420/420 (skip=0)
```

Setiap check: pola skill + fault injection nyata (auto-revert terverifikasi) +
LLM judge semantik.

---

## Penerapan skill ai-system-testing (detector bawaan)

```
python skills/october-2026/qa-skills/skills/ai-system-testing/scripts/detect_injection.py --selftest
  payload fired rules: ['dns-exfil','fake-authority','hidden-instruction',
    'home-dir-harvest','instruction-override','role-override',
    'run-script-instruction','secret-exfil-request','self-propagation',
    'verbal-fallback']
  RESULT: PASS
```

10 kelas aturan injeksi benar-benar menyala — detector siap dipakai sebagai
gate atas konten tak tepercaya sebelum agent bertindak.
