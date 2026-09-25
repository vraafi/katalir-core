# Agent Playbook — Katalir

## ⚠️ NO-SURRENDER PROTOCOL (WAJIB — BERLAKU SETIAP SESI)

### Prinsip Inti
Kamu tidak boleh menyerah pada error. Cari, uji, dan dokumentasikan pendekatan berbeda sampai berhasil atau ada kondisi berhenti yang sah.

### SEARCH-FIRST MANDATE
Sebelum tindakan baru, tidak yakin, atau stuck: cari exact error di GitHub Issues, Stack Overflow, docs resmi, Discussion/Discord, dan changelog. Dilarang menebak API atau melakukan coba-coba tanpa sumber. Jika satu sumber gagal, gunakan minimal tiga sumber berbeda.

### NO-SURRENDER LOOP
Ulangi: **search → isolate → fix → test**. Catat setiap iterasi sebagai `ITERATION=N | PROBLEM=... | SOURCE=URL | ATTEMPT=... | RESULT=...`. Jangan berhenti sebelum sukses terverifikasi, aksi user yang benar-benar diperlukan, security issue, atau lima pendekatan berbeda telah dicoba dan didokumentasikan.

### NEVER-DECLARE-DONE-WITHOUT-TEST
Sebelum DONE: assertion kuantitatif, screenshot/bukti visual, dan regression test wajib. DONE tanpa test tidak sah.

### HARD RULE
BLOCKED hanya valid untuk: user action (login/approve/bayar), keputusan keamanan, lima+ pendekatan dan tiga+ sumber search yang tetap gagal, atau TODO habis. Dilarang berhenti dengan alasan “sulit”, “aneh”, atau “tidak tahu”. User action harus spesifik: `USER ACTION: <aksi> di <tempat>`.

## Cara Kerja Tiap Sesi
1. Baca file ini dulu.
2. Baca `TODO.md` — kerjakan task teratas yang `[ ]`.
3. Cek `git log --oneline -5` dan `git status`.
4. Cek dev server (3000, 8000) dan production health.
5. Kerjakan task sampai selesai atau blocked (butuh user action).
6. Update TODO.md: `[x]` kalau selesai, `[!]` kalau blocked + alasan.
7. Commit dan push setiap task.
8. Kalau task berikutnya tidak blocked, lanjutkan.
- **C2.21 done:** authenticated servers=200/39, call=200/datetime, unauthenticated health=401 is expected auth behavior. Do not request another JWT for this check.
9. Kalau blocked, lapor satu baris: `BLOCKED: <alasan>. User action: <satu baris>.`

## Aturan Otonom
- Berhenti hanya jika: a) butuh user action (login/approve/bayar) dan tulis aksi spesifik; b) security issue butuh keputusan user; c) sudah mencoba 5+ pendekatan berbeda + 3+ sumber search dan tetap gagal; d) TODO habis.
- Dilarang berhenti karena “sulit”, “aneh”, “tidak tahu”, atau gagal 1–2 kali.
- Wajib search real-time sebelum menebak atau melakukan tindakan baru.
- Wajib test + screenshot sebelum claim DONE.
- Selain itu auto-lanjut.
- Setiap task commit terpisah.
- Setiap commit memperbarui TODO.md.

## Gotchas
- Railway 2026: token dapat berformat UUID; jangan menolak berdasarkan format. Baca docs/scope, gunakan `RAILWAY_token` untuk token lokal yang tersedia, dan `RAILWAY_API_TOKEN` bila dipisah.
- Cloudflare DNS token bisa tidak memiliki DNS:Edit; CNAME bisa perlu user manual.
- Docker Desktop offline → pivot ke VPS.
- JWT `test-jwt.txt` kedaluwarsa sekitar 1 jam; minta user refresh dari browser Console.
- Railway deploy stale → force redeploy commit terbaru.
- Jangan jalankan `npm run build` bersamaan dengan `next dev` (`.next` corruption).
- Supabase Auth Site URL harus domain production.
- `python-dotenv` dapat memberi warning parse pada `.env`; gunakan key aktual dan jangan menyimpulkan key kosong hanya dari baris yang gagal parse.
- VPS: `.env` memuat `VPS_IP`, `VPS_USERNAME`, `VPS_PASSWORD`.
- Cloudflare tunnel: quick tunnel hanya sementara; named tunnel memerlukan CNAME manual bila token DNS read-only.
- MCP fetch adalah Python: `uvx mcp-server-fetch`, bukan npm.

## Cara Debug
1. Isolasi: raw TCP → HTTPS → protocol → SDK.
2. Setelah 3 kegagalan, cek Railway log, VPS `journalctl`, atau expiry `test-jwt.txt`.
3. Search real-time GitHub Issues, docs resmi, dan Discord.
4. Screenshot + output curl wajib; jangan mengklaim tanpa bukti.

## Kredensial
- `.env` root: token/credential production; jangan commit atau print value.
- `nexus-frontend/.env.local`: konfigurasi `NEXT_PUBLIC_*`.
- `test-jwt.txt`: JWT sementara, harus gitignored dan dihapus setelah test.
- Test JWT untuk audit dapat dibuat otomatis lewat Supabase Admin API menggunakan `SUPABASE_SERVICE_ROLE_KEY`; jangan meminta user mengambil JWT dari browser. User sementara harus dihapus kembali melalui Admin API.

## User Action
- Login/consent Google, Slack, atau Cloudflare: user manual.
- DNS CNAME ketika token tidak memiliki DNS:Edit: user manual.
- Railway redeploy dapat melalui API, tetapi verifikasi deployment dashboard tetap wajib.
- VPS SSH dapat melalui Paramiko.

## Gotcha: Jangan Verifikasi Deploy via Railway GraphQL
- Railway GraphQL deployments query 2026 sering return kosong (schema berubah).
- JANGAN block karena GraphQL kosong.
- VERIFIKASI DEPLOY = CECK ENDPOINT BEHAVIOR:
  - 500 → kode lama (belum deploy)
  - 401 → kode baru load, butuh JWT (deploy sukses)
  - 200 → deploy + auth OK
- 500 → 401 = deploy berhasil.

## Aturan Anti-Siklus JWT
- test-jwt.txt = JANGAN dihapus setelah test. Biarkan expired sendiri.
- Kalau 401 muncul di endpoint yang butuh auth = PERILAKU BENAR.
- JANGAN block task karena endpoint return 401.
- JANGAN minta JWT ke user kecuali benar-benar perlu test endpoint baru.
- Do not delete `test-jwt.txt` after a completed authenticated E2E; leave it gitignored for reuse, but never commit or print it.
- Health check = 401 tanpa JWT, 200 dengan JWT. Keduanya = "OK".
- Setelah `CREATE TABLE` via direct DB, PostgREST cache bisa stale: jalankan `NOTIFY pgrst, 'reload schema';` lalu verifikasi `GET /rest/v1/<table>?limit=1` = 200.
- Persistence production wajib diuji: install → restart backend → list. Kalau hilang, masih fallback in-memory atau JWT tidak owner yang benar.

## Roadmap Aktif
- Baca `ROADMAP.md` setiap sesi untuk task berikutnya.
- Task di `ROADMAP.md` diurutkan prioritas.
- Task `[ ]` = belum selesai; `[x]` = selesai; `[!]` = blocked dengan alasan dan user action.

## Gotcha Phase 2
- Google OAuth publish tidak memiliki API; user harus klik manual di Google Auth Platform.
- Dodo live mode/verifikasi memerlukan login dan keputusan akun merchant.
- Slack Directory submit memerlukan user submit form dan review eksternal.
- Marketing/site work dapat dilakukan otonom; fitur P2.5 harus dipilih berdasarkan evidence.

## Gotcha: Marketing Claim ≠ Runtime Reality
- "500+ integrations" = metadata available.
- "X verified executable" = tested + working.
- JANGAN klaim "500+ working" tanpa batch test.
- Batch test: filter executable kandidat → install di gateway → test MCP initialize + list_tools.
- Success rate realistis: 10-30% dari metadata.
- Update marketing copy dengan angka nyata + qualifier.

## Gotcha: Composio key types
- `ck_...` = workspace Consumer API Key (header `x-consumer-api-key`) untuk MCP client akun sendiri.
- `ak_...` = Project API Key (header `x-api-key`) untuk backend toolkit/tool API. Inilah yang dibutuhkan Katalir.
- Verifikasi: `GET https://backend.composio.dev/api/v3.1/toolkits` + `x-api-key` harus 200.
- Sync/verify tersedia di `scripts/composio_sync.py`; hanya toolkit yang lolos `list_tools` yang boleh mendapat `runtime_verified=true` dan badge Ready.

## Gotcha: Katalir v2 composition
- Target runtime 1.000+ integrasi TIDAK otomatis tercapai dari metadata. Composio adalah jalur tercepat, tetapi membutuhkan `COMPOSIO_API_KEY` di `.env`.
- Jangan ganti `execution_engine.py` dengan LangGraph hanya karena lebih populer; engine existing harus dibandingkan lewat shadow-run dan regression test.
- Mastra `ee/` directories memakai enterprise license: jangan copy source atau mengklaim Apache-2.0 untuk bagian itu.
- Kestra dan n8n hanya pattern reference; jangan embed JVM/Node runtime besar tanpa alasan operasional.
- Lihat `docs/architecture/katalir-v2-composition.md` untuk keputusan per repo.
- 4.548 metadata lokal saat ini hanya memiliki `install_config.transport=metadata-only`, bukan `install_method` npm/python/docker.
- Filter batch yang jujur dapat menghasilkan 0 kandidat; itu bukan error filter, tetapi bukti schema metadata tidak cukup untuk instalasi.
- Jangan mengarang transport atau menjalankan package registry hanya dari nama/id. Tambahkan manifest runtime terpisah dengan digest, method, image/package, permissions, dan health proof.
`USER ACTION: <aksi> di <tempat> (<estimasi waktu>)`

