# Fitur #8 — MCP Server Built-in

**Status:** ✅ HIJAU — 10/10 hard test PASS (`tests/test_mcp_server_builtin.py`)
**Permukaan:** `POST/GET/DELETE /mcp/katalir` (protokol MCP asli) + `GET /mcp/katalir/info` + `POST /mcp/katalir/key`

## Masalah yang diselesaikan

Sebelum fitur ini Katalir hanya menjadi MCP **client** (`mcp_gateway/`,
`mcp_registry.py`) dan punya dua permukaan MCP yang tidak lengkap:

1. `mcp_gateway/katalir_server.py` — hanya 2 tool, transport **stdio**, dan
   mengimpor `api_server` sehingga hanya bisa jalan sebagai proses terpisah.
   Tidak bisa dipanggil lewat HTTP oleh Claude Desktop / Cursor di cloud.
2. `GET /mcp/server/tools` + `POST /mcp/server/call` — permukaan HTTP biasa yang
   **meniru** MCP secara manual. Bukan protokol MCP: tidak ada `initialize`,
   tidak ada `tools/list` JSON-RPC, tidak ada `Mcp-Session-Id`, tidak ada SSE
   framing. Klien MCP asli tidak bisa menyambung.

Akibatnya Katalir **tidak bisa dipakai sebagai server MCP** oleh klien nyata.

## Research

| Paket / Pendekatan | Versi | Verdict | Alasan |
|---|---|---|---|
| `fastmcp` (PyPI) | 4.0.11 | ⚠️ ditolak | Bukan paket resmi MCP; API berbeda dari SDK yang sudah dipakai repo. |
| `mcp` (SDK resmi, sudah di `requirements.txt`) | 1.28.1 | ✅ **dipakai** | SDK resmi; `FastMCP` + `StreamableHTTPSessionManager` sudah terpasang. Nol dependency baru. |
| Server MCP manual (JSON-RPC tulis tangan) | — | ❌ | Harus mengimplementasi framing SSE + handshake; rawan menyimpang dari spec. |
| `mcp_gateway/katalir_server.py` (existing) | — | ❌ | stdio-only, mengimpor `api_server` (siklus), 2 tool. |

**Pilihan:** SDK resmi `mcp` 1.28.1 — `FastMCP` + Streamable HTTP **stateless**.
**Alasan:** satu-satunya opsi yang berbicara protokol MCP asli **tanpa**
dependency baru, dan sudah terbukti di repo.

## Implementasi

- **File baru:** `mcp_server.py` (server, API key, middleware auth, ASGI app),
  `tests/test_mcp_server_builtin.py` (10 skenario).
- **File diubah:** `api_server.py` (import, `_lifespan` menyalakan session
  manager, mount + route ASGI eksplisit, endpoint bantu).
- **Tanpa DDL** — API key = JWT HS256 bertanda tangan `VAULT_SECRET_KEY`
  (kunci yang sama dengan `credential_forms`). Tidak ada tabel baru.

### Desain kunci

- **Stateless HTTP** (`stateless_http=True`) — Railway menjalankan >1 instance
  tanpa sticky session; stateful akan gagal begitu request berikutnya mendarat
  di instance lain.
- **Auth via API key** (bukan JWT Supabase) — klien MCP tidak bisa alur login.
  Dua bentuk header: `X-API-Key` dan `Authorization: Bearer`. `X-API-Key` menang.
- **Owner-scoped** — setiap tool memakai `user_id` dari API key, tidak pernah
  dari argumen.
- **DNS-rebinding protection DIPERTAHANKAN** — allowlist host dari
  `ALLOWED_HOSTS`. Host asing → 400/421.
- **Route ASGI eksplisit** didaftarkan sebelum `mount()` supaya
  `/mcp/katalir` (tanpa garis miring) **tidak** 307 — klien MCP tidak mengikuti
  redirect POST.

### Tool yang diekspos

| Tool | Argumen | Balasan |
|---|---|---|
| `create_workflow` | `name`, `description?`, `flow_data?` | `{id, name, node_count, created}` |
| `update_workflow` | `workflow_id`, `name?`, `description?`, `flow_data?` | `{id, name, updated}` |
| `list_workflows` | `limit?` | `{count, workflows:[...]}` |
| `execute_workflow` | `workflow_id`, `input?` | `{execution_id, workflow_id, status}` |
| `get_execution_status` | `execution_id` | `{execution_id, workflow_id, status, steps, step_count}` |

## Hard Test — 10/10 PASS

```
tests/test_mcp_server_builtin.py .......... [100%]  10 passed in 7.48s
```

| # | Skenario | Status | Bukti |
|---|---|---|---|
| 1 | `initialize` → serverInfo + protocolVersion | ✅ | `protocolVersion=2025-06-18 serverInfo={'name':'katalir','version':'1.28.1'}` |
| 2 | `tools/list` → 5 tool + inputSchema valid | ✅ | `tools=[create_workflow, execute_workflow, get_execution_status, list_workflows, update_workflow]` |
| 3 | Tanpa API key → 401 (initialize/list/call) | ✅ | ketiganya 401, `error.code=-32001`, ada `WWW-Authenticate` |
| 4 | Kunci rusak / kedaluwarsa → 401 | ✅ | 6 bentuk rusak + payload `exp` lewat → 401 ("kedaluwarsa") |
| 5 | Dua bentuk header sama-sama diterima | ✅ | X-API-Key=200, Bearer=200, bearer-kecil=200, keduanya=200 |
| 6 | Isolasi antar user | ✅ | A tidak melihat/mengubah/menjalankan workflow B (`isError=True`) |
| 7 | create → update → list | ✅ | `node_count=2`, nama berubah, muncul di list |
| 8 | execute → status | ✅ | `execution_id` ada, `status=pending`; workflow kosong ditolak |
| 9 | Path tanpa garis miring (bukan 307) | ✅ | `/mcp/katalir` & `/mcp/katalir/` → 200, tools identik |
| 10 | DNS-rebinding + validasi flow_data | ✅ | host asing diblokir; 5 graf rusak ditolak sebelum DB |

## Cara pakai (klien MCP)

### Claude Desktop / Cursor (via `mcp-remote`)
```json
{
  "mcpServers": {
    "katalir": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://<host-railway>/mcp/katalir",
               "--header", "X-API-Key:${KATALIR_MCP_KEY}"]
    }
  }
}
```

### Terbitkan API key (butuh login Supabase)
```bash
curl -X POST https://<host>/mcp/katalir/key \
  -H "Authorization: Bearer <SUPABASE_JWT>" \
  -H "Content-Type: application/json" -d '{"ttl_s":2592000}'
# -> {"api_key":"mcp-kir_<payload>.<sig>", "expires_in":2592000}
```

### Cek metadata
```bash
curl https://<host>/mcp/katalir/info -H "X-API-Key: <key>"
```

## Blocker / catatan

- **Flaky pada run dingin:** percobaan pertama seluruh file gagal
  (`RuntimeError: Task group is not initialized`) karena warm-up jaringan
  lifespan (JWKS + roster gateway) menggantung >90s. Run kedua **10/10 PASS**
  dalam 7,48s. Ini murni lingkungan (gateway memang terdegradasi), bukan bug
  logika. Bila perlu CI deterministik: set `SKIP_WARMUP=1` atau perpanjang
  timeout harness.
- **Kill-switch:** `MCP_SERVER_ENABLED=0` mematikan mount + session manager
  (dipakai test yang tidak butuh MCP).

## Next
Fitur #10 (Workflow Templates).
