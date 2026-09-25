# Katalir Metrics

## Current Status
- Phase: 1 of 5
- **Unique call-verified integrations: 27**
- **Unique tools-listed integrations: 1.781**
- Unique catalog integrations: 22.789
- Community devs: 0
- Monthly revenue: $0

## The ladder (do not collapse these)
| Level | Meaning | Count |
|---|---|---|
| call_verified | a real `tools/call` executed and returned | **27** |
| tools_listed | MCP `initialize` + `tools/list` succeeded | **1.781** |
| discovered | present in a catalogue only | 21.008 |

## History
| Phase | Unique call-verified | Unique tools-listed | Commit |
|---|---|---|---|
| pre-blitz | 45 (pre-dedup, never validated) | unknown | - |
| 1.1 dedup | 25 | 1.576 | 8aaf5f6 |
| 1.2 openapi | 25 (+1 generated tool) | 1.576 | 439d291 |
| 1.3 ai tools | 27 | 1.576 | 5209be6 |
| 1.4 verify pool | **27** | **1.781** | (this) |

## P1.4 detail
420 Glama no-auth connectors probed read-only (initialize + tools/list only):
- **236 ok** -> 2.313 tools listed
- 175 auth_required (Glama's `auth:none` label is not reliable)
- 4 protocol_error, 5 unreachable, 0 ssrf_blocked

These 236 are `tools_listed`, **not** `call_verified`: calling a tool on someone
else's server needs their credential and their data, which is not ours to do.

## Target vs reality
- Blitz target: 2.000+ unique call-verified
- Reality: **27 call-verified / 1.781 tools-listed**
- The measurable ceiling for this approach is the tools-listed line; getting past
  it requires credentials per provider (user action) or our own execution.
