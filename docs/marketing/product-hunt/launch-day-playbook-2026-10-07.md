# LAUNCH DAY PLAYBOOK — Katalir

**Tanggal: 7 Oktober 2026 · Launch 14:01 WIB (00:01 PST / 07:01 UTC)**

Dokumen ini ditulis malam sebelumnya (6 Okt) berdasarkan kondisi produksi yang
sudah diverifikasi: `/health` 200, `GET /mcp/gateway/servers` 44 tool,
workflow MCP end-to-end (`everything_echo`) berjalan, pytest 947 passed,
Playwright approval 15/15 + MCP 2/2.

---

## 1. TIMELINE HARI-H

### 13:00 WIB — Persiapan (T-60 menit)
- [ ] Jalankan `python _ops_monitor.py` → **ketiga baris produksi harus OK**
      (`/health` 200, `/workflows` 401, `/mcp/gateway/health` 200 `{"status":"ok"}`).
- [ ] Cek VPS: `agentgateway=active`, `guard_timer=active`, `mcp_procs` kecil,
      `mem_avail_MB` > 500.
- [ ] Cek commit aktif di Railway == commit `main` terakhir.
- [ ] Pastikan tidak ada deploy yang sedang berjalan (BUILDING/DEPLOYING).
- [ ] **Bekukan deployment**: tidak ada push ke `main` setelah 13:30 kecuali
      perbaikan darurat.

### 13:55 WIB — Final check (T-6 menit)
- [ ] `curl -s https://web-production-dc90b.up.railway.app/health` → 200
- [ ] `curl -I https://katalir.de5.net` → 200
- [ ] Buka `/chat` di browser (login) → kirim satu prompt uji: *"halo"* → dapat balasan.
- [ ] Buka `/builder` → pilih node MCP → daftar tool muncul (44 opsi).
- [ ] **Siapkan** tab Product Hunt, tab analytics, dan dokumen ini.

### 14:01 WIB — SUBMIT
- [ ] Submit Product Hunt.
- [ ] **Langsung** pasang komentar pertama (buat sendiri) — lihat §2.1.
- [ ] Pastikan tautan mengarah ke `https://katalir.de5.net` (bukan URL Railway).

### 14:05 WIB — Sebar
- [ ] Twitter/X thread (§3.1)
- [ ] LinkedIn post (§3.2)
- [ ] WhatsApp/Telegram announcement (§3.3)

### 14:30 WIB — Komentar #1
- [ ] Balas **semua** komentar dengan template §2.2.

### 16:00 WIB — Update status
- [ ] Post update di Product Hunt: jumlah upvote + satu insight teknis.

### 18:00 WIB — Update status
- [ ] Post update: milestone berikutnya, terima kasih, sebut satu fitur yang jarang disorot.

### 20:00 WIB — Ronde komentar
- [ ] Balas lagi semua komentar; prioritaskan yang bertanya teknis.

### 22:00 WIB — Laporan hari-1
- [ ] Tulis ringkasan: upvote akhir, jumlah komentar, jumlah user, error yang muncul.
- [ ] Catat semua bug yang dilaporkan → masukkan ke backlog dengan bukti.

---

## 2. RESPONS PRODUCT HUNT

### 2.1 Komentar pertama (pasang sendiri di 14:01)
```
Halo Product Hunt! 👋

Saya Verdi, pembuat Katalir. Katalir adalah kanvas otomasi di mana Anda
membangun workflow dengan BAHASA BIASA — lalu AI-nya menyusun node, sambungan,
dan konfigurasinya untuk Anda.

Tiga hal yang membuat kami berbeda:

1. MCP native. Kami tidak memakai satu katalog tertutup. Katalir terhubung ke
   server MCP sungguhan (agentgateway) dengan 44 tool hidup — filesystem, memory,
   fetch, time, dan konektor kami sendiri. Anda bisa memilih tool-nya dari
   dropdown di kanvas; nama tool yang tersimpan adalah nama tool yang benar-benar
   dieksekusi (mis. `everything_echo`).

2. Kredensial tidak pernah terlihat oleh model. Secret Anda didekripsi di
   server, hanya saat benar-benar dipakai. Agen tidak pernah menerima tokennya.

3. Persetujuan sebelum kirim ke luar. Setiap aksi yang mengirim data ke pihak
   ketiga (Telegram/Slack/email) memunculkan kartu persetujuan berisi argumen
   yang akan dikirim — bukan sekadar "yakin?".

Kami baru menyelesaikan audit integrasi MCP semalam: 44 tool terverifikasi
lewat `tools/list`, tool call `echo` berhasil end-to-end dari workflow, dan
suite keamanan 20/20 memblokir percobaan prompt-injection, SSRF, homoglyph, dan
cross-tenant.

Saya di sini sepanjang hari — tanya apa saja, termasuk yang teknis. 🙏
```

### 2.2 Template balasan komentar

**Apresiasi (semua komentar, tanpa kecuali)**
```
Terima kasih sudah mampir dan meninggalkan komentar! 🙏
```

**Pertanyaan teknis — jawab konkret, sebut angka**
```
Pertanyaan bagus. Konkretnya: [JAWABAN].

Kalau berguna, ini detailnya: [angka/arsitektur singkat].
Saya bisa jelaskan bagian mana pun lebih dalam — mau yang mana?
```

**Pertanyaan "apa bedanya dengan n8n / Zapier / Make?"**
```
Pertanyaan yang paling sering muncul, dan wajar.

n8n/Zapier/Make sangat kuat untuk ALUR yang sudah Anda tahu bentuknya.
Katalir dimulai dari INTENSI: Anda menulis "setiap pagi ambil data dari API
lalu kirim ke Telegram", dan kanvasnya terisi sendiri — node, sambungan, dan
konfigurasi, dengan placeholder untuk nilai yang belum Anda sebutkan.

Bedanya juga di lapisan MCP: kami tidak mengunci Anda ke katalog milik kami.
Server MCP apa pun yang Anda punya bisa dipakai.

Jujurnya: untuk orkestrasi tingkat perusahaan yang butuh ratusan konektor
matang, n8n masih lebih dalam. Kami menang di waktu-dari-ide-ke-workflow.
```

**Laporan bug**
```
Terima kasih sudah melaporkan ini — dan maaf Anda mengalaminya.

Yang saya pahami: [ULANGI GEJALA DENGAN KATA SENDIRI].
Saya sudah cek [bagian yang relevan]; sekarang saya telusuri.

ETA: [perkiraan jujur]. Saya balas lagi di utas ini begitu ada kabar, termasuk
kalau ternyata penyebabnya bukan seperti dugaan awal saya.
```
> **Aturan:** jangan pernah bilang "sudah diperbaiki" sebelum Anda benar-benar
> melihat perbaikannya bekerja di produksi. Sebut apa yang sudah Anda lakukan
> dan apa yang belum.

**Kritik / ketidaksetujuan**
```
Kritik yang adil, terima kasih sudah menyampaikannya terus terang.

Saya setuju dengan [bagian yang memang benar]. Untuk [bagian yang belum
sependapat], alasan kami begini: [ALASAN] — tapi itu keputusan yang bisa
berubah kalau ternyata salah.

Yang belum ada sekarang: [JUJUR SEBUTKAN YANG BELUM ADA].
Roadmap: [URUTAN YANG REALISTIS].
```

**Harga**
```
Saat ini [MODEL HARGA]. Bagi yang mendaftar dari Product Hunt hari ini,
[PENAWARAN BILA ADA — JANGAN menjanjikan yang tidak bisa Anda tepati].
```

**Kompetitor yang lebih murah**
```
Cek saja — beberapa memang lebih murah untuk kasus tertentu, dan saya tidak
akan mengarang alasan untuk menahan Anda. Yang bisa saya tawarkan: [NILAI NYATA].
Kalau setelah mencoba ternyata bukan untuk Anda, itu juga jawaban yang sah.
```

---

## 3. KONTEN SOSIAL

### 3.1 Twitter/X thread (5 tweet)

**1/5**
```
Hari ini kami meluncurkan Katalir di @ProductHunt 🚀

Kanvas otomasi di mana Anda menulis "setiap pagi ambil data dari API lalu
kirim ke Telegram" — dan workflow-nya tersusun sendiri.

Tapi yang ingin saya ceritakan adalah apa yang kami temukan semalam. 🧵
```

**2/5**
```
Kami mengaudit integrasi MCP kami. 44 tool hidup lewat agentgateway.

Awalnya model MENOLAK memakai katalog itu: diminta "pakai MCP tool echo", ia
mengarang panggilan HTTP ke https://echo.free.beeceptor.com — URL yang tidak
pernah ada.

Akar masalahnya: model tidak tahu katalognya ada.
```

**3/5**
```
Perbaikannya bukan menambah tool, tapi memberi tahu model apa yang sudah ada:
katalog 44 nama disuntikkan ke system prompt.

Caranya harus hati-hati. `initialize` ke gateway butuh 8-13 detik, dan system
prompt dibangun SETIAP request. Jadi katalognya diisi thread latar, dan request
hanya membaca cache.
```

**4/5**
```
Temuan kedua lebih menyakitkan: endpoint katalog membalas 503 saat gateway
sedang tidak bisa dihubungi — pemilih tool di UI langsung mati, padahal daftar
44 tool nyaris tidak pernah berubah.

Sekarang: cache 30 menit + fallback ke data lama. 503 hanya kalau benar-benar
belum ada data. 11 detik → milidetik.
```

**5/5**
```
Kami juga uji keamanannya secara adversarial: 20 kasus — prompt injection,
SSRF ke metadata cloud, homoglyph Cyrillic, zero-width, cross-tenant.

Hasil: 20/20 diblokir. Dua celah ditemukan malam ini dan sudah ditutup.

Katalir hari ini di Product Hunt. Tanya apa saja 👇
https://katalir.de5.net
```

### 3.2 LinkedIn

```
Hari ini saya meluncurkan Katalir.

Masalahnya sederhana: membuat otomasi seharusnya semudah menuliskannya.
Anda menulis "setiap pagi ambil data dari API lalu kirim ke Telegram", dan
kanvasnya terisi sendiri — node, sambungan, konfigurasi.

Yang membuat saya bangga bukan fiturnya, tapi audit malam terakhir sebelum
peluncuran.

Kami menemukan bahwa model bahasa kami menolak memakai katalog tool MCP kami
sendiri. Diminta memakai tool "echo", ia malah mengarang panggilan HTTP ke URL
yang tidak pernah ada. Bukan karena katalognya kosong — 44 tool hidup di sana —
tapi karena model tidak pernah diberi tahu.

Lalu kami menemukan endpoint katalog membalas 503 ketika gateway sedang sibuk,
sehingga pemilih tool di antarmuka mati total. Daftar 44 tool yang nyaris tidak
pernah berubah itu kami cache, dengan fallback ke data lama: 11 detik menjadi
milidetik, dan 503 hanya muncul kalau benar-benar belum ada data sama sekali.

Terakhir, kami menyerang sistem kami sendiri: 20 kasus injeksi prompt, SSRF ke
endpoint metadata cloud, homoglyph Sirilik, karakter zero-width, dan percobaan
menembus data pengguna lain. Dua celah ditemukan dan ditutup pada malam yang sama.

Pelajaran yang saya ambil: "sudah terintegrasi" dan "terbukti bekerja" adalah
dua klaim yang sangat berbeda. Yang pertama bisa Anda tulis di README; yang
kedua butuh output mentah, angka, dan keberanian mengakui apa yang belum diuji.

Katalir hari ini di Product Hunt. Saya senang menjawab pertanyaan teknis.
https://katalir.de5.net
```

### 3.3 WhatsApp / Telegram

```
Halo semuanya! Hari ini Katalir resmi diluncurkan di Product Hunt 🚀

Katalir = kanvas otomasi yang dibangun dengan bahasa biasa. Tulis alurnya,
AI-nya menyusun workflow-nya. MCP native, kredensial Anda tidak pernah
dilihat model, dan setiap kirim ke luar butuh persetujuan Anda.

Kalau sempat mampir dan kasih masukan, saya sangat berterima kasih 🙏
https://katalir.de5.net
```

---

## 4. KONTAK & TINDAKAN DARURAT

### 4.1 Kalau produksi mati total
1. Cek `curl -s .../health` dan `curl -I https://katalir.de5.net`.
2. Cek Railway: apakah deploy terakhir `SUCCESS`?
   ```
   python _ops_verify_deploy.py <commit-7-char>
   ```
3. **Rollback backend**: di Railway, redeploy deployment terakhir yang
   `SUCCESS` sebelum commit terakhir. Commit yang diketahui baik:
   * `cb9b7a6` — UI tool selector + katalog MCP di prompt (terverifikasi produksi)
   * `94e27c4` — cache + prefilter + SSRF (terverifikasi produksi)
   * `065fc731` — baseline sebelum pekerjaan MCP (paling konservatif)
4. **Rollback frontend**: `python nexus-frontend/_deploy_pages.py` setelah
   `git checkout <commit-baik> -- nexus-frontend` lalu build ulang.
   Catatan: Pages tidak punya riwayat versi di repo ini, jadi simpan `out/`
   yang diketahui baik bila perlu.
5. Umumkan di Product Hunt: *"Kami sedang memperbaiki gangguan; kabar menyusul."*
   — jangan diam.

### 4.2 Kalau MCP / gateway bermasalah
```bash
# 1. Lihat kondisi
ssh root@<VPS> "systemctl is-active agentgateway; tail -5 /var/log/agentgateway-guard.log"

# 2. Bersihkan set proses terlantar (TANPA restart, tanpa downtime)
ssh root@<VPS> "IDLE_MINUTES=0 /opt/agentgateway/agentgateway-guard.sh"

# 3. Kalau masih buruk, restart service (ini MENYEBABKAN 503 sesaat)
ssh root@<VPS> "systemctl restart agentgateway"

# 4. Verifikasi
curl -s -H "Authorization: Bearer $JWT" .../mcp/gateway/health   # harus {"status":"ok"}
curl -s -H "Authorization: Bearer $JWT" .../mcp/gateway/servers  # harus 44 tool
```
Rollback guard ke versi v1 (restart-based) bila reaper bermasalah:
```bash
ssh root@<VPS> "cp /opt/agentgateway/agentgateway-guard.sh.v1.bak /opt/agentgateway/agentgateway-guard.sh"
```

### 4.3 Kalau Railway error / deploy gagal
```
python scripts/security/railway_vars.py --list      # cek env ada (nilai tidak dicetak)
python _ops_verify_deploy.py <commit>               # status deployment
```
Pastikan `AGENTGATEWAY_URL` dan `AGENTGATEWAY_TOKEN` masih ada (keduanya **wajib**;
`GatewayClient` gagal-tertutup tanpa token).

### 4.4 Kalau chat membalas 503 "semua kunci cooldown"
**Ini transien — terukur pulih dalam ~49 detik.** Jangan panik, jangan rollback.
* Minta pengguna mencoba lagi sebentar (klien sudah retry 2×, backoff 2 s + 5 s).
* Bila berulang terus sepanjang hari, tambahkan `GEMINI_KEY_*` baru
  (kuota RPM naik berbanding jumlah kunci) → set env di Railway → redeploy.

### 4.5 Nomor/akun darurat
| Layanan | Akses |
|---|---|
| Railway | project `sunny-vibrancy` → service `web` (env production) |
| Cloudflare Pages | project `proyek-agent` (deploy via `_deploy_pages.py`) |
| VPS | `ssh $VPS_USERNAME@$VPS_IP` (kredensial di `.env`) |
| Supabase | `SUPABASE_URL` di `.env` (jangan pernah dicetak) |

---

## 5. YANG **TIDAK** BOLEH DILAKUKAN HARI INI

1. **Jangan deploy fitur baru.** Hanya perbaikan darurat.
2. **Jangan `git push` setelah 13:30** kecuali darurat — setiap push memicu
   deploy Railway (~2 menit) dan mengganti commit aktif.
3. **Jangan upgrade agentgateway** ke 1.6.0 hari ini (lihat
   `docs/OVERNIGHT-REPORT-2026-10-07.md` §Task 1: tidak ada bukti changelog
   bahwa ia memperbaiki kebocoran proses; risikonya tidak sepadan saat launch).
4. **Jangan hapus data produksi** atau menjalankan migrasi.
5. **Jangan `git push --force`.**
6. **Jangan menjanjikan fitur di kolom komentar** yang belum ada di roadmap.
