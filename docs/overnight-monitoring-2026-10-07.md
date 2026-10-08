# Overnight Monitoring — 7 → 8 Oktober 2026

**Launch:** 8 Oktober 2026, **14:01 WIB** · **Backend:** `https://web-production-dc90b.up.railway.app`
**Commit produksi:** `22d7405` (HEAD == origin/main) · **Zona waktu:** WIB (UTC+7)

**Keputusan yang sudah diambil (dari user):**
1. Gateway LLM degradasi 10× → **TIDAK diperbaiki H-1 launch** (risiko break).
2. Live test **Telegram saja** (confidence 95%) — Sheets/GitHub tidak.
3. Monitoring overnight sampai launch.

---

## 1. TABEL MONITORING

| Waktu | Health | MCP | Gateway Latency | VPS | Anomali |
|---|---|---|---|---|---|
| 19:35 | 200 · 1.56s · `persisted` | 401 · 7.79s | — | tidak dapat diakses | `/mcp/gateway/health` 7.79s (lambat) |
| 19:42 | 200 · 4.49s · `persisted` | 401 · 1.62s | **200 · ≥30.0s · 8646B** | tidak dapat diakses | **Gateway ≥30s (menembus batas), payload terpotong** |
| 21:44 | 200 · 0.64s · `persisted` | 401 · 1.86s | **200 · 6.89s · 74354B** | tidak dapat diakses | tidak ada 5xx; **gateway pulih** (≥30s → 6.89s) |
| 05:58 | 200 · 0.42s · `persisted` | 401 · 0.33s | **200 · 1.66s · 74354B** | tidak dapat diakses | tidak ada 5xx; gateway cepat & payload utuh |
| 07:59 | 200 · 0.43s · `persisted` | 401 · 0.33s | **200 · 1.90s · 74354B** | tidak dapat diakses | tidak ada 5xx; semua endpoint sesuai kontrak, gateway < 10s |
| 20:00 | _otomasi_ | | | | |
| 22:00 | _otomasi_ | | | | |
| 00:00 | _otomasi_ | | | | |
| 02:00 | _otomasi_ | | | | |
| 04:00 | _otomasi_ | | | | |
| 06:00 | _otomasi_ | | | | |

> Baris 19:35 berasal dari `docs/launch-eve-monitoring-2026-10-07.md`.
> Baris berikutnya diisi otomasi **`375e771c-7880-4307-bcea-e64841ab2c05`**
> (setiap 2 jam, aktif 7 Okt → 8 Okt 22:00).

---

## 2. ANOMALI

| # | Anomali | Bukti | Tingkat | Blocker? |
|---|---|---|---|---|
| A-1 | **Gateway LLM makin lambat** | 19:35: 20–25s · 19:42: **≥30s** (menembus `--max-time 30`) | 🟠 TINGGI | **TIDAK** (fallback chain) |
| A-2 | **Payload terpotong** | 19:42 payload 8646B vs 36–74KB sebelumnya → unduhan terputus saat timeout | 🟠 TINGGI | **TIDAK** |
| A-3 | Latensi `/health` naik | 1.56s (19:35) → 4.49s (19:42) | 🟡 SEDANG | TIDAK |
| A-4 | Latensi MCP fluktuatif | 7.79s (19:35) → 1.62s (19:42) | 🟡 SEDANG | TIDAK |
| A-5 | Metrik VPS buta | SSH `Permission denied (publickey,password)`; tidak ada `sshpass`/`plink` | 🟡 SEDANG | TIDAK |

**Tidak ada 5xx.** Endpoint inti (`/health`, `/workflows`) sesuai kontrak.

> **Pembaruan 21:44 (otomasi `375e771c`).** Tidak ada anomali berat pada run ini.
> Gateway LLM **pulih**: 6.89s (di bawah ambang 10s) dengan payload utuh 74.354B —
> turun dari ≥30s / 8.646B (terpotong) pada 19:42, jadi A-1/A-2 untuk sementara
> tidak teramati. A-3 (`/health`) juga normal (0.64s). A-5 (VPS) **masih** terjadi.

> **Pembaruan 05:58 (otomasi `375e771c`).** Tidak ada anomali berat pada run ini.
> `/health` 200 · 0.42s · `persisted`; `/workflows` 401; `/mcp/gateway/health` 401
> (normal). Gateway LLM **200 · 1.66s · 74.354B** — paling cepat sejauh monitoring,
> payload utuh (di bawah ambang 10s). Tidak ada 5xx / status tak diduga. A-5 (VPS)
> **masih** terjadi (SSH `Permission denied (publickey,password)`).

> **Pembaruan 07:59 (otomasi `375e771c`).** Tidak ada anomali berat pada run ini.
> `/health` **200 · 0.43s · `persisted`** (supabase); `/workflows` **401** (kontrak
> terpenuhi); `/mcp/gateway/health` **401** (butuh JWT — normal). Gateway LLM
> **200 · 1.90s · 74.354B** — payload utuh dan jauh di bawah ambang 10s. Tidak ada
> 5xx / status tak diduga. A-5 (VPS) **masih** terjadi (SSH
> `Permission denied (publickey,password)`).

A-1/A-2 konsisten dengan risiko residual **R-1** (`docs/security/launch-ready-v2-2026-10-07.md`).
Produk **tidak bergantung** pada gateway (rantai cadangan
`gemini_pool → groq → nvidia → github`), jadi ini **bukan blocker launch**,
tetapi menaikkan latensi node agent.

---

## 3. BAGIAN 3 — RENCANA LAUNCH DAY (8 Oktober, WIB)

| Jam | Aksi | Siapa |
|---|---|---|
| 06:00 | Laporan overnight final | otomasi + agen |
| 07:00–13:00 | Monitoring tiap 30 menit | ⚠️ lihat catatan di bawah |
| 13:30 | Final health check + lapor | agen |
| 13:45 | Lapor status siap launch | agen |
| 13:55 | **STOP semua aktivitas — jangan sentuh production** | agen |
| 14:01 | User submit Product Hunt | user |
| 14:05–22:00 | Standby + fix bila ada issue | agen |

> **Catatan keterbatasan (penting).** Penjadwal otomasi **tidak mendukung
> `MINUTELY`** dan menolak `BYHOUR` bernilai ganda, sehingga cadence **"tiap 30
> menit" tidak bisa diekspresikan**. Otomasi berjalan **tiap 2 jam**
> (00:00, 02:00, …, 12:00, 14:00). Untuk menutup jendela 07:00–13:00 yang lebih
> rapat, jalankan pemeriksaan manual atau minta agen memeriksa saat itu.

**Larangan yang dipatuhi:** tidak ada deploy setelah 13:30 WIB 8 Okt, tidak
merestart gateway H-1, tidak mengubah config production.

---

## 4. BAGIAN 4 — PLAYBOOK JIKA ADA MASALAH SAAT LAUNCH

### 4.1 Production down
1. **Rollback** ke commit terverifikasi sebelumnya — commit terakhir yang sudah
   diverifikasi penuh: `9c623a6` (deploy `ddf9c70d`, SUCCESS) atau `1a2889d`.
2. Restart Railway + Cloudflare (via dashboard; **bukan** dari agen tanpa izin).
3. Laporkan ke user **dengan bukti mentah** (kode HTTP, respons, timestamp).

### 4.2 Gateway down
1. **Fallback chain menangani otomatis** (`gemini_pool → groq → nvidia → github`).
2. Monitor error rate.
3. Laporkan bila **> 10% error**.

### 4.3 User komplain latency
1. Acknowledge.
2. Jelaskan: *"Gateway sedang di-restart, fallback chain bekerja."*
3. Fix post-launch.

---

## 5. STATUS BAGIAN 1 — LIVE TEST TELEGRAM

**BELUM BISA DIJALANKAN.** Prasyarat belum ada:

```
.env.test                -> tidak ada
TEST_ di .env            -> 0
TEST_ di environment     -> tidak ada
```

Menunggu user membuat `.env.test` berisi:
```
TEST_TELEGRAM_BOT_TOKEN=<bot token dari BotFather>
TEST_TELEGRAM_CHAT_ID=<id grup test>
```

Begitu ada, langkah 1a–1g dijalankan: validasi format
(`\d+:[A-Za-z0-9_-]+` dan `-?\d+`), aktifkan `live.enabled=true`, jalankan
LIVE #1 (Trigger → Telegram real), verifikasi pesan terkirim + screenshot,
lalu canary scan (harus 0).

**Larangan dipatuhi:** tidak memakai kredensial produksi (`TELEGRAM_BOT_TOKEN`
produksi) — hanya `TEST_TELEGRAM_*`.

---

## 6. LAMPIRAN — Perintah mentah

```bash
curl -s -o /dev/null -w "HTTP %{http_code} %{time_total}s" $B/health
curl -s -o /dev/null -w "HTTP %{http_code} %{time_total}s" $B/workflows
curl -s -o /dev/null -w "HTTP %{http_code} %{time_total}s" $B/mcp/gateway/health
curl -s -o /dev/null -w "HTTP %{http_code} %{time_total}s payload=%{size_download}B" \
     --max-time 30 -H "Authorization: Bearer <LLM_GATEWAY_KEY>" $GW/v1/models
ssh -o BatchMode=yes -o ConnectTimeout=8 <VPS_USERNAME>@<VPS_IP> 'uptime'
```

Tidak ada kredensial yang dicetak dalam dokumen ini.
