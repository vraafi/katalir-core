# ROADMAP-BLITZ — Katalir vs n8n

**Rule of this file:** a number is only allowed on it if it was produced by a run
whose output is in the repo. Phase-based, no deadline, auto-continue.

That rule is enforced, not just stated: `node verify_roadmap_claims.mjs`
re-derives every number below from the artefacts it cites and exits non-zero if
any claim stops reproducing. **If you edit a number here, run that script.**

## Reality check (measured 2026-09-26, not projected)

| Metric | Value | Where it comes from |
| --- | --- | --- |
| Raw catalogue entries | 28.670 | sum of the 5 source files |
| **Unique integrations (deduped)** | **22.904** | `mcp_dedup.py` → `dedup_report.json` |
| Unique % | 79.89 % (5.766 collapsed) | same |
| Groups present in >1 source | 1.602 | same |
| **Unique call-verified** | **26** + Groq + Gemini | `dedup_report.json` → `unique_verified` |
| **Integrations that list tools** | **1.896** | `dedup_report.json` → `tools_listed` |
| discovered only | 21.008 | `dedup_report.json` |
| Generated OpenAPI tools | 884 registered (889 generated) | `openapi_tools_manifest.json` |
| Glama no-auth pool | 351 connectors → **4.714 tools** | `glama-connector-verify-batch{1,2}.json` |

**Two different units — do not add or compare these.** 1.896 counts
*integrations* that answer `tools/list` (1.896 + 21.008 = 22.904, the deduped
total). 4.714 counts *tools* returned by those calls. They are not the same kind
of number, so "1.781 vs 4.714" was never a meaningful comparison.

Measured containment: all **351 of 351** pool connectors are already keys in
`glama_connectors.json`. The pool sweep therefore adds **no new sourcing** — it
converts 351 already-catalogued entries from "listed" to "listed, with a counted
tool inventory". **Neither figure is call-verified**; the sweep never issued a
single `tools/call`.

**The honest gap:** the blitz target is 2.000 unique *verified*. Reality is **28
call-verified**, with 1.896 integrations proven to list tools and 4.714 tools
enumerated across 351 of them. The gap is a *verification* problem, not a
sourcing problem: 22.904 unique integrations are already in the catalogue, and a
`tools/call` against the 351 is the next cheap step.

## FASE 1 — Batch Verify  ← current
- [!] F1.1 Nango key → **BLOCKED-USER** (key present, API returns 401 both header forms)
- [!] F1.2 Nango provider templates → blocked by F1.1
- [!] F1.3 Metorial tools → **BLOCKED-USER** (key valid, project has 0 providers connected)
- [x] F1.4 Batch verify candidates — **complete, no-auth Glama pool exhausted**:
      619 attempted → **351 ok** / **4.714 tools** (batch 1: 420 → 236 / 2.313,
      batch 2: 199 → 115 / 2.401). The two batches overlap by **0** connectors, so
      236 + 115 = 351 is a real union, not a double count.
      Evidence: `glama-connector-verify-batch{1,2}.json`. Still **tools-list only**
      — no `tools/call` was issued, so none of this counts toward "verified".
- [x] F1.6 commit — both batch JSONs are tracked at `6dcbfd0`
- [ ] F1.5 metrics

## FASE 1b — UI polish (shipped alongside F1.4)
- [x] F1b.1 Chat empty state → DeepSeek minimalism: decorative Sparkles/Bot icons
      removed, text-only greeting, rounded suggestion pills.
- [x] F1b.2 Magnetic, non-clickable MCP logo cloud, 55 brands. Hover moves the
      nearest tile (150px range, 0.3 strength) + tilt + spotlight. Live on
      `katalir.de5.net` — 55/55 render as inline SVG, 0 remote images,
      `pointer-events: none`, 0 focusable children.
- Evidence: `docs/evidence/{landing-logos,chat-empty}-{desktop,mobile}.png`,
  commits `7959dae`, `507cc7c`, `810bf9b`, `f0cf704`.

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
- [x] MCP gateway: sends auth headers and **fails closed** when no credential
      (`mcp_gateway/client.py` + `tests/test_mcp_gateway/test_client.py`, `2b2f8f5`)
- [x] MCP auto-config preview + runtime allowlist gate (`mcp_autoconfig.py`, `fc94d21`)
- [x] Katalir MCP server proven by a **real external SDK client**, not an in-repo
      stub (`tests/test_katalir_mcp_external.py`, `9e2e0bb`)

These three landed on the MCP track and are tracked in `TODO.md`; they are listed
here only so the blitz totals are not mistaken for the whole of what exists.

## Blocked on the user
1. **Nango Cloud key** — a key exists in `.env` but the API rejects it
   (`GET /api/v1/providers` → 401 with both `Bearer` and `Secret-Key`).
   Action: create a secret key at https://app.nango.dev/settings and set `NANGO_API_KEY`.
2. **Metorial providers** — the key is valid, but the project has **0 providers
   connected**. Action: connect providers in the Metorial dashboard, then re-sync.

## Agent Rules

- Search-first; no-surrender loop; test before DONE.
- Commit per sub-task; update this roadmap each task.
