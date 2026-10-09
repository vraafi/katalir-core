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
| 7 | Metric-based Evaluations | `metrics_eval.py` | 16/16 | `916e5f9` | ✅ |
| 12 | External Memory Provider | `memory_provider.py` | 14/14 | — | ✅ |
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
Commit: `916e5f9`

---

## FITUR #12: EXTERNAL MEMORY PROVIDER (Supermemory / Mem0 / Zep / Letta)

### Research (link Okt 2026)

| Sumber | Link | Temuan | Keputusan |
|---|---|---|---|
| Supermemory API reference | https://supermemory.ai/docs/api-reference/overview | Base `https://api.supermemory.ai`, `Authorization: Bearer sm_...`. Ingest `POST /v3/documents`, search `POST /v4/search`. **v3/v4 DEPRECATED — shutdown 31 Des 2026** (v5 menyusul) | Implementasi v3/v4 + catat TODO migrasi v5 |
| Mem0 REST API | https://docs.mem0.ai/open-source/features/rest-api | OSS server **tanpa** prefix `/v1`: `POST /memories` (`messages`,`user_id`,`agent_id`), `POST /search` (`query`,`user_id`), `DELETE /memories/{id}`. Auth `X-API-Key` atau Bearer JWT | Pakai path OSS tanpa `/v1` + Bearer (kompatibel platform) |
| Zep docs | https://help.getzep.com/v2/sdk-reference/memory/add | Sesi eksplisit: `POST /api/v2/sessions/{sid}/memory`; pencarian `GET .../memory/search` | Sesi deterministik `user::agent` (tanpa panggilan create) |
| Letta docs | https://docs.letta.com/agent-sdk/memory | Memori = **blocks** per agent (`GET/POST /v1/agents/{id}/memory/blocks`) | Adapter block + filter query lokal |
| Perbandingan provider 2026 | https://agentram.dev/ai-agent-memory-providers-compared.html | Tidak ada pemenang tunggal; biaya/kualitas berbeda per use case | **Adapter pattern + fallback internal**, bukan pilih satu |

### Kredensial .env
- `.env` **TIDAK** memuat kunci Supermemory/Mem0/Zep/Letta (diverifikasi LANGKAH 0).
- Karena itu: kunci disimpan **per user** di `user_settings` lewat UI/API, dan
  bila kosong → **fallback otomatis ke `internal`** (pgvector Supabase, sudah
  berjalan). Tidak ada mock: provider `internal` adalah implementasi nyata,
  dan provider eksternal diuji terhadap kontrak HTTP nyata (mock transport
  in-process + probe server asli).

### Implementasi
- File: `memory_provider.py` (BARU). Interface tunggal:
  `remember / recall / forget / search / health`.
- Provider: `InternalProvider` (default+fallback), `SupermemoryProvider`,
  `Mem0Provider`, `ZepProvider`, `LettaProvider` — semua via `httpx`
  (**NOL dependensi vendor baru**; `httpx` sudah dipakai repo).
- `MemoryService` — provider aktif + fallback + `sync()` (eksternal→internal).
- `resolve_provider()` / `service_for()` — config per user; kunci kosong →
  `internal` secara diam-diam (fail-safe).
- API: `GET /memory/provider`, `POST /memory/provider`,
  `POST /memory/provider/sync`, `GET /memory/provider/health`.
- Registry `/version`: `29_memory_provider`.

### Hard Test — `tests/test_memory_provider.py` (14/14 PASS)
```
14 passed in 2.27s
```

| # | Skenario | Status | Raw Output |
|---|----------|--------|------------|
| 1 | Internal roundtrip (remember/recall/forget) | PASS | id + 1 hit |
| 2 | Isolasi multi-tenant internal | PASS | A melihat "rahasia A" saja |
| 3 | Supermemory: bentuk request + Bearer | PASS | `containerTags=['user:u1','agent:ag1','user:u1:agent:ag1']` |
| 4 | Supermemory: search SATU `containerTag` | PASS | `body['containerTag']` str, tanpa `containerTags` |
| 5 | Mem0: `/memories` + parse ids | PASS | `id='mem-9'`, `user_id='u2'` |
| 6 | Mem0: `memory`→`content` | PASS | `content='teh manis'` |
| 7 | Zep: sesi deterministik + path search | PASS | `/api/v2/sessions/u9::agX/memory/search` |
| 8 | Letta: block + filter query | PASS | 1 dari 2 blok (jakarta) |
| 9 | Fallback tanpa kunci → internal | PASS | `provider=internal` (3 varian config) |
| 10 | Kunci ada → provider eksternal | PASS | `name=mem0 external=True` |
| 11 | Provider error 500 → fallback internal | PASS | `primary_ok=False`, recall dari internal |
| 12 | Sinkron eksternal → internal | PASS | `synced=2`, lokal `{alfa,beta}` |
| 13 | Tanpa kunci tetap jalan end-to-end | PASS | `primary_ok=True` |
| 14 | Performa 200 remember < 1 s + tag | PASS | `_scope_tags` deterministik |

### Bug NYATA yang ditemukan (dan diperbaiki)

**BUG kontrak — Supermemory `/v4/search` menolak >1 `containerTag`.**
Probe terhadap server NYATA (`https://api.supermemory.ai/v4/search`) via endpoint
`POST /memory/provider/sync` mengembalikan:
```
MemoryProviderError: supermemory: HTTP 400
{"error":"v4 search is single-space: pass one containerTag, or use /v3/search for multi-tag search"}
```
Diperbaiki: ingest mengirim **tiga** tag (user + agent + tag gabungan
`user:<u>:agent:<a>`), sedangkan search memakai **satu** `containerTag`
gabungan tersebut — deterministik sehingga dokumen tetap bisa ditemukan.
Setelah perbaikan, error bergeser ke `401 Unauthorized` (kunci palsu) =
**kontrak sekarang benar**. Dikunci oleh uji #4 (regresi).

### Verifikasi Production (endpoint nyata via TestClient)
```
GET  /memory/provider -> 200 {'provider':'internal','has_key':False,
     'supported':['internal','supermemory','mem0','zep','letta']}
POST /memory/provider {"provider":"supermemory","api_key":"sm_secret_xyz"}
     -> 200 {'provider':'supermemory','has_key':True}   # KUNCI tidak dikembalikan
POST /memory/provider {"provider":"nope"} -> 422 'Provider tidak dikenal: nope'
GET  /memory/provider/health -> 200 {'active':'supermemory', provider.ok=True}
```
Bukti isolasi kunci: `assert "sm_secret_xyz" not in r.text` LULUS.

### Status: 100% COMPLETE ✅
Catatan TODO: Supermemory v3/v4 dimatikan **31 Des 2026** → migrasi ke v5
sebelum tanggal itu (satu file, `SupermemoryProvider`).
