# Audit Keamanan Katalir — Laporan Lengkap

- **Tanggal:** 2026-09-30
- **Target:** `https://katalir.de5.net` · `https://web-production-dc90b.up.railway.app`
- **Database:** Supabase `qmukkphwaajzbqjrcvaz`, region `aws-0-ap-southeast-1`
- **Alat:** gitleaks 8.30.1 · pip-audit · npm audit 11.13.0 · psycopg2 2.9.13 · curl

> **Tidak ada nilai credential di laporan ini** — hanya nama key, lokasi, panjang.

---

## ⚠️ RINGKASAN EKSEKUTIF — 1 CRITICAL terbuka

| # | Temuan | Severity | Status |
|---|---|---|---|
| **R-1** | `execution_logs`/`executions`/`workflows` terbaca **anonim** (85 baris) | 🔴 **CRITICAL** | **OPEN — butuh approval** |
| C-1 | CVE-2026-48710 Starlette BadHost | 🔴 HIGH (6.5) | ✅ **MITIGATED** (PoC terbukti) |
| C-2 | Venv lokal ≠ produksi (0.52.1 vs ~0.40–0.41) | 🟠 MEDIUM | ✅ **DOCUMENTED** |
| S-1 | `SUPABASE_DB_PASSWORD` bocor di git history | 🔴 P0 | ⏳ **Fase F** (rotasi) |
| N-1 | npm `postcss` → butuh **Next 16** (major) | 🟠 HIGH | ⚠️ **ACCEPTED RISK** |
| N-2 | npm 5 HIGH lain (rantai `wrangler`) | 🟠 HIGH | 📋 deferred (tool deploy) |
| H-1 | CSP `report-only`, belum `enforce` | 🟡 MEDIUM | ⚠️ **ACCEPTED** |

---

## BAGIAN A (retry) — Gitleaks Full History: ✅ DITERIMA

```
$ git rev-list --all --count                        -> 1584
$ gitleaks git . --log-opts="--all"                -> 793 commits scanned.
$ gitleaks git . --log-opts="--all --full-history" -> 793 commits scanned.
$ gitleaks git .            (default)              -> 793 commits scanned.
LEAKS_FOUND: 98  (96 vps_ssh_test.py + 2 test-jwt.txt.txt)
```

**Akar kontradiksi 793 ≠ 1584:**

```
$ git log --all -p -U0 --format=COMMIT:%H
total blocks: 1584
  commits with EMPTY diff     : 790   <- refs/cline/checkpoints/*,
  commits with non-empty diff : 794      mayoritas "tree identik dgn parent"
793 = 794 - 1 (commit saya sendiri, ikut terhitung)
```

**Bukti kelengkapan independen** (`scripts/security/verify_blob_coverage.py`
— memindai **setiap** blob, tidak bergantung pada gitleaks):

```
objects_total=5533
blobs_total=1799
blob_findings_total=8
  1 JWT          vps_ssh_test.py
  2 JWT          test-jwt.txt.txt / test-jwt.txt
  1 DODO_WEBHOOK .env.example            (placeholder whsec_xxxx)
  4 IP_PASSWORD  gen-test-jwt.py, _e2e_setup.mjs x2  (fixture user uji)
```

**BLOB_COVERAGE = 1799/1799 = 100%.** 98 temuan menyempit ke **2 blob rahasia
unik** (satu diulang di 96 commit); 6 sisanya false positive.

**Riwayat yang TIDAK dilakukan:** tidak ada `git filter-repo`, tidak ada
`rebase`, tidak ada `force push`, tidak ada scan ulang.


---

## BAGIAN B — Supabase RLS: 🔴 1 CRITICAL (OPEN)

### B.1 Katalog

```
$ python scripts/security/audit_rls.py
=== pg_tables (schemaname='public'): 16 ===
chat_messages True   chat_sessions True   community_earnings True
community_integrations True   execution_logs True   executions True
payment_events True   roster_cache True   user_balances True
user_integrations True   user_mcp_instances True   user_preferences True
user_usage True   user_vault True   users True   workflows True
=== pg_policies (schemaname='public'): 10 ===
```

**`RLS_TABLES_TOTAL=16`, `RLS_OFF=none`** — RLS aktif di **semua** tabel.

### B.2 Uji bypass (`SET ROLE anon` → `SELECT count(*)`)

```
tablename              rls   pol  rows_visible_as_anon
chat_messages          True  0    0
chat_sessions          True  0    0
community_earnings     True  1    0
community_integrations True  3    0
execution_logs         True  1    44      <-- BOCOR
executions             True  1    21      <-- BOCOR
payment_events         True  0    0
roster_cache           True  0    0
user_balances          True  0    0
user_integrations      True  0    0
user_mcp_instances     True  1    0
user_preferences       True  1    0
user_usage             True  0    0
user_vault             True  0    0
users                  True  0    0
workflows              True  2    20      <-- BOCOR
```

**`RLS_MISCONFIGURED=3` → `RLS_FIXED=0` (menunggu approval)**

### B.3 Akar masalah — `qual=true` + `cmd=ALL` + `roles={public}`

```
execution_logs | Izinkan semua akses ke execution_logs | ALL | qual=true
executions     | Izinkan semua akses ke executions     | ALL | qual=true
workflows      | Allow public read and write            | ALL | qual=true
--- aman: difilter dengan benar ---
user_mcp_instances | users manage own mcp instances | qual=(auth.uid() = user_id)
user_preferences   | user_own_prefs                 | qual=(user_email = auth.jwt()->>'email')
workflows          | workflows_owner_all            | qual=(auth.uid() = user_id)
```

Tiga policy pertama memberi **CRUD penuh untuk siapa pun**, termasuk `anon`.

### B.4 Verifikasi independen via REST (path serangan nyata)

```
GET /rest/v1/execution_logs?select=*&limit=1  -> 200  (execution_id, node_id, status)
GET /rest/v1/executions?select=*&limit=1      -> 200  (workflow_id, result, created_at)
GET /rest/v1/workflows?select=*&limit=1       -> 200  (name, description, flow_data)
GET /rest/v1/users?select=*&limit=1           -> 200  0 baris
GET /rest/v1/user_vault?select=*&limit=1      -> 200  0 baris
```

`SUPABASE_KEY` **sudah publik** lewat `NEXT_PUBLIC_SUPABASE_ANON_KEY` di bundle
browser. Jadi `flow_data` (blueprint workflow user) dan `executions.result`
(output LLM, bisa berisi data user) **terbaca tanpa login**.

### B.5 Kenapa fix-nya aman secara fungsional

```
$ grep "from('workflows')|from('executions')|from('execution_logs')" nexus-frontend/src/**
  (0 hasil — frontend TIDAK accessed tabel ini)
$ grep -n SERVICE_ROLE database.py
L41: # Service_role key: bypasa RLS
L46: or (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
```

Backend menulis lewat `service_role` (bypass RLS). Menghapus policy longgar
**tidak** memutus alur aplikasi.

### B.6 SQL fix (disiapkan, **belum** dieksekusi)

```sql
-- Policy Postgres di-OR-kan: MENAMBAH policy ketat tanpa DROP policy longgar
-- = tidak mengubah apa pun. Fix wajib DROP.
DROP POLICY "Izinkan semua akses ke execution_logs" ON public.execution_logs;
DROP POLICY "Izinkan semua akses ke executions"     ON public.executions;
DROP POLICY "Allow public read and write"           ON public.workflows;

CREATE POLICY execution_logs_authenticated_only ON public.execution_logs
  FOR ALL TO authenticated
  USING ((auth.jwt() ->> 'email') IS NOT NULL)
  WITH CHECK ((auth.jwt() ->> 'email') IS NOT NULL);
-- executions: policy serupa.
-- workflows: JANGAN buat policy baru — `workflows_owner_all` yang sudah ada
-- (auth.uid() = user_id) sudah benar, cukup hapus yang longgar.
```


---

## BAGIAN C — CVE-2026-48710 (Starlette BadHost): ✅ MITIGATED

Detail lengkap + PoC: `docs/security/cve-investigation.md`.

| Item | Nilai |
|---|---|
| Affected | `starlette <= 1.0.0` · CVSS 6.5 · CWE-444/1289 |
| Patched | `1.0.1` (X41 D-Sec / OSTIF) |
| Produksi | `fastapi==0.115.6` → `starlette~0.40–0.41` (**rentan**) |
| Venv lokal | `fastapi 0.128.8` + `starlette 0.52.1` (**rentan**) |

### C.1 PoC BEFORE → AFTER

```
BEFORE  middleware chain: [0] CORSMiddleware
        Host=evil.com/health?x= -> HTTP 200      (TIDAK TERBLOKIR)
AFTER   middleware chain: [0] TrustedHostMiddleware / [1] CORSMiddleware
        Host=evil.com/health?x= -> HTTP 400  'Invalid host header'
        Host=localhost          -> HTTP 200     (bukan 400)
```

### C.2 Kenapa urutan middleware dibalik dari yang tertulis di prompt

`app.add_middleware()` pada Starlette **mendasarik** (prepend). Bukti:

```
add TrustedHost lalu CORSMiddleware -> [0]=CORSMiddleware       (innermost)
add CORSMiddleware lalu TrustedHost -> [0]=TrustedHostMiddleware (outermost) OK
```

"Teratas" = **berjalan pertama** = ditambahkan **terakhir**. Instruksi
"letakkan sebelum CORS" akan membuatnya tidak efektif.

### C.3 Webhook tidak break

```
/api/payments/dodo-webhook (Host=railway) -> 405   (route ada, method salah)
/api/payments/dodo-webhook (Host=katalir) -> 405
/oauth/google/callback   (Host=railway)   -> 302   (redirect normal)
/webhook/{id}            (Host=railway)   -> 405
/health                  (Host=127.0.0.1) -> 200
```

Host pengirim webhook = domain Katalir (Dodo memanggil URL Katalir), bukan
domain Dodo — jadi tetap di allowlist.

### C.4 Fail-secure terverifikasi

```
ALLOWED_HOSTS=''   -> RuntimeError: ALLOWED_HOSTS wajib diisi...

---

## BAGIAN D — Frontend: ✅ BERSIH

```
$ grep -rn "dangerouslySetInnerHTML"  nexus-frontend/src/**   -> 0
$ grep -rn "eval("                   nexus-frontend/src/**   -> 0
$ grep -rn "innerHTML"               nexus-frontend/src/**   -> 0
$ grep -rn "new Function"            nexus-frontend/src/**   -> 0
$ grep -rn "document.write"          nexus-frontend/src/**   -> 0

$ grep -o "NEXT_PUBLIC_[A-Z_]+" nexus-frontend/src/** | sort | uniq -c
  NEXT_PUBLIC_API_URL               1
  NEXT_PUBLIC_SUPABASE_URL          1
  NEXT_PUBLIC_SUPABASE_ANON_KEY     1     <- memang public by design
  NEXT_PUBLIC_DODO_CHECKOUT_URL     5
```

`FRONTEND_ISSUES=0`, `FRONTEND_FIXED=0`.

Token di browser: `sessionStorage` hanya untuk state UI non-sensitif
(`useBack.ts` flag navigasi internal, `auth-actions.ts` URL return,
`LanguageSwitcher` preferensi bahasa). **Tidak ada token disimpan manual** —
auth dikelola Supabase SDK.

CSRF: API memakai `Authorization: Bearer` (bukan cookie session), sehingga tidak
rentan CSRF klasik.

---

## BAGIAN E — Headers / CORS / Dependencies

### E.1 Security headers (produksi)

```
$ curl -I https://katalir.de5.net/
HTTP/1.1 200 OK
x-frame-options: DENY                                            OK
Strict-Transport-Security: max-age=31536000; includeSubDomains   OK
content-security-policy-report-only: default-src 'self'; ...     report-only
permissions-policy: camera=(), microphone=(), geolocation=()     OK
referrer-policy: strict-origin-when-cross-origin                OK
x-content-type-options: nosniff                                 OK
```

`HEADERS_MISSING` = `enforce-CSP` (sudah `report-only` — temuan M-1 dari audit
2026-09, **ACCEPTED** menunggu optimizer production).

### E.2 CORS

```
$ curl -H "Origin: https://evil.com" .../health
  -> HTTP 200, TANPA access-control-allow-origin                OK (ditolak browser)
$ curl -H "Origin: https://katalir.de5.net" .../health
  -> HTTP 200, access-control-allow-origin: https://katalir.de5.net   OK
```

### E.3 npm audit

```
$ npm audit --json
NPM AUDIT SUMMARY: {"info":0,"low":0,"moderate":1,"high":6,"critical":0,"total":7}
```

`NPM_VULN_CRIT=0`, `NPM_VULN_HIGH=6` → `NPM_FIXED=0`, `NPM_ACCEPTED=1` (+5 deferred).

| Package | Severity | Fix | Status |
|---|---|---|---|
| `brace-expansion` | HIGH | non-major | deferred (rantai `wrangler`) |
| `miniflare` | HIGH | non-major | deferred |
| `sharp` | HIGH | non-major | deferred |
| `undici` | HIGH | non-major | deferred |
| `wrangler` | HIGH | non-major | deferred |
| `postcss` → `next` | HIGH | **`isSemVerMajor` → Next 16** | **ACCEPTED RISK** |

**Kenapa `npm audit fix` tidak dijalankan:** 5 dari 6 HIGH berasal dari rantai
tool deploy Cloudflare (`wrangler → miniflare → sharp/undici`) yang tidak ikut
production bundle; dan satu-satunya fix yang konsisten adalah menaikkan Next ke
16 — **major**, terlarang [10] dan berisiko merusak build. Tidak ada
`npm audit fix --force` yang dijalankan.

### E.4 pip-audit

```
$ pip-audit -r requirements.txt --format json -o docs/security/pip-audit-req.json
deps scanned: 138
TOTAL VULNS: 110
```

> **Catatan cakupan:** percobaan pertama **tanpa `-r`** memindai 433 paket
> *global site-packages* (termasuk `browser-use`, `hermes-agent` yang bukan
> dependency Katalir) dan melaporkan 233 temuan. Angka itu **bukan** scope
> Katalir dan sengaja tidak dipakai sebagai angka resmi.

**Bukti tak terduga yang memperkuat C.2:** `pip-audit` meresolusi dependency
dan menemukan **`starlette 0.41.3`** — persis rentang yang saya prediksi dari
`fastapi==0.115.6` → `starlette<0.42.0`. Jadi venv lokal (0.52.1) memang
**tidak** mewakili produksi (0.41.3).

Paket dengan temuan terbanyak:

| Paket | Versi | Jumlah advisory | Fix |
|---|---|---|---|
| `pillow` | 11.3.0 | 18 | 12.1.1 – 12.3.0 |
| `starlette` | 0.41.3 | 12 | 0.47.2 – **1.0.1** (termasuk BadHost) |
| `litellm` | 1.65.1 | 17 | 1.82.0 – 1.84.0 |
| `langchain-core` | 0.3.49 | 10 | 0.3.80+ |
| `streamlit` | 1.41.1 | 4 | 1.53.1+ |
| `mcp` | 1.26.0 | 3 | 1.27.2+ |
| `pytest` | 8.3.3 | 1 | 9.0.3 (major) |
| `python-dotenv` | 1.0.1 | 1 | 1.2.2 |

**`PIP_FIXED=0` — tidak ada satu pun yang di-upgrade.** Alasannya bukan
malas: `pip check` baseline sudah rusak 8+ konflik (`browser-use` vs
`anthropic`/`openai`/`groq`/`pydantic`/`requests`), dan hampir semua fix di atas
menyentuh paket yang sama (`langchain-*`, `litellm`) yang saling bergantung.
Menaikkan `pillow` 11.3.0 → 12.x saja sudah mayor, dan `pytest` → 9.0.3 juga
mayor. Menaikkan semuanya sekaligus di tengah audit tanpa ruang uji
justru **membuat** risiko regresi, bukan mengurangi.

Semua temuan pip tercatat lengkap di `docs/security/pip-audit-req.json` untuk
pekerjaan dependency-remediation terpisah.

---

## BAGIAN FIX — Ringkasan Perubahan

| Commit | Isi | Status |
|---|---|---|
| `a9b32d6` | `TrustedHostMiddleware` + `ALLOWED_HOSTS` + `tests/conftest.py` + PoC harness | ✅ Mitigasi CVE |
| (commit ini) | Laporan audit lengkap + skrip audit RLS + artefak scan | 📄 Dokumentasi |

**File produk yang diubah:** hanya `api_server.py` (penambahan middleware) dan
`.env.example` (placeholder). **Tidak ada** upgrade FastAPI / Starlette /
Next.js. **Tidak ada** rewrite git history. **Tidak ada** push.

**Regresi test:** `344 passed` — identik dengan baseline sebelum perubahan.

---

## KESIMPULAN

**Yang sudah tertutup:**
- ✅ CVE-2026-48710 — MITIGATED dengan bukti PoC before/after (200 → 400)
- ✅ Gitleaks full history — 100% cakupan blob terbukti independen
- ✅ Frontend — 0 vektor XSS, `NEXT_PUBLIC_*` bersih
- ✅ Headers & CORS — 5/6 header ada, CORS menolak origin asing
- ✅ Regresi test — nol

**Yang TERBUKA dan butuh keputusan Anda:**

1. 🔴 **R-1 (CRITICAL)** — 3 policy RLS `qual=true`/full-CRUD untuk `anon`,
   membuka 85 baris (`workflows.flow_data`, `executions.result`) ke siapa pun
   yang punya anon key. **Fix butuh `DROP POLICY` = perubahan schema produksi,
   di luar otorisasi [10].** SQL sudah siap di §B.6.
2. 🔴 **S-1 (P0)** — `SUPABASE_DB_PASSWORD` + `VPS_PASSWORD` masih perlu
   rotasi (Fase F, di luar prompt ini).
3. 🟠 **110 advisory pip** — perlu remediation terpisah dengan ruang uji.
4. 🟠 **Upgrade FastAPI/Starlette** — P0 post-launch (`ROADMAP-BLITZ.md`).



ALLOWED_HOSTS='*'  -> RuntimeError: ALLOWED_HOSTS tidak boleh berisi '*'
```

### C.5 Regresi test (ditemukan, di-root-cause, diperbaiki)

| Run | Hasil |
|---|---|
| Baseline (`git stash api_server.py`) | **344 passed, 0 failed** |
| Setelah middleware, sebelum fix | **44 failed, 300 passed** |
| Setelah fix | **344 passed, 0 failed** OK |

Dua root cause: (1) `TestClient` default host `testserver` tidak di allowlist;
(2) `scripts/ai_tools_mcp.py:20` `load_dotenv(override=True)` menimpa nilai dari
conftest (`ai_tools+community` = 8 failed; `community` sendiri = 10 passed).

### C.6 Upgrade FastAPI/Starlette — DEFERRED

`fastapi==0.115.6` → `starlette<0.42.0`. Cap baru dipecah di fastapi ~0.13x
(`starlette>=0.46.0` tanpa upper cap) → lompat **27 versi minor**, di atas
`pip check` yang sudah rusak 8+ konflik. Tercatat di `ROADMAP-BLITZ.md` sebagai
**P0 post-launch**.

> **Kenapa belum dieksekusi:** `DROP POLICY` = perubahan schema produksi,
> sedangkan [10] hanya mengizinkan "tambah RLS policy". Butuh approval.
