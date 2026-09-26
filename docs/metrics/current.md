# Katalir Metrics

## Current Status
- Fase: 1 of 9
- **Unique call-verified integrations: 227** (+ Groq + Gemini = **229** total)
- **Unique tools-listed integrations: 1.896**
- Unique catalog integrations: 23.474
- Community devs: 0
- Monthly revenue: $0

## The ladder (never collapse these)
| Level | Meaning | Count |
|---|---|---|
| call_verified | a real `tools/call` executed and returned | **227** |
| tools_listed | MCP `initialize` + `tools/list` succeeded | **1.896** |
| discovered | present in a catalogue only | 21.578 |

## History
| Fase | call-verified | tools-listed | Commit |
|---|---|---|---|
| pre-blitz | 45 (pre-dedup, never validated) | unknown | - |
| 1.1 dedup | 25 | 1.576 | 8aaf5f6 |
| 1.2 openapi | 25 (+1 generated tool) | 1.576 | 439d291 |
| 1.3 ai tools | 27 | 1.576 | 5209be6 |
| 1.4 batch 1 (420 probed) | 27 | 1.781 | dab3b5e |
| 1.4 batch 2 (199 probed) | 27 | 1.896 | 6dcbfd0 |
| 1.7 **tools/call (351 attempted)** | **227** | 1.896 | 59f3ec4 |
| 1.7 + Nango/Metorial synced | 227 | 1.896 | (this) |

## F1.7 detail - 203 connectors call-verified
All **351** no-auth Glama connectors were called with **one read-only tool each**:
- **203 call_verified**
- 107 call_failed
- 14 call_validation_error (server rejected our synthetic arguments — **not** counted)
- 26 no_readonly_tool (every listed tool was unsafe to call)
- 1 reinit_failed

`unique_verified` went **26 -> 227**. The 203 connectors are **201** distinct
integrations: one is a directory rather than an integration (`AI Tools Directory`),
and two share the name `rnv-color-mcp` and collapse in dedup. 26 + 201 = 227.

## What `call_verified` does and does not mean here
It means one read-only tool on a no-auth endpoint returned a real result. It is
**not** a full integration test: single call, synthetic arguments, third-party
servers, no auth, no persistence, no error handling, no retry. Call it
"one read-only call succeeded" in marketing copy, not "fully working".

Safety constraints, because this touches someone else's server:
- no_auth endpoints only, SSRF-guarded, sequential with a delay;
- a tool is callable only if its name matches a read-verb allowlist AND no
  mutating verb, so `get_and_delete` is refused;
- arguments are synthesised from the tool's own JSON schema, with RFC 2606
  `.invalid` for anything email-shaped.
- `scripts/audit_call_safety.py` re-derives this from the recorded tool names
  rather than trusting the sweep: **0 mutating, 0 outside the allowlist**.

## Why call-verified was previously stuck at 27
The old note said calling a tool on someone else's server needs their credential,
so it was not ours to do. That was **half right**: it is true for the 251
connectors that require auth, and false for the `auth:none` ones, which answer
with no credential at all. Those 351 were reachable all along. The blocker was
never the servers — it was that nobody ran the call.

## Nango and Metorial are NOT tools catalogues
| Source | Count | What it actually is |
|---|---|---|
| Nango | 1.024 | OAuth / connection providers, **0 tools**. `GET /providers`, no `/api/v1`. |
| Metorial | 1 | Managed MCP platform; this account has GitHub active on a Production instance. |

Nango added **570** genuinely new integrations. Its other **434** providers are
duplicates of Composio/Glama/OpenConnector entries and were collapsed, not counted
twice — that collapse is the dedup working, not a loss. Metorial added **0** new
integrations: GitHub already existed in the catalogue, and it now carries a 7th
source tag.

Metorial sits behind Cloudflare error 1010, which answers **403** to any
non-browser signature. That is a WAF fingerprint block, not an auth failure, and
it produced one false "not connected" blocker before the body was read.

## Target vs reality
- Blitz target: 2.000+ unique call-verified
- Reality: **229 call-verified / 1.896 tools-listed**
- The remaining ceiling is structural: the 251 auth_required connectors need a
  user credential (user action), and a single read-only call is a low bar. The
  next honest step is depth on what we already have — error handling, retries,
  argument filling from real schemas — not more counting.