# Katalir — Penyelarasan n8n AI, ITERASI 2 (11 Oktober 2026)

- Mode: AUTONOMOUS + SKILL-FIRST + WEB-FIRST + HARD TEST GATE
- Standar acuan: n8n **2.42.0** (29 Sep 2026) & **2.41.4** (30 Sep 2026), praktik Okt 2026
- Aturan: **tidak ada klaim tanpa bukti**. Setiap angka berasal dari log mentah di repo.

---

## 0. Ringkasan eksekutif

| Task | Item | Status | Hard test |
|---|---|---|---|
| 1 | Riset fitur n8n Okt 2026 + update matriks gap | **DONE** | — (riset + `docs/feature-gap-closure.md`) |
| 5 | Validasi payload token sebelum resolusi user | **DONE** | **19/19** |
| 4 | `extendsCredential` (pewarisan kredensial vault) | **DONE** | **16/16** |
| 2 | Upgrade `mcp>=2` (breaking) | **PARTIAL — keputusan terdokumentasi** | **13/13** |
| 3 | Hash-chained evidence ledger | **DONE** | **15/15** |
| 6 | Streaming `/chat` + idle watchdog | **DONE** | **14/14** |
| — | Endpoint API (evidence + stream) | **DONE** | **5/5** |

**Total test baru: 82 skenario, 100% lulus.** Regresi: **317** (auth) + **71**
(vault/kredensial) + **62** (MCP) = **450 lulus, 0 gagal**.

---

## 1. TASK 1 — Riset fitur n8n (web-first, Oktober 2026)

Sumber yang benar-benar terbaca: `undercodenews.com` (analisis rilis 2.42.0),
`releasebot.io/updates/n8n`, `docs.n8n.io/changelog/release-notes`,
`github.com/n8n-io/n8n/releases`, `deepwiki.com/n8n-io/n8n` (AI Agent &
tool-execution). Catatan jujur: `docs.n8n.io` & `github.com/.../releases`
mengembalikan badan kosong saat di-fetch (JS-rendered/blocked); temuan di bawah
berasal dari sumber yang berhasil dibaca + snippet pencarian.

### Fitur baru n8n 2.42.0 (29 Sep 2026)

| Fitur | Dampak ke Katalir |
|---|---|
| AI Agent Tool boleh memakai tool-nya **sendiri** (agent bersarang) | Sudah setara: `[DELEGATE:]` + `subworkflow.py` + `subworkflow_batch.py` |
| **MCP Registry jadi GA** di AI Assistant (flag dihapus) | Sudah setara: `mcp_registry.py`, `mcp_autoconfig.py` |
| **Assistant mencatat live test run sebagai *verification evidence*** | **Ditutup iterasi ini** → `evidence_ledger.py` |
| **`extendsCredential` diterima saat create/update workflow** | **Ditutup iterasi ini** → `vault_extends.py` |
| **Validasi payload token sebelum resolusi user** | **Ditutup iterasi ini** → `token_guard.py` |
| Deskripsi workflow saat create | Sudah ada (`POST /workflows`) |
| Validasi nama path-parameter OpenAPI | Sudah setara (`openapi_connectors.py`) |
| Redis: pulihkan langganan setelah reconnect + deteksi half-open | TODO (Katalir pakai Supabase, bukan Redis pub/sub) |
| Persistensi OpenTelemetry | Sudah ada (`tracing.py`) |
| Batas hasil queue-job pada eksekusi milik proses | N/A (tidak ada worker queue terpisah) |

Matriks lengkap: `docs/feature-gap-closure.md` §4–§5.

---

## 2. TASK 5 — Validasi payload token (SECURITY)

**Modul:** `token_guard.py` · **Integrasi:** `security._guard_claims` (dipanggil
di `_decode_local` SETELAH signature sah).

### Aturan yang ditegakkan
1. **Allow-list algoritma** — tolak `alg: none` dan apa pun di luar
   `{HS256, RS256, ES256, ES384, RS384}`.
2. **`exp` wajib** dan belum kedaluwarsa (toleransi jam 30 s).
3. **`nbf`** tidak boleh di masa depan.
4. **`iss`** cocok persis (bila diminta); **`aud`** memuat nilai yang diharapkan
   (kebijakan proyek: `aud` boleh absen untuk token Supabase lama → `require_aud=False`).
5. **`sub`** wajib cocok `^[A-Za-z0-9._:@|+-]{1,255}$`.
6. **`role`/`roles`** harus ada di whitelist.
7. **Batas payload 10 KB** + tolak klaim terlarang (`__proto__`, `constructor`,
   `prototype`).
8. **Tidak pernah** memakai klaim hasil `jwt.decode(options={"verify_signature": False})`.

### Bukti mentah
```
$ pytest tests/test_token_guard.py -q
19 passed in 0.60s
```
Kasus: valid diterima · expired ditolak · signature palsu ditolak · `aud`
absen/salah ditolak · `iss` salah/absen ditolak · `nbf` masa depan ditolak ·
payload >10 KB ditolak · `sub` aneh ditolak · role injection ditolak ·
`alg: none` ditolak · `alg` di luar allow-list ditolak · performa
**< 10 ms/validasi** · klaim terlarang ditolak.

### Regresi (integrasi ke jalur auth nyata)
```
$ pytest <22 file yang memakai get_current_user> -q
317 passed, 1 warning in 549.33s
```
→ Integrasi **tidak merusak** jalur auth yang sudah ada.

---

## 3. TASK 4 — `extendsCredential`

**Modul:** `vault_extends.py` · **Integrasi:** `vault_broker.resolve_secret` +
`resolve_secrets_in_args` (kini mengenali `extends://`).

### Semantik
- `secret://<provider>/<field>` dan `secret://<provider>#<field>` (alias brief).
- `extends://<provider>` → dict gabungan; `extends://<provider>#<field>` → satu field.
- Entri anak menyatakan induk lewat `__extends__`; **anak menang**.
- **Deteksi siklus**, **batas kedalaman 5**, **induk hilang → error**,
  **isolasi multi-tenant** (loader selalu menerima `user_email`),
  **audit** (jejak tanpa nilai rahasia).

### Bukti mentah
```
$ pytest tests/test_vault_extends.py -q
16 passed in 0.53s
```
Kasus: extends dasar · 3 level · siklus (termasuk self-cycle) · batas kedalaman
(dan batas tepat di ambang) · induk hilang · override anak menang · isolasi
tenant · jalur dekripsi default · performa 1000 resolve < 1 s · 50 resolve
paralel · audit log · regresi parsing + delegasi `secret://`.

### Regresi
```
$ pytest tests/test_vault_broker_and_check_credential.py tests/test_credential_flow.py \
         tests/test_secrets_enterprise.py tests/test_telegram_vault_multifield.py -q
71 passed in 5.28s
```

---

## 4. TASK 2 — Upgrade `mcp>=2` (BREAKING) — keputusan terdokumentasi

### Riset (web-first)
`explore.n1n.ai` (analisis breaking change 2.0), `deepwiki.com/modelcontextprotocol/python-sdk`
(v1→v2 migration guide), `blog.modelcontextprotocol.io` (beta SDK spec 2026-07-28).

### Breaking change yang DIVERIFIKASI langsung dari paket nyata
Dipasang terisolasi: `pip install --target _mcp2_probe "mcp>=2,<3"` → **mcp 2.3.0**.
Intropeksi sumber (bukan asumsi):

| 1.x (terpasang, dipakai proyek) | 2.x (2.3.0) |
|---|---|
| `mcp.server.fastmcp.FastMCP` | `mcp.server.mcpserver.MCPServer` |
| `streamablehttp_client(url, headers=…, timeout=…)` → **3-tuple** | `streamable_http_client(url, *, http_client=<httpx2.AsyncClient>)` → **2-tuple** |
| `tool.inputSchema`, `result.isError`, `nextCursor`, `structuredContent` | `input_schema`, `is_error`, `next_cursor`, `structured_content` |
| paket `httpx` | paket **`httpx2`** |

### Cutover DIUJI dan GAGAL (bukti mentah)
```
$ PYTHONPATH=_mcp2_probe python -c "import mcp_server; mcp_server.build_server()"
BUILD FAILED: ModuleNotFoundError
MSG: No module named 'mcp.server.fastmcp'. This is mcp 2.x, where FastMCP was
     renamed to MCPServer (from mcp.server.mcpserver import MCPServer) and other
     APIs changed; ... or pin 'mcp<2' to keep running v1 code.
```
Konflik dependensi terukur: mcp 2.3.0 menarik **pydantic 2.14.0 + starlette 1.7.0
+ httpx2 2.13.1**, bertabrakan dengan pin proyek `pydantic==2.12.5`,
`starlette==1.0.1`, `httpx==0.28.1` (yang sudah lolos 353+ test).

### Yang DIKERJAKAN (jalur client dibuat siap-2.x)
`mcp_compat.py` — deteksi versi via **major metadata** (nama fungsi tidak andal:
1.x terbaru juga punya alias `streamable_http_client`), normalisasi 3-tuple/2-tuple,
`httpx2` eksplisit pada 2.x, helper model lintas versi, dan adapter server
(`make_server` membuang kwarg khusus FastMCP pada 2.x).
`mcp_gateway/client.py` **dirutekan lewat** `mcp_compat` dan memakai
`dump_wire` (`model_dump(by_alias=True)`) agar bentuk respons ke klien **tidak
berubah** saat SDK di-upgrade.

### Diverifikasi terhadap mcp 2.3.0 NYATA
```
$ PYTHONPATH=_mcp2_probe python -c "... mcp_compat ..."
version: 2.3.0
major  : 2 | is_v2: True
server class: MCPServer
built: MCPServer
has streamable_http_app: True
dropped: ['stateless_http', 'transport_security', 'streamable_http_path']
transport fn: ['streamable_http_client']
```

### Bukti mentah test + regresi
```
$ pytest tests/test_mcp_compat.py -q
13 passed in 1.44s

$ pytest <6 file MCP + test_mcp_compat> -q
62 passed in 19.27s
```

### Keputusan (sesuai izin brief "kalau gagal: rollback + dokumentasi")
`requirements.txt` tetap `mcp>=1.28.1,<3` dengan blok komentar yang menjelaskan
**mengapa** cutover server ditunda, apa yang sudah siap, dan apa yang tersisa.
Migrasi server (`mcp_server.py`: FastMCP + `stateless_http` + `transport_security`
→ `MCPServer` + `auth`/`token_verifier`) = pekerjaan terpisah, **tidak diklaim selesai**.

---

## 5. TASK 3 — Hash-chained evidence ledger

**Modul:** `evidence_ledger.py` · **Endpoint:** `POST /evidence`,
`GET /evidence/{id}/verify`.

### Struktur entri
`seq · id · ts · content_hash = sha256(canonical_json(content)) ·
prev_hash · hash = sha256(prev:content_hash:seq) · sig = HMAC-SHA256(key, hash)`

### Jaminan
Integritas (hitung ulang tiap tautan) · **deteksi tamper** (ubah `content`/`hash`/
`prev_hash` → rantai pecah pada entri itu) · autentikasi (HMAC) · serialisasi
kanonik stabil lintas proses · append thread-safe · store memori **dan** DDL
Postgres (`PostgresEvidenceStore`).

### Bukti mentah
```
$ pytest tests/test_evidence_ledger.py -q
15 passed in 0.56s
```
Kasus: append+hash · integritas rantai 20 entri · tamper content/hash · **reorder**
terdeteksi · **1000 append < 1 s** · verifikasi entri tunggal · verifikasi rantai
penuh (termasuk entri hilang) · verifikasi signature (kunci beda ditolak) ·
**100 append paralel** (seq unik 0..99, rantai utuh) · persist→reload hash sama ·
reload stabil · helper `verify_payload` (endpoint) · regresi genesis/kunci
wajib/kanonik.

---

## 6. TASK 6 — Streaming `/chat` + idle watchdog

**Modul:** `chat_stream.py` · **Endpoint:** `POST /chat/stream` (SSE).

### Perilaku
Heartbeat tiap 10 s · **abort idle 30 s** dengan frame `error` yang jelas ·
urutan chunk terjaga (satu `__anext__` hidup pada satu waktu) · **cleanup saat
klien memutus** (task pending dibatalkan, sumber ditutup) · **fallback**
non-streaming bila gagal sebelum chunk pertama · **resume** via `Last-Event-ID`.

### Bukti mentah
```
$ pytest tests/test_chat_stream.py -q
14 passed in 1.02s
```
Kasus: streaming dasar · idle abort (pesan + `idle_seconds`) · heartbeat ≥2 ·
cleanup disconnect · **100 stream paralel** · urutan + `id` terjaga ·
error sumber → frame `error` graceful · fallback saat error · tanpa fallback
saat normal · **chunk pertama < 100 ms** · tidak ada task bocor · resume
`start_index` · format frame + helper.

### Endpoint API
```
$ pytest tests/test_evidence_stream_api.py -q
5 passed in 3.71s
```
Kasus: `/chat/stream` mengirim frame chunk+done · tanpa auth → 401 ·
`/evidence` append→verify valid · id tak dikenal → `found=false` ·
`/evidence` tanpa auth → 401.

---

## 7. Berkas yang ditambahkan / diubah

**Baru:** `token_guard.py` · `vault_extends.py` · `evidence_ledger.py` ·
`chat_stream.py` · `mcp_compat.py` ·
`tests/test_token_guard.py` · `tests/test_vault_extends.py` ·
`tests/test_evidence_ledger.py` · `tests/test_chat_stream.py` ·
`tests/test_mcp_compat.py` · `tests/test_evidence_stream_api.py`

**Diubah:** `security.py` (hook `_guard_claims`) · `vault_broker.py`
(`is_credential_ref`, delegasi `extends://`) · `mcp_gateway/client.py`
(rute lewat `mcp_compat`) · `api_server.py` (import + 3 endpoint) ·
`requirements.txt` (komentar keputusan mcp) · `.gitignore` (`_mcp2_probe/`) ·
`docs/feature-gap-closure.md` (§4 status, §5 delta 2.42.0)

---

## 8. Yang TIDAK diklaim selesai (jujur)

1. **Migrasi server MCP ke 2.x** — hanya jalur client yang siap-2.x; jalur server
   masih 1.x dan cutover-nya gagal terverifikasi.
2. **Redis pub/sub recovery** (n8n 2.42.0) — Katalir tidak memakai Redis.
3. **Streaming token-level dari provider LLM** — `/chat/stream` men-stream
   potongan jawaban final; lapisan watchdog/heartbeat/fallback sudah siap untuk
   sumber token-nyata.
