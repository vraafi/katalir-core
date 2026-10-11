# Connector Verification — 8-Layer REAL vs FAKE

- dibuat: 2026-10-11 00:08 UTC (Oktober 2026)
- konektor terverifikasi: **1000**
- deep (tool eksternal nyata dijalankan): **648**
- sumber: `glama_connectors.json` (MCP server dengan `endpoint_url`)

## Klasifikasi

| klasifikasi | jumlah | arti |
|---|---:|---|
| NON_CONFORMANT | 513 | handshake OK tapi gagal ≥1 syarat spec 2026-07-28 |
| AUTH_REQUIRED | 289 | bicara MCP, minta kredensial (bukan NOT_MCP) |
| UNAUTH_EXPOSED | 68 | tools/list berhasil TANPA auth padahal deklarasi auth |
| NOT_MCP | 58 | tidak melayani MCP sama sekali |
| DEAD | 31 | tidak reachable |
| FAKE | 19 | balas 200 tapi konten kosong/refusal/stub |
| REAL_GRADE_A | 15 | MCP hidup, data nyata, mcpdoctor 80+ |
| DRIFT | 5 | endpoint redirect ke host pihak ketiga |
| JACKABLE | 1 | domain tidak resolve (kandidat takeover) |
| REAL_GRADE_B | 1 | MCP hidup, data nyata, skor 60-79 |

## Supply-chain audit

- **MCPJacking** (DNS tidak resolve): 1
- **Silent drift** (redirect ke host lain): 6
- **Unauthenticated exposure** (tools/list tanpa auth): 68
- **False-green / FAKE**: 19

### Contoh UNAUTH_EXPOSED (deklarasi auth, tapi terbuka)

| connector | deklarasi | tools terlihat | url |
|---|---|---:|---|
| glama-connector/mhi4eqr3gd | api_key | 15 | https://mcp.kyrodata.com/mcp |
| glama-connector/he3v9r54as | oauth2 | 19 | https://www.arroway.app/api/mcp |
| glama-connector/sqbxxxr9pq | api_key | 14 | https://urlpipe.dev/mcp |
| glama-connector/uwske4scmp | api_key | 4 | https://mcp.hasdata.com/api/mcp?apis=youtube |
| glama-connector/rs8t6wzq1k | api_key | 1 | https://mcp.hasdata.com/api/mcp?apis=google_travel_hotels |
| glama-connector/rce845758j | api_key | 13 | https://chatbot.amzscout.net/mcp |
| glama-connector/u0q8i2de18 | api_key | 2 | https://mcp.hasdata.com/api/mcp?apis=indeed |
| glama-connector/jmzd55kidi | api_key | 1 | https://mcp.hasdata.com/api/mcp?apis=duckduckgo |
| glama-connector/jmfyrn9wau | api_key | 5 | https://mcp.hasdata.com/api/mcp?apis=amazon |
| glama-connector/e7gqd1qdsw | oauth2 | 2 | https://flights.flightpowers.com/mcp |
| glama-connector/mrhf60zhrh | api_key | 3 | https://mcp.hasdata.com/api/mcp?apis=yelp |
| glama-connector/zl2gyyzvw0 | api_key | 2 | https://mcp.hasdata.com/api/mcp?apis=yellowpages |
| glama-connector/geffovyt37 | api_key | 2 | https://mcp.hasdata.com/api/mcp?apis=shopify |
| glama-connector/vlt8pki8m5 | api_key | 3 | https://mcp.hasdata.com/api/mcp?apis=instagram |
| glama-connector/bb0ncm8xri | api_key | 10 | https://mcp.hasdata.com/api/mcp?apis=google_serp |

### Contoh FAKE (200 tapi data palsu)

| connector | alasan |
|---|---|
| glama-connector/oll2h14zrh | tool error: {"code": -32000, "message": "ExitProof operation failed", "data": {"code": "invalid_input", "message": "merchant is requ |
| glama-connector/mlz2mayp1o | tool error: {"code": -32000, "message": "Bad Request: Server not initialized"} |
| glama-connector/drhuv33m5q | refusal/stub marker: 'placeholder' |
| glama-connector/s0hms42de7 | empty content (false-green) |
| glama-connector/xrvncthxn3 | tool error: {"code": -32000, "message": "invalid or disabled token"} |
| glama-connector/mwhgdpdi5h | refusal/stub marker: 'placeholder' |
| glama-connector/mqc09cf8db | empty content (false-green) |
| glama-connector/xph2vx440w | tool error: {"code": -32001, "message": "This address needs a personal link: https://mcp.askwatch.ai/gsc/<your key>. The key is free |
| glama-connector/xmbot5cl8n | empty content (false-green) |
| glama-connector/rdbpth0qcb | tool error: {"code": -32002, "message": "No key on this request: none of authorization, x-api-key, x-klarix-key arrived. Get a free  |
| glama-connector/nhdausg3yp | empty content (false-green) |
| glama-connector/ay4ay997ag | tool error: {"code": -32600, "message": "Bad Request: Missing session ID"} |
| glama-connector/ibbw96nk9b | tool error: {"code": -32603, "message": "Internal error", "data": "web_search requires 'query' parameter"} |
| glama-connector/x93zktrkfn | refusal/stub marker: 'example.com' |
| glama-connector/skc2fp03y0 | empty content (false-green) |

### Contoh DRIFT

| connector | rantai redirect |
|---|---|
| glama-connector/mhi4eqr3gd | https://mcp.kyrodata.com/mcp -> https://kyrodata.com/en-US/developers |
| glama-connector/wvfbxvfl1y | https://fincraftly.com/api/mcp |
| glama-connector/xe1tnn274k | https://filmrightsproof.com/mcp |
| glama-connector/gy08asij3k | https://spinorflip.com/mcp |
| glama-connector/xwrixgc214 | https://mcp.snacs.trade |
| glama-connector/d14sdt89t7 | https://mcp.collidemcp.com |

## Cakupan tool nyata (deep)

- mcp-spec-test dijalankan: 648 (conformant: 69)
- mcpdoctor dijalankan: 629
- mcp-reality-check dijalankan: 584
- mcp-contract-check dijalankan: 648
- mcp-probe dijalankan: 648

- skor mcpdoctor: min=0 median=0 max=100

## Metodologi

Layer 1-3, 8 + 3 audit dijalankan in-process (asyncio, httpx).
Layer 4-7 dijalankan lewat tool NYATA (Oktober 2026):
`mcp-reality-check` (pip), `mcp-contract-check` (npm), `@hasmcp/mcp-spec-test` (npm, spec 2026-07-28), `mcpdoctor` (parallelromb, dibangun dari git), `@beeeeen/mcp-probe` (npm).
Layer 8 (mock-vs-real) diimplementasikan lokal karena paket skillsmp `mock-vs-real-detector` mengembalikan 404 (tidak ada).

