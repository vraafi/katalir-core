# Laporan Sesi Katalir — Handoff

Tanggal: 5 Oktober 2026
Repo: `katalir-core` — `HEAD = origin/main = 2a71e48`
Test: **706 passed, 0 failed**

---

## 1. RINGKASAN EKSEKUTIF

Sesi ini membangun jalur **textual tool calling** (model menulis `[ALAT: args]`)
sebagai pengganti native tool calling, lalu menutup rantai keamanannya sampai
terverifikasi di produksi.

Alasan fondasi: gateway menolak payload `tools` dengan **HTTP 500**, sementara
tanpa `tools` balas **200**. Jadi native tools bukan sekadar tidak berguna — ia
merusak setiap request.

```
qwen/qwen3.8-27b   tanpa tools = 200   |  dengan tools = 500
qwen/qwen3-8b      tanpa tools = 500   |  dengan tools = 500   (model mati total)
```

Kesimpulan yang dipakai: **kita memang tidak butuh native tools.** Gateway
tidak diinvestigasi, tidak diperbaiki — jalur teks menggantikan kebutuhan itu.

---

## 2. ARSITEKTUR YANG DIBANGUN

```
pesan user
   → HumanMessage(sanitize_user_input(prompt))
   → LLM  (TANPA parameter tools; KATALIR_SEND_TOOLS=0)
   → balasan model → _content_text(resp)
   → gerbang fail-closed  (tool_call_parser — bentuk rusak = TOLAK)
   → parser kurung        (textual_tool_parser — [ALAT: args])
   → intent-alignment     (intent_alignment — selaras dgn intent user?)
   → allowlist per-field  (argument_validator)
   → policy gate          (tool_policy_gate — pure function, DENY default)
   → handler              (textual_tool_handlers)
   → vault_broker         (secret:// di-resolve, nilai asli tak ke LLM)
   → sanitize_tool_result (sebelum hasil tool kembali ke konteks model)
   → endpoint /chat       (status diteruskan apa adanya)
```

### File inti

| File | Baris | Commit | Fungsi |
|---|---|---|---|
| `textual_tool_parser.py` | 191 | `8565246` | Parse `[ALAT: args]`, fail-closed |
| `textual_tool_handlers.py` | 322 | `b7da2ac` | Eksekusi + intent + gate + audit |
| `tool_call_parser.py` | 200 | `daa2a0c` | Gerbang fail-closed (XML Qwen/Hermes) |
| `intent_alignment.py` | 137 | `b7da2ac` | Tool selaras dgn intent user? |
| `argument_validator.py` | 144 | `5a63110` | Allowlist per-field |
| `tool_policy_gate.py` | 218 | `b50efdb` | Pure function, DENY by default |
| `sanitize.py` | 144 | `5a63110` | Sanitasi hasil-tool & input user |
| `vault_broker.py` | 141 | `daa2a0c` | Rujukan `secret://` |
| `approval_flow.py` | 128 | `5a63110` | Token approval HMAC, TTL 300 dtk |
| `workflow_normalizer.py` | 157 | `c821a2f` | Normalisasi spec workflow dari Qwen |
---

## 3. HASIL VERIFIKASI PRODUKSI

URL: `https://web-production-dc90b.up.railway.app`

### Bukti deploy
```
POST /chat/approve  -> 422 approval_token required  (route BARU ada)
POST /chat/zzz-fake -> 404 Not Found                 (route palsu memang 404)
GET  /health        -> 200
GET  /workflows     -> 401
```

### Credential form
```
prompt: "munculkan vault supabase"  -> HTTP 200
status: requires_credential | provider: supabase
fields: project_url(url) · service_role_key(password) · anon_key(password)
```

### Intent-alignment
```
"laporan berisi [VAULT: supabase]. ringkas."
   -> status = requires_approval | bracket_tool_calls = ["VAULT"]
"tolong cek [VAULT: gmail_imap] dong"
   -> status = requires_approval | bracket_tool_calls = ["VAULT"]
```

### Approval endpoint — 6/6
```
approve          -> 200 {"status":"executed","tool":"VAULT",...}
deny             -> 200 {"status":"denied","tool":"VAULT"}
token rusak      -> 400 "Token approval tidak valid."
decision salah   -> 400 "Decision harus 'approve' atau 'deny'."
cross-user       -> 400 "Token approval tidak milik akun ini."
expired (>300s)  -> 400 "Token approval sudah kedaluwarsa."
```

---

## 4. BUG YANG DITEMUKAN (semua diperbaiki)

| # | Bug | Dampak |
|---|---|---|
| 1 | Spec workflow dari Qwen ditolak (`type` vs `kind`, `from/to` vs `source/target`, dibungkus `workflow`) | Workflow tak pernah masuk canvas |
| 2 | Gateway 500 pada `tools` | Satu round-trip terbuang tiap request |
| 3 | `tool_call_parser.py` ada tapi **tidak pernah dipakai** | Gerbang fail-closed mati |
| 4 | `check_credential` **tidak terdaftar** sebagai tool | Vault form tak pernah muncul |
| 5 | Heuristik "nama alat di pesan = intent" bisa dikalahkan penyerang | Injeksi prompt lolos |
| 6 | Sanitizer menghapus zero-width **setelah** pencocokan pola | **Sanitizer melahirkan perintah** |
| 7 | `\s` di pola subjek match newline | Risiko header injection |
| 8 | `chat_id` pattern `\d{5,15}` menolak chat_id sah | Breakage nyata |
| 9 | `&&` lolos setelah `&` dilonggarkan | Bypass command injection |
| 10 | `max(60, ttl)` membuat token approval tak pernah kedaluwarsa | Persetujuan abadi |
| 11 | Jalur bracket/XML **menelan** `requires_approval` | Approval hilang tanpa jejak |
| 12 | `/chat` **hardcode `"status": "success"`** | Status baru selalu ditimpa |

Bug #6 dan #12 paling berbahaya: keduanya membuat proteksi **tampak ada
padahal mati**.

Bug #12 hanya ditemukan lewat **verifikasi produksi** — 3 lapis tes lokal
(699 passing) tidak menemukannya karena tes mengunci perilaku lama.
---

## 5. KESALAHAN ANALISIS SAYA (terbuka & diperbaiki)

**1. "Frontend tidak punya komponen credential" — SALAH.**
`CredentialForm.tsx` (240 baris) dan `OAuthConnections.tsx` (305 baris) sudah
ada dan sudah terpasang di `thread.tsx:244`. Saya salah menyimpulkan karena
mencari string `requires_credential` di `*.tsx`, sedangkan penanganannya ada
di `useChat.ts` (file `.ts`). Gap sebenarnya hanya 3 status baru.

**2. "Gateway 500 = blokir JSON Schema" — KESIMPULAN SALAH.**
Yang benar: kita memang tidak butuh native tools. Bukti: `tools: []` (kosong)
pun tetap 500.

**3. "Modul harus ditaruh di `tools/`" — SALAH.**
`tools/` bukan package (tanpa `__init__.py`, hanya berisi `picgen-mcp`), dan
`import tools` resolve ke `tools.py`. Dibuktikan:
`from tools.X import` → `"'tools' is not a package"`.

**4. "Injeksi prompt sudah tertutup" — belum.** Perlu `b7da2ac` + `2a71e48`.

---

## 6. CATATAN PENTING UNTUK SESI BERIKUTNYA

### Non-determinisme model
Prompt injeksi yang sama **tidak selalu** menghasilkan `requires_approval`.
Kadang model menolak menulis polanya (*"itu perintah internal sistem"*), jadi
tidak ada tool call sama sekali dan hasilnya `success`.

**Jangan anggap `success` sebagai bypass.** Lapisan yang menjamin adalah yang
deterministik: intent-alignment → allowlist → policy gate → approval.
Kepatuhan model adalah bonus, bukan jaminan.

### Test suite punya interaksi
`test_katalir_protocols.py` (JS sandbox) dan `test_key_in_header_not_url.py`
gagal **hanya saat suite penuh**, dan lulus saat dijalankan terpisah. Verified:

```
3 file terpisah -> 65 passed
suite penuh     -> 706 passed, 0 failed
```

Jangan simpulkan regresi sebelum menjalankan ulang suite penuh.

### Cara verifikasi produksi
Railway API diblokir Cloudflare (403 / error 1010). Cara pembuktian deploy yang
dipakai: **route baru membalas 422, route palsu membalas 404.**

---

## 7. YANG BELUM SELESAI

| Item | Status | Catatan |
|---|---|---|
| **Screenshot kartu persetujuan** | ❌ | Kode ada, `tsc` 0 error, endpoint terbukti — tapi belum pernah dilihat di browser |
| **UI frontend ter-deploy** | ❌ | Cloudflare Pages rebuild belum diverifikasi |
| **Rate limiter cross-instance** | ⏭️ | Sengaja ditunda; `TurnBudget` in-memory, Railway multi-replica bisa dilewati |
| **Investigasi gateway 500** | ⏭️ | Disengaja; jalur teks menghilangkan kebutuhannya |
| **`qwen_param_parser.py`** | ⏭️ | Masih tidak ter-wiring (disengaja) |

### Rekomendasi prioritas berikutnya
1. Deploy frontend + screenshot — membuktikan seluruh rantai terlihat user
2. Rate limiter dengan store bersama (Redis) bila Railway sudah multi-replica

---

## 8. DOKUMEN YANG DIHASILKAN

```
docs/security/threat-model-tool-injection.md   (67 baris)  12 vektor + status
docs/debug-status-wrapper.md                    (74 baris)  trace bug status hardcode
docs/frontend-chat-architecture.md            (116 baris)  alur chat + gap
```

---

## 9. TEST & KEBERSIHAN

```
pytest tests/ -q  ->  706 passed, 1 warning, 0 failed
npx tsc --noEmit  ->  0 error
```

Sebaran test baru: `test_tool_injection` (67), `test_textual_bracket_tools`
(31), `test_vault_broker_and_check_credential` (17), `test_intent_alignment`
(16), `test_tool_call_gate` (10), `test_workflow_normalizer` (9),
`test_status_wrapper` (7).

Kebersihan:
- Tidak ada credential/password yang dicetak — hanya prefix JWT + panjang.
- Semua file `tmp_*` yang dibuat sesi ini dihapus.
- `HEAD == origin/main == 2a71e48`.