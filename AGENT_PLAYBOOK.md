# Agent Playbook — Katalir

## Cara Kerja Tiap Sesi
1. Baca file ini dulu.
2. Baca `TODO.md` — kerjakan task teratas yang `[ ]`.
3. Cek `git log --oneline -5` dan `git status`.
4. Cek dev server (3000, 8000) dan production health.
5. Kerjakan task sampai selesai atau blocked (butuh user action).
6. Update TODO.md: `[x]` kalau selesai, `[!]` kalau blocked + alasan.
7. Commit dan push setiap task.
8. Kalau task berikutnya tidak blocked, lanjutkan.
9. Kalau blocked, lapor satu baris: `BLOCKED: <alasan>. User action: <satu baris>.`

## Aturan Otonom
- Berhenti hanya jika butuh user action (login/API/approve), error 7 iterasi, security issue, atau TODO habis.
- Selain itu auto-lanjut.
- Setiap task commit terpisah.
- Setiap commit memperbarui TODO.md.

## Gotchas
- Railway 2026: token UUID tetap valid; yang menentukan write adalah Scope `Account`, bukan format.
- Cloudflare DNS token bisa tidak memiliki DNS:Edit; CNAME bisa perlu user manual.
- Docker Desktop offline → pivot ke VPS.
- JWT `test-jwt.txt` kedaluwarsa sekitar 1 jam; minta user refresh dari browser Console.
- Railway deploy stale → force redeploy commit terbaru.
- Jangan jalankan `npm run build` bersamaan dengan `next dev` (`.next` corruption).
- Supabase Auth Site URL harus domain production.
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

## User Action
- Login/consent Google, Slack, atau Cloudflare: user manual.
- DNS CNAME ketika token tidak memiliki DNS:Edit: user manual.
- Railway redeploy dapat melalui API, tetapi verifikasi deployment dashboard tetap wajib.
- VPS SSH dapat melalui Paramiko.
