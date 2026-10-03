# Status Provider & OAuth

Diaudit 2026-09-28. Semua isi di sini diverifikasi terhadap source, bukan
disalin dari tampilan layar. Dua klaim yang sebelumnya dipakai ternyata salah,
dan dikoreksi di bawah beserta alasannya.

## Ringkas

Ada dua alur OAuth, dan itu memang sesuai desain. Tapi angka "2 OAuth /
2 manual / 1 deferred" yang pernah dipakai sebelumnya tidak akurat: satu
provider salah dikategorikan (HTTP), dan tiga provider lain tidak tercatat.

| Provider | Jenis | Status | Tempat token |
| --- | --- | --- | --- |
| Google Sheets | oauth | ready | `/oauth/google/authorize` -> `user_vault[google_sheets]` |
| Slack | oauth | ready | `/oauth/slack/authorize` -> `user_vault[slack]` |
| Gmail | manual | broken end-to-end | `POST /integrations` (tanpa UI) |
| Google Calendar | manual | broken end-to-end | `POST /integrations` (tanpa UI) |
| Telegram | manual | works, tanpa UI | `POST /integrations` (tanpa UI) |
| WhatsApp | manual | ready | form kredensial `/settings` |
| HTTP request | tanpa auth | ready | tidak butuh kredensial |
| Groq / OpenAI / Gemini / Custom LLM | manual | ready | form kredensial `/settings` |

## 1. Kenapa hanya dua kartu OAuth

Karena hanya ada dua alur OAuth yang benar-benar diimplementasikan:

- `oauth_google.py` -- Authorization Code + PKCE, scope `auth/spreadsheets`
- `oauth_slack.py` -- Authorization Code, scope `chat:write, channels:read, users:read`

Keduanya jalan di produksi: `GET /oauth/slack/status` pada
`web-production-dc90b.up.railway.app` membalas `keys_present: 5, keys_total: 5`.

### Koreksi: Gmail bukan sekadar "deferred karena restricted scope"

Klaim sebelumnya menyebut Gmail butuh restricted scope plus verifikasi
Google, lalu ditunda. Itu sebagian benar, tapi menutupi bug yang lebih serius.

`api_server._oauth_providers` pernah memuat `gmail` dan `google_calendar`,
keduanya diarahkan ke `/oauth/google/authorize`. Itu janji palsu, dengan dua
sebab yang berdiri sendiri:

1. **Scope tidak pernah diminta.** `oauth_google.build_authorize_url`
   meng-hardcode `scope` menjadi `SHEETS_SCOPE`
   (`https://www.googleapis.com/auth/spreadsheets`). Consent screen tidak
   pernah meminta izin Gmail maupun Calendar.
2. **Store kredensialnya berbeda.** `kirim_email_gmail` membaca
   `db.get_integration(email, "gmail")`, sedangkan token OAuth disimpan di
   `user_vault` dengan provider `google_sheets`. Bahkan kalau scope ditambah,
   token itu secara struktur tetap tidak akan dipakai.

Jadi user yang butuh Gmail diberi tombol "Connect", menyetujuinya, melihat
"Connected", lalu tool-nya tetap gagal. Itu lebih buruk daripada tidak
menawarkannya sama sekali.

**Perbaikan:** `gmail` dan `google_calendar` dikeluarkan dari
`_oauth_providers`, sehingga keduanya jatuh ke `needs_credential` -- jujur
walaupun form manual belum punya entri untuk mereka. Dijaga oleh
`tests/test_oauth_provider_honesty.py`.

Koreksi ini TIDAK membuat Gmail berfungsi. Itu tetap butuh pekerjaan nyata:
tambah scope, samakan store kredensial, dan menyelesaikan verifikasi Google.
Yang berubah adalah produk berhenti promising sesuatu yang tidak bisa diberikan.

## 2. Kenapa "Not connected" padahal ada di stored credentials

Ini bukan dua sumber data. Semua credential tinggal di satu tabel `user_vault`
dengan kunci `(email, provider)`. Yang berbeda adalah seberapa dalam
masing-masing pembacaan:

| Layar | Endpoint | Seberapa dalam |
| --- | --- | --- |
| Stored credentials | `GET /api/vault/list` | `SELECT provider` saja, tidak pernah dekripsi |
| Kartu OAuth | `GET /oauth/{id}/status` | `vault_get` lalu `decrypt_key` lalu `json.loads` |

Artinya baris bisa ada (terlihat di daftar) tapi tidak terbaca (gagal di
status). `oauth_google.load_tokens` menelan setiap exception dan mengembalikan
`None`, sehingga tiga kondisi berikut menyatu menjadi satu boolean `false`
yang sama di UI:

1. belum pernah connect (memang tidak ada baris)
2. baris ada, ciphertext tidak terbaca -- misalnya `VAULT_SECRET_KEY` berganti
3. baris ada, isinya bukan blob token OAuth

Kasus 2 dan 3 adalah "pernah connect lalu rusak", tapi UI menampilkan "Not
connected" dan mengarahkan user ke layar consent. Kalau kuncinya memang
berganti, consent baru akan menimpa baris itu tanpa menjelaskan kenapa yang
lama hilang.

Dinyatakan terbuka: test
`test_status_tidak_bisa_membedakan_tidak_ada_dan_tidak_terbaca` membuktikan
ambiguitas ini masih ada. Testnya sengaja ditulis sebagai dokumentasi defect
yang belum diperbaiki. Begitu backend menambah field `stored` atau
`unreadable`, test itu akan gagal dengan pesan yang menyuruh menghapus testnya
dan memperbarui dokumen ini.

### Langkah diagnosis

Tidak bisa dipastikan tanpa JWT akun tersebut, tapi urutan pemeriksaan ini
paling murah:

1. Cek apakah `VAULT_SECRET_KEY` pernah berganti setelah token disimpan.
   Rotasi kunci membuat setiap token lama tidak terbaca.
2. Kalau tidak pernah berganti, coba connect ulang lewat consent. Kalau
   setelah itu tetap "Not connected" padahal barisnya ada, problemnya di
   jalur callback, bukan di endpoint status.


## 3. HTTP bukan "manual paste"

Klaim sebelumnya menyebut HTTP sebagai manual paste. Itu keliru.
`tools.http_request` sengaja tidak memakai kredensial apa pun; docstring-nya
sendiri menyatakan token provider tidak dipakai di sana. Yang dilakukan hanya
validasi bentuk URL, whitelist method, dan SSRF guard.

Jadi HTTP tidak masuk hitungan provider. Kalau tetap dihitung, kategorinya
"tanpa auth", bukan "manual".

## 4. Yang belum punya UI

Tiga provider punya jalur teknis tapi tidak punya tempat diketik di UI Next.js:
`gmail`, `google_calendar`, dan `telegram`. Semuanya bisa disimpan lewat
`POST /integrations` (`db.save_integration`), tapi form kredensial di
`/settings` hanya menawarkan `groq`, `openai`, `gemini`, `whatsapp`, dan
`custom_llm`.

Halaman integrasi yang menaruh gmail, google_sheets, dan nvidia ada di
`app_frontend.py`. Itu Streamlit, dan `ARCHITECTURE_REPORT.txt` sudah
menandainya sebagai legacy dan mati di produksi. Bagi user SaaS saat ini,
ketiga provider itu praktis tidak bisa dikonfigurasi.

Kartu "Other integrations" adalah langkah yang benar, tapi cakupannya harus
gmail, google_calendar, dan telegram, bukan hanya Telegram dan HTTP.

## 5. Yang belum terverifikasi

 consenting OAuth di produksi belum diuji. Butuh browser dan akun asli, jadi
tidak bisa dibuktikan dari sini. Yang sudah terverifikasi:

- `GET /health` -> `200`, persistence `supabase`
- `GET /oauth/slack/status` -> `200`, `keys_present: 5/5`, `implemented: true`
- `GET /oauth/google/status` -> `401` (memerlukan JWT, perilaku yang benar)

Yang masih perlu orang sungguhan: menyelesaikan consent Google Sheets dan
Slack, lalu memastikan badge berubah menjadi "Connected".


---

## Update 2026-10-03 — verifikasi "Gmail trigger multi-tenant"

Tugas: buktikan apakah Gmail trigger benar-benar multi-tenant. Jawabannya:
**belum, dan tidak dapat dibuktikan sekarang.** Yang ditemukan justru satu
cacat nyata yang sebelumnya belum terdeteksi.

### Tidak ada "Gmail trigger" sama sekali

Pencarian menyeluruh (semua `.py`) tidak menemukan tool inbox/polling Gmail.
Yang ada hanya `kirim_email_gmail`, dan itu tool **kirim** (bukan trigger), serta
masih **simulasi**:

```
tools.py:136  def kirim_email_gmail(...):
tools.py:137      """Kirim email via Gmail (simulasi)."""
tools.py:141      return f"Email terkirim ke {tujuan} ..."   # tidak memanggil API
```

Tidak ada `Gmail watch`, tidak ada polling, tidak ada push notification
(`historyId`/Pub/Sub) di mana pun. Jadi tidak ada yang bisa disebut
"multi-tenant" — trigger-nya belum ada.

### Tidak ada token Gmail sama sekali

```
user_vault:  3 baris  -> {openai: 1, google_sheets: 1, slack: 1}
             provider='gmail' : 0
user_integrations: 0 baris
```

Provider `google_sheets` yang ada milik `verdi0377@gmail.com` (key terenkripsi
panjang 888 karakter). Token itu **tidak punya scope Gmail** — hanya
`auth/spreadsheets` (`oauth_google.SHEETS_SCOPE`, satu-satunya scope yang
dikirim consent).

### Yang SEBENARNYA multi-tenant (dan bisa dibuktikan)

Resolusi token Google **benar-benar per-user**, terenkripsi, dan tidak pernah
lintas user:

| Bukti | Hasil |
| --- | --- |
| `vault_save` / `vault_get` | `.eq("email", email).eq("provider", provider)` — PK komposit |
| `user_vault` rows | 3 user berbeda, ciphertext berbeda, tidak saling bocor |
| `oauth_google.access_token(email)` | token diambil berdasarkan email pemanggil |
| `dispatcher` | meneruskan `email=email` ke setiap tool |
| user tanpa token | `CredentialMissingError`, **tidak** memakai token orang lain |

Jadi multi-tenancy-nya ada **di lapisan penyimpanan**, bukan di Gmail karena
Gmail-nya sendiri belum punya akses.

### CACAT BARU YANG DITEMUKAN: tombol Connect palsu untuk Gmail

Audit 2026-09-28 sudah menghapus `gmail` dari `_oauth_providers` di
`api_server.py`. Namun `tools.OAUTH_CONNECT_URLS` **lupa** dan masih
memuat:

```
tools.py:743  OAUTH_CONNECT_URLS = {
tools.py:744      "google_sheets": "/oauth/google/authorize",
tools.py:745      "gmail":         "/oauth/google/authorize",   <-- janji kosong
tools.py:746      "google_calendar": "/oauth/google/authorize", <-- janji kosong
```

Dampaknya persis yang dijelaskan audit itu: `execute_tool("kirim_email_gmail")`
mengembalikan `{"status": "needs_oauth", "connect_url": ...}` sehingga UI
menampilkan tombol "Connect". User menekan, menyetujui consent screen yang
hanya meminta izin Sheets, melihat "Connected", lalu tool tetap gagal.

**Perbaikan:** `gmail` dan `google_calendar` dihapus juga dari
`tools.OAUTH_CONNECT_URLS`. Keduanya kini melempar `CredentialMissingError` ->
`needs_credential`, yang jujur walaupun form manual belum punya entri gmail.
Diperbarui: `tests/test_needs_oauth.py` (2 kasus-parametris dihapus, dengan
alasan tertulis) dan dikunci lagi oleh `tests/test_gmail_multitenant.py`.

### Cara menghidupkan Gmail dengan benar (SEMUA harus bersama)

1. **Scope.** `oauth_google` harus meminta scope Gmail, bukan hanya
   `auth/spreadsheets`. Dua hal yang perlu diperhatikan:
   - `gmail.send` / `gmail.readonly` / `gmail.compose` adalah scope
     **sensitive**: butuh OAuth App Verification tambahan, dan penyimpanan
     token di server juga memaksa security assessment tambahan.
   - Meminta scope yang lebih luas hanya untuk satu provider adalah keputusan
     produk, bukan sekadar perubahan kode. Consent screen yang lebih luas
     menurunkan tingkat persetujuan user.
2. **Sumber token.** `kirim_email_gmail` harus membaca
   `oauth_google.access_token(email)` (vault terenkripsi), bukan
   `db.get_integration(email, "gmail")` yang menunjuk `user_integrations`
   (plaintext) dan saat ini kosong.
3. **Baris baru di dict.** Hanya setelah 1 dan 2 selesai, `gmail` boleh masuk
   lagi ke `tools.OAUTH_CONNECT_URLS`.

Selama tiga langkah itu belum dikerjakan, status Gmail tetap
**manual / broken end-to-end** — sama seperti tabel di atas.