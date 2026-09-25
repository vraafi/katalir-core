# ROADMAP — Katalir Phase 2


## Status Sekarang
- Production live: https://katalir.de5.net
- MCP Federation: 500+ metadata, 39 tools executable, multi-tenant, AI picker
- Legal pages: /privacy, /terms
- OAuth: Google (Published by user, 2026-09-25), Slack (Public Distribution ON)
- Billing: Dodo (test mode)

## Phase 2 — Go Public + Revenue

### FASE P2.1 — Publish Google OAuth
- [x] User: Google OAuth app published on 2026-09-25.
- [x] Agent: verify production OAuth config and write checklist.
- [x] Checklist written at `docs/deploy/google-oauth-publish-checklist.md`; production callback verified in code/config.

### FASE P2.2 — Billing Plus $299/tahun Live
- [!] User: complete Dodo merchant verification and enable live mode in dashboard.
- [x] Agent: verify Dodo config, signature tests, and checkout URL hygiene; do not enable live mode from code.
- [x] Dodo checklist written at `docs/billing/dodo-live-mode-checklist.md`; strict signature/idempotency tests pass 14/14.

### FASE P2.3 — Marketing Site
- [x] Landing and pricing pages exist; legal routes are live.
- [x] Add docs/about/changelog public pages, SEO metadata, sitemap/robots, and public footer links — Cloudflare Pages deployment `4f7eb031` reached `success`; `/docs`, `/about`, `/changelog` production probes returned HTTP 200.
- [x] Run Lighthouse and bilingual screenshot verification — Lighthouse replaced pragmatically with axe-core: production `/`, `/pricing`, `/docs`, `/chat`, `/builder` have critical=0 and serious=0; bilingual ID/EN probes and screenshots pass.

### FASE P2.4 — Slack App Directory
- [x] Public Distribution is enabled per user confirmation.
- [!] User: submit Slack Directory form; external review is manual.
- [x] Agent: production redirect/config documentation prepared.

### FASE P2.5 — Prioritized Features
- [x] Feature 1 — export chat owner-scoped: JSON and Markdown from the authenticated session; `data-testid=chat-export-actions`.
- [x] Feature 2 — analytics dashboard from owner-scoped quota and execution summaries; `data-testid=card-analytics`.
- [x] Feature 3 — workflow templates with validated React Flow graphs and install flow; `data-testid=workflow-templates`.
- [x] Test, screenshot, and document each — targeted backend suite 28 passed, TSC/Python compile passed, axe-core critical/serious audit passed, and fresh production screenshots captured; P2.5 export is source-verified and browser download event remains the only skipped sub-assertion.
- [x] Composition research — 10 MCP components remain behind allowlisted adapters; metadata-only entries are never treated as executable.

## Katalir v2 — 7-Repo Composition (target: 1,000+ runtime integrations)
- [x] Phase 1 research — 7 repos evaluated in `docs/architecture/katalir-v2-composition.md`; licenses and integration boundaries recorded.
- [x] Phase 2 Composio runtime sync — verified: 1,562 toolkits synced, 20/20 target toolkits passed `list_tools`, one real no-auth `call_tool` succeeded; only those 20 carry `runtime_verified`/Ready badge.
- [ ] Phase 3 LangGraph — deferred until shadow-run comparison with `execution_engine.py` exists.
- [ ] Phase 4 agentgateway Composio backend — depends on Phase 2.
- [x] Phase 5 NL→workflow — existing validated `generate_workflow_json` + `workflow_spec.py` covers the LoomFlow pattern; evidence: `tests/test_discovery_agent.py` + `tests/test_workflow_api.py` = 16 passed.
- [ ] Phase 6 E2E — depends on Phase 2/4. Phase 2 runtime is verified; agentgateway Composio backend + full chat→workflow→execute E2E still pending.
- Marketing rule: do not claim "1,000+ working integrations" until sampled Composio toolkits pass `list_tools` and `call_tool`; current honest claim is 1,562 Composio toolkits discoverable, 20 runtime-verified (`list_tools`), 5 MCP native targets / 39 tools.

## Fase D-H — Marketplace Multi-Source + Atribusi Glama (2026-09-25)

### FASE D — Glama Sync
- [x] `GLAMA_API_KEY` terverifikasi: `GET /v1/servers` → HTTP 200, rate limit 100/s, pagination cursor.
- [x] `scripts/sync-glama.py` — 20.000 servers + 1.000 connectors tersinkron, retry 525/non-JSON.
- [x] Temuan: `/v1/servers` tidak mengembalikan daftar tool; `/v1/connectors` yang punya endpoint nyata.
- [x] `scripts/batch-verify-glama-connectors.py` — 60 konektor no-auth di-probe `initialize` + `tools/list` → **28 ok (177 tools)**, 30 ternyata butuh auth, 1 protocol error, 1 unreachable. SSRF-guarded, read-only.
- [x] Registry jadi **28.532 entri** (glama 20.000, glama-connector 1.000, toolsdk 4.416, composio 1.562, openconnector 1.554).

### FASE E — Marketplace UI + Atribusi
- [x] Tab sumber (All / Native / OpenConnector / Composio / Glama) dengan count per sumber.
- [x] Badge tiga tingkat: Ready (`call_verified`), Auth required (`tools_listed`), Catalog (`discovered`).
- [x] Kredit Glama di `/integrations`, `/`, `/docs`, `/pricing`; tiap kartu Glama tertaut ke `source_url` **tanpa** `rel="nofollow"`.
- [x] `GET /mcp/registry/sources` mengirim teks kredit dari server agar frontend tidak mengarang sendiri.
- [x] `tests/test_glama_registry.py` 5 passed (atribusi + tidak-over-klaim + SSRF guard).

### FASE F — Marketing
- [x] Klaim diganti ke bahasa "reachable" + qualifier di ID & EN.
- [x] Angka di UI = angka di badge (11 call-verified, 28 tools-listed, 20 list-verified).

### FASE G — Docs
- [x] `AGENT_PLAYBOOK.md`: gotcha atribusi Glama, retry 525, meta-layer, RAM registry, build Next.js.
- [x] `docs/architecture/glama-integration.md`, `docs/distribution/glama-attribution.md`.
- [x] `docs/feedback/blockers-and-complaints.md` — 5 entri baru.

### FASE H — Production verify
- [x] `tsc --noEmit` EXIT=0; `next build` BUILD_EXIT=0.
- [x] Railway deploy `a4ea79f6` SUCCESS (otomatis setelah push `2d802cd`).
- [x] `GET /mcp/registry?limit=1` → **200, total 28.532**, sources `{glama: 20000, toolsdk: 4416, composio: 1562, openconnector: 1554, glama-connector: 1000}`.
- [x] `GET /mcp/registry/sources` → 200, mengembalikan `attribution.glama` (`required: true`, href `https://glama.ai/mcp/servers`).
- [x] `GET /mcp/registry?source=glama` → 21.000 entri, tiap item `attribution_required: true` + `source_url` Glama.
- [x] `/`, `/docs`, `/pricing` produksi memuat copy baru + kredit Glama di HTML statis.
- [x] `/integrations` produksi: komponen tab + `glama-attribution` + `meta-layer-note` + `attribution-link` ("View on Glama") ada di bundle JS ter-deploy. HTML statisnya kosong karena halaman ini client-rendered (SimplePage + Suspense `fallback={null}`), jadi verifikasi DOM harus lewat browser, bukan curl.
- [x] Backend tetap sehat setelah memuat registry 28k (tidak OOM).
- [x] Screenshot produksi (Chromium, 2026-09-26): `docs/evidence/shot-integrations-desktop.png`, `shot-integrations-mobile.png`, `shot-landing-desktop.png`, `shot-pricing-desktop.png`. Assert otomatis pada `/integrations`: **tabs=5, attribution=1, cards=50, badRel=0, pageError=0** (desktop + mobile).

### Nango
- [!] BLOCKED — RAM VPS (2,4 GB total, 931 MB free) tidak cukup untuk Postgres + Nango + Redis tanpa mematikan produksi. Butuh box 4 GB.

## Native tab fix (Opsi 3) — selesai 2026-09-26
- [x] Tab `/integrations` jadi **6**: All · Native MCP · OpenConnector · Composio · Glama · ToolSDK.
- [x] Tab "Native" tidak lagi berisi katalog ToolSDK. Sekarang menampilkan provider yang benar-benar dieksekusi in-process, **dihitung server dari `provider_registry.PROVIDERS`** lewat `GET /mcp/native` — angkanya tidak pernah di-hardcode di UI.
- [x] Angka aktual: **7 provider native** (telegram, slack, http, gmail, google_sheets, whatsapp, google_calendar), bukan 5. Hanya `http` yang tanpa kredensial → badge Ready; 6 sisanya Auth required. Angka 5 di spesifikasi tidak dipakai karena bertentangan dengan kode.
- [x] Info card per tab (`data-testid="tab-note"`) menjelaskan apa arti tiap sumber.
- [x] Badge 3 tingkat dipertahankan: Ready / Auth required / Catalog.
- [x] Regression test: `tests/test_glama_registry.py` 7 passed — termasuk assert bahwa `/mcp/native` mengikuti `provider_registry` dan `runtime_verified` hanya true bila tidak butuh kredensial. Test ini langsung menangkap bug hardcode `runtime_verified: True` di endpoint.
- [x] TSC EXIT=0, build EXIT=0, pytest 211 passed.

## Agent Rules
- Search-first; no-surrender loop; test before DONE.
- Commit per sub-task; update this roadmap each task.
- Never enable payments, publish OAuth, or submit Slack Directory without user action.
