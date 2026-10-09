# Keputusan Arsitektur Framework Connector Katalir

> **FASE 1 brief "2000+ FITUR INTEGRASI KATALIR"** — riset 5 repo terbaik,
> lalu putuskan arsitektur.
>
> **Prasyarat yang dipatuhi:** `docs/connector-existing-audit.md`. Setiap
> keputusan di bawah **dibatasi** oleh temuan audit: katalog sudah berisi
> **25.925 entri**, 8 sumber, dedup engine, 17 endpoint, UI `/integrations`.
> Arsitektur yang dipilih **harus memperluas** itu, bukan menggantinya.
>
> Tanggal riset: 9 Okt 2026. Standar: Oktober 2026.

---

## 1. Ringkasan 5 repo yang dibaca

| # | Repo | Bintang | Yang dipelajari | Sumber |
|---|---|---|---|---|
| 1 | `activepieces/activepieces` | ~20k | **Pieces Framework** — TS type-safe, 1 class `Piece` per integrasi, `createPiece({displayName, auth, actions[], triggers[]})`, `.metadata()` menghasilkan manifest | `packages/pieces/framework/src/lib/piece.ts` (dibaca verbatim) |
| 2 | `ComposioHQ/composio` | ~30k | **Toolkit + AuthConfig + ConnectedAccount + Session** — auth dikelola platform, tool dipanggil dengan kredensial disuntik server | `docs.composio.dev/kb/topic/tools-actions-and-execution` |
| 3 | `airbytehq/airbyte` | ~19k | **Declarative Manifest Framework** — satu YAML mendeskripsikan retriever/requester/authenticator/paginator; 50+ connector produksi dari format yang sama | `docs.airbyte.com/.../understanding-the-yaml-file/reference` (316 KB, dibaca) |
| 4 | `oomol-lab/open-connector` | ~6k | **Auth gateway 1500+ SaaS → MCP** — katalog aksi dengan `noAuthRunnable`, `locally_executable`, `credential_free`, `call_verified` | `github.com/oomol-lab/open-connector` + `openconnector_actions.json` lokal |
| 5 | **Katalir ADR-003 sendiri** | — | Keputusan lama proyek ini soal registry/dedup/verifikasi | `docs/architecture/` + `mcp_registry.py` |

### Temuan penting dari tiap repo

**1. Activepieces — `Piece` adalah objek, manifest adalah turunannya.**
`piece.ts` yang dibaca verbatim menunjukkan pola ini:

```ts
export class Piece<PieceAuth ...> {
  private readonly _actions: Record<string, Action> = {};
  private readonly _triggers: Record<string, Trigger> = {};
  constructor(public readonly displayName, public readonly logoUrl, ...) { ... }

  metadata(): BackwardCompatiblePieceMetadata {
    return { displayName, logoUrl, actions: this._actions, triggers: this._triggers,
             categories, description, authors, auth, minimumSupportedRelease,
             maximumSupportedRelease, deprecated, contextInfo };
  }
}
export const createPiece = <...>(params: CreatePieceParams<PieceAuth>) => {
  if (params.auth && Array.isArray(params.auth)) {
    // "Auth properties must be unique by type"
  }
  return new Piece(...);
};
```

**Pelajaran yang diambil:** (a) definisi connector = **satu objek deklaratif**,
bukan kode imperatif per integrasi; (b) `metadata()` adalah **proyeksi** dari
objek itu — manifest tidak pernah ditulis tangan, sehingga tidak bisa drift;
(c) ada **versi minimum yang didukung** (`minimumSupportedRelease`) dan flag
`deprecated` per piece — connector mati ditandai, bukan dihapus diam-diam;
(d) auth boleh berupa **array** (multi-metode) tetapi harus unik per tipe.

**2. Composio — pemisahan tegas antara *auth config* dan *connected account*.**
Dari docs yang dibaca: `Session` men-scope *user + tools + toolkits + auth +
MCP state*. Ada `Custom Tools and Toolkits` (tool lokal berjalan in-process di
samping tool remote), `Proxy execute` (panggil endpoint apa pun pada toolkit,
Composio menyuntikkan kredensial), `Shared connections` (satu connected account
dipakai banyak user via ACL), dan **`Create Read-Only and Restricted Sessions`**
(membatasi akses tool via tag, allowlist eksak, OAuth scope).

**Pelajaran yang diambil:** (a) **kredensial bukan milik connector, melainkan
milik *koneksi* per-user** — ini yang membuat 2000 connector tetap aman
multi-tenant; (b) **tool lokal + tool remote harus bisa hidup di sesi yang
sama**; (c) **pembatasan harus jadi kelas satu** (tag/allowlist/scope), bukan
tambalan; (d) `Proxy execute` = pola yang memungkinkan connector "tanpa kode
eksekusi" tetap jalan.

**3. Airbyte — YAML deklaratif dengan kosakata komponen yang ketat.**
Referensi 316 KB yang dibaca memberi kosakata lengkap dan **tertutup**:

```
DeclarativeSource: check | streams | dynamic_streams | version | schemas | spec
                   concurrency_level | api_budget | stream_groups | metadata | description
DeclarativeStream: retriever | schema_loader | primary_key | name | transformations
Retriever:         SimpleRetriever | AsyncRetriever | CustomRetriever
Requester:         HttpRequester | CustomRequester
Authenticator:     NoAuth | ApiKeyAuthenticator | BearerAuthenticator
                   BasicHttpAuthenticator | SelectiveAuthenticator
                   RateLimitedMultipleTokenAuthenticator | OAuthAuthenticator
                   JwtAuthenticator | SessionTokenAuthenticator | CustomAuthenticator
Paginator:         DefaultPaginator | NoPagination | CustomPaginationStrategy
ErrorHandler:      DefaultErrorHandler | CompositeErrorHandler | CustomErrorHandler
BackoffStrategy:   ConstantBackoffStrategy | ExponentialBackoffStrategy | CustomBackoffStrategy
Decoder:           JsonDecoder | JsonItemsDecoder | JsonlDecoder | IterableDecoder
                   XmlDecoder | CsvDecoder | GzipDecoder | ZipfileDecoder | CustomDecoder
Extractor:         DpathExtractor | CombinedExtractor | ResponseToFileExtractor
PartitionRouter:   ListPartitionRouter | SubstreamPartitionRouter | GroupingPartitionRouter
                   UnionPartitionRouter | CustomPartitionRouter
Requester fields:  url_base | path | http_method | authenticator | error_handler
                   request_parameters | request_headers | request_body_json
Interpolasi:       {{ config['x'] }} | {{ record['y'] }} | {{ stream_slice }} | {{ now_utc() }}
Filter:            hash | base64encode | base64decode | string | regex_search | regex_replace
```

**Pelajaran yang diambil:** (a) **satu format YAML bisa melayani ratusan
connector** — inilah bukti bahwa 2000 connector tidak perlu 2000 file kode;
(b) kosakata komponen **tertutup dan tervalidasi skema** → bisa di-lint;
(c) `Spec.connection_specification` = kontrak form kredensial yang bisa
dirender UI; (d) ada `rate_limit`, `backoff`, `error_handler` sebagai komponen
deklaratif — bukan kode.

**4. OpenConnector — katalog aksi dengan flag kejujuran yang sudah dipakai Katalir.**
Struktur lokal `openconnector_actions.json` (1.554 service / 18.010 aksi):

```
service:  auth_schemes | description | id | install_config | name | no_auth
          no_auth_runnable_count | runtime_verified | slug | source
          tenant_scope | tools | tools_count | validated | verification
tool:     auth_types | call_verified | credential_free | description | id
          locally_executable | name | no_auth_runnable | no_input
          operation_type | status
```

**Pelajaran yang diambil:** (a) `no_auth_runnable` + `no_input` + `credential_free`
= **cara verifikasi nyata tanpa meminta kredensial user** — ini kunci untuk
"100% PASS" yang jujur; (b) `locally_executable` = apakah aksi bisa dijalankan
di proses sendiri; (c) `tenant_scope` = apakah connector mengakses data satu
tenant atau publik; (d) Katalir sudah memakai format ini (`noAuthRunnable`).

**5. ADR-003 Katalir sendiri — dedup + verifikasi bertingkat sudah diputuskan.**
`mcp_dedup.py` → `dedup_canonical.json` (23.474 baris) dengan
`canonical_key`, `member_ids`, `source_count`, `quality_score`, `unique_verified`.
`coverage()` memisahkan `executable` (23) dari `metadata_only` (25.902).

---

## 2. Perbandingan arsitektur

| Dimensi | Activepieces | Composio | Airbyte | OpenConnector | **Katalir hari ini** |
|---|---|---|---|---|---|
| Bahasa definisi | TypeScript | API platform | YAML | JSON katalog | **JSON katalog + Python** |
| Unit definisi | `Piece` | Toolkit | Manifest | Service+action | **entry registry** |
| Auth | `PieceAuth` per piece | AuthConfig+ConnectedAccount | `authenticator` komponen | `auth_schemes` | **`credential_forms`+vault** |
| Trigger | `Trigger[]` kelas satu | Trigger terpisah | Stream | — | **webhook/cron engine** |
| Eksekusi | V8 isolate worker | Server-managed | Python runner | Gateway token | **in-process + MCP gateway** |
| Versi | `minimumSupportedRelease` | — | `version` CDK | — | **belum ada per-connector** |
| Deprecation | `deprecated` flag | — | — | `status` | **`deprecated_at`** ✔ |
| Verifikasi | — | — | — | `call_verified` | **3 tingkat** ✔ |
| Dedup lintas sumber | — | — | — | — | **`mcp_dedup.py`** ✔ unik |
| Jumlah skala | ~720 piece | ~3000 tool | ~600 konektor | ~1500 service | **25.925 entri** |

**Kesimpulan:** Katalir **sudah unggul** di dua hal yang tidak dimiliki siapa
pun dari empat repo: **dedup lintas-sumber** (23.474 kanonik dari 25.925) dan
**registri verifikasi 3 tingkat**. Katalir **tertinggal** di tiga hal:
**bahasa definisi deklaratif** (punya JSON tapi bukan skema tervalidasi),
**versi + deprecation per-connector** (ada kolom, belum ada kontrak), dan
**jalur eksekusi** (23 dari 25.925).

---

## 3. Keputusan: **Extend, Don't Replace** — Manifest Deklaratif di atas Registry yang Ada

### 3.1 Keputusan utama

> **Bangun `connector_manifest.py`: satu skema manifest deklaratif (mengadopsi
> kosakata Airbyte yang sudah terbukti + semantik auth Composio), yang
> di-*compile* menjadi entri `mcp_registry` yang sudah ada — BUKAN registry baru.**

```
                    ┌──────────────────────────────────────────┐
                    │  connector_manifest.py  (BARU)           │
                    │  ConnectorManifest — skema tertutup      │
                    │  auth | actions[] | triggers[] | retry   │
                    │  rate_limit | paginator | verification   │
                    └────────────────┬─────────────────────────┘
                                     │ compile()
                                     ▼
   ┌─────────────────┬───────────────────────────────┬──────────────────┐
   │ provider_registry│ mcp_registry (8 sumber, 25.925)│ generated_mcp    │
   │ 8 native        │ + dedup_canonical.json (23.474)│ 889 tool OpenAPI │
   └─────────────────┴───────────────────────────────┴──────────────────┘
                                     │
                                     ▼
              /mcp/registry/*  •  /integrations  •  /mcp/gateway/call
```

### 3.2 Mengapa bukan arsitektur baru

| Kalau kita bangun registry baru | Akibatnya |
|---|---|
| 25.925 entri lama tak terlihat | `/integrations` jadi kosong; UI rusak |
| Dedup engine dilewati | duplikasi 22% kembali; angka membengkak palsu |
| 17 endpoint harus ditulis ulang | API depan pecah |
| 4 sync script jadi sia-sia | sinkronisasi berhenti |
| **= duplikat** | **melanggar instruksi pembuka brief** |

### 3.3 Mengapa manifest deklaratif (bukan Python per connector)

Dituntut oleh **angka**: 2000+ connector. Kalau 1 connector = 1 file Python,
itu 2000 file × ~200 baris = 400.000 baris kode yang tidak bisa diaudit.
Airbyte membuktikan satu YAML melayani ratusan connector. Karena itu:

**Format manifest Katalir:** YAML, satu file per connector, di
`connectors/<source>/<slug>.yaml`.

```yaml
# connectors/native/github_issue_create.yaml
manifest_version: 1
id: github.issue.create
display_name: "GitHub — Buat Issue"
slug: github_issue_create
source: native
category: developer-tools
tenant_scope: per-user            # per-user | public
deprecated: false
minimum_supported_release: "1.0.0"

auth:
  type: bearer                    # none|api_key|bearer|basic|oauth2|session_token
  credential_form: github_pat     # -> credential_forms.py
  connect_url: null               # diisi kalau oauth2
  scopes: ["repo"]

actions:
  - name: create_issue
    operation_type: write         # read|write|delete  (dipakai gate keamanan)
    method: POST
    url_base: https://api.github.com
    path: /repos/{{ config.owner }}/{{ config.repo }}/issues
    request_body_json:
      title: "{{ input.title }}"
      body: "{{ input.body | default('') }}"
    record_selector:                # kosakata Airbyte
      type: DpathExtractor
      field_path: ["html_url"]
    error_handler:
      type: DefaultErrorHandler
      retry: { type: ExponentialBackoffStrategy, max_retries: 3 }
    verification:
      level: call_verified          # listed|callable|call_verified

triggers:
  - name: issue_opened
    type: webhook
    signature: hmac_sha256
    header: X-Hub-Signature-256

rate_limit:
  type: FixedWindowCallRatePolicy
  max_calls: 5000
  window_seconds: 3600
```

### 3.4 Kosakata yang diadopsi (langsung dari riset, bukan karangan)

Diambil **verbatim** dari Airbyte karena sudah terbukti pada 50+ connector
produksi, sehingga tidak perlu kita desain ulang:

| Kelompok | Nilai yang didukung |
|---|---|
| `auth.type` | `none`, `api_key`, `bearer`, `basic`, `oauth2`, `jwt`, `session_token`, `selective` |
| `actions[].operation_type` | `read`, `write`, `delete` |
| `record_selector.type` | `DpathExtractor`, `CombinedExtractor`, `ResponseToFileExtractor` |
| `paginator.type` | `NoPagination`, `DefaultPaginator`, `OffsetIncrement`, `PageIncrement`, `CursorPagination` |
| `error_handler.type` | `DefaultErrorHandler`, `CompositeErrorHandler` |
| `retry.type` | `ConstantBackoffStrategy`, `ExponentialBackoffStrategy` |
| `triggers[].type` | `webhook`, `cron`, `polling` |
| `rate_limit.type` | `FixedWindowCallRatePolicy`, `MovingWindowCallRatePolicy`, `UnlimitedCallRatePolicy` |
| Interpolasi | `{{ config.x }}`, `{{ input.x }}`, `{{ record.x }}`, `{{ now_utc() }}` |
| Filter | `default`, `hash`, `base64encode`, `string`, `regex_replace` |

### 3.5 Yang diadopsi dari Composio

1. **Auth ≠ Connector.** `auth.credential_form` menunjuk ke `credential_forms.py`;
   kredensial aktual disimpan per-user di vault lewat `end_user_credentials.py`
   (fitur #35, sudah ada). 2000 connector tetap aman multi-tenant.
2. **`tenant_scope`** (`per-user` | `public`) — memisahkan connector yang
   menyentuh data pelanggan dari yang publik.
3. **Pembatasan sebagai kelas satu** — `tool_policy_gate.py` (sudah ada)
   menerapkan allowlist operasi; manifest hanya mendeklarasikan
   `operation_type`, gate yang memutuskan.

### 3.6 Yang diadopsi dari OpenConnector

1. **Flag kejujuran 3 tingkat** yang sudah dipakai Katalir:
   `listed` → `callable` → `call_verified`. **Tidak pernah** dipromosikan tanpa
   bukti panggilan nyata.
2. **`credential_free` + `no_input`** — connector yang bisa diuji **tanpa
   kredensial user**. Ini yang memungkinkan "100% PASS" jujur pada ribuan
   connector tanpa meminta satu pun rahasia.
3. **`locally_executable`** — apakah aksi bisa dijalankan di proses Katalir.

### 3.7 Yang diadopsi dari Activepieces

1. **`minimum_supported_release` + `deprecated`** per connector — connector
   mati ditandai, tidak dihapus diam-diam.
2. **Manifest adalah proyeksi, bukan sumber kebenaran ganda.** Sama seperti
   `Piece.metadata()`, manifest Katalir di-*compile* ke bentuk registry yang
   sudah ada; tidak ada dua daftar yang bisa berbeda.
3. **Kategori wajib** (`category`) untuk faset UI yang sudah ada di
   `/mcp/registry/categories`.

---

## 4. Rencana FASE 2–5 (dibatasi oleh keputusan di atas)

### FASE 2 — Master framework (memperluas, bukan menggantikan)

| Komponen | Nama | Memperluas | Bukan |
|---|---|---|---|
| Skema manifest | `connector_manifest.py` | `mcp_registry.load_cached()` | registry baru |
| Compiler | `manifest → registry entry` | bentuk `mcp_registry` yang ada | format baru |
| Validator YAML | `validate_manifest()` | `pglast`-nya Python: **jsonschema** | parser ad-hoc |
| Harness 10 test | `connector_harness.py` | `workflow_testkit.py` + 5 script batch | harness baru dari nol |
| Progres | `docs/connector-progress.md` | — | — |

`ConnectorTestHarness` — 10 test (dari brief FASE 4, verbatim):

| # | Test | Bisa diuji tanpa kredensial? |
|---|---|---|
| 1 | YAML valid + skema cocok | ✅ ya |
| 2 | Auth schema lengkap | ✅ ya |
| 3 | Action complete (method+path+selector) | ✅ ya |
| 4 | Trigger valid (kalau ada) | ✅ ya |
| 5 | Endpoint **reachable** (DNS+TLS+HTTP) | ✅ ya (tanpa auth) |
| 6 | Alur auth nyata | ⚠️ hanya bila `credential_free` |
| 7 | Integrasi engine (compile→registry→resolve) | ✅ ya |
| 8 | Error handling (retry/backoff terdeklarasi & dipatuhi) | ✅ ya (mock 429) |
| 9 | Keamanan (SSRF, `operation_type` gate, tidak ada secret di log) | ✅ ya |
| 10 | E2E workflow (node→gateway→hasil) | ⚠️ hanya bila `credential_free` |

**Konsekuensi jujur:** pada connector ber-kredensial, test 6 dan 10 **tidak
dapat dinilai PASS** tanpa kredensial user. Manifest karena itu mewajibkan
`credential_free` untuk connector yang diklaim `call_verified` **kecuali**
pemilik koneksi memberi kredensial uji. Connector lain maksimal berstatus
`callable`, dan itu **dilaporkan apa adanya** — sesuai tabiat proyek ini.

### FASE 3 — Batch eksekusi

Tetap 20 connector/batch, 200 test/batch, gerbang 100% PASS (per brief).
**Tambahan wajib dari audit:** setiap batch harus menaikkan
`coverage()["executable"]`, bukan `coverage()["total"]`. Batch yang hanya
menambah entri katalog **ditolak** oleh gerbang.

### FASE 4 — 10 hard test (di atas)

### FASE 5 — OpenAPI auto-generation (memperluas `openapi_to_mcp.py`)

Hari ini `SPECS` di `scripts/openapi_to_mcp.py` **hardcode 6 API** →
889 tool. Perluasan: tambah sumber **APIs.guru** (2500+ spec) + **public-apis**.
**Bukan** script baru — perluasan dict `SPECS` menjadi pemuat spec + generator
manifest YAML, sehingga hasil generate masuk lewat `connector_manifest.py`
yang sama.

---

## 5. Risiko dan mitigasi

| Risiko | Mitigasi |
|---|---|
| 2000 manifest memperbesar `metadata_only` | Gerbang FASE 3 menolak batch yang tidak menaikkan `executable` |
| Duplikasi lintas sumber baru | Wajib lewat `mcp_dedup.py` sebelum masuk registry |
| Secret bocor ke log manifest | Test 9 harness: scan secret-shaped strings |
| SSRF dari `url_base` sembarang | Pakai `_host_blocked()` dari `tools.py` (sudah ada) |
| Manifest drift dari registry | `compile()` deterministik + test invariant (seperti `test_x10` Fitur #2) |
| Janji "100% PASS" jadi bohong | Status 3 tingkat; `call_verified` hanya setelah panggilan nyata |

---

## 6. Bukti

**Repo yang dibaca:**
- `raw.githubusercontent.com/activepieces/activepieces/main/packages/pieces/framework/src/lib/piece.ts` — 5.302 byte, dibaca verbatim (`Piece`, `createPiece`, `metadata()`, `minimumSupportedRelease`)
- `docs.composio.dev/kb/topic/tools-actions-and-execution` — Session/AuthConfig/ConnectedAccount, custom tools, proxy execute, restricted sessions
- `docs.airbyte.com/platform/connector-development/config-based/understanding-the-yaml-file/reference` — 316.443 byte → 797 baris teks; kosakata komponen lengkap
- `github.com/oomol-lab/open-connector` (5.971 ★) + `openconnector_actions.json` lokal
- `mcp_registry.py`, `mcp_dedup.py`, `provider_registry.py`, `scripts/openapi_to_mcp.py`

**Angka verifikasi audit** (`docs/connector-existing-audit.md`):
`AUDIT NUMBERS VERIFIED OK` / `38 MODULES VERIFIED OK`

---

## 7. Keputusan akhir (satu paragraf)

> Katalir **tidak akan membangun registry connector kedua.** Katalir akan
> menambahkan **`connector_manifest.py`** — skema manifest deklaratif berbahasa
> YAML yang mengadopsi kosakata komponen Airbyte (retriever/requester/
> authenticator/paginator/error_handler), semantik auth Composio (kredensial
> milik koneksi per-user, bukan connector), dan flag verifikasi 3 tingkat
> OpenConnector (`listed`/`callable`/`call_verified`, tidak pernah dipromosikan
> tanpa panggilan nyata). Manifest di-*compile* ke `mcp_registry` yang sudah
> ada, melewati `mcp_dedup.py`, dan disajikan lewat 17 endpoint + UI
> `/integrations` yang sudah jalan. Target "2000+" diukur sebagai
> **`coverage()["executable"]` naik dari 23 → ≥2000**, bukan
> `coverage()["total"]` naik dari 25.925 → 27.925. Setiap batch 20 connector
> dikunci gerbang 100% PASS dari `connector_harness.py` yang 10 test-nya
> termasuk satu **panggilan endpoint nyata**, dan status `call_verified` hanya
> diberikan setelah panggilan itu benar-benar terjadi.
