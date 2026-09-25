# Progress Katalir — Latest

## Phase 1.4 — Verify the existing pool [DONE 2026-09-26]
- 420 Glama no-auth connectors probed read-only, sequential, 0.5s delay
- **236 tools_listed (2.313 tools)** · 175 auth_required · 4 protocol_error · 5 unreachable · 0 ssrf_blocked
- Registry merged; unique tools-listed 1.576 -> **1.781**
- unique call-verified unchanged at 27, correctly: listing is not calling

## Phase 1.3 — AI Tools [DONE 2026-09-26]
- Groq `qwen/qwen3.8-27b` -> "KATALIR_OK" (571 ms)
- Gemini `gemini-2.5-flash` -> "KATALIR_OK" (1.773 ms)
- Hardcoded model ids had both rotted (Groq llama removed, Gemini 2.0-flash retired)

## Phase 1.2 — OpenAPI Generator [DONE 2026-09-26]
- 6 public specs, 889 generated, **884 registered**, 1 call-verified

## Phase 1.1 — Dedup [DONE 2026-09-26]
- 28.664 -> **22.789 unique** (79,5%)

## Phase 3.1 — Community platform [CODE DONE, DDL NOT APPLIED]
- schema + 4 endpoints + 5 tests committed (de2d876)
- production Supabase tables NOT created: that is a bigger step than adding columns

## Phase 3.1 — Community platform [DEPLOYED 2026-09-26]

Bug yang ditemukan user review dan sudah diperbaiki:
- `alter table community_integrations add constraint ... foreign key (id) references community_integrations (id)`
  adalah **no-op** — `id` sudah primary key, jadi constraint-nya mustahil dilanggar
  dan tidak menegakkan apa pun soal `status`. Diganti trigger `check_integration_approved()`.
- Ditambahkan `check_status_change_with_earnings()` karena trigger saja bisa dilewati:
  approve -> catat earnings -> ubah status jadi 'rejected'.
- RLS **tidak pernah diaktifkan** di versi pertama, padahal verifikasi mengharapkan
  `relrowsecurity = true`. Sekarang RLS aktif di kedua tabel + 4 policy:
  hanya `approved` yang bisa dibaca publik, developer hanya menulis barisnya sendiri,
  dan tidak ada policy insert untuk earnings (hanya service role).

Hasil apply ke produksi (`qmukkphwaajzbqjrcvaz`, region `ap-southeast-1`):
```
tables=2  rls_integrations=True  rls_earnings=True  policies=4
triggers=[community_earnings_approved_check, community_integrations_status_guard]
old_self_fk_still_present=False
integrations_count=0  earnings_count=0
```
Uji trigger nyata (lalu dibersihkan, 0 baris sebelum & sesudah):
1. earnings untuk integrasi **pending** -> ERROR "Cannot record earnings for non-approved integration" ✅
2. earnings untuk integrasi **approved** -> OK ✅
3. un-approve integrasi yang sudah punya earnings -> ERROR ✅
4. `GET /community/browse` -> **200** `{"items":[],"total":0}` (sebelumnya 503) ✅

Catatan koneksi: `db.<ref>.supabase.co` hanya punya **IPv6**, jadi dari jaringan IPv4
harus lewat pooler `aws-0-ap-southeast-1.pooler.supabase.com` user `postgres.<ref>`.

## Blockers (need the user)
1. `USER ACTION: create a valid secret key at https://app.nango.dev/settings and set NANGO_API_KEY`
   (the current key is rejected: GET /api/v1/providers -> 401)
2. `USER ACTION: connect providers in the Metorial dashboard` (key is valid, project has 0 providers)
3. `USER ACTION: approve applying docs/architecture/community-platform.sql to production Supabase`
