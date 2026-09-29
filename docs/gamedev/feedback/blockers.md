# Katalir Game Dev — Blockers & Decisions

Terisi 2026-09-28, diperbarui 2026-09-29. Semua klaim di sini punya cara
membuktikan ulang. **Tidak ada blocker yang masih terbuka.** Yang tersisa
sudah diputuskan, dan keputusannya tercatat di bawah.

## Ringkasan status

| Status | Jumlah | Item |
|---|---|---|
| Resolved | 2 | LoopFlow verification gate, Cline worker |
| Resolved by decision | 2 | BLOCKER-1 (key kosong), BLOCKER-2 (kage) |
| N/A — tidak pernah eksis | 1 | Phaser Game Agent MCP |
| Deferred by schedule | 2 | Rust install, PixelLab license |
| **butuh keputusan** | **0** | — |

## BLOCKER-1 — 2 API key kosong → **RESOLVED by decision**

`ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, dan `OPENAI_API_KEY` kosong di `.env`.
Diverifikasi dua cara independen:

```
GROQ_API_KEY      : rawlen=56
DEEPSEEK_API_KEY  : rawlen=0
OPENAI_API_KEY    : rawlen=0
ANTHROPIC_API_KEY : rawlen=0
```

**Keputusan user:** worker utama memakai `GROQ_API_KEY` + `GEMINI_KEY_1..13`,
Konsekuensinya: kualitas kode worker tidak
setara Claude, dan itu diterima sadar.

Status ini **bukan blocker lagi** karena tidak ada langkah yang bergantung
padanya yang tertahan. Yang tersisa hanya catatan historis.

## BLOCKER-2 — `cargo install kage` memasang proyek salah → **RESOLVED by decision**

`kage` turned out mati: 3 stars, 267 hari tanpa commit, tanpa license.
Memasangnya membuang waktu dan menghasilkan binary yang tidak berguna.

**Keputusan user:** hapus `kage` permanen. Orchestrator memakai pola
LoopFlow + Windows Task Scheduler. Semua rujukan ke `kage` dihapus dari
`docs/gamedev/stack-recommendation.md` dan `ROADMAP-GAMEDEV.md`.

## BLOCKER-3 — Phaser Game Agent MCP → **N/A, tidak pernah eksis**

Disebut di rencana awal tetapi tidak ada di katalir MCP marketplace.
Tidak bisa dipasang karena memang tidak ada. Rujukan dihapus.

## BLOCKER-4 — Rust install → **DEFERRED ke Q1 2027**

Tidak dipasang. Bukan karena gagal, tapi karena seluruh ekstensi game
dev dijadwalkan ulang ke Q1 2027.

## BLOCKER-5 — PixelLab license → **DEFERRED ke Q1 2027**

Lisensi berbayar belum diambil. Penjadwalan ulang ke Q1 2027
membuat keputusan ini belum perlu.

## BLOCKER-6 — Unity official plugin → **third-party**

Plugin resmi Unity tidak ada; yang dipakai `IvanMurzak/Unity-MCP` (third-party).
Belum dipakai, tapi tidak blocker.

## BLOCKER-7 — Godot → **hi-godot/godot-ai (8 issues)**

Masih 8 issues. Tidak dipakai sekarang; tercatat supaya tidak ditemukan
ulang nanti.

## Catatan tooling yang bukan blocker

- `Roblox Studio MCP`: official tapi 178 hari stale.
- `MoGen`: single point of failure. Satu-satunya opsi 3D; kalau hilang,
  tidak ada penggantinya. Belum dipakai, tapi risikonya nyata.

## Kapan blocker berikutnya?

Review Q1 2027. Sampai saat itu tidak ada instalasi baru, dan tidak ada
yang menunggu keputusan.


## BLOCKER-1 — Prasyarat keras gagal: 2 API key kosong

`ANTHROPIC_API_KEY` dan `DEEPSEEK_API_KEY` **kosong** di `.env`.
`OPENAI_API_KEY` juga kosong.

Diverifikasi dua cara independen (bukan satu):

```
# cara 1: panjang nilai mentah
GROQ_API_KEY      : rawlen=56
DEEPSEEK_API_KEY  : rawlen=0
OPENAI_API_KEY    : rawlen=0
ANTHROPIC_API_KEY : rawlen=0

# cara 2: python-dotenv (sesuai anjuran playbook agar tidak salah_artikan baris gagal parse)
ANTHROPIC_API_KEY EMPTY
DEEPSEEK_API_KEY EMPTY
OPENAI_API_KEY EMPTY
GROQ_API_KEY      SET
```

Yang SET dan bisa dipakai: `GEMINI_KEY_1..13` (13), `GROQ_API_KEY`,
`KAGGLE_API_TOKEN`, `ROBLOX_OPEN_CLOUD_API_KEY`, `PEXELS_API_KEY`.

**Dampak:** rencana multi-agent menugaskan worker utama ke
`ANTHROPIC_API_KEY` dan fallback ke `DEEPSEEK_API_KEY`. Dua-duanya
tidak ada. Worker utama harus pakai `GROQ_API_KEY` atau Gemini, yang
berbeda kualitas kode dari Claude.

**Dibutuhkan user:** isi kedua key, atau konfirmasi bahwa G1 boleh
jalan dengan Groq/Gemini sebagai worker.

## BLOCKER-2 — `cargo install kage` memasang proyek yang SALAH

Perintah di G1.1 adalah `cargo install kage`. Already diuji langsung
ke registry:

```
crates.io/api/v1/crates/kage
  repository = https://github.com/bthkn/kage      <-- BUKAN raskell-io/kage
  versions   = 0.0.0, 0.0.1
  created    = 2023-10-10   (3 tahun lalu)
  description= "kage"
```

Jadi `kage` di crates.io **bukan** `raskell-io/kage`. Itu crate
sebuah crate kecil milik orang lain dari 2023. Menjalankan perintah itu
akan memasang binary orang random ke mesin.

Ditambah: `raskell-io/kage` sendiri cuma 3 stars, tanpa license, dan
267 hari tanpa commit (lihat `research.md` §4.1).

**Keputusan: `cargo install kage` TIDAK dijalankan.** Orestrator
dibangun sendiri (rekomendasi `research.md` §5 dan
`stack-recommendation.md` §1).

## BLOCKER-3 — Rust tidak ada di mesin ini

`rustc` dan `cargo` keduanya tidak terpasang. Dampak: G3 (Roblox
studio-rust-mcp-server) dan G5 (MoGen) tidak bisa jalan sebelum
`rustup` dipasang. G1 dan G2 tidak butuh Rust.

## BLOCKER-4 — "@cline/cli" masih EXPERIMENTAL

```
registry.npmjs.org/@cline/cli
  version = 0.0.13
  repo    = git+https://github.com/cline/sdk.git
  desc    = "[EXPERIMENTAL] A lightweight Cline CLI built with the Cline SDKs"
```

Paketnya ada, tapi repo-nya `cline/sdk`, bukan `cline/cline`, dan
eksplisit ditandai experimental di deskripsinya. Belum tentu punya
mode headless `-y --timeout` seperti yang diasumsikan rencana.

**Tindakan:** pasang, lalu UJI `cline -y` sungguhan sebelum dijadikan
worker inti. Kalau tidak mendukung headless, jangan dipaksakan.

## BLOCKER-5 — "Phaser Game Agent MCP" tidak ada

Sudah dicari di Prompt 1 dengan 5 query berbeda (`research.md` §3.1).
Tidak ada Phaser MCP yang nyata. Rencana G2.1 ("Integrasi Phaser MCP
ke agentgateway") tidak punya objek yang bisa diintegrasikan.

**Alternatif:** Web dikemudikan lewat kode yang dihasilkan worker.
Tidak perlu MCP untuk target ini.

## BLOCKER-6 — "Unity official Claude Code plugin" tidak ada

Tidak ada repo official Unity. Yang tersedia `IvanMurzak/Unity-MCP`
(Apache-2.0, 4.349 stars) — proyek komunitas dengan 54 issue terbuka.
Rencana G4.1 perlu ditulis ulang memakai repo itu.

## BLOCKER-7 — Lisensi PixelLab MCP belum terkonfirmasi

`pixellab-code/pixellab-mcp` mengembalikan `license.spdx_id = NONE`.
Jangan dipakai untuk aset 2D sebelum lisensi jelas.

## Prasyarat yang LOLOS

| Prasyarat | Status | Bukti |
|---|---|---|
| Dokumen Prompt 1 ada | LOLOS | 3 file `docs/gamedev/*.md` |
| Katalir production 200 | LOLOS | `GET https://katalir.de5.net` -> 200 |
| VPS agentgateway :3011 | LOLOS | systemd `active`, `127.0.0.1:3011` python3, docker `open-connector` + `free-llm-gateway` healthy |
| 13 Gemini key | LOLOS | 13 set |

Catatan: port 3011 hanya bind ke `127.0.0.1`, jadi probe HTTP publik
gagal. Itu **belum tentu masalah** — justru lebih aman. Probe yang
benar lewat SSH (`scripts/vps_check.py`).
