# Launch-Eve Monitoring — 7 Oktober 2026

**Launch:** 8 Oktober 2026 · **Backend:** `https://web-production-dc90b.up.railway.app`
**Commit produksi:** `006c86f` (HEAD == origin/main)

> **Transparansi cakupan.** Brief meminta cek 3× (pagi, siang, malam).
> Sesi ini berjalan **19:35**, jadi hanya slot **malam** yang dapat dijalankan;
> slot pagi & siang sudah lewat sebelum sesi dimulai dan **tidak** direkonstruksi
> (data retroaktif akan mengarang). Otomasi 3× harian dibuat agar slot berikutnya
> benar-benar tereksekusi (§4).

---

## 1. Slot MALAM — 2026-10-07 19:35 (SEAST)

### 1.1 Endpoint produksi

```
GET /health             -> HTTP 200   1.556s
  {"status":"ok","persistence":{"status":"persisted","backend":"supabase",
   "url":"https://qmukkphwaajzbqjrcvaz.supabase.co"}}

GET /workflows          -> HTTP 401   0.694s
  {"detail":"Token wajib (Authorization: Bearer <jwt>)."}

GET /mcp/gateway/health -> HTTP 401   7.792s
  {"detail":"Token wajib (Authorization: Bearer <jwt>)."}
```

| Cek | Harapan | Hasil | Status |
|---|---|---|---|
| `GET /health` | 200 | **200** · persistence `persisted` (supabase) | ✅ |
| `GET /workflows` | 401 | **401** | ✅ |
| MCP `/mcp/gateway/health` | ok | **401** (butuh JWT) | ⚠️ tidak dapat diverifikasi tanpa token |

Catatan: persistence **`persisted`** (bukan fallback memori) — jalur tulis Supabase
sehat. `/mcp/gateway/health` menuntut autentikasi, jadi "ok"-nya tidak bisa
dibuktikan tanpa JWT user; yang terbukti adalah **endpoint hidup** (menjawab 401).

### 1.2 VPS (proses / memory / load) — TIDAK DAPAT DIAMBIL

```
ssh       : ADA
sshpass   : TIDAK ADA
plink     : TIDAK ADA
TCP VPS:22: TERBUKA
SSH BatchMode: Permission denied (publickey,password)
```

Port 22 terbuka, tetapi kunci lokal tidak diotorisasi di VPS dan tidak ada
`sshpass`/`plink` untuk autentikasi password non-interaktif. **Metrik
proses/memory/load VPS tidak dapat diambil dari lingkungan ini.** Ini keterbatasan
lingkungan, bukan indikasi VPS mati (lihat §1.3: VPS jelas hidup).

### 1.3 Indikator tidak langsung: gateway LLM (berjalan di VPS)

```
host LLM_GATEWAY_URL : nexus-gateway-vps.tail7f0d5a.ts.net

tanpa auth:
  #1 HTTP 401   1.898s   41B
  #2 HTTP 401  14.189s   41B

dengan auth:
  #1 HTTP 200  25.007s  45056B   <- menyentuh batas --max-time 25s
  #2 HTTP 200  20.920s  74354B
  #3 HTTP 200  25.005s  36858B   <- menyentuh batas --max-time 25s
```

**VPS hidup** (endpoint menjawab). Tetapi latensi **sangat buruk dan tidak
konsisten**: 1,9s → 14,2s tanpa auth; **20–25s** dengan auth. Ukuran respons untuk
endpoint yang sama bervariasi 36–74 KB.

---

## 2. ANOMALI

| # | Anomali | Bukti | Dampak | Tingkat |
|---|---|---|---|---|
| A-1 | **Latensi gateway memburuk drastis** | `/v1/models` butuh **20–25s** (sesi 7 Okt pagi: **2,69s**) | Node agent lambat; sudah dimitigasi rantai cadangan Opsi C | 🟠 TINGGI |
| A-2 | **Latensi tidak konsisten** | 1,9s vs 14,2s untuk request 401 yang sama | Sulit diprediksi; timeout bisa acak | 🟠 TINGGI |
| A-3 | **Ukuran respons tak konsisten** | 45056B / 74354B / 36858B untuk `/v1/models` | Gateway tampak merakit roster per-request (memanggil upstream yang menggantung) | 🟡 SEDANG |
| A-4 | `/mcp/gateway/health` 7,79s untuk 401 | §1.1 | Endpoint auth pun lambat | 🟡 SEDANG |
| A-5 | Metrik VPS tak terambil | §1.2 | Monitoring VPS buta menjelang launch | 🟡 SEDANG |

**Tidak ada anomali pada endpoint inti**: `/health` 200 dan persistence
`persisted`; `/workflows` menolak dengan benar (401). **Tidak ada 5xx.**

A-1/A-2 konsisten dengan risiko residual **R-1** di
`docs/security/launch-ready-v2-2026-10-07.md` (gateway self-hosted degraded).
Karena produk sudah **tidak bergantung** pada gateway (rantai cadangan
`gemini_pool → groq → nvidia → github`), A-1 **tidak memblokir launch**, tetapi
menaikkan latensi node agent.

---

## 3. KESIMPULAN SLOT MALAM

- Endpoint produksi inti: **SEHAT** (200 / 401 sesuai kontrak, persistence
  `persisted`, 0×5xx).
- Gateway LLM di VPS: **hidup tetapi degraded berat** (20–25s) — risiko
  operasional, bukan blocker (lihat R-1).
- Metrik VPS: **tidak dapat diverifikasi** dari lingkungan ini.

**Verdict slot malam: PASS dengan 1 catatan operasional (A-1).**

---

## 4. OTOMASI 3× HARIAN (agar slot pagi/siang/malam benar-benar jalan)

Dibuat otomasi **`375e771c-7880-4307-bcea-e64841ab2c05`** — *Katalir — health
check produksi 3x harian (launch 8 Okt)*.

- **Jadwal:** setiap **8 jam** (≈ 3× sehari: 00:00, 08:00, 16:00) — 3× per hari.
- **Aktif:** 2026-10-07 s/d 2026-10-09.
- **Aksi:** `/health` (200 + `persisted`), `/workflows` (401), MCP gateway,
  latensi gateway LLM, SSH VPS; menulis ke dokumen monitoring harian dan
  melaporkan anomali (5xx / non-200-401 / latensi > 10s).

**Catatan penyimpangan:** `rrule` yang divalidasi tool menolak `BYHOUR` bernilai
ganda (koma), sehingga jadwal "08:00, 13:00, 20:00" tidak bisa diekspresikan
dalam satu aturan. Dipakai `INTERVAL=8` — tetap **3× sehari** dan justru lebih
merata. Hapus otomasi ini bila tidak diperlukan lagi setelah launch.

---

## 5. LAMPIRAN — Perintah mentah

```bash
curl -s -o /dev/null -w "HTTP %{http_code} %{time_total}s" $B/health
curl -s -o /dev/null -w "HTTP %{http_code} %{time_total}s" $B/workflows
curl -s -o /dev/null -w "HTTP %{http_code} %{time_total}s" $B/mcp/gateway/health
curl -s -o /dev/null -w "HTTP %{http_code} %{time_total}s" --max-time 25 \
     -H "Authorization: Bearer <LLM_GATEWAY_KEY>" $GW/v1/models
ssh -o BatchMode=yes -o ConnectTimeout=8 <VPS_USERNAME>@<VPS_IP> 'uptime'
```

Tidak ada kredensial yang dicetak dalam dokumen ini.
