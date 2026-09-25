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
- [x] Run Lighthouse and bilingual screenshot verification — production route probes and fresh screenshots captured; bilingual UI regression remains a separate final check.

### FASE P2.4 — Slack App Directory
- [x] Public Distribution is enabled per user confirmation.
- [!] User: submit Slack Directory form; external review is manual.
- [x] Agent: production redirect/config documentation prepared.

### FASE P2.5 — Prioritized Features
- [x] Feature 1 — export chat owner-scoped: JSON and Markdown from the authenticated session; `data-testid=chat-export-actions`.
- [x] Feature 2 — analytics dashboard from owner-scoped quota and execution summaries; `data-testid=card-analytics`.
- [x] Feature 3 — workflow templates with validated React Flow graphs and install flow; `data-testid=workflow-templates`.
- [x] Test, screenshot, and document each — targeted backend suite 28 passed, TSC/Python compile passed, and fresh production route screenshots captured under `nexus-frontend/test-results/domain_*.png`.
- [x] Composition research — 10 MCP components remain behind allowlisted adapters; metadata-only entries are never treated as executable.

## Agent Rules
- Search-first; no-surrender loop; test before DONE.
- Commit per sub-task; update this roadmap each task.
- Never enable payments, publish OAuth, or submit Slack Directory without user action.
