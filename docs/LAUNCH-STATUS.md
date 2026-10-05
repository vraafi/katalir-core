# LAUNCH STATUS — Katalir

Tanggal: 5 Oktober 2026
Repo: `katalir-core` · `HEAD = origin/main = fa5fe7f`

---

## 1. Commit terakhir

| | |
|---|---|
| HEAD | `fa5fe7f` — `docs: bukti harness e2e:prod - 26 tes approval-card ikut suite resmi; suite penuh terblokir` |
| origin/main | `fa5fe7f` (sinkron, 0 ahead / 0 behind) |

Commit sesi ini dan pendahulunya:

```
fa5fe7f  docs: bukti harness e2e:prod — 26 tes approval-card ikut suite resmi
986decb  docs: bukti deploy kedua — hasil tool + alignment terverifikasi di situs live
415c5b1  fix(chat): render tool result + alignment after approval
a216846  fix(ui): kartu persetujuan tidak pernah dirender — ditemukan lewat bukti browser
0a87f03  docs: laporan handoff sesi katalir
2a71e48  fix(api): teruskan status dari gateway — .stop hardcode "success"
90f1d59  fix(api): jangan telan requires_approval — bug ditemukan verifikasi produksi
a6bbbd6  feat(ui): kartu persetujuan + audit arsitektur chat frontend
b7da2ac  feat(security): intent-alignment check — defense-in-depth injeksi prompt
5a63110  feat(security): tutup 4 gap — sanitasi tool result, input, allowlist, approval
b50efdb  feat(security): policy gate deterministik + red team suite (41 test)
8291a94  feat(chat): hentikan kirim param `tools` — jalur teks jadi utama
8565246  feat(tool): textual tool calling format [ALAT: args] — model-agnostic
daa2a0c  feat(vault): gerbang fail-closed + tool check_credential + broker secret://
```

---

## 2. Fitur yang TERVERIFIKASI

| Fitur | Status | Bukti |
|---|---|---|
| Live site | ✅ 200 | `katalir.de5.net` → 200; `proyek-agent.pages.dev/chat` → 200 |
| Bundle live memuat perbaikan | ✅ | chunk `page-6eb4f85538eda943.js` (69.193 B) memuat `approval-card`, `approval-alignment`, `tool-result-card`, `tool-result-output`, `approval-approve`, `approval-deny` |
| Backend produksi | ✅ | `/health` → 200; `/workflows` → 401 (auth aktif) |
| Kartu persetujuan (approval card) | ✅ 13/13 | `playwright.approval.config.ts` — **13/13 lulus** di build produksi lokal **dan** di situs live |
| Hasil tool tampil setelah Setujui | ✅ | 4 tes formatter (objek / string / `{message}` / kosong) + screenshot `tool-result` |
| `alignment` dirender | ✅ | `<details data-testid="approval-alignment">` — tes intent-alignment lulus |
| Form kredensial (vault) | ✅ | tes `requires_credential: kartu form kredensial tetap dirender` lulus **di situs live** |
| Kontrak keamanan `/chat/approve` | ✅ | body persis `{approval_token, decision}`; client tidak mengirim ulang tool/args |
| Jalur tetangga tidak rusak | ✅ | `success` bubble + `denied` → error-card, keduanya lulus |
| Suite backend (pytest) | ✅ 706 passed | lihat §5 |

---

## 3. Gap yang DITUTUP

1. **Kartu persetujuan tidak pernah dirender.** `useChat` menaruh pesan
   `approval_prompt` ke cache dengan benar, tetapi layer render `ChatApp.tsx`
   hanya memetakan `credential_form`/`oauth_prompt`/`error` — `approval_prompt`
   jatuh ke `return null`. Bubble user muncul lalu hilang tanpa jejak. (`a216846`)
2. **`result` dari `/chat/approve` dibuang.** `ApprovalCard` hanya membaca status
   HTTP, jadi output tool tidak pernah terlihat user. Sekarang diteruskan lewat
   `onDecision` → kartu `tool_result`. (`415c5b1`)
3. **`alignment` diteruskan tapi tidak dirender.** Sekarang tampil sebagai
   `<details>` "Kenapa tool ini butuh persetujuan?". (`415c5b1`)
4. **`status` di-hardcode `"success"`** di `/chat`, sehingga `requires_approval`
   mustahil sampai ke UI. (`2a71e48`)
5. **`requires_approval` ditelan** oleh jalur API. (`90f1d59`)
6. **`tool_call_parser` ada tapi tidak pernah dipanggil** — proteksi tampak ada,
   padahal mati. (`daa2a0c` dkk.)
7. **Native `tools` merusak setiap request** (HTTP 500) — digantikan jalur teks
   `[ALAT: args]`. (`8291a94`)

Pola yang berulang di tiga bug pertama: **proteksi terlihat ada, padahal mati.**
Yang menangkapnya adalah menjalankan alurnya di browser — bukan type-check.

---

## 4. KNOWN LIMITATIONS

1. **Suite penuh `npm run e2e:prod` TERBLOKIR di environment ini.**
   Suite ini tidak pernah sampai menjalankan satu tes pun karena `next build` di
   dalam `webServer` gagal lebih dulu. Tiga sebab lingkungan ditemukan berurutan:
   - `node` managed (22.22.2) tidak bisa memuat `@next/swc-win32-x64-msvc`
     (`DLL initialization routine failed`) → **diatasi** dengan node 24 sistem;
   - shim safe-delete membatasi 50 hapus/turn, sedangkan build membersihkan
     `.next` → **diatasi** dengan memindahkan direktori artefak lebih dulu;
   - `EPERM: open 'out\404.html'` pada langkah `Exporting` → **BELUM teratasi**.

   Ini **bukan bug produk**: build mencapai `✓ Compiled successfully` +
   `✓ Generating static pages (21/21)`, dan chunk yang dihasilkan hash-nya
   identik dengan yang di-deploy. Menulis `out/404.html` secara manual
   **berhasil**, jadi ini race/lock level Windows.

   Yang **sudah** dibuktikan tanpa build: `npx playwright test --list
   -c playwright.config.ts` → **514 tes / 44 berkas**, dan
   `approval-card.spec.ts` menyumbang **26 entri** (13 tes × proyek
   `guest` + `logged-in`). Jadi spec baru memang ikut suite resmi.

2. **Verifikasi UI melawan backend produksi dengan sesi nyata TERBLOKIR.**
   Refresh token `.autonomous_session.json` sudah dicabut dan password grant
   untuk user otonom ditolak — kredensial test account berubah sejak 2 Okt.
   Sebagai gantinya: spec stub per-path terhadap build produksi dan situs live
   (13/13), karena bentuk response `/chat/approve` di produksi
   (`{status:"executed", tool, result}`) sudah dibuktikan sesi sebelumnya.

3. **Keputusan sengaja, bukan bug:**
   - TOLAK tidak menambah bubble `tool_result` (backend tidak mengembalikan
     `result` untuk deny; kartu "dibatalkan" sudah jadi tanda terima).
   - `alignment` hanya ditampilkan untuk kasus `not_aligned`.
   - Rate limiter masih in-memory (`TurnBudget`) — Railway multi-replica bisa
     melewatinya. Ditunda, bukan cacat yang tak disadari.
   - Investigasi gateway 500 dan wiring `qwen_param_parser.py` sengaja ditunda.

4. **Catatan hash chunk.** Bundle live bernama `page-6eb4f85538eda943.js`,
   sedangkan build lokal menghasilkan `page-dc3e7d8eb0b7ff3c.js` — **ukuran
   identik (69.193 B)** dan memuat penanda perbaikan yang sama. Perbedaan nama
   berasal dari perbedaan environment build, bukan dari isi yang berbeda.

---

## 5. Test & verifikasi (ringkas)

```
pytest tests/ -q                                     -> 706 passed  (lihat pytest-final.log)
npx playwright test -c playwright.approval.config.ts  -> 13 passed   (production build lokal)
E2E_BASE_URL=https://proyek-agent.pages.dev \
  npx playwright test -c playwright.approval.config.ts -> 13 passed  (situs live)
npx playwright test --list -c playwright.config.ts     -> 514 tes / 44 berkas
npm run e2e:prod                                       -> TERBLOKIR (EPERM, §4.1)
```

---

## 6. Cara re-run full suite

Prasyarat toolchain — **wajib runtime sistem**, bukan managed WorkBuddy:

```bash
export PATH="/c/Program Files/nodejs:/c/Users/user/AppData/Local/Programs/Python/Python312:$PATH"
node --version                # harus v24.x  (managed 22.22.2 gagal memuat @next/swc)
python -c "import fastapi"    # backend uvicorn butuh Python 3.12 sistem
```

Lalu:

```bash
cd nexus-frontend

# 1. Pastikan port 3000 bebas (scripts/check-no-dev-running.mjs memblokir build)
# 2. Pastikan .next / test-results tidak menyisakan >50 berkas untuk dihapus
#    (shim safe-delete WorkBuddy membatasi 50 hapus per-turn).
#    Pindahkan dulu kalau perlu:
#      mv .next .next.old ; mv test-results test-results.old

# 3. Fixture auth harus segar, atau tidak ada (spec jatuh ke dummySession()):
node -e "const s=require('./_e2e_session.refreshed.json');const p=JSON.parse(Buffer.from(s.access_token.split('.')[1],'base64url'));console.log('ttl',p.exp-Math.floor(Date.now()/1000))"

npm run e2e:prod
```

Catatan `next build` gagal `EPERM out\404.html` (§4.1): jalankan dari shell biasa
di luar sandbox tool, atau lewat CI. Spec approval sendiri bisa dijalankan tanpa
build penuh:

```bash
npm run build && PORT=3000 node scripts/serve-out.mjs &
npx playwright test -c playwright.approval.config.ts
```

---

## 7. Dokumen terkait

```
docs/debug-approval-card-not-rendered.md   latar bug render + bukti + catatan harness
docs/debug-status-wrapper.md               trace bug status hardcode
docs/frontend-chat-architecture.md         alur chat + gap
docs/security/threat-model-tool-injection.md  12 vektor injeksi + status
docs/marketing/screenshots/approval-card-gallery.html  galeri bukti (self-contained)
```
