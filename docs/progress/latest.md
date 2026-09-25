## Phase 1.3 — AI Tools [DONE 2026-09-26]

- Groq `groq_chat` -> HTTP 200, model `qwen/qwen3.8-27b`, answered "KATALIR_OK" (571 ms)
- Gemini `gemini_generate` -> HTTP 200, model `gemini-2.5-flash`, answered "KATALIR_OK" (1.773 ms)
- 2 new **unique call-verified** integrations: 25 -> 27
- Both models are now discovered from the live catalogue at runtime. The hardcoded
  `llama-3.3-70b-versatile` no longer exists on Groq, and `gemini-2.0-flash` has
  been retired by Google - both failures were found by actually calling.
- Evidence: `ai_tools_evidence.json`; tests: `tests/test_ai_tools.py` (4 passed)

## Phase 1.2 — OpenAPI Generator [DONE 2026-09-26]
- 6 public specs, 889 tools generated, **884 registered** in one FastMCP process
- 1 call-verified: `petstore_getpetbyid(petid=1)` -> HTTP 200 `{id:1, name:'Dogs'}`
- Kubernetes 220 tools recorded as listed-but-not-callable (its swagger declares no server)

## Phase 1.1 — Dedup [DONE 2026-09-26]
- 28.664 -> **22.789 unique** (79,5%, 5.875 collapsed, 1.610 multi-source groups)
- unique_verified 25, tools_listed 1.576, discovered_only 21.213

## Blockers
- Nango Cloud: key present in `.env` but rejected by the API (401, both auth headers)
- Metorial: key valid, but the project has 0 providers connected (needs dashboard)

Next: Phase 1.4 — verify the 1.159 unverified candidates we already have.
