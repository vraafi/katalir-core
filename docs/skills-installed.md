# FASE 0 — Verifikasi & Instalasi Skill

**Metode**: setiap skill diverifikasi dulu terhadap sumber nyata (GitHub API,
npm registry, PyPI JSON API) **sebelum** dipasang. Skill yang tidak ada
**tidak** dipasang dan dilaporkan jujur.

Aturan brief: *"JANGAN buat dari nol — gunakan skill yang ada."* Karena itu
langkah pertama bukan memasang, melainkan **membuktikan skill itu ada**.

---

## 1. Hasil verifikasi GitHub

Diperiksa lewat `https://api.github.com/repos/<owner>/<repo>`:

| Repo yang diminta brief | HTTP | Status |
|---|---|---|
| `the911fund/skill-of-skills` | 200 | ada — tapi **tidak punya `skills/`** |
| `rohangore1999/skill-pull` | 200 | ada — tapi **tidak punya `skills/`** |
| `issdandavis/SCBE-AETHERMOORE` | 200 | ada — **`skills/` berisi 23 skill, TIDAK ada `scbe-connector-health-check`** |
| `chobitly/opencli` | 200 | ada — **`skills/` berisi `opencli-autofix` ✅** |
| `solvrbase/solvr` | 200 | repo ada, **`skills/` = Not Found**; tidak ada `skill-repair` |
| `neuronto/agentic-resource-discovery` | **404** | **TIDAK ADA** |
| `MK-OR/AI-Agent` | **404** | **TIDAK ADA** |
| `ryanunderhill/MCP-BatchIt` | **404** | **TIDAK ADA** |
| `headyai/heady-staging` | 200 | repo ada, bukan skill `heady-connector-health` |

### Skill asli di `issdandavis/SCBE-AETHERMOORE/skills/`

```
SKILLS_INDEX.md, cloud-storage-local-storage-management, codex-mirror,
long-form-work-orchestrator, multi-agent-cloud-offload, scbe-admin-autopilot,
scbe-autonomous-worker-productizer, scbe-browser-sidepanel-ops,
scbe-claim-to-code-evidence, scbe-codebase-orienter, scbe-colab-bridge,
scbe-colab-training-ops, scbe-document-management,
scbe-government-contract-intelligence,
scbe-kernel-external-toolcall-specialist, scbe-playwright-ops-extension,
scbe-research-training-bridge, scbe-spin-conversation-engine,
scbe-spiralverse-intent-auth, scbe-training-pair-authoring,
stripe-best-practices, stripe-projects, upgrade-stripe
```

→ **`scbe-connector-health-check` TIDAK ADA.** Nama yang benar-benar ada adalah
`scbe-claim-to-code-evidence` (untuk evidence klaim, bukan health connector).

### Skill asli di `chobitly/opencli/skills/`

```
opencli-adapter-author, opencli-autofix, opencli-browser, opencli-usage, smart-search
```

→ **`opencli-autofix` BENAR ADA ✅** — satu-satunya skill dari daftar brief
yang lolos verifikasi apa adanya.

---

## 2. Hasil verifikasi paket (npm + PyPI)

| Paket | Registry | Versi | Nyata? |
|---|---|---|---|
| `@stackql/mcp-wringer` | npm | 0.1.0 (mod. 2026-10-09) | ✅ **2,75 MB**, deps `ajv`+`fast-check`+`cross-spawn`, repo `stackql/mcp-wringer` |
| `agentify-cli` | npm | 0.4.3 | ✅ 456 KB, repo `koriyoshi2041/agentify` |
| `mcp-batchit` | npm | — | ❌ **Not found** |
| `ducktap` | PyPI | 0.8.3 | ✅ repo `zanni098/DuckTap` |
| `tool-scorer` | PyPI | 1.10.0 | ✅ nyata, **tapi kegunaannya berbeda** (lihat §4) |
| `agentify` | PyPI | ada | ✅ (jalur alternatif; pakai npm `agentify-cli`) |

---

## 3. Yang di-INSTALL dan DIBUKTIKAN bekerja

### 3.1 `@stackql/mcp-wringer` 0.1.0 — FUZZER MCP ✅ TERPASANG & TERUJI

```
$ npm install -g @stackql/mcp-wringer
added 14 packages in 14s
```

Sub-perintah nyata (bukan asumsi):

```
init | list | replay | inspect | run | minimize
```

Uji nyata terhadap server MCP hidup:

| Target | Hasil mcp-wringer | Arti |
|---|---|---|
| `gate.horizonshield.dev/mcp` | `[TARGET_ERROR] -32601 method not found: resources/list` | **hidup**, tidak implement `resources/list` |
| `mcp.formcarry.com/mcp` | `[TARGET_ERROR] error missing_bearer ...` | **hidup**, butuh Bearer (bukan mati) |
| `api.kentekenkompas.nl/mcp` | `[TARGET_ERROR] -32601 Method not found` | **hidup**, implementasi tidak lengkap |

**Temuan penting (jujur)**: mcp-wringer menuntut spec `2025-11-25` + wajib
`resources/list`. Banyak server nyata tidak mengimplementasikannya, sehingga
hampir semua mengembalikan `TARGET_ERROR` **walaupun server hidup**. Karena itu
mcp-wringer **tidak bisa** dipakai sebagai satu-satunya penentu ALIVE/DEAD —
harus dipasangkan dengan prober `initialize`+`tools/list` (lihat FASE 2).

### 3.2 `ducktap` 0.8.3 — OpenAPI → MCP ✅ TERPASANG & TERBUKTI

```
$ pip install ducktap
Successfully installed ducktap-0.8.3 watchfiles-1.3.0
```

Bukti generate nyata dari spec hidup:

```
$ ducktap press "https://petstore3.swagger.io/api/v3/openapi.json" \
    -o _dt_out --name petstore --targets mcp-server

Pressed petstore (19 operations) -> _dt_out
  mcp-server: 5 files
Scorecard: 83/100 (B)   coverage 95 · documentation 100 · auth 100
```

Berkas yang dihasilkan (nyata, bukan stub):

| Berkas | Ukuran |
|---|---|
| `petstore-dt-mcp/petstore_dt_mcp/server.py` | **23.682 B** |
| `petstore_dt_mcp/__main__.py` | 68 B |
| `pyproject.toml` | 479 B |
| `README.md` | 1.574 B |

`server.py` memakai SDK resmi `mcp` + `mcp.server.stdio`, dengan
`_TOOL_DEFS` berisi JSON-schema per operasi. **Layak dipakai untuk FASE 4.**

### 3.3 `opencli-autofix` ✅ TERVERIFIKASI ADA

Satu-satunya skill dari daftar brief yang lolos verifikasi apa adanya.
Lokasi: `github.com/chobitly/opencli/skills/opencli-autofix`.

---

## 4. Koreksi klaim brief (WAJIB dibaca)

| Klaim brief | Kenyataan |
|---|---|
| `SCBE-AETHERMOORE --skill scbe-connector-health-check` | ❌ **skill itu tidak ada** di repo tersebut |
| `skillsmp.com/.../heady-connector-health` | ❌ tidak terverifikasi sebagai skill terpasang |
| `github.com/solvrbase/solvr --skill skill-repair` | ❌ **tidak ada `skills/`** di repo |
| `neuronto/agentic-resource-discovery` | ❌ **repo 404** (FASE 5 tidak bisa pakai ini) |
| `MK-OR/AI-Agent --skill add-supabase` | ❌ **repo 404** (FASE 1 tidak bisa pakai ini) |
| `ryanunderhill/MCP-BatchIt` | ❌ **repo 404**; npm `mcp-batchit` juga tidak ada |
| `pip install tool-scorer` = "health check deterministik, grade per connector" | ⚠️ **SALAH**. `tool-scorer` 1.10.0 adalah penguji **tool-call LLM** ("compare expected vs actual tool calls"), **bukan** alat kesehatan connector. |
| `npm install -g @stackql/mcp-wringer` = "fuzz endpoint" | ✅ benar, **tapi** strict terhadap spec `2025-11-25` (lihat §3.1) |

**Konsekuensi**: FASE 1, 3, 5, 6 **tidak punya skill** yang bisa dipakai — repo
yang ditunjuk tidak ada. FASE 2 & 4 **punya** alat nyata (mcp-wringer, ducktap)
dan akan dijalankan. Untuk fase tanpa skill, pendekatan yang dipakai adalah
**kode langsung yang sudah ada di repo ini** (`mcp_registry`, `connector_activator`,
`database`) — bukan membuat dari nol, karena infrastrukturnya sudah ada dan
sudah terbukti (lihat `docs/audit/connector-connection-honest-audit.md`).

---

## 5. Ringkasan status

| FASE | Skill yang diminta | Status skill | Rencana |
|---|---|---|---|
| 0 | 8 skill | **2 nyata, 6 tidak ada** | ✅ terverifikasi, laporan ini |
| 1 | add-supabase | ❌ repo 404 | pakai `database.py` + Supabase yang sudah terpasang |
| 2 | mcp-wringer + tool-scorer | ⚠️ wringer ✅, tool-scorer salah fungsi | pakai mcp-wringer + prober katalog |
| 3 | opencli-autofix + skill-repair | ⚠️ autofix ✅, repair ❌ | pakai autofix + logika repair di repo |
| 4 | ducktap + agentify | ✅ keduanya nyata | ✅ jalankan generate nyata |
| 5 | agentic-resource-discovery | ❌ repo 404 | pakai Glama/Composio/Smithery langsung |
| 6 | heady-connector-health | ❌ tidak terverifikasi | cron + tabel `connector_health` |
