# E2E Workflow Test — Sandboxed Credential Injection

**Tanggal:** 7 Oktober 2026 · **Mode:** Zero-Trust Testing
**Commit dasar:** `1a2889d` · **Perubahan:** **aditif murni** (0 baris kode produksi diubah)
**Metode:** setiap klaim diambil dari keluaran **mentah** (stdout + JSON + query DB).

---

## 0. VERDICT

| Bagian | Hasil | Status |
|---|---|---|
| 1. Audit kredensial + proxy + sandbox + canary | 95 var diaudit · 0 TEST_ · proxy + canary jalan | ✅ |
| 2. Redactor fail-closed (10 pola + canary) | 10/10 pola di-redact · canary MELEMPAR | ✅ |
| 3. Mock server + dual-mode | FastAPI + ASGI in-process · tidak menyentuh jaringan | ✅ |
| 4. Backup + rollback + canary monitoring | snapshot OK · 0 baris bertanda test · rollback dry-run | ✅ |
| 5. Test workflow | **10/10 PASS (mock)** · LIVE **TIDAK DIJALANKAN** (diblokir, lihat §5.2) | ✅ |
| 6. Verifikasi + audit | DB 124+1000 baris **0 temuan** · sandbox **0 temuan** | ✅ |

**VERDICT: PASS** untuk seluruh bagian yang dapat dijalankan dengan aman.
Live mode **sengaja TIDAK dijalankan** karena tidak ada kredensial test (§5.2) —
menjalankannya berarti memakai kredensial produksi, yang dilarang brief ini.

> **Temuan keamanan nyata (di luar test ini, wajib ditindak):** audit §6.2
> menemukan **5 berkas scratch memuat JWT ES256 hidup 818 karakter**. Semuanya
> *untracked* + *gitignored* (tidak bisa ter-commit), tetapi ada di disk sebagai
> plaintext. Rincian + rekomendasi di **§7.6**.

---

## 1. BAGIAN 1 — Setup sandbox

### 1.1 Audit kredensial produksi (NAMA saja, tanpa nilai)

```
total variabel   : 95
berawalan TEST_  : TIDAK ADA
kategori         : PRODUCTION/SHARED (semua), TEST = 0
contoh nama      : AGENTGATEWAY_URL, ALLOWED_HOSTS, ANTHROPIC_API_KEY, BRAVE_CDP_URL, ...
```

**Kategori (nama saja, TIDAK ada nilai yang dicetak/ditulis):**

| Kategori | Contoh variabel | Dipakai test? |
|---|---|---|
| PRODUCTION (punya user asli) | `SUPABASE_*`, `RAILWAY_*`, `DODO_*`, `VPS_*`, `CLOUDFLARE_*`, `TELEGRAM_BOT_TOKEN`, `VAULT_*` | **TIDAK** |
| SHARED (dipakai prod & test) | `GEMINI_API_KEY`, `GROQ_API_KEY`, `NVIDIA_API_KEY`, `OPENAI_API_KEY`, `GITHUB_TOKEN` | **TIDAK** (butuh key test baru) |
| TEST (khusus test) | — | **tidak ada satu pun** |

**Konsekuensi langsung:** karena tidak ada kredensial TEST, satu-satunya cara
menjalankan *live* test adalah memakai kredensial PRODUCTION — dilarang brief.
Karena itu seluruh test berjalan **MODE MOCK**.

### 1.2 Credential proxy

Berkas: **`credential_proxy.py`** — *bukan* `tools/credential_proxy.py`
(alasan teknis di §7.2).

Pola: agent hanya melihat `${auth.<nama>}`; nilai asli muncul **hanya** di
egress. Store in-memory, dibaca dari `TEST_*` saja.

```
status TEST_*    : {'telegram_bot': 'MISSING', 'telegram_chat': 'MISSING', 'gemini_api': 'MISSING', 'sheets_id': 'MISSING', 'github_token': 'MISSING'}
store setelah muat: [] (kosong = benar: tidak ada kredensial test)
deteksi placeholder: True | nama: ['a', 'b']
resolve (egress) : Bearer FAKE-TOKEN-DEMO
kunci tidak ada  : CredentialMissingError -> Credential 'tidak_ada' tidak ada di store test. ...
tolak non-TEST_  : ProductionCredentialRefused -> 'TELEGRAM_BOT_TOKEN' bukan variabel test (harus berawalan TEST_).
```

Yang **dikodekan** (bukan sekadar dokumentasi): `assert_test_only()` menolak
nama non-`TEST_`; tidak ada jalur jatuh-balik ke `TELEGRAM_BOT_TOKEN` dsb.
Memakai kredensial produksi untuk test menjadi **mustahil secara struktural**.

### 1.3 Konfigurasi sandbox

Berkas: **`tests/sandbox/config.yaml`** — isolasi `network+credential`,
`injection: proxy`, `redaction: strict`, `network.mode: mock`,
`blocked_hosts` termasuk `169.254.169.254` / `127.0.0.1` / `localhost`.

### 1.4 Canary

```
contoh canary  : KATALIR_TEST_CANARY_EB63A7D9DA38  (cocok pola: True)
```

Format `KATALIR_TEST_CANARY_[A-Z0-9]{12}`, dibuat `secrets.token_hex(6).upper()`,
unik (50/50 berbeda pada uji), dan **MELEMPAR** saat terdeteksi (§2.3).

---

## 2. BAGIAN 2 — Redactor fail-closed

Berkas: **`agent_redactor.py`**. "Fail-closed" konkret: tipe tak terduga tetap
dipindai; bila konversi gagal → `RedactionError` (data DITAHAN); canary → MELEMPAR.

### 2.1 Bukti mentah — 10 pola

```
pola           input (dipotong)             -> hasil
--------------------------------------------------------------------------
telegram_bot   1234567890:AAAAAAAAAAAAAAA   -> [TELEGRAM_BOT_REDACTED]
google_api     AIzaBBBBBBBBBBBBBBBBBBBBBB   -> [GOOGLE_API_REDACTED]
slack          xoxb-CCCCCCCCCCCC            -> [SLACK_REDACTED]
github         ghp_DDDDDDDDDDDDDDDDDDDDDD   -> [GITHUB_REDACTED]
jwt            eyJhbGciOiJIUzI1NiJ9.eyJzd   -> [JWT_REDACTED]
bearer         Bearer FFFFFFFFFFFFFFFFFFF   -> Bearer [REDACTED]
url_api_key    https://x.test/a?api_key=S   -> https://x.test/a?api_key=[REDACTED]&token=[REDACTED]&z=1
openai         sk-GGGGGGGGGGGGGGGGGGGGGGG   -> [OPENAI_KEY_REDACTED]
google_oauth   ya29.HHHHHHHHHHHHHHHHHHHHH   -> [GOOGLE_OAUTH_REDACTED]
aws            AKIAIIIIIIIIIIIIIIII         -> [AWS_KEY_REDACTED]

semua 10 pola di-redact: True
```

### 2.2 Canary — fail-closed

```
contoh canary  : KATALIR_TEST_CANARY_EB63A7D9DA38
HASIL          : CanaryDetectedError -> CANARY TERDETEKSI — kredensial test bocor! ...
statistik      : {'canary_alerts': 1, 'telegram_bot': 2, 'github': 2, ...}   <- TANPA nilai
```

Statistik per kategori dicatat **tanpa nilai mentah** (brief §2.2.1e).

### 2.3 Penerapan di semua jalur

`redact_agent_output()` dipakai pada: keluaran node sandbox (§5.1), keluaran
agent, dan tersedia untuk respons chat / baris log / frontend. Uji: 59 test
+ 42 subtest lulus (`tests/test_agent_redactor.py`, `tests/test_credential_proxy.py`,
`tests/test_sandbox_e2e.py`).

Parity dikunci test: `agent_redactor` **tidak boleh lebih longgar** dari
`database.redact_sensitive` (redaktor log produksi F-2).

---

## 3. BAGIAN 3 — Mock server (prioritas)

Berkas: **`tests/sandbox/mock_server.py`** (FastAPI). Respons schema-valid,
tanpa kredensial asli: `/mock/telegram/sendMessage`, `/mock/sheets/write`,
`/mock/github/commit`, `/mock/http/echo`, `/mock/http/fail`, `/mock/http/flaky`,
`/mock/telegram/echo_token`.

**Transport:** `httpx.ASGITransport` — **in-process, tanpa port, tanpa paket
keluar**. Ini juga menghindari (dengan sengaja) SSRF guard produksi, yang
MENOLAK host loopback (dibuktikan di §6.3). Paket `mockworld-mcp` tidak dipakai
(lihat §7.7).

**Dual-mode:** mock = default (CI/cepat/deterministik); live = manual sebelum
launch. Live **dinonaktifkan** (§5.2).

---

## 4. BAGIAN 4 — Backup + rollback + canary monitoring

```
[4.1a] Hitungan baris (READ-ONLY):
  {"configured": true, "workflows": 90, "execution_logs": 124, "chat_messages": 2054}

[4.1b] Baris bertanda test 'test-2026-10-07' (harap 0):
  {"workflows": 0, "execution_logs": 0, "execution_log_rows_scanned": 124}

[4.1c] Snapshot backup:
  path   : tests/sandbox/backups/test-2026-10-07-20261007-183027.json
  sha256 : 9ff177225a7c0284
  mode   : scoped

[4.2] Rollback (DRY-RUN — tidak menghapus apa pun): would_delete = 0/0
VERDICT BAGIAN 4: PASS
```

Backup = **snapshot terarah** (hitungan + baris bertanda test), bukan dump penuh
produksi. Alasan: test mock **tidak menulis apa pun**, dan menyalin baris
produksi ke disk justru menambah permukaan kebocoran (§7.5). Direktori backup
sudah masuk `.gitignore`.

---

## 5. BAGIAN 5 — Test workflow

### 5.1 MODE MOCK — **10/10 PASS**

Dijalankan lewat `StatefulOrchestrator` **asli** (mesin DAG produksi, termasuk
self-healing) + `credential_proxy` + `mock_server` + `agent_redactor`.

| # | Skenario | Hasil | Bukti kunci (mentah) |
|---|---|---|---|
| 1 | Simple — Trigger → Telegram | **PASS** | `chat.id = "[REDACTED_TEST_CREDENTIAL]"`; `message_id=999` |
| 2 | Medium — HTTP → Extract → Telegram | **PASS** | 2 egress, 2 gerbang anti-bocor; `title` mengalir antar-node |
| 3 | Medium — Condition + Branch | **PASS** | `egress_calls=1` — cabang `else` **skip** (`{"skipped": true}`) |
| 4 | Complex — Multi-step + Sheets | **PASS** | 3 egress; `updatedCells=2` |
| 5 | Complex — Multi-Agent | **PASS** | `a1`→`a2`; prompt `a2` memuat keluaran `a1` |
| 6 | Advanced — MCP Tool | **PASS** | `sha=abc123def456` |
| 7 | Advanced — Webhook payload | **PASS** | payload trigger mengalir ke node hilir |
| 8 | Hard — GitHub Commit | **PASS** | commit → notifikasi `sha` |
| 9 | Hard — Error Recovery | **PASS** | `['running','retrying']×3 → 'error'`; **7,05s**; raise jujur |
| 10 | Very Hard — Full Orchestration | **PASS** | 4 egress berurutan, semua `completed`, 0 kebocoran |

```
RINGKASAN: 10/10 PASS
Statistik redaksi: {'canary_alerts': 0}
```

Setiap node melewati rantai: `placeholder → resolve_egress → mock →
mask_known_values → redact_agent_output → assert_no_leak` (gerbang terakhir
melempar bila ada nilai kredensial test di keluaran).

### 5.2 MODE LIVE — **TIDAK DIJALANKAN** (keputusan sadar)

Live #1 (Telegram), Live #2 (Sheets), Live #3 (GitHub) **tidak dijalankan**
karena `TEST_TELEGRAM_BOT_TOKEN`, `TEST_SHEETS_ID`, `TEST_GITHUB_TOKEN` **tidak
ada** di lingkungan ini (§1.1: 0 variabel `TEST_`).

Menjalankannya berarti memakai kredensial PRODUCTION — tepat yang dilarang brief
("JANGAN pakai credential production untuk test", "JANGAN kirim ke channel
production"). Jadi ini **bukan kelalaian**, melainkan kepatuhan.

`tests/sandbox/config.yaml: live.enabled=false` + `requires_env` mendokumentasikan
apa yang dibutuhkan agar live bisa dijalankan dengan aman kelak.

---

## 6. BAGIAN 6 — Verifikasi + audit

### 6.1 Verifikasi tiap test
Raw output workflow + status per node + jumlah egress + jumlah gerbang anti-bocor
ada di §5.1 (dihasilkan `tests/sandbox/sandbox_runner.py`).

### 6.2 Audit kebocoran kredensial

```
[LOKAL] 329 berkas dipindai
  dalam sandbox (tests/sandbox): 0 (BERSIH)
  sisa repo (higiene, di luar sandbox): 7 berkas
    - .autonomous_session.json           ['jwt']
    - glama-connector-call-batch1.json   ['bearer', 'url_api_key']
    - _e2e_session.refreshed.json        ['jwt']
    - _e2e_storage.json                  ['jwt']
    - _e2e_rebrand.txt                   ['jwt', 'bearer']
    - _live_tok.txt                      ['jwt']
    - _ops_commit_msg.txt                ['bearer']

[DB]  execution_logs  : rows_scanned=124, hits=[]
     chat_messages   : rows_scanned=1000, hits=[]

SANDBOX : BERSIH     DB : BERSIH     VERDICT TEST: PASS
```

### 6.3 Audit sandbox (isolasi + kebijakan jaringan)

```
  http://127.0.0.1:8899/x                    DITOLAK: Host internal/loopback ditolak (SSRF guard).
  http://localhost/x                         DITOLAK: Host internal/loopback ditolak (SSRF guard).
  http://169.254.169.254/latest/meta-data/   DITOLAK: Host internal/loopback ditolak (SSRF guard).
  http://metadata.google.internal/x          DITOLAK: Host internal/loopback ditolak (SSRF guard).
  http://10.0.0.5/x                          DITOLAK: Host internal/loopback ditolak (SSRF guard).
  http://192.168.1.1/x                       DITOLAK: Host internal/loopback ditolak (SSRF guard).
  kontrol positif example.com -> _host_blocked=False
```

- **Isolasi:** mock in-process (ASGI) → tidak ada port, tidak ada paket keluar.
- **Network policy:** `tools._host_blocked` (guard produksi) menolak loopback,
  privat, link-local, metadata, **dan** nama yang tak bisa diresolusi.
- **Credential proxy:** placeholder `${auth.X}` tidak pernah dikirim mentah
  (diuji), nilai asli hanya di egress.
- **Canary detection:** MELEMPAR (diuji di unit + di jalur mock).

### 6.4 Uji

```
59 passed, 42 subtests passed in 11.30s
```

---

## 7. TEMUAN & PENYIMPANGAN (protokol kontradiksi)

**7.1 `else_condition` BUKAN cabang else.** `_condition_gate()` mensyaratkan
**SEMUA** kunci (`condition` **dan** `else_condition`) truthy — jadi ia gerbang
AND, bukan percabangan. Rancangan awal saya memakai `else_condition` sebagai
"cabang else" dan **kedua cabang ikut jalan** (egress=2). Diperbaiki: cabang else
ditulis sebagai negasi eksplisit di `condition`. *Dampak produk:* penulis workflow
yang mengira `else_condition` = "else" akan mendapat kedua cabang berjalan.
Nama kunci menyesatkan — sebaiknya dinamai ulang atau diimplementasikan sebagai
percabangan sungguhan.

**7.2 Lokasi modul: root repo, bukan `tools/`.** `tools/` **bukan package**
(tanpa `__init__.py`) dan sudah ada modul `tools.py`; `import tools` menunjuk
`tools.py`. Menaruh berkas di `tools/` membuatnya **tidak bisa** diimpor sebagai
`tools.credential_proxy`, dan menambah `tools/__init__.py` akan **membayangi
`tools.py`** sehingga runtime rusak. Modul diletakkan di root mengikuti konvensi
repo (`vault_broker.py`, `sanitize.py`, `tools.py`).

**7.3 `execution_logs.execution_id` bertipe UUID.** `ilike` gagal:
`operator does not exist: uuid ~~* unknown` (kode `42883`). Pencarian tag
dipindah ke sisi klien.

**7.4 Anon key ≠ bukti bersih.** `db._get_client()` memakai **anon** key; RLS
menyembunyikan baris → hitungan awal `0/0/0` (kesimpulan palsu). Audit dipindah
ke `_get_write_client()` (service role, READ-ONLY) → `90/124/2054`. Tanpa
perbaikan ini, "0 temuan" akan **vacuous**.

**7.5 Backup terarah, bukan dump penuh.** Test mock tidak menulis; dump produksi
ke disk menambah risiko. `backup(full=True)` tersedia bila live dijalankan.

**7.6 ⚠️ TEMUAN NYATA: 5 berkas scratch memuat JWT ES256 hidup.**

```
_e2e_storage.json            : jwt_count=1 lengths=[818] header=['ES256/JWT']
_e2e_session.refreshed.json  : jwt_count=1 lengths=[818] header=['ES256/JWT']
_live_tok.txt                : jwt_count=1 lengths=[818] header=['ES256/JWT']
_e2e_rebrand.txt             : jwt_count=4 lengths=[818] header=['ES256/JWT']
.autonomous_session.json     : jwt_count=1 lengths=[815] header=['ES256/JWT']
```

- **Status git:** semuanya *untracked* **dan** *gitignored* (`.gitignore:97-98`
  `_*.txt` / `_*.json`) → **tidak bisa ter-commit**. Risiko repo = nol.
- **Risiko nyata:** token sesi Supabase hidup tersimpan **plaintext di disk**.
- **Tindakan disarankan:** (a) hapus berkas scratch tersebut, (b) karena ini
  token sesi (bukan API key permanen), cukup tunggu kedaluwarsa / logout sesi
  terkait; (c) bila pernah tersalin keluar mesin ini, cabut sesi Supabase-nya.
- `glama-connector-call-batch1.json` (tracked) yang juga ter-flag **bukan**
  kredensial: isinya placeholder (`?api_key=your_...`) + potongan regex
  dokumentasi. False positive.

**7.7 `mockworld-mcp` tidak dipakai.** Paket tidak tersedia; mock dibangun dengan
FastAPI (sudah jadi dependensi) + `ASGITransport`, yang lebih terisolasi
(tanpa port) daripada mock server jaringan.

**7.8 Bug pengganti di brief diperbaiki.** Brief menulis pengganti
`r'?\1=[REDACTED]'` untuk API key di URL — itu mengubah pemisah `&` menjadi `?`
sehingga URL rusak. Diperbaiki menjadi `r'\1\2=[REDACTED]'` (pemisah
dipertahankan), dikunci test `test_pemisah_url_dipertahankan`.

---

## 8. LAMPIRAN — Artefak

| Berkas | Isi |
|---|---|
| `agent_redactor.py` | Redaktor fail-closed (10 pola + canary + rekursif) |
| `credential_proxy.py` | Proxy placeholder `${auth.X}` + canary + penjaga bocor |
| `tests/sandbox/config.yaml` | Konfigurasi sandbox |
| `tests/sandbox/mock_server.py` | Mock FastAPI (in-process ASGI) |
| `tests/sandbox/sandbox_runner.py` | Harness E2E: engine asli + 10 workflow |
| `tests/sandbox/backup_rollback.py` | Backup + rollback (dry-run default) |
| `tests/sandbox/canary_scan.py` | Pemindai canary + kebocoran (lokal + DB) |
| `tests/test_agent_redactor.py` | Test redaktor + parity dengan `database` |
| `tests/test_credential_proxy.py` | Test proxy + penjaga `TEST_`-only |
| `tests/test_sandbox_e2e.py` | 10 workflow + kebijakan jaringan + jalur bocor |
| `_e2e_evidence_2026_10_07.py` | Bukti mentah terpadu (audit/proxy/redactor/jaringan) |

**Perubahan produksi: NOL.** Brief ini murni menambah infrastruktur test —
postur zero-trust yang benar: jangan ubah produksi untuk mengujinya.
