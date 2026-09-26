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
| **Unique call-verified** | **227** + Groq + Gemini = **229** | `dedup_report.json` → `unique_verified` |
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

**The honest gap:** the blitz target is 2.000 unique *verified*. Reality is **229
call-verified** (227 from the catalogue + Groq + Gemini), up from 28. The gap is
still a *verification* problem, not a sourcing problem: 22.904 unique integrations
are in the catalogue, and only the ones with a working no-auth endpoint can be
call-verified without a user's credential.

## FASE 1 — Batch Verify  ← current
- [x] F1.5 metrics — `dedup_report.json` regenerated after the call phase
- [x] F1.6 commit — batch + call artefacts tracked
- [x] **F1.7 tools/call phase** — 351 no-auth Glama connectors attempted, one
      read-only `tools/call` each → **203 call_verified** (107 failed, 14 rejected
      our synthetic args, 26 had no read-only tool, 1 would not re-initialize).
      `unique_verified` **26 → 227**; with Groq + Gemini that is **229 verified**.
      Reconciled exactly: 203 connectors − 1 (`AI Tools Directory` is a directory,
      not an integration) − 1 (two connectors share the name `rnv-color-mcp`)
      = 201 new canonical rows, and 26 + 201 = 227.
      Evidence: `glama-connector-call-batch1.json`, `scripts/audit_call_safety.py`.
      Safety: only no-auth endpoints, SSRF-guarded, sequential, and a tool is
      callable only if its name matches a read-verb allowlist and no mutating
      verb. The audit re-derives that independently from the recorded tool names:
      **0 mutating, 0 outside the allowlist, 188 distinct tools.**
      An argument-rejection response is recorded as `call_validation_error` and
      is **not** counted as verified — "the endpoint answered" is not "the
      integration works".
- [x] F1.1 Nango key → **WORKS**. `GET https://api.nango.dev/providers` → **200**,
      **1.024** provider. The earlier "401" was our own bug: we called
      `/api/v1/providers`, which is not a Nango route. Auth is
      `Authorization: Bearer <Environment API key>`; the endpoint has no `/api/v1`
      prefix. Evidence: `nango_providers_evidence.json`.
- [x] F1.2 Nango provider templates → 1 integration configured
      (`github-getting-started`, provider `github`, created 2026-09-25) via
      `GET /integrations`. Note `/provider-templates` returns **HTML**, not JSON —
      it is the Connect UI docs page, not an API. Use `/integrations` instead.
- [!] F1.3 Metorial tools → **BLOCKED-USER** (key valid, project has 0 providers connected)
- [x] F1.4 Batch verify candidates — **complete, no-auth Glama pool exhausted**:
      619 attempted → **351 ok** / **4.714 tools** (batch 1: 420 → 236 / 2.313,
      batch 2: 199 → 115 / 2.401). The two batches overlap by **0** connectors, so
      236 + 115 = 351 is a real union, not a double count.
      Evidence: `glama-connector-verify-batch{1,2}.json` at `6dcbfd0`. That phase
      was **tools-list only**; `tools/call` came later as F1.7 below.

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
- [x] F2.3 marketplace 8+ source tabs — **8 tabs, one per real `source`**, verified
      against a live backend: 28.533 / 7 / 20.000 / 1.000 / 1.554 / 1.558 / 4.415 / 6.
      `glama` and `glama-connector` were merged under one "Glama" label, which hid
      the only source we can verify at runtime and made the count match neither tab;
      `openapi-generated` had no tab at all. `tests/marketplace-tabs.spec.ts` asserts
      each count is non-zero, because a missing key renders "(0)" and looks
      identical to a genuinely empty source. · [ ] F2.4 commit

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
1. ~~**Nango Cloud key**~~ → **NOT BLOCKED, false alarm.** The key works; the
   401 we recorded came from calling `/api/v1/providers`, a route that does not
   exist. The real call is `GET https://api.nango.dev/providers` with
   `Authorization: Bearer <key>` → 200, 1.024 providers. Corrected 2026-09-26.
2. **Metorial providers** — the key is valid, but the project has **0 providers
   connected**. Action: connect providers in the Metorial dashboard, then re-sync.

## Agent Rules

- Search-first; no-surrender loop; test before DONE.
- Commit per sub-task; update this roadmap each task.
