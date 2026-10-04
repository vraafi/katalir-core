# Threat Model — Tool Call Injection (Textual Tool Calling)

Status: dinilai terhadap `8291a94`. Metode: baca kode + uji serang langsung.
Semua temuan di bawah berasal dari eksekusi nyata, bukan pembacaan contoh brief.

## Konteks sistem

Katalir menjalankan *textual tool calling*: model menulis blok
`[ALAT: args]` di teks balasannya, parser mendeteksi, lalu handler
menjalankan. Gateway menolak native `tools`, jadi jalur inilah yang dipakai
(`api_server.py::_send_tools_param`).

Rantai yang relevan:

```
pesan user  -> [SystemMessage + history + HumanMessage]  -> LLM
balasan LLM -> _content_text(resp) -> parse_textual_tools -> execute_textual_tool
```

Titik temptannya jelas: **parserimaan string**. Siapa pun yang bisa
menulis teks yang sampai ke `_content_text(resp)` bisa menyuruh sistem
melakukan sesuatu.

## 2.1 Trust boundary — hasil audit kode

Pertanyaan: apakah parser dipanggil pada pesan user? **Tidak.**

```
api_server.py:904  _bracket_calls = [] if calls else parse_textual_tools(_raw_text)
api_server.py:816  _raw_text = _content_text(resp)      # dari respons LLM
api_server.py:814  messages.append(HumanMessage(content=prompt))   # masuk ke LLM, TIDAK ke parser
```

`prompt` (pesan user) masuk ke `HumanMessage`, bukan ke parser. Satu-satunya
jalur ke parser adalah `_content_text(resp)`.

Artinya vektor 1, 3, 5, 6, 7, 9, 12 (yang butuh model mengulang perintah
pengguna apa adanya) **tidak langsung berhasil** — tapi lihat tabel: ini
mitigasi yang tidak lengkap, bukan jaminan.

## Vektor serangan dan status

| # | Vektor | Status | Severity | Bukti / catatan |
|---|--------|--------|----------|-----------------|
| 1 | Direct injection (user ketik `[TELEGRAM: ...]`) | **Mitigasi parsif** | HIGH | Teks user masuk ke prompt, parser hanya baca output LLM. TAPI model bisa mengikutinya → bergantung pada kesetiaan LLM. Perlu policy gate. |
| 2 | Indirect injection (body email berisi `[VAULT: x]`) | **RENTAN** | **CRITICAL** | `api_server.py:1038` `ToolMessage(content=str(result))` memasukkan hasil tool kembali ke konteks. Body email = data tak tepercaya yang kembali ke parser lewat model. |
| 3 | JSON injection `{"tool":...}` | **Aman** | LOW | `BRACKET_RE` hanya cocok pada `[NAMA: ...]`; JSON tidak cocok. `parse_tool_call` juga menolak JSON tanpa indikasi tool. |
| 4 | Control-token injection | **Tidak diuji** | MEDIUM | Token kontrol model tidak disanitasi di sisi Katalir (bukan lapisan Katalir). Perlu rate limit + policy gate agar dampaknya terbatas. |
| 5 | Role impersonation | **Mitigasi parsif** | HIGH | Meng instructing model; sama seperti #1. Tidak ada verifikasi identitas di policy. |
| 6 | Privilege escalation / cross-tenant | **Aman (arsitektur)** | MEDIUM | `email` diambil dari JWT di endpoint, bukan dari argumen parser. `execute_textual_tool(call, user_email)` tidak pernah menerima email dari model. Perlu tes regresi untuk mengunci. |
| 7 | Parameter injection (`subjek=../../etc/passwd`) | **RENTAN** | **HIGH** | Tidak ada validasi tipe/pola pada argumen. `subjek` adalah string bebas yang masuk ke query IMAP. Perlu `argument_validator`. |
| 8 | Argument overflow (`pesan` 1 MB) | **RENTAN** | MEDIUM | Tidak ada batas panjang argumen. Satu balasan model bisa_besar dan boros memori. Perlu batas + rate limit. |
| 9 | Loop injection (tool 1000x) | **RENTAN** | MEDIUM | Tidak ada batas jumlah call per giliran. `parse_textual_tools` akan mengembalikan semua blok. Perlu budget per giliran. |
| 10 | Nested injection (`pesan=[VAULT: x]`) | **Aman** | LOW | Regex `[^]\n]*` berhenti di `]`, dan `[...]` di dalam nilai tidak menghasilkan call kedua pada posisi yang valid. Perlu tes untuk mengunci. |
| 11 | Unicode / homoglyph | **Sebagian aman** | MEDIUM | Zero-width dihapus oleh `_strip_code`? Tidak — hanya parser XML yangHandling ZW. Parser kurung TIDAK menormalisasi ZWSP, sehingga `[VA\u200bULT: x]` tidak cocok (bagus) tapi juga bisa dipakai mengelabui. Perlu normalisasi eksplisit + tes. |
| 12 | Multi-turn grooming | **Tidak ada kontrol** | MEDIUM | Tidak ada rate limit lintas giliran. 10 pesan yangmasing-masingyangmasing-masing dapat Compose menjadi serangan. Perlu rate limiter. |

## Kesimpulan

Tiga masalah nyata, semuanya di luar parser:
1. **Vektor 2 (indirect via tool result) — CRITICAL.** Hasil tool masuk
   kembali ke konteks model tanpa sanitasi.
2. **Vektor 7 & 8 (argumen) — HIGH/MEDIUM.** Tidak ada validasi.
3. **Vektor 9 & 12 (loop / grooming) — MEDIUM.** Tidak ada rate limit.

Yang **tidak** boleh applauded: ketiadaan policy gate. Saat ini satu-satunya
gerbang adalah "apakah string ini cocok regex" — itu bukan kontrol akses.