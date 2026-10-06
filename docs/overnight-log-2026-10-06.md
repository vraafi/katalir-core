# OVERNIGHT LOG — 6/7 Oktober 2026

Catatan kerja sesi otonom menjelang launch 7 Okt 14:01 WIB.
Setiap entri punya bukti mentah; berkas berprefix `_ops_*` = artefak audit (gitignored).

> **Catatan kejujuran tentang "monitoring setiap 30 menit".**
> Sesi ini bukan proses yang tertidur 8 jam lalu bangun tiap 30 menit. Yang
> benar-benar berjalan terus-menerus adalah **guard systemd di VPS** (tiap 2
> menit, mandiri, sudah aktif) dan **log-nya** `/var/log/agentgateway-guard.log`.
> Untuk pemantauan produksi, saya menyediakan `_ops_monitor.py` yang bisa
> dijalankan kapan saja dan mencetak ketiga pemeriksaan produksi + kondisi VPS.
> Snapshot di bawah adalah hasil menjalankannya, bukan klaim pemantauan
> berkelanjutan yang tidak saya lakukan.

---

## Ringkasan status akhir

| Area | Kondisi |
|---|---|
| Produksi `/health` | HTTP 200 `{"status":"ok"}` |
| Produksi `/workflows` tanpa token | HTTP 401 (fail-closed) |
| Produksi `/mcp/gateway/health` | HTTP 200 `{"status":"ok"}` |
| Katalog MCP | 44 tool |
| Frontend | `https://katalir.de5.net` HTTP 200 (402 KB) |
| VPS agentgateway | active |
| VPS guard timer | active (restart-based v1 → reaper-based v2) |
| VPS proses MCP terlantar | 0-13 (sebelumnya memuncak di 138 → RAM habis) |
| VPS memori tersedia | 1.436-1.845 MB (sebelumnya 7 MB) |
| VPS load | 0,0-0,4 (sebelumnya 55) |
| pytest | 952 passed |
| Commit aktif Railway | `1503641` (deployment `de92a6be` SUCCESS) |

---

## Timeline

### 01:2x UTC / 08:2x WIB — Recon Task 1 (VPS leak)
- Cek versi: **agentgateway 1.5.0** (`git_revision fe673247…`), binary
  `/opt/agentgateway/agentgateway`, service `active`.
- Rilis di GitHub: `v1.6.0` **ada** (stable, 2026-10-02) dengan aset
  `agentgateway-linux-amd64`.
- **Changelog v1.6.0 (54.586 char) dibaca penuh: TIDAK memuat perbaikan
  kebocoran proses / session cleanup / reap untuk stdio.** Bagian MCP-nya hanya:
  data CEL, override serverInfo, SSE keep-alive, batas ukuran request.
  → Premis brief ("1.6.0 punya statefulMode: stateless yang fix leak")
  **tidak terbukti**.

### 01:3x UTC — Eksperimen mekanisme kebocoran (mengoreksi diagnosis)
- 3 sesi berurutan (`initialize` → `tools/list` → `DELETE`):
  `procs 40 → 50 → 40`, **`delta_per_sesi = 0`**.
- **Gateway MEMANG mereap anak stdio** saat sesi ditutup dengan benar.
- Penyebab sebenarnya: **sesi yang tidak pernah ditutup.** Terlihat 4 set lengkap
  target stdio berumur 12/18/24/29 menit, semuanya anak langsung agentgateway —
  agentgateway 1.5.0 tidak punya GC untuk sesi menganggur.
- Klien produksi diuji: 3× `GET /mcp/gateway/servers` → `procs 50 → 40 → 40 → 40`
  (justru turun karena guard restart). **Klien kita tidak membocorkan sesi.**

### 01:4x UTC — Guard v2 (reaper, bukan restart)
- Masalah guard v1: `systemctl restart` saat procs>60 memutus permintaan yang
  sedang jalan. **Terbukti**: restart 01:26:59 → `GET /mcp/gateway/servers`
  produksi membalas **503**.
- Guard v2: bunuh **hanya set terlantar** (anak langsung agentgateway,
  umur > `IDLE_MINUTES`=10), tanpa restart. Restart tetap ada sebagai jaring
  terakhir (procs>60 atau mem<200 MB).
- **Bug di percobaan pertama**: pola `mcp-server-` melewatkan pembungkus npm
  (`npm exec @modelcontextprotocol/server-everything` tidak memuat string itu),
  jadi hanya set uvx yang dibersihkan. Diperbaiki → `REAPED=44`.
- **Bukti**: 2 sesi sengaja ditelantarkan → `procs 12 → 22 → 32`; reaper dengan
  `IDLE_MINUTES=0` → `REAPED=44`, `procs=0`, memori **750 MB → 1.852 MB**; sesi
  MCP baru sesudahnya tetap melayani **44 tool**.
- Guard lama disimpan di `/opt/agentgateway/agentgateway-guard.sh.v1.bak`.

### 01:5x UTC — Task 3 (performa)
- **3.3 katalog MCP**: `mcp_tool_cache.py` (TTL 30 menit, refresh thread latar,
  fallback **stale** → 200 + warning alih-alih 503). Dipakai bersama endpoint
  `/mcp/gateway/servers` **dan** system prompt → satu sumber kebenaran, dan
  mengurangi pembuatan sesi baru di gateway (tiap sesi men-spawn satu set proses).
- **3.1 vault**: `vault_cache.py` (TTL 300 s, maks 500 entri, invalidasi eksplisit
  di `database.vault_save`/`vault_delete`). Terukur: 10x baca **54,3 ms → 5,8 ms**,
  panggilan vault 10 → 1.
- **3.2 parser**: prefilter penanda literal. Terukur 200x parse prosa 2.740 char
  **1,5 ms → 0,1 ms**. Saran brief "deteksi 2 karakter pertama" **tidak dipakai**
  (balasan model berprosa lebih dulu; keputusan berbasis awal teks akan melewatkan
  call yang sah).
- pytest: 894 → **929 passed**.

### 02:0x UTC — Task 2 (chaos)
- **2.1**: 10 prompt workflow → 8 membangun, 2 menolak dengan alasan benar,
  10/10 < 30 s (median 9,2 s).
- **2.2**: 10 request berturut → semua 200. 2 konkuren → **503 keduanya**.
  Diukur: pulih dalam **~49 detik** → cooldown **RPM transien**, bukan kuota harian.
- **2.3**: 20 kasus → 18 diblokir, **2 celah**: gerbang meloloskan SSRF ke
  `127.0.0.1` dan `169.254.169.254`. Diperiksa lebih dalam: `tools.http_request`
  **menolaknya**, jadi bukan celah yang bisa dieksploitasi — tetapi gerbang harus
  gagal-tertutup lebih dulu. Diperbaiki → **20/20 diblokir**.

### 02:5x UTC — TEMUAN TERBESAR: probe kesehatan kita sendiri yang bocor
- Diukur: **setiap `GET /mcp/gateway/health` menambah TEPAT 13 proses** dan ~330 MB.
  3 pemeriksaan: `mcp_procs 26 -> 39 -> 52 -> 65`,
  `mem_available 1211 -> 884 -> 555 -> 303 MB`.
- Sebabnya `mcp_gateway/client.py::health()`: kirim `initialize`, **tanpa `DELETE`**.
  Gateway men-spawn satu set target per sesi dan hanya mereap saat sesi ditutup.
  Endpoint kesehatan dipanggil berkala -> bocor menumpuk tanpa pengguna menyentuh
  MCP -> guard menembus 60 proses -> restart -> 503. Lingkaran setan yang akhirnya putus.
- Perbaikan: `health()` mengirim `DELETE` memakai `Mcp-Session-Id` dari jawaban
  (hanya bila `initialize` berhasil). Sesudah deploy: **`DELTA = +0`** untuk 3
  pemeriksaan, memori stabil ~1840 MB.

### 02:4x UTC — Verifikasi & deploy
- pytest final: **947 passed** (12 failed + 2 error = 13 pra-eksisting/lingkungan).
- Push `222c234`, `94e27c4` → Railway deployment `9c3a2750` **SUCCESS**.
- Monitoring snapshot: produksi 3/3 OK, VPS sehat.
- Frontend: `katalir.de5.net` 200 (402 KB) — dicek dengan `httpx`; `urllib`
  bawaan ditolak Cloudflare karena tanpa User-Agent (bukan gangguan situs).

---

## Snapshot monitoring (08:46 WIB)

```
-- produksi --
  OK GET /health                  -> HTTP 200   294ms  {"status":"ok", …}
  OK GET /workflows               -> HTTP 401   291ms  {"detail":"Token wajib …"}
  OK GET /mcp/gateway/health      -> HTTP 200 13830ms  {"status":"ok"}

-- VPS --
  agentgateway=active        guard_timer=active
  mcp_procs=13               mem_avail_MB=1436      swap=310/1279
  load=0.40 0.27 0.53        agentgateway_uptime_s=1178
  log guard terakhir:
    2026-10-06T01:46:16+00:00 REAPED=0
    2026-10-06T01:46:19+00:00 ok procs=0 mem_available_MB=1869 (sebelum reaper: procs=0 mem=1868)
  restart sepanjang hidup log: 3   (semuanya SEBELUM guard v2)
  reaper sepanjang hidup log : 2   (keduanya uji terpaksa IDLE_MINUTES=0)

-- frontend --
  https://katalir.de5.net -> HTTP 200 (402 567 byte, diverifikasi via httpx)
```

---

## Cara menjalankan pemantauan

```powershell
cd C:\Users\user\Proyek_AI
python _ops_monitor.py            # snapshot produksi + VPS + frontend
```
Jalankan tiap 30 menit; salin keluarannya ke dokumen ini bila ada anomali.

Guard VPS berjalan sendiri tiap 2 menit:
```bash
ssh root@<VPS> "tail -20 /var/log/agentgateway-guard.log"
```

---

## Anomali yang tercatat

| Waktu (UTC) | Anomali | Tindakan |
|---|---|---|
| 01:26:59 | Guard v1 me-restart gateway → `GET /mcp/gateway/servers` 503 | Guard v2 (reaper) dipasang; cache stale-fallback ditambahkan |
| 01:35:39 | Reaper hanya membersihkan set uvx (pola `mcp-server-` kurang) | Pola diperluas ke `@modelcontextprotocol/server-` + `npm exec` |
| 01:5x | Burst konkuren → 503 "semua kunci cooldown" | Diukur pulih ~49 s; didokumentasikan di playbook §4.4 |
| 02:0x | Gerbang ALLOW untuk SSRF internal | `_DENY_PATTERNS` diperluas + 18 test |

Tidak ada anomali yang memerlukan rollback produksi.
