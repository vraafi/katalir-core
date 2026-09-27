# ROADMAP-BLITZ — Katalir vs n8n

**Rule of this file:** a number is only allowed on it if it was produced by a run
whose output is in the repo. Phase-based, no deadline, auto-continue.

That rule is enforced, not just stated: `node verify_roadmap_claims.mjs`
re-derives every number below from the artefacts it cites and exits non-zero if
any claim stops reproducing. **If you edit a number here, run that script.**

## Reality check (measured 2026-09-26, not projected)

| Metric | Value | Where it comes from |
| --- | --- | --- |
| Raw catalogue entries | 29.695 | sum of the 8 source files |
| **Unique integrations (deduped)** | **23.474** | `mcp_dedup.py` → `dedup_report.json` |
| Unique % | 79.05 % (6.221 collapsed) | same |
| Groups present in >1 source | 1.797 | same |
| **Unique call-verified** | **227** + Groq + Gemini = **229** | `dedup_report.json` → `unique_verified` |
| **Integrations that list tools** | **1.896** | `dedup_report.json` → `tools_listed` |
| discovered only | 21.578 | `dedup_report.json` |
| Generated OpenAPI tools | 884 registered (889 generated) | `openapi_tools_manifest.json` |
| Glama no-auth pool | 351 connectors → **4.714 tools** | `glama-connector-verify-batch{1,2}.json` |
| Glama pool, call-verified | 351 attempted → **203 connectors** | `glama-connector-call-batch1.json` |
| Nango (OAuth) | 1.024 providers, **0 tools** | `nango_providers.json` |
| Metorial | 1 integration provider (GitHub) | `metorial_integrations.json` |

**Two different units — do not add or compare these.** 1.896 counts
*integrations* that answer `tools/list` (1.896 + 21.578 = 23.474, the deduped
total). 4.714 counts *tools* returned by those calls. They are not the same kind
of number, so "1.781 vs 4.714" was never a meaningful comparison.

Measured containment: all **351 of 351** pool connectors are already keys in
`glama_connectors.json`, so the pool sweep added **no new sourcing** — it
upgraded 351 already-catalogued entries from "listed" to "call-verified".

**Nango and Metorial are not tools catalogues and must never be counted as
tools.** Nango is an OAuth/connection layer: 1.024 providers, 0 tools. It added
**570** genuinely new integrations and its other **434** are duplicates of
Composio/Glama/OpenConnector entries that dedup collapsed rather than counted
twice. Metorial added **0** new integrations — GitHub already existed, and now
carries a 7th source tag.

**The honest gap:** the blitz target is 2.000 unique *verified*. Reality is **229
call-verified** (227 from the catalogue + Groq + Gemini), up from 28. The gap is
still a *verification* problem, not a sourcing problem: 23.474 unique integrations
are in the catalogue, and only the ones with a working no-auth endpoint can be
call-verified without a user's credential.

## FASE 1 — Batch Verify  ← current
- [x] F1.5 metrics — `dedup_report.json` regenerated after the call phase
- [x] F1.6 commit — batch + call artefacts tracked
- [x] **F1.7 tools/call phase** — 351 no-auth Glama connectors attempted, one
      read-only `tools/call` each → **203 call_verified** (107 failed, 14 rejected
      our synthetic args, 26 had no read-only tool, 1 would not re-initialize).
      `unique_verified` **26 → 227**; with Groq + Gemini that is **229 verified**.
      Reconciled exactly: 203 connectors − 1 (`AI Tools Directory` is a directory,
      not an integration) − 1 (two connectors share the name `rnv-color-mcp`)
      = 201 new canonical rows, and 26 + 201 = 227.
      Evidence: `glama-connector-call-batch1.json`, `scripts/audit_call_safety.py`.
      Safety: only no-auth endpoints, SSRF-guarded, sequential, and a tool is
      callable only if its name matches a read-verb allowlist and no mutating
      verb. The audit re-derives that independently from the recorded tool names:
      **0 mutating, 0 outside the allowlist, 188 distinct tools.**
      An argument-rejection response is recorded as `call_validation_error` and
      is **not** counted as verified — "the endpoint answered" is not "the
      integration works".
- [x] F1.1 Nango key → **WORKS**. `GET https://api.nango.dev/providers` → **200**,
      **1.024** provider. The earlier "401" was our own bug: we called
      `/api/v1/providers`, which is not a Nango route. Auth is
      `Authorization: Bearer <Environment API key>`; the endpoint has no `/api/v1`
      prefix. Evidence: `nango_providers_evidence.json`.
- [x] F1.2 Nango provider templates → 1 integration configured
      (`github-getting-started`, provider `github`, created 2026-09-25) via
      `GET /integrations`. Note `/provider-templates` returns **HTML**, not JSON —
      it is the Connect UI docs page, not an API. Use `/integrations` instead.
- [x] F1.3 Metorial tools → **works.** `GET /integration-providers` → 200, **1 active
      integration provider (GitHub)** on a Production instance (`katalir`). The
      recorded "0 providers" was stale, and a first probe reported 403 — that 403
      was Cloudflare **error 1010**, a WAF block on a non-browser signature, not
      an auth failure. Read from the body, not assumed. It added **0** new
      integrations because GitHub was already in the catalogue.
- [x] F1.4 Batch verify candidates — **complete, no-auth Glama pool exhausted**:
      619 attempted → **351 ok** / **4.714 tools** (batch 1: 420 → 236 / 2.313,
      batch 2: 199 → 115 / 2.401). The two batches overlap by **0** connectors, so
      236 + 115 = 351 is a real union, not a double count.
      Evidence: `glama-connector-verify-batch{1,2}.json` at `6dcbfd0`. That phase
      was **tools-list only**; `tools/call` came later as F1.7 below.

## FASE 1b — UI polish (shipped alongside F1.4)
- [x] F1b.1 Chat empty state → DeepSeek minimalism: decorative Sparkles/Bot icons
      removed, text-only greeting, rounded suggestion pills.
- [x] F1b.2 Magnetic, non-clickable MCP logo cloud, 55 brands. Hover moves the
      nearest tile (150px range, 0.3 strength) + tilt + spotlight. Live on
      `katalir.de5.net` — 55/55 render as inline SVG, 0 remote images,
      `pointer-events: none`, 0 focusable children.
- Evidence: `docs/evidence/{landing-logos,chat-empty}-{desktop,mobile}.png`,
  commits `7959dae`, `507cc7c`, `810bf9b`, `f0cf704`.

## FASE 2 — Sync All Sources
- [ ] F2.1 sync the 884 OpenAPI tools (dedup first) · [ ] F2.2 source tags
- [x] F2.3 marketplace tabs + dedup toggle + runtime badge — **10 tabs, one per real
      `source`**, plus the two controls this phase asked for.
      - Tabs: All, Native MCP, Glama, Glama Connector, OpenConnector, Composio,
        ToolSDK, OpenAPI, Nango (OAuth), Metorial. Two are beyond the 8 requested
        because both are real sources that previously had no tab.
      - **Dedup toggle** All / Unique: 29.558 raw vs 23.474 deduped, 6.084
        collapsed. `view=bogus` → 400, never a silent fallback. If
        `dedup_canonical.json` is absent the unique view errors rather than
        returning a "unique" total that is not unique.
      - **Runtime badge, 4 tiers**: call_verified / auth_required / tools_listed /
        discovered. `no_auth === false` means auth_required; *absent* `no_auth`
        stays discovered, so "unknown" is never upgraded to "needs a key".
      - Fixed a real bug found while doing this: the backend folded
        `glama-connector` into `glama`, so the Glama tab read 20.000 while its own
        grid held 21.000 rows. Every tab count now equals its grid in **both** views.
      - 7/7 Playwright green, `tsc` clean. · [x] F2.4 commit

## FASE 3 — Multi-Protocol Executor (MCP + OpenAPI + GraphQL + JS)
- [x] F3.1 OpenAPI import — `katalir_protocols/openapi.py`. Parses paths[]/operations
      into the same tool-descriptor shape the other protocols use. Refuses an
      operation whose `{id}` has no matching `parameters[]` (imports clean, 404s on
      first call), refuses deprecated ops, refuses a non-public `servers[0].url`.
- [x] F3.2 GraphQL import — `katalir_protocols/graphql.py`. Live introspection of
      countries.trevorblades.com → 35 tools. Walks every object type rather than
      only the root queryType, so nested fields are reachable.
- [x] F3.3 JS sandbox — `katalir_protocols/jsandbox.py` + `js_runner.js`. The
      sandbox has **no network of its own**: its `fetch` emits a request over stdio
      and Python applies the guard. Giving it node's fetch would put the SSRF check
      in a second language, and a second guard is a second thing to forget to update.
- [x] F3.4 MCP remote import — `katalir_protocols/mcp_remote.py`. Real `initialize`
      + `tools/list` over streamable HTTP. **Never calls a tool during an import** —
      importing an entry must not be able to mutate a third party's data.
- [x] F3.5 test each — `tests/test_katalir_protocols.py`, **50 passing**;
      `scripts/f3_evidence.py` writes one evidence file and exits non-zero on
      regression. Measured: 4 protocols, **960 tools listed**, 5/5 SSRF escapes
      blocked, **0 false call_verified**.
- [x] F3.6 commit

**The one number that must never move is `false_call_verified` = 0.** OpenAPI,
GraphQL and remote MCP all produce *descriptions*, so they are `tools_listed` and
stay there. Only the JS sandbox actually executes, so it is the single path that
can honestly be `call_verified`. The evidence script asserts this, because
"verified" that was never executed is the failure this project keeps undoing.

## FASE 4 — Marketplace UI v2
- [x] F4.1 dedup toggle — done di F2.3, diverifikasi ulang.
- [x] F4.2 search across all sources — done di F2.3 (server-side `search`).
- [x] F4.3 filter kategori + status runtime — **baru, ini kerja utama F4.**
      - `runtime_tier()` di `mcp_registry.py` jadi **satu-satunya** definisi tier.
        Badge dan filter memakai fungsi yang sama, jadi keduanya tidak bisa
        berbeda pendapat. Di UI sebelumnya badge dihitung ulang sendiri; dua
        salinan satu aturan pasti akan menyimpang.
      - `?tier=` di kedua view (all/unique). Tier **partisi katalog**:
        226 + 12.866 + 1.532 + 14.934 = **29.558**, tanpa celah atau dobel.
      - `?tier=bogus` → **400**, bukan hasil kosong senyap.
      - Facet kategori dari `/mcp/registry/categories` (200 kategori nyata,
        bukan daftar hardcode yang menawarkan opsi kosong).
- [x] F4.4 screenshot 8+ tab desktop + mobile — 10 file di `f3-shots/`
      (6 tab + All/Unique + Nango + mobile 390px).
- [x] F4.5 a11y — 0 control tanpa nama, 0 field tanpa label, semua tab punya
      `aria-selected`.
- [x] F4.6 commit

**Tiga bug nyata yang tertangkap F4:**
1. `list_servers` memakai `x['category']` → **KeyError** di 3.112 baris yang tidak
   punya key itu. Tidak pernah muncul karena tidak ada yang pernah mengirim
   parameter `category`. Bug laten yang justru tidak terjangkau.
2. `pickTier` memanggil `setTier(t)` lalu `load()`, dan `load()` membaca `tier`
   dari closure — **masih nilai lama**, karena React belum re-render. Filter
   diam-diam tidak melakukan apa-apa. Semua picker kini meneruskan nilainya.
3. Semua kartu ber-`source_url` menampilkan "View on Glama" yang di-hardcode,
   jadi **1.024 kartu Nango** menunjuk ke Nango sambil mengklaim sebagai listing
   Glama. Link yang salah menyebut vendor lebih buruk daripada tanpa link.
   Sekarang hanya sumber Glama yang memakai label itu, dan `rel=nofollow
   sponsored` (syarat Glama Data License) ikut dipertahankan di sana.

## FASE 5 — Marketing + Launch Prep
- [x] F5.1 landing claim — angka **diubah dari sumber yang sama** dengan roadmap, dan
      setiap angka marketing sekarang jadi klaim di `verify_roadmap_claims.mjs`.
      Halaman landing tadinya bilang "28,500+ catalog entries" dan "28 Glama
      connectors runtime-verified" — keduanya angka **sebelum** fase `tools/call`,
      jadi sudah tidak didukung bukti. Kini: 23.474 unik, 229 call-verified.
- [x] F5.2 pricing + docs — **grep menemukan klaim basi di TIGA tempat**, bukan satu.
      Landing (i18n EN + ID), halaman **pricing**, dan halaman **docs** semuanya
      masih mengulang angka pra-`tools/call`. Semuanya dikoreksi. Klaim
      "no stale pre-call-phase claim" sekarang menscan keempat permukaan itu,
      karena permukaan marketing bukan cuma file yang kita ingat.
- [x] F5.3 Product Hunt kit — `docs/marketing/product-hunt/launch-kit.md`:
      tagline, subtitle, deskripsi, tabel tier, topik, founder comment, checklist
      hari-launch, 5 screenshot production, dan **video 60 detik yang benar-benar
      direkam** (1,0 menit, 1,1 MB webm, 1440x900).
- [x] F5.4 playbook final — 4 gotcha baru: Cloudflare 1010, satu sumber tier,
      React setState-lalu-load, dan parameter yang tak pernah dipanggil.
- [x] F5.5 commit
- [x] F5.6 report

**Yang dikasih tahu di kit, bukan disembunyikan:** Dodo KYC **ditunda**, verifikasi
vendor tambahan **ditunda**, dan target 2.000 **tidak tercapai** (sekarang 229).
Kalau ada yang bertanya "apakah pembayaran jalan", jawabannya kebenaran, bukan
rencana. Video masih kasar tanpa suara — itu langkah produksi manusia.

Rekaman demo sengaja tidak masuk `testMatch`: ia bukan assertion, dan kamera di
regression suite membuat setiap test run ikut merekam serta membuat gangguan
rekaman terlihat seperti regresi produk.

## FASE 6 — Product Hunt Launch ⭐ USER ACTION
- [ ] F6.1–F6.4 submit, announce, respond · [ ] F6.5 metrics snapshot

## FASE 7 — Community Outreach
- [x] F7.1 outreach shortlist (public GitHub profiles only — no emails/contact data) · [x] F7.2 tutorial · [x] F7.3 bounty doc (design only) · [ ] F7.4 dashboard *(blocked: backend down)* · [x] F7.5 waiting-list email
- F7.1 note: `docs/community/outreach-sea.json` holds public profile data only
  (login, URL, bio, self-declared location, public repos). **No email addresses
  and no scraped contact details** — a human decides who to contact and how.
  Regenerate with `python scripts/collect_outreach_sea.py`.

## FASE 8 — Regional + Vertical Expansion
> **`[!] DEFERRED` — F8 skipped by explicit decision (2026-09-28).**
> Regional expansion (F8.1 SEA VN/TH/PH/MY) and the vertical pushes
> (healthcare, logistics, education) are deferred, not cancelled. The blocking
> constraint is credentials: each regional/vertical target needs live provider
> API keys (payment rails, health data agreements, logistics accounts) that we
> do not have and were instructed not to request. Building the integration
> shells without keys would produce untestable code and unverifiable claims.
> Revisit once keys exist.
- [ ] F8.1 SEA (VN/TH/PH/MY) · [ ] F8.2 healthcare · [ ] F8.3 logistics
- [ ] F8.4 education · [ ] F8.5 sync + test + commit

## FASE 9 — Parity Push
- [x] F9.1 audit n8n nodes → gap map · [ ] F9.2 generate missing via OpenAPI
- [x] F9.3 community bounty (doc only) · [ ] F9.4 batch verify + commit
- [x] F9.5 update claim · [ ] F9.6 THE END

### F9.1 results (measured, `docs/audit/n8n-gap-analysis.json`)

| Number | Value | Note |
|---|---|---|
| n8n distinct nodes | **685** | not the ~2.864 in earlier notes; measured from n8n-nodes-base 2.15.1 |
| already in catalogue | 225 (32.85%) | |
| raw gaps | 181 | **not 181 missing integrations** |
| ├ real integrations | 83 | the only genuinely fillable set |
| ├ n8n core nodes | 63 | `If`, `Merge`, `Webhook`, `Cron`, `SplitInBatches`… |
| ├ infrastructure | 6 | databases / transports |
| └ helper artefacts | 29 | `*Helpers`, `*Interfaces`, `currencies` — not nodes at all |

Of the 83 real integration gaps, **exactly 1** (Cloudflare) is fillable from
the provider snapshots already in this repo; 82 have no source snapshot yet.
`dedup_canonical.json` was **not modified** — see
`docs/audit/f9-gap-fill-proposal.json` (`applied_to_canonical: false`).
Quoting "181 gaps" as backlog size would overstate the work by ~180x.


## Already done (earlier phases, kept for continuity)
- [x] Dedup engine · [x] OpenAPI generator · [x] AI tools (Groq + Gemini call-verified)
- [x] P3.1 Community platform **deployed**: 2 tables, RLS on, 2 triggers, live-tested
- [x] MCP gateway: sends auth headers and **fails closed** when no credential
      (`mcp_gateway/client.py` + `tests/test_mcp_gateway/test_client.py`, `2b2f8f5`)
- [x] MCP auto-config preview + runtime allowlist gate (`mcp_autoconfig.py`, `fc94d21`)
- [x] Katalir MCP server proven by a **real external SDK client**, not an in-repo
      stub (`tests/test_katalir_mcp_external.py`, `9e2e0bb`)

These three landed on the MCP track and are tracked in `TODO.md`; they are listed
here only so the blitz totals are not mistaken for the whole of what exists.

## Blocked on the user
1. ~~**Nango Cloud key**~~ → **NOT BLOCKED, false alarm.** The key works; the
   401 we recorded came from calling `/api/v1/providers`, a route that does not
   exist. The real call is `GET https://api.nango.dev/providers` with
   `Authorization: Bearer <key>` → 200, 1.024 providers. Corrected 2026-09-26.
2. **Metorial providers** — the key is valid, but the project has **0 providers
   connected**. Action: connect providers in the Metorial dashboard, then re-sync.

## Agent Rules

- Search-first; no-surrender loop; test before DONE.
- Commit per sub-task; update this roadmap each task.
