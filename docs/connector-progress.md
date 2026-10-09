# Progress — 2000+ Fitur Integrasi Katalir

> Brief: `MASTER PROMPT — 2000+ FITUR INTEGRASI KATALIR` (CHAIN EXECUTION +
> HARD TEST GATE, standar Okt 2026).
>
> **Prasyarat yang dipatuhi lebih dulu:** *"baca dulu dengan seksama apa saja
> fitur yang sudah ada jangan ada duplikat"* →
> `docs/connector-existing-audit.md`.

---

## Angka yang BENAR (bukan angka inflasi)

Target brief "2000+ connector" diukur pada **`executable`**, bukan `total`.
Alasan lengkap: `docs/connector-existing-audit.md` (katalog sudah berisi
25.925 entri; hanya 23 yang executable).

| Metrik | Nilai | Sumber |
|---|---|---|
| Katalog total (semua sumber) | **25.925** | `mcp_registry.coverage()["total"]` |
| Katalog unik (setelah dedup) | **23.474** | `dedup_canonical.json` |
| `metadata_only` (tidak bisa jalan) | **25.902** | `coverage()["metadata_only"]` |
| **`executable` (baseline)** | **23** | `executable_servers()` |
| Provider native (in-process) | **8** | `provider_registry.PROVIDERS` |
| Connector default (Fitur #6) | **1** | `provider_registry.PROVIDERS` |
| Manifest yang lolos 10 test | **1** | `GET /connectors/coverage` |
| **`executable_total` HARI INI** | **24** | `GET /connectors/coverage` |
| **Target** | **≥2000** | brief |
| **Gap** | **1.976** | `gap_to_target` |

Endpoint pembuktian: `GET /connectors/coverage` (tidak ada konstanta di sana;
semua dihitung runtime).

---

## FASE — status

| FASE | Isi | Status | Bukti |
|---|---|---|---|
| **Prasyarat** | Audit fitur yang sudah ada + daftar dedup | ✅ **SELESAI** | `docs/connector-existing-audit.md` |
| **FASE 1** | Riset 5 repo → keputusan arsitektur | ✅ **SELESAI** | `docs/connector-architecture-decision.md` |
| **FASE 2** | Master framework: skema manifest + harness 10 test | ✅ **SELESAI** | `connector_manifest.py`, `connector_harness.py`, `connectors/_template/connector.yaml` — commit **`6fc9760`** |
| **FASE 3** | Batch eksekusi 20 connector / 200 test, gerbang 100% PASS | ⏳ **BELUM** | butuh FASE 2 ✅ (kini siap) |
| **FASE 4** | 10 hard test per connector | ✅ **TERDEFINISI + TERJALAN** | `connector_harness.py` (10 test, `describe()`) — commit **`6fc9760`** |
| **FASE 5** | OpenAPI → auto-generate | ⏳ **BELUM** | `scripts/openapi_to_mcp.py` sudah ada (889 tool); perluasan ke APIs.guru belum |

---

## FASE 2 — apa yang dibangun

### `connector_manifest.py` (809 baris)

Skema manifest **deklaratif YAML**, kosakata **tertutup**, di-*compile* menjadi
entri `mcp_registry` yang **sudah ada**. **Tidak** membangun registry kedua.

| Fungsi | Guna |
|---|---|
| `validate_manifest(data)` | Daftar error; kosong = valid |
| `parse_manifest(text)` | YAML → dict (via `yaml.safe_load`) |
| `load_manifest(path)` | Baca + validasi + `scan_secrets` |
| `compile_manifest(data)` | → entri registry (deterministik) |
| `manifest_canonical_key(data)` | Kunci dedup lintas sumber |
| `manifest_hash(data)` | Deteksi drift (SHA-256) |
| `host_is_blocked(url)` | Guard SSRF |
| `scan_secrets(text)` | Cegah token masuk manifest yang di-commit |
| `BatchGate` | Gerbang batch FASE 3 |
| `describe()` | Kosakata (dipakai endpoint + test invarian) |

**Kosakata** (diadopsi dari Airbyte/Composio/OpenConnector — bukan karangan):

- `auth.type`: `none, api_key, bearer, basic, oauth2, jwt, session_token, selective`
- `operation_type`: `read, write, delete`
- `tenant_scope`: `per-user, public`
- `record_selector`: `DpathExtractor, CombinedExtractor, ResponseToFileExtractor, JsonItemsDecoder`
- `paginator`: `NoPagination, DefaultPaginator, OffsetIncrement, PageIncrement, CursorPagination`
- `error_handler`: `DefaultErrorHandler, CompositeErrorHandler`
- `retry.type`: `ConstantBackoffStrategy, ExponentialBackoffStrategy`
- `rate_limit.type`: `FixedWindowCallRatePolicy, MovingWindowCallRatePolicy, UnlimitedCallRatePolicy`
- `verification.level`: `listed, callable, call_verified`
- Interpolasi: variabel `config, input, record, stream_slice, stream_interval, now_utc, today_utc, timestamp`; filter `default, hash, base64encode, string, regex_replace`

### `connector_harness.py` (10 hard test)

| # | Test | Bukti | Selalu bisa diuji? |
|---|---|---|---|
| 1 | `yaml_valid` | skema cocok | ✅ |
| 2 | `auth_schema` | form/scope/connect_url | ✅ |
| 3 | `action_complete` | method+path+body mengikuti operation_type | ✅ |
| 4 | `trigger_valid` | signature/header/schedule | ✅ |
| 5 | `endpoint_reachable` | **HTTP nyata** (status + ms) | perlu jaringan |
| 6 | `auth_flow_real` | hanya bila `credential_free` | butuh kredensial |
| 7 | `engine_integration` | compile→registry→transport siap | ✅ |
| 8 | `error_handling` | retry+backoff tiap action | ✅ |
| 9 | `security` | SSRF + rahasia + gate operasi | ✅ |
| 10 | `e2e_workflow` | hanya bila `credential_free` | butuh kredensial |

**Aturan penilaian yang tidak bisa dinegosiasikan:**
`skipped` **tidak pernah** dihitung PASS. Manifest ber-kredensial maksimal
berstatus `callable`; klaim `call_verified` **diturunkan** oleh compiler bila
`credential_free=false`. Ini yang membuat angka "100% PASS" bermakna.

### Connector referensi — bukti harness tidak kosong

`connectors/native/restcountries_lookup.yaml` (REST Countries v3.2, publik,
tanpa auth, 3 action read):

```
verdict pass  passed 10  failed 0  skipped 0   18.11s
 5 endpoint_reachable pass | 1/1 endpoint dapat dijangkau (HTTP nyata)
   evidence: [{'url': 'https://restcountries.com', 'ok': True, 'status': 200, 'ms': 15688}]
 9 security           pass | SSRF bersih, tidak ada rahasia, gate operasi konsisten (['read'])
10 e2e_workflow       pass | 3 tool siap, credential_free=true, transport=http
```

---

## API (6 endpoint baru)

| Method | Path | Guna |
|---|---|---|
| GET | `/connectors/schema` | kosakata skema + prinsip 10 test |
| GET | `/connectors/template` | isi template mentah |
| GET | `/connectors` | daftar manifest + status validasi (yang gagal DITAMPILKAN, tidak disembunyikan) |
| POST | `/connectors/validate` | validasi + compile + jalankan 10 test |
| POST | `/connectors/compile` | manifest valid → entri registry |
| GET | `/connectors/coverage` | angka jujur: `executable` vs `total` |

Registry fitur: `_FEATURE_MODULES["39_connector_manifest"]`.

---

## BUKTI

| Berkas | Isi |
|---|---|
| `tests/test_connector_manifest.py` | **57 passed** (B4, D4, E18, P3, S11, X17) |
| `_c39_api_e2e.py` | **50 LULUS / 0 GAGAL** — 9 bagian A–I |
| `connector_harness` test jaringan | 10/10 PASS pada connector referensi |

Perintah:
```
C:/Users/user/AppData/Local/Programs/Python/Python312/python.exe -m pytest tests/test_connector_manifest.py -q
C:/Users/user/AppData/Local/Programs/Python/Python312/python.exe _c39_api_e2e.py
```

---

## Yang BELUM (jujur)

1. **FASE 3 batch eksekusi belum dijalankan.** Baru **1** connector manifest.
   Target 2000+ berarti ~100 batch × 20 connector, masing-masing 200 test.
   Gerbang `BatchGate` sudah siap dan **akan menolak** batch yang hanya
   menaikkan `total` tanpa menaikkan `executable`.
2. **FASE 5 perluasan belum.** `scripts/openapi_to_mcp.py` masih 6 API
   hardcoded (889 tool). APIs.guru (2.500+ spec) + public-apis belum tersambung
   ke jalur manifest.
3. **Alur koneksi OAuth generik belum.** `oauth_google` + `oauth_slack` saja;
   1.024 provider Nango terkatalog tanpa jalur connect. Tanpa ini, mayoritas
   connector dari katalog tetap tidak dapat `call_verified`.
4. **Fitur #1 (n8n Agents first-class) & #9 (Dapr) dari brief lama** belum.

---

## Aturan yang tidak boleh dilanggar (dari brief + audit)

- Jangan bangun registry connector kedua — perluas `mcp_registry.py`.
- Jangan menaikkan `coverage()["total"]` sebagai ukuran keberhasilan.
- Jangan pernah mempromosikan `call_verified` tanpa panggilan nyata.
- Jangan hitung `skipped` sebagai PASS.
- Jangan commit rahasia ke manifest (`scan_secrets` adalah jaring, bukan izin).
- Jangan kirim operasi `write`/`delete` ke API pihak ketiga dari harness.
