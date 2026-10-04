# Keputusan Produk: Gmail Trigger (diperbarui 3 Oktober 2026)

> **DOKUMEN INI PERLU DIKOREKSI.** Versi pertama dokumen ini ditulis sebelum
> jalur IMAP ada, dan ia menyimpulkan "jangan implementasikan, butuh CASA".
> Kesimpulan itu SUDAH TIDAK BENAR. Lihat bagian "Koreksi" di bawah.

---

## Koreksi: Gmail trigger SUDAH ADA, tanpa CASA

Commit `b8095a8 feat(tools): trigger Gmail via IMAP (tanpa OAuth)`
mengimplementasikan `gmail_imap.py` (248 baris):

```
gmail_imap.py:52   IMAP_HOST = "imap.gmail.com"
gmail_imap.py:121  def trigger_gmail_imap(...)
gmail_imap.py:132  "Poll Gmail via IMAP dan kembalikan email baru sebagai dict."
gmail_imap.py:171  client = imaplib.IMAP4_SSL(...)
gmail_imap.py:61   def normalize_app_password(raw)
```

Wiring lengkap:
- `tools.py:741` deklarasi tool `trigger_gmail_imap`
- `tools.py:810` terdaftar di TOOL_DECLARATIONS
- `tools.py:1015` dispatcher
- `api_server.py:2461/2486/2505/2521` endpoint status / save / poll / delete
- `nexus-frontend/src/components/GmailImapCard.tsx` (166 baris) form di /settings

### Mengapa IMAP tidak butuh CASA

CASA (Cloud Application Security Assessment) mewajibkan aplikasi yang
meminta **OAuth restricted scope**. Jalur IMAP tidak memakai OAuth sama
sekali - user menempel **App Password** miliknya sendiri, yang diterbitkan
Google lewat halaman Akun Google.

Konsekuensi: tanpa OAuth app verification, tanpa CASA, tanpa biaya tahunan.

| | OAuth (Gmail scope) | IMAP + App Password |
| --- | --- | --- |
| Scope | `gmail.readonly` = RESTRICTED | tidak ada scope OAuth |
| CASA tahunan | ya | tidak |
| Verifikasi aplikasi | ya | tidak |
| Cara kerja | token OAuth | App Password + polling IMAP |

### Batasan IMAP yang harus jujur disampaikan

1. **App Password hanya bisa dibuat kalau 2-Step Verification aktif.** Itu
   syarat Google, bukan pilihan Katalir.
2. **Ini polling, bukan push.** `trigger_gmail_imap` melakukan poll lewat
   IMAP4_SSL. Latensi trigger mengikuti interval poll - bukan realtime push
   seperti Gmail API `users.watch` + Pub/Sub.
3. **App Password adalah kredensial nyata.** kartu di UI menyimpannya di
   vault terenkripsi dan tidak pernah menampilkannya lagi.
4. **IMAP adalah jalur yang lebih tua.** Google masih mendukungnya,
   tapi bukan jalur yang direkomendasikan Google untuk aplikasi baru.

---

## Yang TIDAK berubah: jalur OAuth Gmail tetap butuh CASA

Kalau nanti mau Gmail trigger lewat OAuth (atau akses inbox penuh lewat Gmail
API dengan push notification), itu tetap memerlukan:

| Scope | Klasifikasi | Yang dibutuhkan |
| --- | --- | --- |
| `gmail.readonly` | RESTRICTED | Google verification + CASA |
| `gmail.modify` | RESTRICTED | Google verification + CASA |
| `gmail.compose` | RESTRICTED | Google verification + CASA |
| `mail.google.com/` | RESTRICTED | Google verification + CASA |
| `gmail.send` | SENSITIVE | Brand verification saja |
| `gmail.labels` | Non-sensitive | tidak perlu verifikasi |

Catatan biaya: dokumentasi Google menyatakan restricted scope "must undergo an
annual security assessment by a Google-approved third party" tetapi TIDAK
mencantumkan harga di halaman publik. Angka $500-6000/tahun yang sering
dibahit adalah perkiraan pasar, bukan fakta yang bisa diverifikasi dari
dokumentasi resmi.

---

## Keputusan UI: kartu "comingSoon" dihapus

Saya sempat menambahkan kartu OAuth Gmail berlabel "Segera" dengan alasan CASA.
Kartu itu **dihapus**, karena:

1. Di halaman yang sama sudah ada `GmailImapCard` yang **benar-benar jalan**.
   Dua kartu Gmail - satu hidup, satu mati - hanya membingungkan.
2. Label "Segera" jadi berbohong: yang akan datang adalah jalur OAuth, sementara
   kebutuhan Gmail trigger sudah terpenuhi lewat IMAP.

Kalau jalur OAuth Gmail suatu saat dibuka, ia harus berupa tombol Connect yang
sungguhan - bukan label roadmap.

---

## Status sekarang

| Item | Status |
| --- | --- |
| Gmail trigger (IMAP + App Password) | jalan |
| Tombol OAuth Gmail yang tidak berfungsi | tidak ada |
| Kartu OAuth Gmail "Segera" | dihapus (berbohong) |
| Panduan prompt | ada (`docs/workflow-prompt-guide.md`) |
