# Progress Katalir — Latest

## Status
- Current Fase: 3/9 selesai, berikutnya F4
- Last completed: **F3 Multi-Protocol Executor** — 2026-09-26
- Metrics: call_verified=229, tools_listed=1.896, catalog_unique=23.474, revenue=$0
- Next: F4 (Marketplace UI v2 polish)

## Fase 3 — Multi-Protocol Executor [DONE 2026-09-26]
Empat protokol, satu kontrak, satu choke point untuk SSRF.
- F3.1 OpenAPI `katalir_protocols/openapi.py` — operation tanpa `parameters[]` untuk `{id}` ditolak
- F3.2 GraphQL `katalir_protocols/graphql.py` — live introspection → **35 tools**
- F3.3 JS sandbox `katalir_protocols/jsandbox.py` — **sandbox tidak punya network sendiri**
- F3.4 MCP remote `katalir_protocols/mcp_remote.py` — live, **7/12 server, 36 tools**
- F3.5 `tests/test_katalir_protocols.py` **50 passing** + `scripts/f3_evidence.py`

Bukti terukur (`f3_protocol_evidence.json`): `TOOLS_LISTED=960`, `CALL_VERIFIED=1`,
`FALSE_CALL_VERIFIED=0`, `SSRF_ESCAPES_BLOCKED=5/5`.

**Kenapa hanya 1 call_verified.** OpenAPI/GraphQL/MCP-remote semuanya menghasilkan
*deskripsi*, bukan eksekusi — jadi `tools_listed` dan tetap di sana. Hanya sandbox JS
yang benar-benar menjalankan, jadi itu satu-satunya jalur yang boleh `call_verified`.
Angka `false_call_verified=0` diassert supaya tidak ada klaim "verified" yang tak
pernah dieksekusi.

## Keputusan desain F3.3 (penting)
Sandbox JS tidak diberi `fetch` milik Node. `fetch`-nya emit request lewat stdio,
lalu **Python** yang applying guard. Kalau sandbox punya network sendiri, guard
SSRF ada di dua bahasa — dan dua guard adalah dua hal yang bisa lupa di-update.
Redirect di F3.4 juga di-resolve manual + guard diulang tiap hop, karena
`follow_redirects=True` membiarkan URL publik yang lolos lalu menjawab 302 ke
169.254.169.254 tanpa dicek.

## Catatan jujur
- F3.3 adalah **process sandbox, bukan security boundary** terhadap penyerang
  gigih. Ini tertulis di docstring module. Multi-tenant yang benar-benar hostil
  butuh container/seccomp.
- F3.4 **tidak pernah memanggil tool** saat import. Import tidak boleh bisa
  mengubah data pihak ketiga sebagai efek samping.