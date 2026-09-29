# Self-Healing — Reflection + Search-Retry

Diperbarui 29 September 2026. Versi kedua (hybrid), setelah user meminta
lebih otonom.

## Tabel keputusan

| Kategori | Retry | Search | Max | Escalate |
|---|---|---|---|---|
| Credential (401/403, token expired) | tidak | tidak | **0** | langsung |
| Network / timeout | ya | setiap percobaan | **5** | setelah 5x |
| API 5xx | ya | setiap percobaan | **5** | setelah 5x |
| Rate limit (429) | ya + delay | setiap percobaan | **5** | setelah 5x |
| Unknown | ya | setiap percobaan | **2** | setelah 2x |
| 404 / 400 | tidak | tidak | 0 | — (`abort`) |

Backoff rate limit: `1000, 2000, 4000, 8000, 16000` ms (eksponensial).
Backoff transient: `0, 1000, 2000, 4000, 8000` ms.

## Apa yang berubah dari versi konservatif, dan kenapa

Versi pertama memakai satu `MAX_ATTEMPTS = 3` untuk semua jenis error.
Tiga perubahan, masing-masing atas permintaan user:

1. **Batas global → batas per kategori.** Network/5xx/rate-limit memang
   bisa pulih sendiri. Dengan batas 3, heal yang berhasil di percobaan
   ke-4 akan dilaporkan gagal.
2. **Search hanya dari attempt ≥2 → setiap percobaan.** Kalau ternyata
   perlu intervensi manusia, saran forum sudah tersedia sejak awal, bukan
   baru muncul di percobaan terakhir.
3. **Unknown: abort seketika → 2 percobaan lalu escalate.** Ini
   pelonggaran yang paling berisiko menutupi bug asli, jadi batasnya
   sengaja pendek (2, bukan 5).

Aksi `credential` berubah nama menjadi `escalate` dan sekarang membawa
`provider` + `suggestions`, supaya UI bisa menampilkan "hubungkan ulang
Gmail", bukan teks pasif "butuh kredensial".

## Yang TIDAK berubah, dan alasannya

**Credential tidak pernah di-retry.** Ini tetap satu-satunya bagian
yang saya pertahankan dari versi lama. Retry dengan token kedaluwarsa
dijamin gagal; mengulang 5x hanya membakar kuota user untuk membuktikan
hal yang sudah tertulis di error. Yang berubah adalah *bentuk* hasilnya
(escalate + saran), bukan jumlah percobaannya.

**404/400 tetap abort.** Payload yang sama tidak akan menemukan target
yang tidak ada, dan tidak akan mengubah 400 jadi 200.

## Bukti

```
.......................                                          [100%]
23 passed in 0.44s
```

Test menutup: credential 0 retry di semua attempt; network & 5xx retry 5x
lalu escalate; unknown retry 2x lalu escalate; backoff rate limit
eksponensial persis; transient mulai dari 0; no delay setelah escalate;
search jalan di attempt 1 untuk non-credential dan TIDAK PERNAH untuk
credential; escalate selalu membawa saran walau search gagal; LLM rusak
tidak memblokir healing; error dict dan str mengklasifikasi sama.

## Batasan yang diketahui

- Integrasi ke `execution_engine._run_node` **belum** ada. Modul ini
  belum dipakai engine mana pun; ia kelas yang berdiri sendiri.
- LLM reflection opsional (`llm_reflect`) belum di-wire ke model
  provider mana pun. Semua keputusan saat ini murni rules.
- `RETRY_SUCCESS_RATE` tidak diukur. Butuh workflow yang benar-benar
  gagal dan definisi sukses yang eksplisit.
- Tidak ada screenshot UI; format `suggestions` untuk report chat
  dispesifikasikan di kontrak `to_dict()`, belum dirender.
