# Panduan Prompt Workflow Builder

Cara menulis prompt agar Katalir menghasilkan workflow yang langsung bisa jalan.
Prinsip-prinsip di bawah disusun dari perilaku validator Katalir
(`workflow_spec.py`) dan `provider_registry.REQUIRED_CONFIG` - bukan dari
prinsip umum.

---

## 5 prinsip

### 1. Pikir iteratif, jangan minta kompleks sekaligus

Katalir punya dua tahap: **DISCOVERY** (model wajib bertanya klarifikasi bila
detail belum lengkap) lalu **build**. Jadi Anda tidak perlu menulis spesifikasi
lengkap di satu pesan. Minta satu alur, lihat hasilnya, lalu tambahkan langkah berikutnya.

Pertanyaan yang baik: "Buat workflow kirim email ringkasan tiap Jumat sore."
Setelah jadi: "Tambahkan langkah tulis rekap ke Google Sheets."

### 2. Sebut integrasi secara spesifik

Validator menolak workflow yang config-nya tidak lengkap. Field yang wajib ada
per provider (`provider_registry.REQUIRED_CONFIG`):

| Provider | Field wajib |
| `gmail` | `tujuan`, `subjek` |
| `google_sheets` | `spreadsheet_id` |
| `google_calendar` | `nama_acara`, `waktu` |
| `whatsapp` | `nomor_tujuan` |
| `http` | `url` |

Jadi "kirim ke email" tidak akan menghasilkan workflow yang jalan - nama
provider-nya tidak jelas. Sebut "Gmail", "Slack", "Telegram".

**Penting:** tujuan (`chat_id`, `channel`, `spreadsheet_id`, `tujuan`) TIDAK
boleh dikarang. Katalir akan bertanya, dan itu benar. Anda harus memberi nilai
aslinya.


Sebutkan sumbernya, apa yang dilakukan padanya, lalu ke mana hasilnya dikirim.

### 4. Prompt pendek lebih efektif

Tidak ada batas keras, tapi prompt 1-2 kalimat yang sudah menyebut provider dan
tujuan biasanya langsung lolos validasi. Prompt panjang cenderung memuat
provider yang tidak terdaftar.

### 5. Tidak perlu berpura-pura

Tidak perlu menulis peran ("Kamu adalah ahli otomasi..."). Yang menentukan
kualitas draf adalah kelengkapan config, bukan gaya bahasa.

---

## Contoh: prompt buruk vs baik

### Contoh 1 - email

**Buruk:**
```
Get my emails, summarize, save to table
```
Masalah: provider tidak disebut; `spreadsheet_id` tidak ada; tidak jelas
disimpan ke mana.

**Baik:**
```
Ambil 10 email terbaru dari Gmail, kirim isinya ke node agent untuk diringkas
dalam 3 poin, lalu tulis hasil ke Google Sheets dengan kolom: tanggal, pengirim,
ringkasan.
```

### Contoh 2 - email terjadwal

**Buruk:**
```
Send emails to my team every friday
```
Masalah: jadwal kurang spesifik; `tujuan` tidak ada.

**Baik:**
```
Setiap Jumat jam 17:00, kirim email ke tim@example.com dengan subjek
"Ringkasan Aktivitas Minggu Ini", isi ringkasan dari node agent sebelumnya.
```

### Contoh 3 - bersyarat

**Buruk:**
```
If inventory low then alert me
```
Masalah: "low" tidak terdefinisi; provider WhatsApp tidak disebut.

**Baik:**
```
Baca stok dari Google Sheets (kolom "stok"), lalu untuk setiap baris dengan
stok di bawah 10, kirim pesan ke WhatsApp nomor 628123456789 berisi nama barang
dan stoknya.
```

### Contoh 4 - provider yang belum didukung

**Baik (menyatakan batas dengan jujur):**
```
Setiap hari jam 08:00 kirim ringkasan berita ke Telegram chat_id 123456.
```
Sebelum menulis ini, cek halaman Integrasi: provider yang tidak punya jalur
kredensial bawaan akan mendapat **warning**, bukan error, dan tool-nya tidak
bisa dieksekusi. Lihat `docs/oauth/provider-status.md` untuk status lengkap.

---

## Yang akan Anda terima dari Katalir

| Situasi | Yang terjadi |
| --- | --- |
| Prompt kurang detail | Model bertanya klarifikasi (maks 2-5 pertanyaan) |
| Config provider kurang | Draf **ditolak** dengan pesan menyebut node + field yang kurang |
| Edge menuju node yang tidak ada | Draf **ditolak** - ini lebih baik daripada menggambar garis hantu |
| Provider belum punya jalur kredensial | Draf diterima dengan **warning**, bukan error |
| Prompt mustahil | Pesan jelas, bukan diam |

Yang TIDAK akan terjadi: workflow diam-diam ditambahkan ke kanvas dalam keadaan
tidak bisa dijalankan. Validasi berjalan sebelum draf diterima.

---

## Batasan yang perlu diketahui

- **Node `agent` BISA dijalankan oleh paket Free.** Paket gratis memberi jatah
  kredit bulanan untuk node agent (100 kredit/bulan); batas yang benar-benar
  berlaku adalah jendela **10 percakapan / 22 jam** yang ditegakkan
  `execution_engine.guard_execution`. Sebelum perbaikan 7 Okt 2026 ada dua
  aturan yang bertentangan — gembok resmi mengizinkan tier Free, tetapi cek
  saldo lama menuntut `saldo > 0` sehingga user gratis (tanpa baris
  `user_balances`, saldo terbaca 0.0) **selalu** ditolak `"Saldo habis"` dan
  tidak pernah bisa memakai node agent sama sekali. Cek saldo kini hanya
  berlaku untuk tier Plus (`model: deepseek-flash`), yang memang membayar per
  pemakaian.
- **Gmail trigger tersedia lewat IMAP + App Password**, bukan lewat OAuth.
  Jadi tidak perlu CASA. Ikuti kartu "Gmail" di halaman Pengaturan.
  Kalau OAuth Gmail (push notification) yang diinginkan, itu tetap butuh
  CASA. Lihat `docs/oauth/gmail-decision.md`.
- **Provider yang didukung saat ini:** `telegram`, `gmail`, `google_sheets`, `google_calendar`, `slack`, `http`,
  `whatsapp`.
- **Tidak ada conditional/loop di spec saat ini.** Node hanya tiga jenis:
  `trigger`, `agent`, `mcp`. Percabangan IF/ELSE harus disimulasikan lewat
  node agent - belum ada node branch khusus.
