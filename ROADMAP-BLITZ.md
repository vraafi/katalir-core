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
| **Unique runtime-verified** | **27** call-verified / **1.781** tools-listed | `dedup_report.json`, `glama-connector-verify.json` |
| tools_listed (unique) | 1.781 | `dedup_report.json` |
| discovered only | 21.008 | `dedup_report.json` |
| Generated OpenAPI tools | 884 registered (889 generated) | `openapi_tools_manifest.json` |

**The honest gap:** the target in the blitz brief is 2.000 unique *verified*.
Reality is **27**. The gap is not a sourcing problem - 22.789 unique integrations
are already in the catalogue - it is a *verification* problem.

## PHASE 1 — Dedup + Foundation

- [x] **P1.1 Dedup engine** — `mcp_dedup.py`, 28.664 → 22.789 unique (79,5 %).
      Provenance preserved per entry; anti-inflation tests in `tests/test_dedup.py`.
- [x] **P1.2 OpenAPI → MCP generator** — `scripts/openapi_to_mcp.py`, 6 public specs,
      **884 tools registered** in one FastMCP process, 1 call-verified
      (`petstore_getpetbyid` → HTTP 200, `{id:1, name:'Dogs'}`).
- [x] **P1.3 AI tools** — Groq + Gemini wired and **call-verified**:
      `qwen/qwen3.8-27b` → "KATALIR_OK" (571 ms), `gemini-2.5-flash` → "KATALIR_OK" (1.773 ms).
      Models are discovered at runtime because the hardcoded ones had rotted.
- [x] **P1.4 Verify the existing pool** — 420 Glama no-auth connectors probed read-only
      (`initialize` + `tools/list`): **236 tools_listed / 2.313 tools**, 175 auth_required,
      4 protocol_error, 5 unreachable, 0 ssrf_blocked. Unique tools-listed
      1.576 → **1.781**. Unique call-verified stays **27** — correctly, because
      listing a tool is not calling it.

## PHASE 3 (started early, independent of P2)

- [x] **P3.1 Community platform code** — `docs/architecture/community-platform.sql`
      + `POST /community/submit`, `GET /community/browse|review|my-earnings`, 5 tests.
      Endpoints return 503 when the tables are absent so "not deployed" can never
      read as "nothing exists". **DDL not applied to production** — creating tables
      in the live project is a bigger step than adding columns.
- [ ] P3.2 Community UI · [ ] P3.3 multi-protocol Executor · [ ] P3.4 batch test 100

## PHASE 2 — Unique Sources (SEA + Dev + Creator)

- [ ] P2.1 SEA local · [ ] P2.2 Modern dev · [ ] P2.3 Creator economy · [ ] P2.4 batch test 100
      **Blocked on evidence:** Midtrans returns 503, HuggingFace 401, and most SEA vendors
      publish no OpenAPI spec. Without a spec or a key, these can only be catalogue entries.

## PHASE 3 — Community + Multi-Protocol

- [ ] P3.1 schema · [ ] P3.2 UI · [ ] P3.3 multi-protocol Executor · [ ] P3.4 batch test 100

## PHASE 4 — Polish + Launch-Ready

- [ ] P4.1 Marketplace UI v2 · [ ] P4.2 Product Hunt · [ ] P4.3 final verify

## PHASE 5 — Scale to Parity

- [ ] P5.1 regional · [ ] P5.2 verticals · [ ] P5.3 n8n parity audit ·
      [ ] P5.4 community growth · [ ] P5.5 final marketing

## Blocked on the user

1. **Nango Cloud key** — a key exists in `.env` but the API rejects it
   (`GET /api/v1/providers` → 401 with both `Bearer` and `Secret-Key`).
   Action: create a secret key at https://app.nango.dev/settings and set `NANGO_API_KEY`.
2. **Metorial providers** — the key is valid, but the project has **0 providers
   connected**. Action: connect providers in the Metorial dashboard, then re-sync.

## Agent Rules

- Search-first; no-surrender loop; test before DONE.
- Commit per sub-task; update this roadmap each task.
