# free-llm-gateway — Model Gemini (2026-10-02)

Dokumen ini menjelaskan arsitektur sebenarnya, dan kenapa instruksi "tambahkan
route `GenerateContent` / `GeminiCountTokens` ke `AgentgatewayBackend`" TIDAK
bisa diterapkan apa adanya di setup ini.

## 1. Dua layanan BERBEDA (salah paham yang paling sering terjadi)

| Layanan | Bentuk | Port | Fungsi |
|---------|--------|------|--------|
| `agentgateway` | systemd, `/opt/agentgateway/config.yaml` | 3001 (MCP), 15000 (admin) | **MCP federation saja** |
| `free-llm-gateway` | Docker container | 8080 | **LLM**: `/v1/models`, `/v1/chat/completions` |

Katalir (Railway) memanggil **free-llm-gateway** lewat Tailscale
(`LLM_GATEWAY_URL=https://nexus-gateway-vps.tail7f0d5a.ts.net`), bukan
agentgateway.

`/etc/agentgateway/config.yaml` **tidak punya blok `ai:` sama sekali** — hanya
`mcp:` (apiKey policy + 6 MCP target). Menambah route Gemini ke sana TIDAK akan
muncul di dropdown Katalir.

## 2. Tidak ada Kubernetes

`kubectl`, `k3s`, `minikube` semuanya tidak ada. `AgentgatewayBackend` adalah
CRD Kubernetes; padanannya di mode standalone adalah blok `binds:` pada
`config.yaml` milik free-llm-gateway. Jadi YAML pada instruksi tersebut
tidak bisa di-apply.

## 3. Yang sebenarnya perlu diubah: `models.yaml`

Katalog model free-llm-gateway ada di **`/opt/free-llm-gateway/models.yaml`**
(baked into image, bukan docker mount —harus `docker cp` + restart).
Gemini yang sudah ada: `gemini-2.5-flash`, `gemini-2.5-flash-lite`,
`gemini-3-flash-preview`.

Ditambahkan 2026-10-02: `gemini-3.8-flash`, `gemini-3.5-flash-lite`,
`gemini-3.1-pro-preview`. Backup: `models.yaml.bak.<timestamp>`.

## 4. Jebakan nyata: gateway answering dengan model LAIN

Sebelum ditambahkan, meminta `gemini-3.8-flash` **tidak error** — gateway
diam-diam menjawab dengan model lain:

```
gemini-3.8-flash  HTTP 200  response.model='nvidia/nemotron-3-super-120b-a12b'
gemini-3.5-flash-lite HTTP 200  response.model='nvidia/nemotron-3-super-120b-a12b'
```

Artinya menambahkan model ke dropdown Katalir **tanpa** menambahkannya ke
`models.yaml` akan membuat UI menulis "Gemini" sementara yang menjawab adalah
Nemotron. Selalu verifikasi `X-Routed-Via` = `google_gemini/<id>`.

## 5. Hasil verifikasi

Probe produksi (`gateway_roster.probe_roster(force=True)`):
- `gemini-3.8-flash` → `google_gemini/gemini-3.8-flash` (18.6s)
- `gemini-3.5-flash-lite` → `google_gemini/gemini-3.5-flash-lite` (0.8s)
- `gemini-3.1-pro-preview` → **HTTP 504 "Queued request timed out"** (113s)

`gemini-3.1-pro-preview` tetap dikonfigurasi (untuk pemakaian tier berbayar nanti)
tetapi probe timeout sehingga **tidak muncul** di dropdown — perilaku yang benar,
karena model yang lambat lebih baik disembunyikan daripada ditampilkan ke user.