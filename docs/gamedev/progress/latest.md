# Katalir Game Dev — Progress

Diperbarui 2026-09-29. Semua status punya bukti; yang belum punya bukti
ditandai terbuka, bukan disembunyikan.

## Status Keseluruhan: DEFERRED ke Q1 2027

Ekstensi game dev **dijadwalkan ulang**, bukan sedang dikerjakan. Keputusan
ini datang dari user, bukan dari hambatan teknis yang belum selesai. Yang
sudah selesai tetap selesai dan tetap tercatat di bawah.

## Fase G1 — Infrastructure: DONE SEBAGIAN, lalu DIJEDULE ULANG

| Komponen | Status | Bukti |
|---|---|---|
| Verification gate (LoopFlow) | **DONE** | PASS pada output lengkap, FAIL pada output tidak lengkap; dua-duanya exit code benar |
| Cline worker | **DONE** | `clite` v0.0.13 terpasang; sesi headless membuat `hello.txt`, isi diverifikasi ulang independen |
| Pipeline runner | **DONE** | `run_pipeline.py` kompilasi; memakai flag Cline yang benar |
| 3-file template system | **DONE** | 3 template di `templates/gamedev/` |
| Orchestrator | **DEFERRED** | Pakai pola LoopFlow + Windows Task Scheduler, bukan `kage` |

## Keputusan User (29 Sep 2026)

1. **Worker: Groq + Gemini.** Key yang sudah ada dipakai, tidak membeli baru.
2. **Rust: tidak dipasang.** Dilewati untuk G2.
3. **Engine: Web.** Bukan MCP, karena Phaser MCP yang disebut tidak pernah ada.
4. **Orchestrator: pola LoopFlow + Windows Task Scheduler**, bukan kage.

## Yang DIHAPUS dan alasannya

| Item | Alasan |
|---|---|
| `kage` | Proyek mati: 3 stars, 267 hari tanpa commit, tanpa license. Dihapus permanen, bukan ditunda. |
| Phaser Game Agent MCP | Tidak pernah eksis. Menghapus rujukan mencegah orangisasi sia-sia. |
| `ANTHROPIC`/`DEEPSEEK`/`OPENAI` | Tidak dipakai di rencana sekarang. Key kosong **bukan** blocker lagi. |

## Prasyarat (status terbaru)

| Prasyarat | Status | Bukti |
|---|---|---|
| Dokumen Prompt 1 | LOLOS | 3 file `docs/gamedev/*.md` |
| Katalir production 200 | LOLOS | `GET katalir.de5.net` -> 200 |
| VPS agentgateway :3011 | LOLOS | systemd `active`; docker open-connector + free-llm-gateway healthy |
| Worker LLM | LOLOS | `GROQ_API_KEY` rawlen=56, `GEMINI_KEY_1..13` tersedia |

## Fase G2–G5

Belum dimulai. Semua menunggu jadwal Q1 2027.

## Yang stumbled di tengah, dan tetap tercatat

- `cargo install kage` memasang proyek yang salah. Sudah dicatat di
  `docs/gamedev/stack-recommendation.md`; tidak diulang.
- Dua key kosong sempat dicatat sebagai BLOCKER-1. Sekarang hanya catatan
  historis, bukan blocker — worker sudah diarahkan ke Groq/Gemini.

## Review berikutnya

Q1 2027. Sampai saat itu G1 tetap berhenti; tidak ada instalasi Rust,
kage, atau Phaser MCP.

| Orchestrator | **TERTAHAN** | BLOCKER-2: `cargo install kage` memasang crate orang lain |
| `/gamedev` namespace | BELUM | menunggu orchestrator |
| Studio Connector (Tauri) | BELUM | butuh Rust (BLOCKER-3) |

## Status Engine

| Engine | Status | Catatan |
|---|---|---|
| Web (Phaser) | BELUM | Tidak ada Phaser MCP (BLOCKER-5); dikemudikan via kode |
| Roblox | BELUM | Rust belum ada; MCP repo 178 hari stale |
| Unity | BELUM | Perlu tulis ulang rencana: bukan plugin official (BLOCKER-6) |
| Godot | BELUM | `hi-godot/godot-ai` kandidat, belum diuji |

## Proyek Aktif

Belum ada. Menunggu keputusan user soal BLOCKER-1 (worker utama).

## Blocker

Lihat `docs/gamedev/feedback/blockers.md` untuk detail dan cara
membuktikan ulang. Ringkas: BLOCKER-1 (key kosong) sampai
BLOCKER-7 (lisensi PixelLab).

## Keputusan Tertunda untuk User

1. Isi `ANTHROPIC_API_KEY` + `DEEPSEEK_API_KEY`, atau izinkan G1 jalan
   dengan Groq/Gemini sebagai worker?
2. Boleh pasang Rust (`rustup`)? Wajib untuk G3 dan G5.
3. PoC G2: Web tanpa MCP dulu, atau langsung Godot yang punya MCP?
