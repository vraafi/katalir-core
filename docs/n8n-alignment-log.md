# n8n Alignment Log — Katalir

Log iterasi penyelarasan Katalir dengan fitur AI n8n.
Aturan: **tidak ada klaim tanpa bukti**; setiap iterasi mencatat sumber riset,
skill yang dimuat, celah yang ditemukan, implementasi, dan hasil hard test.

---

## Iterasi 2026-10-11

### 1. Riset (web-first, Oktober 2026)

Query yang dijalankan: `n8n AI features October 2026 assistant agents MCP server release`.

Sumber utama:

| Sumber | Isi |
|---|---|
| n8n **2.42.0** rilis **29 Sep 2026** (via undercodenews.com) | AI Agent Tool bisa memakai tool-nya sendiri (agen bersarang/hierarkis); perbaikan Agent Builder; MCP Registry di AI Assistant (feature flag dihapus → GA); Assistant **mencatat live test run sebagai *verification evidence***; Redis pulih setelah reconnect + deteksi half-open; validasi payload token sebelum resolusi user; **OpenTelemetry persistence** |
| community.n8n.io (10 Sep 2026) | Assistant update: agents, MCP servers, self-hosting satu baris |
| n8n.io/mcp | Integrasi MCP resmi n8n |

Tema rilis 2.42.0: pergeseran n8n dari *workflow automation* ke
**AI-agent orchestration** (Agent Builder, sub-agen, MCP, Assistant, sesi).

### 2. Skills dimuat (skill-first)

| Repo | Status | Yang dibaca |
|---|---|---|
| `natiixnt/n8n-autopilot` | ✅ ter-clone | `skills/n8n-autopilot/SKILL.md` — **5-Phase Autonomous Pipeline**; **Phase 3.2** = `n8n_update_partial_workflow({id, intent, operations:[{type:"addNode"\|"addConnection"\|"updateNode"\|...}]})`, dibangun **iteratif**, bukan sekali jadi |
| `rnarturovich/flowgent` | ✅ ter-clone | `README.md` — NL → workflow JSON (n8n & Make.com), CLI `flowgent gen`, SDK `WorkflowGenerator.generate({platform,prompt})`, `warnings` hasil AI |
| `sickn33/agentic-awesome-skills` | ⚠️ ter-clone (blob-filter) | `skills_index.json` mengindeks `skills/n8n-subworkflows` (sumber: `czlonkowski/n8n-skills`). Materialisasi penuh working tree gagal (RPC/early-EOF jaringan), jadi berkasnya diambil langsung dari repo sumber |

Catatan jujur: **`SUBWORKFLOW_PATTERNS.md` TIDAK ada di root**
`sickn33/agentic-awesome-skills`; ia berada di
`czlonkowski/n8n-skills/skills/n8n-subworkflows/SUBWORKFLOW_PATTERNS.md`
(diindeks oleh repo pertama). Berkas itu diunduh ke
`skills/_fetched/` dan dibaca.

Isi `SUBWORKFLOW_PATTERNS.md`: (a) `mode: all` vs `each`; (b) memecah 1
kemampuan jadi **N+1** sub-workflow ketika kontrak input berbeda; (c)
**fire-and-forget** (`mode: each` + `waitForSubWorkflow: false`) sebagai
satu-satunya cara paralel sejati, dengan **pelacakan selesai + batas waktu**
agar job yang mati tidak menggantung.

### 3. Celah yang ditemukan (setelah matriks di `docs/feature-gap-closure.md`)

Tujuh kapabilitas inti brief **sudah ada dan teruji** di Katalir. Celah yang
benar-benar terbuka:

1. **Edit workflow berbasis operasi** — Katalir hanya punya PATCH (rename/
   deskripsi) atau timpa `flow_data`. n8n-autopilot Phase 3.2 memakai
   `n8n_update_partial_workflow({intent, operations})`. **Belum ada.**
2. **Pola fan-out sub-workflow** — `subworkflow.py` sudah menegakkan kedalaman
   maksimum 3 + siklus, tetapi **belum** punya `mode: all|each` maupun
   fire-and-forget dengan pelacakan selesai + batas waktu.

### 4. Implementasi

#### 4.1 `workflow_ops.py` + `POST /workflows/{id}/ops`

- Operasi: `addNode`, `updateNode`, `removeNode`, `addConnection`,
  `removeConnection`.
- **Atomik** (satu gagal ⇒ dokumen asli kembali, `applied=0`), **anti-node-hantu**
  (edge ke node asing ditolak), **aman** (tolak `__proto__`/`constructor`/
  `prototype`, batas 200 operasi, batas graf dari `flow_limits.py`),
  **`dry_run`** untuk pratinjau, diff memakai ulang `environments.diff_flow`.
- Deterministik & tanpa I/O: lapisan LLM (flowgent-style) cukup **menghasilkan
  operasi**; penerapan/validasi/rollback tidak bergantung model.

#### 4.2 `subworkflow_batch.py`

- `plan_dispatch(items, mode="all"|"each", wait_for=…)` — `all` = 1 run berisi
  semua item; `each` = N run 1 item; `parallel = (each dan not wait_for)`.
- `evaluate_completion(rows, …)` — `done` / `waiting` / `timed_out` dengan
  batas waktu, sehingga job yang mati ditandai `timeout` dan **tidak
  menggantung** (persis resep SUBWORKFLOW_PATTERNS.md).

#### 4.3 Bug nyata yang ditemukan hard test (lalu diperbaiki)

`evaluate_completion` awalnya mengurutkan agregasi dengan `sorted(job_id)`
secara **string** → `"run:10"` mendahului `"run:2"` (urutan leksikografis),
sehingga hasil agregasi salah urut. Diperbaiki dengan `_order_key()` yang
mengutamakan field `index` dan, bila tidak ada, mem-parsing sufiks angka pada
`job_id`. Ditemukan oleh `test_15`, bukan oleh tinjauan manual.

### 5. Hard test — **40/40 PASS (100%)**

```
$ python -m pytest tests/test_workflow_ops.py tests/test_workflow_ops_api.py \
    tests/test_subworkflow_batch.py -q
........................................                                 [100%]
40 passed in 3.70s
```

Cakupan skenario (batas, error, performa, keamanan):

| Berkas | Jml | Contoh cakupan |
|---|---:|---|
| `tests/test_workflow_ops.py` | 20 | jalur bahagia; merge config; cascade hapus edge; **atomik rollback**; edge node hantu (source & target); id duplikat; op tak dikenal; kind tak dikenal; **prototype pollution**; self-loop; kunci update terlarang; batas 200 op; dry-run tanpa mutasi; immutability; **performa 200 op < 1 s**; determinisme; bentuk spec; remove-connection hilang; op kosong |
| `tests/test_workflow_ops_api.py` | 5 | endpoint menerapkan+menyimpan; 422 **tanpa** menyimpan; dry-run pratinjau; daftar kosong → 400; **owner-scoped → 403** |
| `tests/test_subworkflow_batch.py` | 15 | `all`=1 run; `each`=N run; paralel hanya saat fire-and-forget; item kosong; mode invalid; batas job; done+agregasi; waiting; **cap → timed_out**; batas `>=`; error terminal; isolasi `run_id`; baris kosong; **performa 1000 job < 1 s**; determinisme |

### 6. Regresi

Suite terarah pada modul yang bersinggungan dijalankan setelah perubahan:

```
$ python -m pytest tests/test_workflow_spec.py tests/test_workflow_normalizer.py \
    tests/test_delegation.py tests/test_n8n_ai_comparison.py \
    tests/test_503_detail_contract.py tests/test_subworkflow.py -q
59 passed, 1 warning in 126.55s
```

**0 regresi.** Tidak ada kegagalan; penambahan endpoint dan dua modul baru
tidak mengubah perilaku yang sudah ada.

### 7. Artefak iterasi

- `workflow_ops.py` (baru) · `subworkflow_batch.py` (baru)
- `api_server.py` — `WorkflowOpsRequest` + `POST /workflows/{workflow_id}/ops`
- `tests/test_workflow_ops.py`, `tests/test_workflow_ops_api.py`,
  `tests/test_subworkflow_batch.py` (baru)
- `docs/feature-gap-closure.md` (matriks tunggal, baru)
- `docs/n8n-alignment-log.md` (berkas ini)
- `skills/` — 3 repo skill ter-clone + `skills/_fetched/` (SUBWORKFLOW_PATTERNS.md)

### 8. Revisi skill yang dimuat (reproducible)

Direktori `skills/` di-`.gitignore` (pihak ketiga, dapat dikloning ulang).
Revisi yang dibaca dicatat di sini agar dapat direproduksi:

| Repo | Revisi (HEAD) |
|---|---|
| `natiixnt/n8n-autopilot` | `7326e5ea052f9b7b6c4fe397938598df7fc58d49` |
| `rnarturovich/flowgent` | `d0b5d0cba82175daf78089c7417adaf19ae58673` |
| `sickn33/agentic-awesome-skills` | `1c7bdea7f9094080fdb6f8b9b0aefb13030a2e31` |
| `czlonkowski/n8n-skills` (sumber `n8n-subworkflows`) | diambil via `raw.githubusercontent.com` (`skills/n8n-subworkflows/{SKILL.md,SUBWORKFLOW_PATTERNS.md}`) |
