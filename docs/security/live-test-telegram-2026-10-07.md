# Live Test Telegram — 7 Oktober 2026 (Opsi B)

**Status:** ⏳ **PRE-TEST — menunggu grup TEST dari user**
**Launch:** 8 Oktober 2026 · **Commit:** `27a4689` (live_runner versi Opsi B belum di-commit saat dokumen ini ditulis)

## Keputusan: Opsi B (pragmatis)

| Aspek | Pilihan |
|---|---|
| Bot token | `TEST_TELEGRAM_BOT_TOKEN` bila ada → **fallback ke `TELEGRAM_BOT_TOKEN`** (bot produksi) |
| Chat ID tujuan | **WAJIB `TEST_TELEGRAM_CHAT_ID`** (grup TEST baru) — **tidak ada fallback** |
| Chat produksi | **DIBLOKIR KERAS** oleh `assert_not_production_chat()` |

Alasan: bot yang sama, **tujuan kirim berbeda**. Risiko spam ke grup produksi
dihilangkan secara struktural, bukan lewat disiplin.

---

## 1. Verifikasi kredensial (RAW OUTPUT)

```
=== 3b: bot token fallback (Opsi B) ===
  sumber = PRODUCTION_BOT
  format = OK
  panjang = 46 (tidak dicetak nilainya)

=== 1a: chat id WAJIB TEST_ (tanpa fallback) ===
  BLOCKED: Credential 'telegram_chat' tidak ada di store test.

=== 3c: SAFEGUARD chat produksi ===
  chat produksi terisi: True
  HASIL: diblokir -> BLOCKED: TEST_TELEGRAM_CHAT_ID sama dengan production!
                     Buat grup TEST baru.
  chat TEST berbeda -> lolos (benar)

=== 3e: live.enabled gate ===
  live_enabled() = False (harap False)
```

**Tabel hasil:**

| # | Cek | Harapan | Hasil | Status |
|---|---|---|---|---|
| 3b | Bot token fallback ke produksi | `PRODUCTION_BOT` | `PRODUCTION_BOT`, format OK | ✅ |
| 1a | Chat ID tanpa fallback | BLOCKED bila kosong | **BLOCKED** | ✅ |
| 3c | Chat id == produksi | diblokir | **diblokir** | ✅ |
| 3c | Chat id ≠ produksi | lolos | lolos | ✅ |
| 3e | `live.enabled` awal | false | **false** | ✅ |
| 3e | Format token `\d+:[A-Za-z0-9_-]+` | cocok | cocok | ✅ |
| 3e | Format chat `-?\d+` | — | menunggu chat id | ⏳ |

---

## 2. Fail-closed (RAW OUTPUT)

```
$ python tests/sandbox/live_runner.py
==========================================================================
BAGIAN 3 — LIVE #1: Trigger -> Telegram (API NYATA, Opsi B)
==========================================================================

[1a] .env.test ada: False

[1a] BLOCKED: Credential 'telegram_chat' tidak ada di store test. Isi variabel TEST_* yang sesuai di lingkungan test.
     Buat grup TEST, lalu tulis TEST_TELEGRAM_CHAT_ID ke .env.test
```

Skrip **menolak berjalan** tanpa chat ID TEST. Ini bukan crash — ini gerbang.

---

## 3. Perlindungan berkas

```
$ git check-ignore -v .env.test
.gitignore:3:.env.*	.env.test
```

`.env.test` **gitignored** → tidak bisa ter-commit (sesuai larangan brief).

---

## 4. Hasil test — BELUM DIJALANKAN

| Item | Hasil |
|---|---|
| Pesan test terkirim | ⏳ belum (menunggu `TEST_TELEGRAM_CHAT_ID`) |
| Screenshot grup | ⏳ belum |
| Canary terlihat di hasil mentah | ⏳ belum |
| Canary dibersihkan dari output | ⏳ belum |
| Canary di berkas lokal | ⏳ belum |
| Canary di `execution_logs` / `chat_messages` | ⏳ belum |

## 5. VERDICT

**PENDING** — kode + pengaman siap dan terverifikasi; pengiriman menunggu
`TEST_TELEGRAM_CHAT_ID` di `.env.test`.

Setelah user konfirmasi, `live_runner.py --enable-live` dijalankan dan bagian 4
diisi, lalu verdict diubah menjadi PASS/FAIL.

---

## 6. Alur canary (BAGIAN 4)

1. **4a** — canary unik dibuat (`KATALIR_TEST_CANARY_<12 upper-hex>`).
2. **4b** — canary disisipkan ke pesan → muncul di **hasil mentah** tool
   (diverifikasi `canary_seen_in_raw`).
3. Jalur pulang: `mask_known_values` → `redact_agent_output(raise_on_canary=False)`
   → diverifikasi `canary_stripped` (canary TIDAK ada di output).
4. **4c** — `scan_local()` atas berkas lokal → sandbox hits harus `[]`.
5. **4d/4e** — `scan_db()` atas `execution_logs` + `chat_messages` → hits harus `[]`.
6. **4f** — dilaporkan: detected / not detected.

> **Jika canary terdeteksi:** ALERT user, revoke bot token produksi bila perlu,
> perbaiki redactor — dan **STOP** (protokol kontradiksi B3).

---

## 7. Larangan yang dipatuhi

- ✅ Tidak mengirim ke `TELEGRAM_CHAT_ID` produksi (diblokir kode + diuji).
- ✅ Tidak mencetak bot token (hanya panjang + format).
- ✅ Canary scan tidak dilewati (menjadi syarat verdict).
- ✅ `live.enabled` dikembalikan `false` di blok `finally` (kembali ke safe mode).
- ✅ `.env.test` gitignored (tidak bisa ter-commit).
