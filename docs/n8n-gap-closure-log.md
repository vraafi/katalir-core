# n8n GAP CLOSURE LOG — 12 FITUR LANJUTAN (Okt 2026)

Standar: best practice Okt 2026 · Mode: OTONOM (riset → inventory → implementasi
→ hard test → verifikasi → commit → lanjut)

Dokumen ini mencatat 12 fitur penutup gap n8n lanjutan. Fitur sebelumnya
(#1–#11 awal + 5 gap n8n + 11 enterprise) tercatat di
`docs/enterprise-features-log.md`, `docs/feature-gap-closure-2026-10-08.md`,
dan `docs/enterprise-100-percent-log.md`.

## Ringkasan

| # | Fitur | Modul | Hard Test | Commit | Status |
|---|---|---|---|---|---|
| 7 | Metric-based Evaluations | `metrics_eval.py` | 16/16 | — | ✅ |
| 12 | External Memory Provider | — | — | — | pending |
| 11 | Redaction + Enforce 2FA | — | — | — | pending |
| 4 | Log Streaming SIEM | — | — | — | pending |
| 8 | OTel / LangSmith Tracing | — | — | — | pending |
| 3 | Self-healing Persistence | — | — | — | pending |
| 6 | End-user Credentials | — | — | — | pending |
| 10 | Custom RBAC | — | — | — | pending |
| 5 | Agent Sandbox Isolation | — | — | — | pending |
| 2 | MCP Build Workflow | — | — | — | pending |
| 1 | n8n Agents (first-class) | — | — | — | pending |
| 9 | Durable Execution via Dapr | — | — | — | pending |

---

## FITUR #7: METRIC-BASED EVALUATIONS

### Research (link Okt 2026)

| Sumber | Link | Temuan | Keputusan |
|---|---|---|---|
| n8n Evaluations (Pro) | https://docs.n8n.io/ | Evaluations memakai metrik terhitung + panel, bukan hanya lulus/gagal | Tambah lapisan metrik terhitung di atas `evaluation.py` |
| Praktik LLM eval 2026 | https://agentmarketcap.ai/blog/2026/04/08/ai-agent-memory-shootout-2026-mem0-zep-letta-supermemory | Metrik deterministik (P/R/F1) untuk tugas berlabel; LLM-as-judge untuk kualitas terbuka; JANGAN dicampur tanpa menyebut mode | Pisahkan `compare_mode`; labelisasi dari teks, bukan dari skor fuzzy tanpa catatan |
| Confusion matrix & kelas | standar klasifikasi scikit-learn | CM butuh LABEL kelas, skor kontinu tidak bisa jadi kelas tanpa ambang | `labelize()` menurunkan label + laporkan `threshold` |

### Kredensial .env
- Tidak ada kredensial baru yang dibutuhkan (perhitungan murni).
- Memakai kembali backend persistensi `evaluation.save_run` → tabel `eval_runs`
  (Supabase, sudah ada sejak `migrations/2026_evaluation.sql`).

### Implementasi
- File: `metrics_eval.py` (baru, murni — tanpa DB/jaringan/LLM).
- `classification_report()` — accuracy, precision/recall/F1 macro + per-kelas,
  support, confusion matrix persegi.
- `latency_metrics()` — mean/p50/p95/p99/min/max.
- `cost_metrics()` — total/mean/tokens/biaya per 1.000 kasus.
- `chart_data()` — payload siap-render (bar, per-kelas, line, confusion, cost).
- `compare_runs()` — delta akurasi + F1 macro vs baseline, flag `regressed`.
- `evaluate_with_metrics()` — orkestrator; **runner dipanggil SEKALI** per kasus.
- `export_report()` — json / csv / markdown; `confusion_summary()`,
  `top_confusions()`.
- API: `POST /evaluations/metrics`, `GET /evaluations/metrics/metrics`.
- Registry `/version`: `28_metric_eval`.

### Hard Test — `tests/test_metrics_eval.py` (16/16 PASS)
```
33 passed in 0.95s   (16 metrics_eval + 17 evaluation lama — tanpa regresi)
```

| # | Skenario | Status | Raw Output |
|---|----------|--------|------------|
| 1 | Akurasi campuran benar/salah | PASS | `total=4 correct=3 accuracy=0.75` |
| 2 | Precision/recall/F1 eksak kelas tunggal | PASS | `tp=2 fp=1 fn=1 -> P=R=F1=0.6667` |
| 3 | Macro & support | PASS | `support[c]=1`, `0 <= macro.f1 <= 1` |
| 4 | `actual` kosong → kelas `__error__` | PASS | `accuracy=0.5`, `cm[ok][__error__]=1` |
| 5 | `expected` kosong → `__empty__` | PASS | `labels=['__empty__'] accuracy=1.0` |
| 6 | Dataset kosong → tanpa bagi nol | PASS | `total=0 accuracy=0.0 p99=0.0` |
| 7 | Latency p50/p95/p99 eksak (1..100) | PASS | `p50=50.0 p95=95.0 p99=99.0` |
| 8 | Cost total/mean/tokens | PASS | `tokens=4000/2000 total=0.004 mean=0.001` |
| 9 | Confusion matrix persegi & konsisten | PASS | `sum(cm)=total`, `diag=correct` |
| 10 | Chart data shape | PASS | `bar[0]=accuracy`, `line=['p50','p95','p99']` |
| 11 | Baseline mendeteksi regresi | PASS | `delta=-0.2`, `regressed=True` |
| 12 | Baseline mendeteksi perbaikan | PASS | `delta=+0.15`, `regressed=False` |
| 13 | Runner dipanggil SEKALI per kasus | PASS | `calls=2` untuk 2 kasus |
| 14 | Filter metrik (`metrics=["latency"]`) | PASS | `classification=None cost=None` |
| 15 | Ekspor JSON/CSV/Markdown valid | PASS | `accuracy,1.0` pada CSV |
| 16 | Performa 1000 baris | PASS | `< 1.0 s` (murni, tanpa I/O) |

### Bug NYATA yang ditemukan hard test (dan diperbaiki)

**BUG — `_percentile` galat satu langkah pada N genap.** Rumus lama
`round(p/100*(N-1))` memberi **p50 = 51** pada data `1..100` (seharusnya 50),
karena pembulatan `.5` ke atas. Ini juga salah untuk p95/p99 pada dataset
berukuran genap. Diperbaiki ke **nearest-rank** (`ceil(p/100*N)`) dengan
komentar alasan. Terbukti: `p50=50.0 p95=95.0 p99=99.0` (uji #7 GAGAL dengan
rumus lama).

**BUG — `expected` kosong salah diklasifikasikan sebagai error.** Dataset tanpa
ground truth harus menghasilkan label `__empty__` di kedua sisi, bukan
`__error__`. Diperbaiki di `labelize()`.

### Verifikasi Production (endpoint nyata via TestClient)
```
== catalog ==
200 {'status': 'success', 'metrics': ['accuracy','precision','recall','f1','latency','cost','confusion']}

== POST /evaluations/metrics ==
status    = 200
accuracy  = 0.75
macro f1  = 0.75
latency p95 = 42.0
cost total  = 7.2e-05
regressed   = False
chart keys  = ['bar','confusion','cost','line','per_class','type']
confusion   = {'d': {'WRONG': 1, ...}, 'a': {'a': 1, ...}, ...}
export head = "# Evaluation report — live-check"
run_id      = 4a76a33a
+ POST https://qmukkphwaajzbqjrcvaz.supabase.co/rest/v1/eval_runs → HTTP/2 201 Created
```
Persistensi ke Supabase terverifikasi (201 Created pada `eval_runs`).

### Status: 100% COMPLETE ✅
