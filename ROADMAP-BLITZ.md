# ROADMAP-BLITZ — Katalir vs n8n

**Rule of this file:** a number is only allowed on it if it was produced by a run
whose output is in the repo. Phase-based, no deadline, auto-continue.

## Reality check (measured 2026-09-26, not projected)

| Metric | Value | Where it comes from |
| --- | --- | --- |
| Raw catalogue entries | 28.664 | sum of the 5 source files |
| **Unique integrations (deduped)** | **22.789** | `mcp_dedup.py` → `dedup_report.json` |
| Unique % | 79,5 % (5.875 collapsed) | same |
| Groups present in >1 source | 1.610 | same |
| **Unique call-verified** | **27** | 25 (dedup) + Groq + Gemini |
| **Unique tools-listed** | **1.781** | `dedup_report.json` |
| discovered only | 21.008 | `dedup_report.json` |
| Generated OpenAPI tools | 884 registered (889 generated) | `openapi_tools_manifest.json` |

**The honest gap:** the blitz target is 2.000 unique *verified*. Reality is **27**
call-verified / 1.781 tools-listed. The gap is a *verification* problem, not a
sourcing problem: 22.789 unique integrations are already in the catalogue.

## FASE 1 — Batch Verify  ← current
- [x] F1.1 Nango key → **BLOCKED-USER** (key present, API returns 401 both header forms)
- [!] F1.2 Nango provider templates → blocked by F1.1
- [!] F1.3 Metorial tools → **BLOCKED-USER** (key valid, project has 0 providers connected)
- [x] F1.4 Batch verify candidates — batch 1: 420 probed → **236 ok** / 2.313 tools;
      batch 2: 199 remaining in progress
- [ ] F1.5 metrics · [ ] F1.6 commit

## FASE 2 — Sync All Sources
- [ ] F2.1 sync the 884 OpenAPI tools (dedup first) · [ ] F2.2 source tags
- [ ] F2.3 marketplace 8+ source tabs · [ ] F2.4 commit

## FASE 3 — Multi-Protocol Executor (MCP + OpenAPI + GraphQL + JS)
- [ ] F3.1 OpenAPI import · [ ] F3.2 GraphQL import · [ ] F3.3 JS sandbox
- [ ] F3.4 MCP remote import · [ ] F3.5 test each · [ ] F3.6 commit

## FASE 4 — Marketplace UI v2
- [ ] F4.1 dedup toggle · [ ] F4.2 source badges · [ ] F4.3 runtime status tiers
- [ ] F4.4 advanced search/filter · [ ] F4.5 screenshot · [ ] F4.6 commit

## FASE 5 — Marketing + Launch Prep
- [ ] F5.1 landing claim · [ ] F5.2 pricing/docs · [ ] F5.3 Product Hunt kit
- [ ] F5.4 playbook final · [ ] F5.5 commit · [ ] F5.6 report "ready for launch"

## FASE 6 — Product Hunt Launch ⭐ USER ACTION
- [ ] F6.1–F6.4 submit, announce, respond · [ ] F6.5 metrics snapshot

## FASE 7 — Community Outreach
- [ ] F7.1 outreach · [ ] F7.2 tutorial · [ ] F7.3 bounty · [ ] F7.4 dashboard · [ ] F7.5 first 10 reviewed

## FASE 8 — Regional + Vertical Expansion
- [ ] F8.1 SEA (VN/TH/PH/MY) · [ ] F8.2 healthcare · [ ] F8.3 logistics
- [ ] F8.4 education · [ ] F8.5 sync + test + commit

## FASE 9 — Parity Push
- [ ] F9.1 audit n8n nodes → gap map · [ ] F9.2 generate missing via OpenAPI
- [ ] F9.3 community bounty · [ ] F9.4 batch verify + commit
- [ ] F9.5 update claim · [ ] F9.6 THE END

## Already done (earlier phases, kept for continuity)
- [x] Dedup engine · [x] OpenAPI generator · [x] AI tools (Groq + Gemini call-verified)
- [x] P3.1 Community platform **deployed**: 2 tables, RLS on, 2 triggers, live-tested

## Blocked on the user
1. **Nango Cloud key** — a key exists in `.env` but the API rejects it
   (`GET /api/v1/providers` → 401 with both `Bearer` and `Secret-Key`).
   Action: create a secret key at https://app.nango.dev/settings and set `NANGO_API_KEY`.
2. **Metorial providers** — the key is valid, but the project has **0 providers
   connected**. Action: connect providers in the Metorial dashboard, then re-sync.

## Agent Rules

- Search-first; no-surrender loop; test before DONE.
- Commit per sub-task; update this roadmap each task.
