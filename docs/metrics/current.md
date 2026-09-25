# Katalir Metrics

## Current Status
- Fase: 1 of 9
- **Unique call-verified integrations: 27**
- **Unique tools-listed integrations: 1.895**
- Unique catalog integrations: 22.789
- Community devs: 0
- Monthly revenue: $0

## The ladder (never collapse these)
| Level | Meaning | Count |
|---|---|---|
| call_verified | a real `tools/call` executed and returned | **27** |
| tools_listed | MCP `initialize` + `tools/list` succeeded | **1.895** |
| discovered | present in a catalogue only | 20.894 |

## History
| Fase | call-verified | tools-listed | Commit |
|---|---|---|---|
| pre-blitz | 45 (pre-dedup, never validated) | unknown | - |
| 1.1 dedup | 25 | 1.576 | 8aaf5f6 |
| 1.2 openapi | 25 (+1 generated tool) | 1.576 | 439d291 |
| 1.3 ai tools | 27 | 1.576 | 5209be6 |
| 1.4 batch 1 (420 probed) | 27 | 1.781 | dab3b5e |
| 1.4 batch 2 (199 probed) | **27** | **1.895** | (this) |

## F1.4 detail - the whole no-auth Glama pool is now exhausted
All **619** no-auth connectors probed, read-only (initialize + tools/list only):
- **351 ok** -> **4.714 tools listed**
- 251 auth_required (Glama's `auth:none` label is not reliable)
- 8 protocol_error, 9 unreachable, 0 ssrf_blocked

## Why call-verified did not move
351 connectors are `tools_listed`, not `call_verified`: calling a tool on someone
else's server needs their credential and their data. That is not ours to do, and
reporting them as "verified" would be the exact inflation this project keeps
removing from itself.

## Target vs reality
- Blitz target: 2.000+ unique call-verified
- Reality: **27 call-verified / 1.895 tools-listed**
- The remaining ceiling is structural: to go past this we need either per-provider
  credentials (user action) or our own execution surface.
