# Katalir — Feature Gap Closure vs n8n AI (Oktober 2026)

- Iterasi: **2026-10-11**
- Acuan riset: n8n **2.42.0** (rilis 29 Sep 2026) + n8n Assistant update (10 Sep 2026)
- Aturan: **tidak ada klaim tanpa bukti**. Setiap baris menyebut file/fungsi nyata.
- Dokumen ini menggantikan penamaan bertanggal sebelumnya
  (`feature-gap-closure-2026-10-08.md`, `roadmap-n8n-gap-2026-10-07.md`) sebagai
  matriks tunggal yang terus diperbarui.

Legenda: **DONE** = ada + teruji · **PARTIAL** = ada tapi belum lengkap ·
**TODO** = belum ada.

---

## 1. Tujuh kapabilitas inti n8n (checklist brief)

| # | Kapabilitas | Status | Bukti di Katalir |
|---|---|---|---|
| 1 | **Text-to-workflow** (buat/edit/debug via bahasa alami) | **DONE** | `workflow_spec.validate_spec` (validasi+nomalisasi), `ai_workflow_gen.py` (media→workflow), `workflow_autofix.py` (`SelfCorrectingLoop`, repair loop), **`workflow_ops.py` + `POST /workflows/{id}/ops`** (edit sebagian atomik — *baru iterasi ini*) |
| 2 | **Agents** (model, instruksi, tools, knowledge, memory sebagai entitas kelas satu) | **DONE** | `agents.py` (CRUD, state machine `can_transition`, `validate_tools`, `mcp_descriptor`, `recall_scope`), `agent_engine.py`, `agent_reasoner.py`, `memory_manager.py` (pgvector), `tests/test_agents.py`, `tests/test_agent_memory.py` |
| 3 | **Multi-agent collaboration** (delegasi + sub-workflow) | **DONE** | `execution_engine.py` direktif `[DELEGATE: agent_id=…]` (peran `supervisor`/`delegates`), `subworkflow.py` (`check_allowed`, `invoke_subworkflow`, `MAX_DEPTH=3`), `tests/test_delegation.py`, `tests/test_subworkflow.py` |
| 4 | **Built-in MCP server** (klien AI eksternal bisa memanggil Katalir) | **DONE** | `mcp_server.py` (~890 baris), rute `/mcp/server/tools`, `/mcp/server/call`, `/mcp/katalir/info|key|verify`, `mcp_gateway/`, `tests/test_mcp_server_builtin.py`, `tests/test_katalir_mcp_external.py`, `tests/test_mcp_tenant.py` |
| 5 | **Workflow evaluation** (metrik + node evaluasi) | **DONE** | `evaluation.py` (`Evaluator`, `compare` fuzzy/exact, `estimate_cost`, `save_run`/`list_runs` backend memory+Supabase), `tests/test_evaluation.py`, `tests/test_metrics_eval.py` |
| 6 | **Observability** (OpenTelemetry + Prometheus) | **DONE** | `tracing.py` — span OpenTelemetry **asli** + encoder OTLP/protobuf (`encode_export_request`) + propagasi W3C `traceparent`; `monitoring.py` — `Metrics.render_prometheus()`, `AlertManager`, notifier (webhook/Slack/Telegram/email); `tests/test_tracing.py`, `tests/test_monitoring.py` |
| 7 | **Security & governance** (izin granular, redaksi data, MFA wajib) | **DONE** | `agent_redactor.py` (`redact`, `CanaryDetectedError`), `database.redaction_policy_for` + `POST /workflows/{id}/redaction`, `two_factor.py` (TOTP + recovery code + Fernet), `security.py`, `rate_limit.py`, `flow_limits.py`, `tests/test_two_factor.py`, `tests/test_agent_redactor.py` |

**Kesimpulan matriks:** ketujuh kapabilitas inti **sudah ada dan teruji**. Karena
itu iterasi ini tidak "menambah fitur besar", melainkan menutup **celah presisi**
yang muncul dari perilaku n8n terbaru (lihat §2).

---

## 2. Delta n8n 2.42.0 (29 Sep 2026) vs Katalir

| Fitur n8n 2.42.0 | Katalir sebelum iterasi | Tindakan |
|---|---|---|
| **AI Agent Tool bisa memakai tool-nya sendiri** (agent bersarang / hierarkis, parent pra-v3) | Delegasi agen ada (`[DELEGATE:]`) + batas kedalaman sub-workflow 3 | **Sudah setara** — batas kedalaman sudah ditegakkan (`subworkflow.MAX_DEPTH`) |
| **Agent Builder**: layout agen, panduan sub-agen, visibilitas aktivitas | Builder kanvas ada (`nexus-frontend`), node `agent` + ConfigPanel | Sudah setara (UI) |
| **MCP Registry di AI Assistant** (feature flag dihapus → GA) | Registry MCP + rekomendasi + sync sudah ada (`/mcp/registry*`) | **Sudah setara** |
| **Assistant mencatat live test run sebagai *verification evidence*** | Ada `evaluation.save_run`, tapi belum ada konsep "bukti" ber-rantai | **TODO (backlog #2)** — lihat §4 |
| **Deskripsi workflow saat create**; `extendsCredential` saat create/update | `WorkflowCreateRequest` sudah punya `description`; `POST /workflows` menyimpannya | Sudah setara (description); `extendsCredential` = **TODO (backlog #3)** |
| **Validasi nama path-parameter OpenAPI** | Ada `mcp_build_workflow` + gerbang envelope spec 2026-07-28 | Sudah setara |
| **Trace context tak lengkap tidak lagi memblokir eksekusi** | `tracing.is_valid_traceparent` + `parse_traceparent` (tolak all-zero) | Sudah setara |
| **Redis: langganan pulih setelah reconnect; deteksi half-open** | `recovery.py` ada; Redis = infra (bukan kode app) | Di luar cakupan kode aplikasi |
| **Autentikasi: validasi payload token sebelum resolusi user** | `security.get_current_user` + `two_factor` | **TODO (backlog #4)** — audit payload token |
| **OpenTelemetry persistence** | `tracing.py` mengekspor OTLP/HTTP | Sebagian — persistence dititipkan ke backend OTLP penerima |
| **`n8n_update_partial_workflow({intent, operations})`** (pola edit sebagian) | **Belum ada** — edit hanya rename/deskripsi (PATCH) atau timpa `flow_data` | ✅ **DITUTUP iterasi ini** — `workflow_ops.py` + `POST /workflows/{id}/ops` |

---

## 3. Ditutup pada iterasi ini (2026-10-11)

### Edit workflow berbasis OPERASI (atomik) — referensi n8n-autopilot Phase 3.2

- **Modul:** `workflow_ops.py`
- **Endpoint:** `POST /workflows/{workflow_id}/ops`
- **Operasi didukung:** `addNode`, `updateNode`, `removeNode`,
  `addConnection`, `removeConnection`
- **Sifat:**
  - **Atomik** — satu operasi gagal ⇒ dokumen asli kembali utuh (`applied=0`),
    tidak pernah tersimpan dokumen setengah jadi.
  - **Anti-halusinasi** — `addConnection` ke node yang tidak ada **ditolak**
    (mencegah "node hantu" hasil model).
  - **Aman** — menolak kunci `__proto__`/`constructor`/`prototype` (prototype
    pollution), membatasi jumlah operasi (200) dan ukuran graf (500 node /
    1.000 edge, dari **`flow_limits.py`** sebagai sumber kebenaran tunggal).
  - **Pratinjau** — `dry_run=true` menghitung diff tanpa menulis.
  - **Diff** memakai ulang `environments.diff_flow` (konsistensi repo).
- **Mengapa deterministik (bukan LLM di dalam modul):** lapisan bahasa alami
  (`skills/flowgent`) hanya perlu **menghasilkan daftar operasi**; penerapan,
  validasi, dan rollback tidak boleh bergantung pada model.

**Hard test:** `tests/test_workflow_ops.py` (20) + `tests/test_workflow_ops_api.py`
(5) = **25 test, 100% lulus**. Rincian di `docs/n8n-alignment-log.md`.

---

## 4. Backlog iterasi 1 — STATUS setelah iterasi 2 (11 Okt 2026)

| # | Item | Status | Bukti |
|---|---|---|---|
| 1 | **Upgrade `mcp>=2`** | **PARTIAL (keputusan terdokumentasi)** | `mcp_compat.py` + `mcp_gateway/client.py` siap-2.x; **diverifikasi terhadap mcp 2.3.0 nyata** (deteksi major=2, `MCPServer` terbangun, kwarg FastMCP dibuang). Cutover penuh DIUJI-GAGAL di jalur server (`build_server()` → `ModuleNotFoundError: mcp.server.fastmcp`) + konflik pin (pydantic 2.14.0 / starlette 1.7.0 / httpx2). |
| 2 | **Verification Evidence ledger** (rantai bukti ber-hash) | **DONE** | `evidence_ledger.py` — sha256 chain + HMAC, `verify_chain`/`verify_entry`, deteksi tamper, store memori + DDL Postgres; `POST /evidence`, `GET /evidence/{id}/verify`. |
| 3 | **`extendsCredential`** saat create/update workflow | **DONE** | `vault_extends.py` — `extends://parent#field`, rantai pewarisan, deteksi siklus, batas kedalaman 5, isolasi tenant, audit; dijahit ke `vault_broker.resolve_secret`/`resolve_secrets_in_args`. |
| 4 | **Validasi payload token sebelum resolusi user** | **DONE** | `token_guard.py` — allow-list algoritma (tolak `none`), `exp`/`nbf`/`aud`/`iss`, pola `sub`, whitelist `role`, batas payload 10 KB, klaim terlarang; dipanggil di `security._guard_claims` setelah signature sah. |
| 5 | **Streaming `/chat` + watchdog idle** | **DONE** | `chat_stream.py` — frame SSE + heartbeat 10 s + abort idle 30 s + fallback + resume `Last-Event-ID`; `POST /chat/stream`. |

---

## 5. Delta n8n 2.42.0 → kesesuaian Katalir (iterasi 2)

Sumber: n8n **2.42.0** (29 Sep 2026) + **2.41.4** (30 Sep 2026); catatan rilis
`docs.n8n.io/changelog/release-notes`, `github.com/n8n-io/n8n/releases`.

| Fitur n8n 2.42.0 | Katalir | Catatan |
|---|---|---|
| AI Agent Tool boleh memakai tool-nya sendiri (agent bersarang) | DONE (setara) | `execution_engine` `[DELEGATE:]` + `subworkflow.py` (MAX_DEPTH 3) + `subworkflow_batch.py` (mode `all`/`each`) |
| MCP Registry jadi GA di AI Assistant | DONE (setara) | `mcp_registry.py`, `mcp_autoconfig.py` |
| **Assistant mencatat live test run sebagai *verification evidence*** | **DONE (baru)** | `evidence_ledger.py` + `/evidence` — rantai bukti tamper-evident |
| **`extendsCredential` diterima saat create/update workflow** | **DONE (baru)** | `vault_extends.py` |
| **Validasi payload token sebelum resolusi user** | **DONE (baru)** | `token_guard.py` |
| Deskripsi workflow saat create | DONE | `WorkflowCreateRequest.description`, `POST /workflows` |
| Validasi nama path-parameter OpenAPI | DONE (setara) | `openapi_connectors.py` |
| Redis: pemulihan langganan setelah reconnect + deteksi half-open | TODO | Katalir pakai Supabase, bukan Redis pub/sub |
| Persistensi OpenTelemetry | DONE | `tracing.py` (`encode_export_request`, exporter HTTP) |
| Batas hasil queue-job pada eksekusi milik proses | N/A | Tidak ada worker queue terpisah |

**Kesimpulan:** tiga fitur baru n8n 2.42.0 yang paling relevan (verification
evidence, `extendsCredential`, validasi payload token) **sudah ada di Katalir**
per iterasi 2 ini — semuanya dengan hard test ≥12 skenario.

